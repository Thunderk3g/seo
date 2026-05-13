"""REST endpoints for SEO grading runs.

Five routes:

  POST /api/v1/seo/grade/                 → start a new run (async)
  GET  /api/v1/seo/grade/                 → list recent runs
  GET  /api/v1/seo/grade/<id>/            → run header + scores
  GET  /api/v1/seo/grade/<id>/findings/   → findings (filterable by agent)
  GET  /api/v1/seo/grade/<id>/messages/   → conversation log

Run kickoff is fire-and-forget into Celery so the API stays responsive
even when the LLM stage takes 30+ seconds. The view returns the run id
immediately; the client polls the GET endpoint.
"""
from __future__ import annotations

import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .models import SEORun
from .overview import build_overview
from .serializers import (
    SEORunFindingSerializer,
    SEORunMessageSerializer,
    SEORunSerializer,
)
from .tasks import run_grade_task

logger = logging.getLogger("seo.ai.views")


class SEORunViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SEORunSerializer
    queryset = SEORun.objects.all()

    def list(self, request: Request):
        domain = request.query_params.get("domain")
        qs = self.queryset
        if domain:
            qs = qs.filter(domain=domain)
        qs = qs.order_by("-started_at")[:50]
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="findings")
    def findings(self, request: Request, pk: str | None = None):
        run = self.get_object()
        qs = run.findings.all()
        agent = request.query_params.get("agent")
        if agent:
            qs = qs.filter(agent=agent)
        return Response(SEORunFindingSerializer(qs, many=True).data)

    @action(detail=True, methods=["get"], url_path="messages")
    def messages(self, request: Request, pk: str | None = None):
        run = self.get_object()
        qs = run.messages.all().order_by("step_index", "created_at")
        return Response(SEORunMessageSerializer(qs, many=True).data)


@api_view(["POST"])
def start_grade(request: Request):
    """Kick off a grading run.

    Body: ``{"domain": "bajajlifeinsurance.com", "sync": false}``. The
    sync flag is for dev — it runs the orchestrator inline so the
    response carries the final score (useful before Celery is wired in
    local dev).
    """
    domain = (request.data or {}).get("domain", "").strip()
    if not domain:
        return Response(
            {"detail": "domain is required"}, status=status.HTTP_400_BAD_REQUEST
        )
    sync = bool((request.data or {}).get("sync"))

    run = SEORun.objects.create(domain=domain, triggered_by="api")

    if sync:
        # Inline path for dev. Import here so a missing Celery worker
        # doesn't break the import graph at module load.
        from .agents.orchestrator import Orchestrator

        try:
            Orchestrator(run).execute()
        except Exception as exc:  # noqa: BLE001 - surface to client
            return Response(
                {"id": str(run.id), "status": "failed", "detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(SEORunSerializer(run).data)

    run_grade_task.delay(str(run.id))
    return Response(
        {"id": str(run.id), "status": run.status},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["GET"])
def overview(request: Request):
    """Single endpoint that feeds the Overview page.

    Bundles the latest completed run, the GSC rollup, and the crawler
    rollup so the dashboard paints from one query rather than three.
    """
    domain = request.query_params.get("domain") or "bajajlifeinsurance.com"
    return Response(build_overview(domain))
