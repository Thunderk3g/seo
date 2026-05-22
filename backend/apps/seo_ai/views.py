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

import base64
import binascii
import json
import logging
import re
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
from .models import (
    GapCompetitor,
    GapComparison,
    GapDeepCrawl,
    GapLLMResult,
    GapPipelineQuery,
    GapPipelineRun,
    GapPipelineStatus,
    GapSerpResult,
    SEORun,
)
from .overview import build_overview, read_daily_series
from .serializers import (
    SEORunFindingSerializer,
    SEORunMessageSerializer,
    SEORunSerializer,
)
from .tasks import run_gap_pipeline_task, run_grade_task

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
def adobe_dashboard(request: Request):
    """Adobe Analytics 2.0 dashboard — report-suite metadata, top pages
    by page-views over the trailing window, and the capability counters
    (dimensions / metrics) for the configured RSID.

    Query params:
      * ``lookback`` (optional, int) — days of history for the top-pages
        report. Defaults to ``ADOBE_ANALYTICS["default_lookback_days"]``
        (typically 7).
      * ``limit`` (optional, int) — top-N row count. Defaults to
        ``ADOBE_ANALYTICS["default_top_pages_limit"]`` (typically 25).

    Returns the ``available=false`` envelope with a ``reason`` field
    when credentials aren't configured, so the AdobePage UI can render
    the onboarding empty state without parsing exception text.
    """
    from .adapters.adobe_analytics import dashboard_payload

    try:
        lookback = int(request.query_params.get("lookback") or 0) or None
    except ValueError:
        lookback = None
    try:
        limit = int(request.query_params.get("limit") or 0) or None
    except ValueError:
        limit = None

    try:
        body = dashboard_payload(lookback_days=lookback, limit=limit)
    except Exception as exc:  # noqa: BLE001 — render empty state
        logger.warning("adobe analytics dashboard failed: %s", exc)
        return Response({"available": False, "error": str(exc)})
    return Response(body)


