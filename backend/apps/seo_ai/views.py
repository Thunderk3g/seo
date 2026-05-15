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
  GET  /api/v1/seo/competitor/            → competitor gap report (no LLM)

Run kickoff is fire-and-forget into Celery so the API stays responsive
even when the LLM stage takes 30+ seconds. The view returns the run id
immediately; the client polls the GET endpoint.

The /gsc/, /semrush/, and /sitemap/ endpoints are thin REST wrappers
over the adapters in apps.seo_ai.adapters; they expose the same data
the grading agents consume so the UI can render the source tables.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict

from django.http import StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .adapters import GSCCSVAdapter, SemrushAdapter, SitemapAEMAdapter
from .adapters.semrush import SemrushError
from .chat import ChatRouter
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
    """AEM sitemap page list and authoring rollup.

    The list payload is intentionally slim — metadata + word count + a
    short content preview. Full content lives behind
    ``/api/v1/seo/sitemap/page/?path=...`` and is fetched on-demand by
    the frontend drawer. With ~600 pages averaging 18 KB of content
    each, returning the full text inline would push the response past
    11 MB and stall the browser.
    """
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
            "word_count": p.word_count,
            "content_preview": (p.content or "")[:240],
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


@api_view(["GET"])
def competitor_dashboard(request: Request):
    """Competitor gap report for a domain — no LLM call, just the
    deterministic facts built by the same machinery the CompetitorAgent
    uses. Heavy on first call (SEMrush + crawl); cached for 7 days
    after that so subsequent loads are instant.
    """
    domain = request.query_params.get("domain") or "bajajlifeinsurance.com"
    from django.conf import settings as _settings

    if not _settings.SEMRUSH.get("api_key"):
        return Response(
            {"available": False, "error": "SEMRUSH_API_KEY not set"}
        )
    if not _settings.COMPETITOR.get("enabled", True):
        return Response(
            {"available": False, "error": "COMPETITOR_ENABLED=false"}
        )

    # Build a one-off SEORun-less context. CompetitorAgent.build_facts
    # only uses the run for logging system events; we side-step that
    # by using a transient in-memory SEORun row (committed=False).
    from .agents.competitor import CompetitorAgent
    from .models import SEORun

    transient = SEORun(domain=domain, triggered_by="dashboard")
    transient.id = None  # don't persist conversation logs for dashboard hits
    # We need a saved SEORun for SEORunMessage FK; create + delete is
    # cheaper than building a logging-shim.
    transient.save()
    try:
        agent = CompetitorAgent(run=transient, step_index_start=0)
        facts = agent.build_facts(domain=domain)
    except SemrushError as exc:
        transient.delete()
        return Response({"available": False, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - surface to client
        logger.warning("competitor dashboard failed: %s", exc)
        transient.delete()
        return Response({"available": False, "error": str(exc)})
    finally:
        # Keep transient run as the audit log for this dashboard hit
        # so users can replay; could be GC'd by a periodic job.
        pass

    payload = facts.get("competitor", {})
    payload["available"] = True
    payload["domain"] = domain
    return Response(payload)


@api_view(["GET"])
def sitemap_page_detail(request: Request):
    """Return the full extracted content for one AEM page.

    Match by ``aem_path`` (preferred — stable identifier) or
    ``public_url`` (fallback). Returns 404 if the path isn't in the
    current AEM snapshot.
    """
    aem_path = request.query_params.get("path", "").strip()
    public_url = request.query_params.get("url", "").strip()
    if not aem_path and not public_url:
        return Response(
            {"detail": "path or url query param is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    adapter = SitemapAEMAdapter()
    for p in adapter.iter_pages():
        if (aem_path and p.aem_path == aem_path) or (
            public_url and p.public_url == public_url
        ):
            return Response(
                {
                    "public_url": p.public_url,
                    "aem_path": p.aem_path,
                    "title": p.title,
                    "description": p.description,
                    "template_name": p.template_name,
                    "last_modified": (
                        p.last_modified.isoformat() if p.last_modified else None
                    ),
                    "word_count": p.word_count,
                    "content": p.content,
                    "component_types": p.component_types,
                }
            )
    return Response(
        {"detail": "page not found in current AEM snapshot"},
        status=status.HTTP_404_NOT_FOUND,
    )


# ── competitor gap detection ─────────────────────────────────────────────


@api_view(["GET"])
def competitor_gap_detection(request: Request):
    """Per-agent detection findings for the latest completed run.

    Returns one bucket per detection agent (the 7 Phase-2 agents). Each
    bucket is a list of finding rows; an empty bucket means either the
    agent was skipped (missing API key) or it ran and found nothing.
    The caller can disambiguate by reading the run's audit messages.
    """
    from .agents.orchestrator import DETECTION_AGENTS
    from .models import SEORunStatus

    domain = request.query_params.get("domain") or "bajajlifeinsurance.com"
    run = (
        SEORun.objects.filter(domain=domain, status=SEORunStatus.COMPLETE)
        .order_by("-finished_at")
        .first()
    )
    if run is None:
        return Response({"available": False, "domain": domain})

    agent_names = [getattr(c, "name", c.__name__) for c in DETECTION_AGENTS]
    by_agent: dict[str, list] = {n: [] for n in agent_names}
    for f in run.findings.filter(agent__in=agent_names).order_by("-priority"):
        by_agent[f.agent].append(SEORunFindingSerializer(f).data)

    # Lightweight skip / crash audit so the UI can show "skipped: no
    # API key" rather than mistaking empty for "ran clean".
    audit: dict[str, dict[str, str]] = {}
    for msg in run.messages.filter(role="system").only(
        "from_agent", "content"
    ):
        event = (msg.content or {}).get("event") or ""
        if not event.endswith(".skipped") and not event.endswith(".crashed"):
            continue
        agent_key = event.rsplit(".", 1)[0]
        if agent_key in by_agent:
            audit[agent_key] = {
                "status": event.rsplit(".", 1)[1],
                "reason": ((msg.content or {}).get("data") or {}).get(
                    "reason", ""
                )[:300],
            }

    return Response(
        {
            "available": True,
            "domain": domain,
            "run_id": str(run.id),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "findings_by_agent": by_agent,
            "agent_status": audit,
        }
    )


# ── chat (SSE) ───────────────────────────────────────────────────────────


@csrf_exempt
@require_POST
def chat_stream(request):
    """Streaming conversational endpoint.

    Body: ``{"messages": [{"role": "user", "content": "..."}, ...],
    "domain": "bajajlifeinsurance.com"}``.

    Returns ``text/event-stream`` with these event kinds:
      * ``token`` — incremental assistant text
      * ``tool_call`` — completed tool invocation (name, args, result)
      * ``card``     — structured payload to render inline
      * ``done``     — final usage stats
      * ``error``    — terminal error
    """
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return StreamingHttpResponse(
            iter([
                "event: error\ndata: {\"message\":\"invalid JSON body\"}\n\n"
            ]),
            content_type="text/event-stream",
            status=400,
        )
    messages = body.get("messages") or []
    domain = (body.get("domain") or "bajajlifeinsurance.com").strip()
    router = ChatRouter(domain=domain)
    response = StreamingHttpResponse(
        router.handle_sse(messages),
        content_type="text/event-stream",
    )
    # Disable upstream buffering so tokens flush as they're produced.
    response["X-Accel-Buffering"] = "no"
    response["Cache-Control"] = "no-cache"
    return response
