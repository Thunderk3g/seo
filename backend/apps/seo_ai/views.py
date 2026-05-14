"""REST endpoints for SEO grading runs and source-data dashboards.

Routes:

  POST /api/v1/seo/grade/                 → start a new run (async)
  GET  /api/v1/seo/grade/                 → list recent runs
  GET  /api/v1/seo/grade/<id>/            → run header + scores
  GET  /api/v1/seo/grade/<id>/findings/   → findings (filterable by agent)
  GET  /api/v1/seo/grade/<id>/messages/   → conversation log
  GET  /api/v1/seo/overview/              → bundled dashboard payload
  GET  /api/v1/seo/gsc/                   → full GSC dashboard data
  GET  /api/v1/seo/semrush/               → SEMrush overview + keywords
  GET  /api/v1/seo/sitemap/               → AEM sitemap page list + rollup

Run kickoff is fire-and-forget into Celery so the API stays responsive
even when the LLM stage takes 30+ seconds. The view returns the run id
immediately; the client polls the GET endpoint.

The /gsc/, /semrush/, and /sitemap/ endpoints are thin REST wrappers
over the adapters in apps.seo_ai.adapters; they expose the same data
the grading agents consume so the UI can render the source tables.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .adapters import GSCCSVAdapter, SemrushAdapter, SitemapAEMAdapter
from .adapters.semrush import SemrushError
from .models import SEORun
from .overview import build_overview, read_daily_series
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


# ── source-data dashboards (GSC / SEMrush / Sitemap) ─────────────────────


@api_view(["GET"])
def gsc_dashboard(request: Request):
    """Full GSC dashboard payload — queries, pages, daily series, summary."""
    sample = int(request.query_params.get("limit") or 200)
    adapter = GSCCSVAdapter()
    try:
        summary = adapter.summary(sample_size=sample)
    except Exception as exc:  # noqa: BLE001 - render empty state
        logger.warning("gsc dashboard failed: %s", exc)
        return Response({"available": False, "error": str(exc)})
    daily = read_daily_series(adapter)
    return Response(
        {
            "available": True,
            "snapshot_path": summary.snapshot_path,
            "totals": {
                "queries": summary.total_queries,
                "pages": summary.total_pages,
                "clicks": summary.total_clicks,
                "impressions": summary.total_impressions,
                "avg_ctr": summary.avg_ctr,
                "avg_position": summary.avg_position,
            },
            "top_queries": [asdict(q) for q in summary.top_queries_by_clicks],
            "top_pages": [asdict(p) for p in summary.top_pages_by_clicks],
            "underperforming_queries": [
                asdict(q) for q in summary.underperforming_queries
            ],
            "high_impression_low_click_queries": [
                asdict(q) for q in summary.high_impression_low_click_queries
            ],
            "daily_series": daily,
        }
    )


@api_view(["GET"])
def semrush_dashboard(request: Request):
    """SEMrush overview + organic keywords for the configured database."""
    domain = request.query_params.get("domain") or "bajajlifeinsurance.com"
    limit = int(request.query_params.get("limit") or 100)
    try:
        adapter = SemrushAdapter()
    except SemrushError as exc:
        return Response({"available": False, "error": str(exc)})

    try:
        overview_data = adapter.domain_overview(domain)
        keywords = adapter.organic_keywords(domain, limit=limit)
    except SemrushError as exc:
        logger.warning("semrush dashboard failed: %s", exc)
        return Response({"available": False, "error": str(exc)})

    return Response(
        {
            "available": True,
            "domain": domain,
            "database": overview_data.database,
            "overview": asdict(overview_data),
            "keywords": [asdict(k) for k in keywords],
        }
    )


@api_view(["GET"])
def sitemap_dashboard(_request: Request):
    """AEM sitemap page list and authoring rollup."""
    adapter = SitemapAEMAdapter()
    try:
        summary = adapter.summary()
        pages = list(adapter.iter_pages())
    except Exception as exc:  # noqa: BLE001
        logger.warning("sitemap dashboard failed: %s", exc)
        return Response({"available": False, "error": str(exc)})

    def _page_dict(p):
        return {
            "public_url": p.public_url,
            "aem_path": p.aem_path,
            "title": p.title,
            "description": p.description,
            "template_name": p.template_name,
            "last_modified": p.last_modified.isoformat() if p.last_modified else None,
            "component_count": p.component_count,
            "title_length": len(p.title or ""),
            "description_length": len(p.description or ""),
        }

    return Response(
        {
            "available": True,
            "snapshot_path": summary.snapshot_path,
            "totals": {
                "pages": summary.total_pages,
                "with_description": summary.pages_with_description,
                "without_description": summary.pages_without_description,
                "short_title": summary.pages_with_short_title,
                "long_title": summary.pages_with_long_title,
                "short_desc": summary.pages_with_short_desc,
                "long_desc": summary.pages_with_long_desc,
            },
            "distinct_templates": summary.distinct_templates,
            "component_usage": summary.component_usage,
            "most_recent_modification": (
                summary.most_recent_modification.isoformat()
                if summary.most_recent_modification
                else None
            ),
            "least_recent_modification": (
                summary.least_recent_modification.isoformat()
                if summary.least_recent_modification
                else None
            ),
            "pages": [_page_dict(p) for p in pages],
        }
    )