@api_view(["GET"])
def brand_mentions_dashboard(request: Request):
    """Brand-mention monitoring dashboard payload.

    Returns the aggregates + recent feed the BrandMonitorPage renders:
      * KPI strip (total, this-week, % positive, % old-brand, % AI-bot-visible)
      * Sentiment trend (last 90 days, daily bucket)
      * Source-tier donut counts
      * Brand-variant rebrand stickiness (old vs new vs parent over time)
      * Top mentioning domains
      * Recent mentions feed (paginated, filterable)

    Query params:
      * ``sentiment`` (optional) — filter the recent feed by sentiment
      * ``tier`` (optional) — filter by source_tier
      * ``variant`` (optional) — filter by brand_variant
      * ``q`` (optional) — substring search over title + snippet + domain
      * ``page`` / ``page_size`` — pagination of the recent feed
    """
    from collections import defaultdict
    from datetime import datetime, timedelta, timezone as tz
    from .models import (
        BrandMention,
        BrandVariant,
        MentionSentiment,
        MentionSourceTier,
    )

    now = datetime.now(tz.utc)
    cutoff_90 = now - timedelta(days=90)
    cutoff_7 = now - timedelta(days=7)

    qs = BrandMention.objects.all()
    total = qs.count()
    if total == 0:
        return Response({
            "available": True,
            "empty": True,
            "message": (
                "No brand mentions captured yet. Run "
                "`python manage.py pull_brand_mentions` or click "
                "Refresh now."
            ),
            "totals": {},
            "sentiment_trend": [],
            "tier_breakdown": [],
            "variant_breakdown": [],
            "top_domains": [],
            "mentions": [],
        })

    # KPI totals.
    last_week = qs.filter(last_seen_at__gte=cutoff_7).count()
    by_sentiment = {
        s: qs.filter(sentiment=s).count() for s in MentionSentiment.values
    }
    total_scored = sum(
        by_sentiment.get(s, 0)
        for s in (MentionSentiment.POSITIVE, MentionSentiment.NEUTRAL,
                  MentionSentiment.NEGATIVE)
    ) or 1
    pct_positive = round(
        100.0 * by_sentiment.get(MentionSentiment.POSITIVE, 0) / total_scored, 1,
    )
    pct_negative = round(
        100.0 * by_sentiment.get(MentionSentiment.NEGATIVE, 0) / total_scored, 1,
    )
    pct_old_brand = round(
        100.0 * qs.filter(brand_variant=BrandVariant.OLD).count() / total, 1,
    )
    ai_visible_tiers = (
        MentionSourceTier.NEWS_TIER_1, MentionSourceTier.NEWS_TIER_2,
        MentionSourceTier.FORUM, MentionSourceTier.REVIEW,
    )
    pct_ai_visible = round(
        100.0 * qs.filter(source_tier__in=ai_visible_tiers).count() / total, 1,
    )

    # 90-day sentiment trend (daily buckets).
    trend_qs = qs.filter(last_seen_at__gte=cutoff_90).values(
        "sentiment", "last_seen_at",
    )
    bucket: dict[str, dict[str, int]] = defaultdict(
        lambda: {"positive": 0, "neutral": 0, "negative": 0, "unscored": 0}
    )
    for row in trend_qs:
        d = row["last_seen_at"].date().isoformat()
        s = row["sentiment"] or "unscored"
        if s in bucket[d]:
            bucket[d][s] += 1
    sentiment_trend = [
        {"date": d, **counts}
        for d, counts in sorted(bucket.items())
    ]

    # Tier breakdown.
    tier_breakdown = [
        {"tier": t, "count": qs.filter(source_tier=t).count()}
        for t in MentionSourceTier.values
    ]
    tier_breakdown = [t for t in tier_breakdown if t["count"] > 0]
    tier_breakdown.sort(key=lambda x: -x["count"])

    # Variant breakdown.
    variant_breakdown = [
        {"variant": v, "count": qs.filter(brand_variant=v).count()}
        for v in BrandVariant.values
    ]
    variant_breakdown = [v for v in variant_breakdown if v["count"] > 0]

    # Top mentioning domains.
    from django.db.models import Count
    top_domains = list(
        qs.values("source_domain")
        .annotate(count=Count("id"))
        .order_by("-count")[:20]
    )

    # Recent feed — filterable.
    feed_qs = qs
    sentiment_filter = (request.query_params.get("sentiment") or "").strip()
    if sentiment_filter:
        feed_qs = feed_qs.filter(sentiment=sentiment_filter)
    tier_filter = (request.query_params.get("tier") or "").strip()
    if tier_filter:
        feed_qs = feed_qs.filter(source_tier=tier_filter)
    variant_filter = (request.query_params.get("variant") or "").strip()
    if variant_filter:
        feed_qs = feed_qs.filter(brand_variant=variant_filter)
    q = (request.query_params.get("q") or "").strip()
    if q:
        from django.db.models import Q
        feed_qs = feed_qs.filter(
            Q(source_title__icontains=q)
            | Q(snippet__icontains=q)
            | Q(source_domain__icontains=q)
        )

    try:
        page = max(0, int(request.query_params.get("page") or 0))
        page_size = max(1, min(100, int(request.query_params.get("page_size") or 50)))
    except ValueError:
        page, page_size = 0, 50
    start = page * page_size
    feed_total = feed_qs.count()
    rows = list(feed_qs.order_by("-last_seen_at")[start:start + page_size])
    mentions = [
        {
            "id": str(r.id),
            "source_url": r.source_url,
            "source_domain": r.source_domain,
            "source_title": r.source_title,
            "snippet": r.snippet,
            "body_excerpt": r.body_excerpt or "",
            "brand_variant": r.brand_variant,
            "source_tier": r.source_tier,
            "sentiment": r.sentiment,
            "sentiment_confidence": round(r.sentiment_confidence or 0, 2),
            "is_linked": r.is_linked,
            "anchor_texts": r.anchor_texts or [],
            "author": r.author or "",
            "publisher": r.publisher or "",
            "co_mentioned_brands": r.co_mentioned_brands or [],
            "language": r.language or "",
            "rating_value": r.rating_value,
            "rating_max": r.rating_max,
            "page_fetched": bool(r.page_fetched_at),
            "discovered_via": r.discovered_via,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "first_seen_at": r.first_seen_at.isoformat(),
            "last_seen_at": r.last_seen_at.isoformat(),
        }
        for r in rows
    ]

    return Response({
        "available": True,
        "empty": False,
        "totals": {
            "total": total,
            "last_week": last_week,
            "pct_positive": pct_positive,
            "pct_negative": pct_negative,
            "pct_old_brand": pct_old_brand,
            "pct_ai_visible_sources": pct_ai_visible,
            "by_sentiment": {
                k: by_sentiment.get(k, 0)
                for k in MentionSentiment.values
            },
        },
        "sentiment_trend": sentiment_trend,
        "tier_breakdown": tier_breakdown,
        "variant_breakdown": variant_breakdown,
        "top_domains": top_domains,
        "feed_total": feed_total,
        "mentions": mentions,
        "page": page,
        "page_size": page_size,
    })


@api_view(["POST"])
def brand_mentions_refresh(_request: Request):
    """Manual refresh trigger — kicks off ``run_brand_mentions_pull``
    synchronously (it's fast; ~30 s typical). Returns the same summary
    shape the daily job logs.

    For the production deploy we'd wrap this in a Celery delay() so
    the request returns immediately, but in dev this is fine.
    """
    from .adapters.brand_mentions import run_brand_mentions_pull

    try:
        result = run_brand_mentions_pull()
    except Exception as exc:  # noqa: BLE001
        logger.warning("brand-mentions refresh failed: %s", exc)
        return Response({"ok": False, "error": str(exc)}, status=500)
    return Response({
        "ok": True,
        "total_fetched": result.total_fetched,
        "total_new": result.total_new,
        "total_updated": result.total_updated,
        "sentiment_scored": result.sentiment_scored,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "sources": [
            {"source": s.source, "fetched": s.fetched, "new": s.new,
             "updated": s.updated, "error": s.error}
            for s in result.sources
        ],
    })


@api_view(["GET"])
def meta_ads_dashboard(request: Request):
    """Meta Ad Library data (competitor ads via Apify).

    Competitor resolution order:
      1. ``?competitor=`` query param (one or more, repeatable) —
         single-competitor view from CompetitorDetailPage.
      2. Latest ``GapPipelineRun`` → its ``GapCompetitor`` rows ordered
         by rank — the same competitors the deep crawl identified. We
         do NOT hardcode a roster; the data source follows the crawl.
      3. ``APIFY.default_meta_ads_competitors`` env fallback (empty by
         default).

    Other query params:
      * ``country`` (optional) — Ad Library country code (default "IN").
      * ``count`` (optional) — ads per competitor (default 25,
        actor-enforced minimum 10).
      * ``refresh`` (optional, bool) — bypass the 24-hour disk cache.
      * ``limit_competitors`` (optional, int) — when resolving from
        GapCompetitor, cap how many of the top-N to query. Defaults
        to 10 to keep Apify cost predictable (~$0.19 per refresh).
    """
    from .adapters.apify_meta_ads import dashboard_payload
    from .models import GapCompetitor, GapPipelineRun

    competitors = [c for c in request.query_params.getlist("competitor") if c.strip()]
    resolution_source = "query_param"

    if not competitors:
        try:
            limit_n = max(1, int(request.query_params.get("limit_competitors") or 10))
        except ValueError:
            limit_n = 10
        try:
            latest_run = (
                GapPipelineRun.objects
                .order_by("-created_at")
                .first()
            )
            if latest_run is not None:
                competitors = list(
                    GapCompetitor.objects
                    .filter(run=latest_run)
                    .order_by("rank")
                    .values_list("domain", flat=True)[:limit_n]
                )
                resolution_source = "gap_pipeline"
        except Exception as exc:  # noqa: BLE001
            logger.info("meta-ads: GapCompetitor lookup failed (%s)", exc)
        # Final fallback — env list (typically empty so view returns
        # available=False with a clear hint).
        if not competitors:
            resolution_source = "env_default"

    country = (request.query_params.get("country") or "").strip() or None
    try:
        count = int(request.query_params.get("count") or 0) or None
    except ValueError:
        count = None
    refresh = (
        (request.query_params.get("refresh") or "").lower()
        in ("1", "true", "yes", "on")
    )

    try:
        body = dashboard_payload(
            competitors=competitors or None,
            country=country,
            count=count,
            force_refresh=refresh,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("meta-ads dashboard failed: %s", exc)
        return Response({"available": False, "error": str(exc)})
    body["competitor_source"] = resolution_source
    return Response(body)


@api_view(["GET"])
def adobe_seo_join(request: Request):
    """SEO × Adobe cross-source join.

    Returns one row per Adobe top-page with the matching latest-crawl
    row + GSC clicks/impressions/position when available. Used by the
    AdobeSeoJoinPage to surface the "high impression, low actual
    traffic" fix list and the "pages with traffic but no crawl entry"
    sitemap-gap detector.

    Query params:
      * ``lookback`` — days of Adobe history (default 30)
      * ``limit``    — top-N pages from Adobe (default 100)
    """
    from .adapters.adobe_analytics import seo_adobe_join_payload

    try:
        lookback = int(request.query_params.get("lookback") or 30)
    except ValueError:
        lookback = 30
    try:
        limit = int(request.query_params.get("limit") or 100)
    except ValueError:
        limit = 100

    try:
        body = seo_adobe_join_payload(lookback_days=lookback, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("adobe seo join failed: %s", exc)
        return Response({"available": False, "error": str(exc)})
    return Response(body)


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
    """Per-agent detection findings for the latest finished run.

    Returns one bucket per detection agent (the 7 Phase-2 agents). Each
    bucket is a list of finding rows; an empty bucket means either the
    agent was skipped (missing API key) or it ran and found nothing.
    The caller can disambiguate by reading the run's audit messages.
    Accepts both COMPLETE and DEGRADED status.
    """
    from .agents.orchestrator import DETECTION_AGENTS
    from .models import SEORunStatus

    domain = request.query_params.get("domain") or "bajajlifeinsurance.com"
    detection_agent_names = [
        getattr(c, "name", c.__name__) for c in DETECTION_AGENTS
    ]
    # Detection findings persist regardless of the run's terminal
    # status — a critic/narrator LLM crash later in the pipeline
    # doesn't unmake them. So we pick the most recent run on this
    # domain that actually has any detection findings, rather than
    # filtering on status.
    run = (
        SEORun.objects.filter(
            domain=domain,
            findings__agent__in=detection_agent_names,
        )
        .order_by("-started_at")
        .distinct()
        .first()
    )
    if run is None:
        return Response({"available": False, "domain": domain})

    by_agent: dict[str, list] = {n: [] for n in detection_agent_names}
    for f in run.findings.filter(
        agent__in=detection_agent_names
    ).order_by("-priority"):
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
            "run_status": run.status,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "findings_by_agent": by_agent,
            "agent_status": audit,
        }
    )


# ── gap detection pipeline ───────────────────────────────────────────────


def _serialize_query(q: GapPipelineQuery) -> dict:
    return {
        "id": str(q.id),
        "query": q.query,
        "intent": q.intent,
        "rationale": q.rationale,
        "source_keywords": q.source_keywords,
        "order": q.order,
    }


def _serialize_llm_result(r: GapLLMResult) -> dict:
    return {
        "id": str(r.id),
        "query_id": str(r.query_id),
        "provider": r.provider,
        "model": r.model,
        "answer_text": r.answer_text,
        "cited_urls": r.cited_urls,
        "cited_domains": r.cited_domains,
        "mentions_our_brand": r.mentions_our_brand,
        "web_search_used": r.web_search_used,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "cost_usd": r.cost_usd,
        "latency_ms": r.latency_ms,
        "cached": r.cached,
        "error": r.error,
    }


def _serialize_serp_result(r: GapSerpResult) -> dict:
    return {
        "id": str(r.id),
        "query_id": str(r.query_id),
        "engine": r.engine,
        "device": r.device,
        "organic": r.organic,
        "featured_snippet": r.featured_snippet,
        "ai_overview": r.ai_overview,
        "people_also_ask": r.people_also_ask,
        "related_searches": r.related_searches,
        "our_position": r.our_position,
        "cached": r.cached,
        "latency_ms": r.latency_ms,
        "error": r.error,
    }


def _serialize_competitor(c: GapCompetitor) -> dict:
    return {
        "id": str(c.id),
        "domain": c.domain,
        "rank": c.rank,
        "score": c.score,
        "llm_citation_count": c.llm_citation_count,
        "serp_appearance_count": c.serp_appearance_count,
        "serp_top3_count": c.serp_top3_count,
        "featured_snippet_count": c.featured_snippet_count,
        "ai_overview_citation_count": c.ai_overview_citation_count,
        "queries_appeared_for": c.queries_appeared_for,
        "score_breakdown": c.score_breakdown,
    }


def _serialize_deep_crawl(c: GapDeepCrawl) -> dict:
    return {
        "id": str(c.id),
        "competitor_id": str(c.competitor_id) if c.competitor_id else None,
        "domain": c.domain,
        "is_us": c.is_us,
        "sitemap_url_count": c.sitemap_url_count,
        "pages_attempted": c.pages_attempted,
        "pages_ok": c.pages_ok,
        "profile": c.profile,
        "error": c.error,
    }


def _serialize_comparison(c: GapComparison) -> dict:
    return {
        "id": str(c.id),
        "dimension": c.dimension,
        "severity": c.severity,
        "headline": c.headline,
        "our_value": c.our_value,
        "competitor_median": c.competitor_median,
        "delta": c.delta,
        "evidence": c.evidence,
        "priority": c.priority,
    }


def _serialize_run_header(run: GapPipelineRun) -> dict:
    return {
        "id": str(run.id),
        "domain": run.domain,
        "status": run.status,
        "triggered_by": run.triggered_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "query_count": run.query_count,
        "seed_keyword_count": run.seed_keyword_count,
        "llm_provider_count": run.llm_provider_count,
        "llm_call_count": run.llm_call_count,
        "llm_total_cost_usd": run.llm_total_cost_usd,
        "serp_engine_count": run.serp_engine_count,
        "serp_call_count": run.serp_call_count,
        "competitor_count": run.competitor_count,
        "deep_crawl_pages": run.deep_crawl_pages,
        "stage_status": run.stage_status,
        "config_snapshot": run.config_snapshot,
        "error": run.error,
    }


@api_view(["POST"])
def gap_pipeline_start(request: Request):
    """Kick off a gap detection pipeline run.

    Body: ``{"domain": "bajajlifeinsurance.com", "sync": false,
    "top_n": 10, "query_count": 24}``. ``sync`` runs inline for dev;
    default path enqueues a Celery task and returns 202 with the run
    id for the client to poll.
    """
    body = request.data or {}
    domain = (body.get("domain") or "").strip()
    if not domain:
        return Response(
            {"detail": "domain is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    sync = bool(body.get("sync"))
    top_n = max(1, min(int(body.get("top_n") or 10), 20))
    query_count = max(8, min(int(body.get("query_count") or 24), 40))

    run = GapPipelineRun.objects.create(domain=domain, triggered_by="api")
    run.config_snapshot = {
        "top_n": top_n,
        "query_count": query_count,
        "domain": domain,
    }
    run.save(update_fields=["config_snapshot"])

    if sync:
        from .gap_pipeline.orchestrator import GapPipelineOrchestrator

        try:
            GapPipelineOrchestrator(run).execute(
                top_n=top_n, query_count=query_count
            )
        except Exception as exc:  # noqa: BLE001 - surface to client
            return Response(
                {"id": str(run.id), "status": "failed", "detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(_serialize_run_header(run))

    run_gap_pipeline_task.delay(
        str(run.id), top_n=top_n, query_count=query_count
    )
    return Response(
        {"id": str(run.id), "status": run.status},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["GET"])
def gap_pipeline_status(request: Request, run_id: str):
    """Lightweight status endpoint for polling.

    Returns just the run header (status + counters + stage_status JSON),
    not the full child-table payload. The frontend polls this on a 3-5
    second interval while the run is in progress, and switches to the
    full-detail endpoint once status hits a terminal state.
    """
    try:
        run = GapPipelineRun.objects.get(pk=run_id)
    except GapPipelineRun.DoesNotExist:
        return Response(
            {"detail": "run not found"}, status=status.HTTP_404_NOT_FOUND
        )
    return Response(_serialize_run_header(run))


@api_view(["GET"])
def gap_pipeline_detail(request: Request, run_id: str):
    """Full pipeline payload — run header + every child table.

    This is the endpoint the UI uses to render the 6 stage panels. It
    can be heavy (hundreds of LLM/SERP rows), so the frontend only hits
    it after the run reaches a terminal state — or on a slower interval
    while running for incremental refresh.
    """
    try:
        run = GapPipelineRun.objects.get(pk=run_id)
    except GapPipelineRun.DoesNotExist:
        return Response(
            {"detail": "run not found"}, status=status.HTTP_404_NOT_FOUND
        )

    payload = _serialize_run_header(run)
    payload["queries"] = [
        _serialize_query(q) for q in run.queries.all().order_by("order")
    ]
    payload["llm_results"] = [
        _serialize_llm_result(r) for r in run.llm_results.all()
    ]
    payload["serp_results"] = [
        _serialize_serp_result(r) for r in run.serp_results.all()
    ]
    payload["competitors"] = [
        _serialize_competitor(c) for c in run.competitors.all().order_by("rank")
    ]
    payload["deep_crawls"] = [
        _serialize_deep_crawl(c) for c in run.deep_crawls.all()
    ]
    payload["comparisons"] = [
        _serialize_comparison(c) for c in run.comparisons.all().order_by("-priority")
    ]
    return Response(payload)


@api_view(["GET"])
def gap_pipeline_latest(request: Request):
    """Return the most-recent run for a domain (or null payload).

    The frontend opens the Competitors page and calls this first — if a
    recent run exists it renders straight away; if not, the user clicks
    "Run pipeline" to trigger ``gap_pipeline_start``.
    """
    domain = request.query_params.get("domain") or "bajajlifeinsurance.com"
    run = (
        GapPipelineRun.objects.filter(domain=domain)
        .order_by("-started_at")
        .first()
    )
    if run is None:
        return Response({"available": False, "domain": domain})
    payload = {"available": True, **_serialize_run_header(run)}
    return Response(payload)


# ── content comparison (AEM ↔ competitor crawler) ────────────────────────
#
# Two endpoints pair our authored content (from the AEM JSON export) with
# the topically-closest page each competitor has, so the operator can read
# both bodies side-by-side. Pure-string matcher (page_pairing.py), no LLM
# call anywhere — billing not required.
#
#   GET /api/v1/seo-ai/content-comparison/our-pages/?q=&limit=
#       Lightweight list of AEM pages for the dropdown picker.
#   GET /api/v1/seo-ai/content-comparison/?our_url=<aem_public_url>
#       Full payload: our AEM page + ranked competitor match per rival.


def _aem_index_by_url() -> dict:
    """Build a {public_url: AEMPage} index. Lazy + per-request.

    The AEM JSON exports rarely top a few thousand pages and the read is
    plenty fast (~50 ms), so we don't bother caching — keeps the view
    stateless and always reflects the latest sitemap drop on disk.
    """
    adapter = SitemapAEMAdapter()
    return {p.public_url: p for p in adapter.iter_pages()}


def _serialize_our_page(page) -> dict:
    """Trim AEMPage to the JSON-safe shape the frontend renders."""
    last_mod = page.last_modified.isoformat() if page.last_modified else None
    return {
        "url": page.public_url,
        "aem_path": page.aem_path,
        "title": page.title,
        "meta_description": page.description,
        "template_name": page.template_name,
        "last_modified": last_mod,
        "component_count": page.component_count,
        "component_types": page.component_types,
        "word_count": page.word_count,
        "content": page.content,
    }


def _serialize_their_page(cand: dict) -> dict:
    """Pass through the sample_pages entry from GapDeepCrawl.profile.

    The deep_crawl _build_profile already shapes this dict; we just
    re-emit it under a stable key set so the frontend type stays clean.
    """
    return {
        "url": cand.get("url"),
        "title": cand.get("title"),
        "meta_description": cand.get("meta_description") or "",
        "h1_texts": cand.get("h1_texts") or [],
        "h2_texts": cand.get("h2_texts") or [],
        "schema_types": cand.get("schema_types") or [],
        "word_count": cand.get("word_count") or 0,
        "page_type": cand.get("page_type") or "",
        "response_time_ms": cand.get("response_time_ms") or 0,
        "internal_link_count": cand.get("internal_link_count") or 0,
        "external_link_count": cand.get("external_link_count") or 0,
        "last_modified": cand.get("last_modified") or "",
        "body_text": cand.get("body_text") or "",
        "pagespeed_score": cand.get("pagespeed_score"),
        "lcp_ms": cand.get("lcp_ms"),
        "cls": cand.get("cls"),
        "inp_ms": cand.get("inp_ms"),
    }


def _compute_deltas(our_page, their: dict) -> dict:
    """Numerical us-vs-them deltas surfaced at the top of the UI."""
    their_words = int(their.get("word_count") or 0)
    their_schema = list(their.get("schema_types") or [])
    their_score = their.get("pagespeed_score")
    their_lcp = their.get("lcp_ms")

    word_diff = their_words - (our_page.word_count or 0)

    # Our CWV lives in the crawler's CSV, not on the AEM record; we'd need
    # to cross-join to populate "our pagespeed". For v1 of this view we
    # surface only the deltas we can compute from data on hand.
    return {
        "word_count_diff": word_diff,
        "schema_we_lack": their_schema,           # AEM page-model has no
                                                  # schema concept; everything
                                                  # they ship is technically a
                                                  # gap on our side.
        "their_pagespeed": their_score,
        "their_lcp_ms": their_lcp,
    }


@api_view(["GET"])
def content_comparison_our_pages(request: Request):
    """Return a slim list of AEM pages for the dropdown picker.

    Query params:
      ``q`` — case-insensitive substring filter on URL or title.
      ``limit`` — cap on rows returned (default 500, max 2000).

    The body content is NOT included in this response — keep it cheap
    so the dropdown loads fast even on slow connections. The full body
    is fetched only when the user selects a page (the other endpoint).
    """
    q = (request.query_params.get("q") or "").strip().lower()
    try:
        limit = min(max(int(request.query_params.get("limit") or 500), 1), 2000)
    except ValueError:
        limit = 500

    try:
        pages = list(SitemapAEMAdapter().iter_pages())
    except Exception as exc:  # noqa: BLE001
        logger.warning("content_comparison_our_pages: AEM read failed: %s", exc)
        return Response(
            {"available": False, "error": f"AEM read failed: {exc}", "pages": []},
        )

    out = []
    for p in pages:
        if q and q not in (p.public_url or "").lower() and q not in (p.title or "").lower():
            continue
        out.append({
            "url": p.public_url,
            "title": p.title,
            "template_name": p.template_name,
            "word_count": p.word_count,
            "last_modified": p.last_modified.isoformat() if p.last_modified else None,
        })
        if len(out) >= limit:
            break

    return Response({
        "available": True,
        "total": len(pages),
        "returned": len(out),
        "pages": out,
    })


@api_view(["GET"])
def content_comparison(request: Request):
    """Pair one of our AEM pages with every competitor's best match.

    Query params:
      ``our_url`` — required. The AEM public_url to compare from.
      ``domain`` — optional. Defaults to bajajlifeinsurance.com; used to
                  locate the latest GapPipelineRun whose deep crawls
                  hold the competitor candidates.

    Response shape::

        {
          "our_page":   {url, title, meta_description, content, ...},
          "matches":    [{competitor_domain, match_score, reason,
                          their_page: {...}, deltas: {...}}, ...],
          "_meta":      {run_id, matched_at,
                          competitors_with_match, competitors_without_match}
        }
    """
    our_url = (request.query_params.get("our_url") or "").strip()
    if not our_url:
        return Response(
            {"error": "missing required query param: our_url"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Load the AEM index, find our page.
    try:
        aem_index = _aem_index_by_url()
    except Exception as exc:  # noqa: BLE001
        logger.warning("content_comparison: AEM read failed: %s", exc)
        return Response(
            {"error": f"AEM read failed: {exc}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    our_page = aem_index.get(our_url)
    if our_page is None:
        return Response(
            {"error": f"AEM has no page with public_url={our_url}"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Pull the latest gap-pipeline run's deep crawls.
    domain = (request.query_params.get("domain") or "bajajlifeinsurance.com").strip()
    run = (
        GapPipelineRun.objects.filter(domain=domain)
        .order_by("-started_at")
        .first()
    )
    if run is None:
        return Response({
            "our_page": _serialize_our_page(our_page),
            "matches": [],
            "_meta": {
                "run_id": None,
                "competitors_with_match": 0,
                "competitors_without_match": 0,
                "note": "no gap-pipeline run found — start one from the Competitors page",
            },
        })

    crawls = list(
        GapDeepCrawl.objects.filter(run=run, is_us=False).order_by("domain")
    )

    # Lazy import keeps the matcher off the import path until used.
    from .gap_pipeline.page_pairing import match_aem_to_candidates

    matches: list[dict] = []
    with_match = 0
    without_match = 0
    for c in crawls:
        candidates = ((c.profile or {}).get("sample_pages")) or []
        ranked = match_aem_to_candidates(
            our_url=our_page.public_url,
            our_title=our_page.title,
            candidates=candidates,
        )
        if not ranked:
            without_match += 1
            matches.append({
                "competitor_domain": c.domain,
                "match_score": 0.0,
                "match_reason": "no sample pages on this competitor",
                "their_page": None,
                "deltas": None,
            })
            continue
        top = ranked[0]
        with_match += 1
        matches.append({
            "competitor_domain": c.domain,
            "match_score": top.score,
            "slug_jaccard": top.slug_jaccard,
            "title_cosine": top.title_cosine,
            "match_reason": top.reason,
            "their_page": _serialize_their_page(top.candidate),
            "deltas": _compute_deltas(our_page, top.candidate),
            # Surface the next 2 alternatives so the user can swap if
            # the top match looks off.
            "alternatives": [
                {
                    "score": alt.score,
                    "reason": alt.reason,
                    "url": (alt.candidate or {}).get("url"),
                    "title": (alt.candidate or {}).get("title"),
                }
                for alt in ranked[1:3]
            ],
        })

    matches.sort(key=lambda m: m.get("match_score") or 0.0, reverse=True)

    return Response({
        "our_page": _serialize_our_page(our_page),
        "matches": matches,
        "_meta": {
            "run_id": str(run.id),
            "matched_at": run.started_at.isoformat() if run.started_at else None,
            "competitors_with_match": with_match,
            "competitors_without_match": without_match,
        },
    })


# ── Per-competitor + per-URL endpoints (Phase 2) ────────────────────────
#
# Replaces the inline DeepCrawlPanel expandable-rows view with proper
# per-competitor landing pages and per-URL detail pages. Reads the same
# GapDeepCrawl.profile.sample_pages payload already populated by the
# gap pipeline (commit 1f78935 added body_text persistence).
#
#   GET /api/v1/seo-ai/competitor/<domain>/                    landing
#   GET /api/v1/seo-ai/competitor/<domain>/pages/<b64url>/     per-URL
#
# URLs are base64url-encoded path segments so any URL (including ones
# with query strings or special chars) round-trips cleanly through
# Django URL routing without needing query strings.


def _b64url_encode(url: str) -> str:
    """URL-safe base64 encoding without padding — used for per-URL
    routes. Padding-less keeps the URL slug shorter and avoids the `=`
    character that some URL libraries mishandle."""
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def _b64url_decode(b64: str) -> str | None:
    """Reverse of _b64url_encode. Returns None on bad input — callers
    should respond 404 rather than 500."""
    padding = 4 - (len(b64) % 4)
    if padding != 4:
        b64 = b64 + ("=" * padding)
    try:
        return base64.urlsafe_b64decode(b64.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def _normalize_competitor_domain(d: str) -> str:
    """Strip protocol + www prefix + trailing slash so the route param
    matches GapDeepCrawl.domain exactly."""
    d = (d or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\d?\.", "", d)
    return d.split("/")[0]


def _latest_deep_crawl_for(domain: str) -> GapDeepCrawl | None:
    """Most-recent GapDeepCrawl row for a competitor domain across all
    runs. Defensive against ordering quirks: we tier-sort by run start
    time so the freshest snapshot wins."""
    normalized = _normalize_competitor_domain(domain)
    return (
        GapDeepCrawl.objects
        .select_related("run", "competitor")
        .filter(domain=normalized, is_us=False)
        .order_by("-run__started_at")
        .first()
    )


def _build_sample_index(crawl: GapDeepCrawl) -> dict[str, dict]:
    """Map every sample page URL to its dict for O(1) per-URL lookup."""
    samples = (crawl.profile or {}).get("sample_pages") or []
    return {(s.get("url") or "").strip(): s for s in samples if s.get("url")}


def _profile_summary_card(profile: dict) -> dict:
    """Trim the profile JSON to the 12 KPI fields the per-competitor
    landing page renders at the top."""
    if not profile:
        return {}
    return {
        "page_count": profile.get("page_count", 0),
        "ok_count": profile.get("ok_count", 0),
        "avg_word_count": profile.get("avg_word_count", 0),
        "median_word_count": profile.get("median_word_count", 0),
        "avg_response_ms": profile.get("avg_response_ms", 0),
        "schema_pct": profile.get("schema_pct", 0),
        "h1_pct": profile.get("h1_pct", 0),
        "page_types": profile.get("page_types") or {},
        "schema_types": (profile.get("schema_types") or [])[:20],
        "has_pricing_page": profile.get("has_pricing_page", False),
        "has_llms_txt": profile.get("has_llms_txt", False),
        "has_pricing_md": profile.get("has_pricing_md", False),
        "ai_citability_score": profile.get("ai_citability_score", 0),
        # CWV aggregates
        "cwv_pages_count": profile.get("cwv_pages_count", 0),
        "avg_pagespeed_score": profile.get("avg_pagespeed_score", 0),
        "median_lcp_ms": profile.get("median_lcp_ms", 0),
        "median_cls": profile.get("median_cls", 0),
        "median_inp_ms": profile.get("median_inp_ms", 0),
    }


def _slim_sample_for_index(sample: dict) -> dict:
    """Strip body_text from a sample-page dict so the list view stays
    light. Per-URL detail view re-fetches the full body via the second
    endpoint."""
    return {
        "url": sample.get("url"),
        "url_b64": _b64url_encode(sample.get("url") or ""),
        "title": sample.get("title") or "",
        "meta_description": (sample.get("meta_description") or "")[:280],
        "page_type": sample.get("page_type") or "",
        "word_count": sample.get("word_count") or 0,
        "has_schema": sample.get("has_schema", False),
        "schema_types": sample.get("schema_types") or [],
        "response_time_ms": sample.get("response_time_ms") or 0,
        "pagespeed_score": sample.get("pagespeed_score"),
        "lcp_ms": sample.get("lcp_ms"),
        "cls": sample.get("cls"),
        "inp_ms": sample.get("inp_ms"),
        "h1_text": (sample.get("h1_texts") or [None])[0] or "",
        "internal_link_count": sample.get("internal_link_count") or 0,
        "external_link_count": sample.get("external_link_count") or 0,
    }


@api_view(["GET"])
def competitor_detail_view(_request, domain: str):
    """Per-competitor landing page payload.

    Returns:
      - the normalized domain
      - the deep-crawl profile summary (KPIs, page-type breakdown,
        schema coverage, AI citability, CWV aggregates)
      - a slim list of every sample page (URL, title, meta, page_type,
        CWV, etc. — body_text excluded to keep the response under
        ~50 KB even for the 25-page-per-competitor max)
      - the run_id and started_at so the UI can show "based on crawl
        from <date>"

    Returns 404 when we have no GapDeepCrawl for the domain.
    """
    crawl = _latest_deep_crawl_for(domain)
    if crawl is None:
        return Response(
            {
                "error": f"no deep-crawl data for {domain}",
                "hint": "run the gap pipeline first",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    samples = (crawl.profile or {}).get("sample_pages") or []
    return Response({
        "domain": crawl.domain,
        "is_us": crawl.is_us,
        "run_id": str(crawl.run_id),
        "run_started_at": (
            crawl.run.started_at.isoformat() if crawl.run.started_at else None
        ),
        "sitemap_url_count": crawl.sitemap_url_count,
        "pages_attempted": crawl.pages_attempted,
        "pages_ok": crawl.pages_ok,
        "profile_summary": _profile_summary_card(crawl.profile or {}),
        "sample_pages": [_slim_sample_for_index(s) for s in samples],
        "sample_count": len(samples),
        "error": crawl.error or "",
    })


@api_view(["GET"])
def competitor_page_detail_view(_request, domain: str, url_b64: str):
    """Per-URL detail view payload.

    Returns the full sample-page dict including the body_text that the
    landing endpoint omits. Title, meta, H1/H2 texts, schema types,
    response time, per-URL CWV, internal/external link counts, and the
    full visible body text captured by the competitor crawler.

    404 when:
      - the domain has no deep crawl (same as the landing endpoint)
      - the base64 segment doesn't decode to a valid URL
      - that URL isn't in this competitor's sample_pages
    """
    decoded = _b64url_decode(url_b64)
    if decoded is None:
        return Response(
            {"error": "invalid base64url segment"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    crawl = _latest_deep_crawl_for(domain)
    if crawl is None:
        return Response(
            {
                "error": f"no deep-crawl data for {domain}",
                "hint": "run the gap pipeline first",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    index = _build_sample_index(crawl)
    sample = index.get(decoded.strip())
    if sample is None:
        return Response(
            {
                "error": f"URL {decoded} not in {crawl.domain}'s sample pages",
                "available_urls": list(index.keys())[:5],
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response({
        "domain": crawl.domain,
        "url": sample.get("url"),
        "url_b64": url_b64,
        "title": sample.get("title") or "",
        "meta_description": sample.get("meta_description") or "",
        "h1_texts": sample.get("h1_texts") or [],
        "h2_texts": sample.get("h2_texts") or [],
        "schema_types": sample.get("schema_types") or [],
        "word_count": sample.get("word_count") or 0,
        "has_schema": sample.get("has_schema", False),
        "page_type": sample.get("page_type") or "",
        "response_time_ms": sample.get("response_time_ms") or 0,
        "internal_link_count": sample.get("internal_link_count") or 0,
        "external_link_count": sample.get("external_link_count") or 0,
        "last_modified": sample.get("last_modified") or "",
        "body_text": sample.get("body_text") or "",
        "pagespeed_score": sample.get("pagespeed_score"),
        "lcp_ms": sample.get("lcp_ms"),
        "cls": sample.get("cls"),
        "inp_ms": sample.get("inp_ms"),
        "run_id": str(crawl.run_id),
        "run_started_at": (
            crawl.run.started_at.isoformat() if crawl.run.started_at else None
        ),
    })


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
