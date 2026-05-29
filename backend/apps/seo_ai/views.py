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
from pathlib import Path

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
    """Full GSC dashboard payload — every CSV under backend/data/gsc/
    surfaced for the seven-tab UI.

    Strictly file-backed. Never issues a live Search Console API call.
    Refreshing the underlying CSVs is ``backend/scripts/gsc_pull.py``'s
    job — this endpoint just renders what is on disk. Safe to call
    even when operator GSC OAuth access is temporarily revoked.

    Query params:
      * ``limit`` (default 200) — top-N row cap for the big-dim slices
        (top_queries, query_country, query_device, page_country, etc.)
        so the payload stays under ~1 MB even with the full pull.
    """
    sample = int(request.query_params.get("limit") or 200)
    adapter = GSCCSVAdapter()
    try:
        summary = adapter.summary(sample_size=sample)
    except Exception as exc:  # noqa: BLE001 - render empty state
        logger.warning("gsc dashboard failed: %s", exc)
        return Response({"available": False, "error": str(exc)})

    # Daily series for the headline chart. The dedicated overview helper
    # caps to the last 90 days; we additionally expose the full 480-day
    # ``daily_full`` so the Overview tab can show a longer trend.
    daily = read_daily_series(adapter)
    daily_full = [asdict(r) for r in adapter.daily()]

    # ── Segment slices ───────────────────────────────────────────────
    # Each big-dim file is sorted by clicks DESC by the upstream pull,
    # so the first ``limit`` rows are the most-impactful. Daily-cross
    # files are sorted by date and capped at the most recent window
    # to keep the geo / device trend lines lightweight.
    countries = [asdict(r) for r in adapter.countries(limit=sample)]
    devices = [asdict(r) for r in adapter.devices()]
    search_appearances = [asdict(r) for r in adapter.search_appearances()]

    query_country = [asdict(r) for r in adapter.query_country(limit=sample)]
    query_device = [asdict(r) for r in adapter.query_device(limit=sample)]
    page_country = [asdict(r) for r in adapter.page_country(limit=sample)]
    page_device = [asdict(r) for r in adapter.page_device(limit=sample)]

    # Daily geo / device — last 90 days (3 months of trend is plenty
    # for what the UI charts can render). Returns one row per (date,
    # country|device) pair.
    daily_country_window = 90 * 50  # ~50 countries × 90 days max
    daily_device_window = 90 * 4    # 3-4 devices × 90 days
    date_country = [
        asdict(r) for r in adapter.date_country(limit=daily_country_window)
    ]
    date_device = [
        asdict(r) for r in adapter.date_device(limit=daily_device_window)
    ]

    # ── Branded vs unbranded ─────────────────────────────────────────
    branded_split = adapter.branded_split(sample_size=sample)
    branded_payload = {
        "branded_queries": branded_split.branded_queries,
        "unbranded_queries": branded_split.unbranded_queries,
        "branded_clicks": branded_split.branded_clicks,
        "unbranded_clicks": branded_split.unbranded_clicks,
        "branded_impressions": branded_split.branded_impressions,
        "unbranded_impressions": branded_split.unbranded_impressions,
        "branded_avg_position": branded_split.branded_avg_position,
        "unbranded_avg_position": branded_split.unbranded_avg_position,
        "branded_ratio_clicks": branded_split.branded_ratio_clicks,
        "branded_ratio_queries": branded_split.branded_ratio_queries,
        "tokens": branded_split.tokens,
        "top_unbranded_queries": [
            asdict(q) for q in branded_split.top_unbranded_queries
        ],
    }

    # ── Image search (real data for Bajaj — "bajaj life logo" pos 5.8) ──
    image_payload = {
        "queries": [asdict(r) for r in adapter.image_queries(limit=sample)],
        "pages": [asdict(r) for r in adapter.image_pages(limit=sample)],
        "countries": [asdict(r) for r in adapter.image_countries(limit=sample)],
        "devices": [asdict(r) for r in adapter.image_devices()],
        "daily": [asdict(r) for r in adapter.image_daily(limit=90)],
    }

    # ── Other surfaces (mostly empty for Bajaj — still exposed) ──────
    other_surfaces = {
        "news_daily": [asdict(r) for r in adapter.news_daily()],
        "discover_daily": [asdict(r) for r in adapter.discover_daily()],
        "video_daily": [asdict(r) for r in adapter.video_daily()],
        "google_news_daily": [asdict(r) for r in adapter.google_news_daily()],
    }

    # ── Indexation (manual UI export) ────────────────────────────────
    # The Search Console API can't produce the full Pages / Coverage
    # report at the same fidelity; the manual CSV export under
    # coverage/_gsc_export_* is the source of truth for issues like
    # "Crawled - currently not indexed".
    idx = adapter.indexation_report()
    if idx is not None:
        indexation = {
            "available": True,
            "export_dir": idx.export_dir,
            "critical_issues": [asdict(i) for i in idx.critical_issues],
            "noncritical_issues": [asdict(i) for i in idx.noncritical_issues],
            "chart": [asdict(p) for p in idx.chart],
            "latest_indexed": idx.latest_indexed,
            "latest_not_indexed": idx.latest_not_indexed,
            "latest_impressions": idx.latest_impressions,
            "metadata": idx.metadata,
        }
    else:
        indexation = {"available": False}

    # ── Sitemaps + sites verification ───────────────────────────────
    sitemaps = [asdict(s) for s in adapter.sitemaps()]
    available_files = adapter.available_files()

    return Response(
        {
            "available": True,
            "snapshot_path": summary.snapshot_path,
            # Strictly file-backed — surfaced so the UI can show
            # "Last pulled: <mtime>" + a banner when stale.
            "live_api_calls": False,
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
            "daily_full": daily_full,
            "branded_split": branded_payload,
            "countries": countries,
            "devices": devices,
            "search_appearances": search_appearances,
            "query_country": query_country,
            "query_device": query_device,
            "page_country": page_country,
            "page_device": page_device,
            "date_country": date_country,
            "date_device": date_device,
            "image": image_payload,
            "other_surfaces": other_surfaces,
            "indexation": indexation,
            "sitemaps": sitemaps,
            "available_files": available_files,
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

    # ── In-house Bajaj parity ───────────────────────────────────
    # Prepend Bajaj's own brand so the dashboard surfaces "our ads"
    # alongside "their ads". Opt-out via ``?include_ours=false`` for
    # the per-competitor drill-down where Bajaj would be noise.
    include_ours = (
        (request.query_params.get("include_ours") or "true").lower()
        not in ("0", "false", "no")
    )
    if include_ours:
        bajaj_label = (
            request.query_params.get("our_brand")
            or "Bajaj Life Insurance"
        )
        if bajaj_label not in competitors:
            competitors = [bajaj_label] + list(competitors)

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


def _competitor_dashboard_cache_path(domain: str):
    """File-cache location for the competitor_dashboard payload.

    One JSON file per domain under settings.SEO_AI['data_dir'], inside a
    dedicated _competitor_dashboard_cache/ subdir so it's easy to GC
    independent of crawl outputs. Domain is slugified so colons / slashes
    can't escape the cache root.
    """
    from django.conf import settings as _settings

    safe = re.sub(r"[^a-z0-9._-]+", "_", (domain or "").strip().lower()) or "_"
    cache_dir = Path(_settings.SEO_AI["data_dir"]) / "_competitor_dashboard_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{safe}.json"


@api_view(["GET"])
def competitor_dashboard(request: Request):
    """Competitor gap report for a domain — no LLM call, just the
    deterministic facts built by the same machinery the CompetitorAgent
    uses. Heavy on first call (SEMrush + 500-page rival crawl, 3-7 min);
    cached to disk for SEO_AI['competitor_dashboard_cache_ttl_sec']
    (default 7 days) so subsequent loads return in <100ms.

    ``?refresh=true`` forces a rebuild even when cache is fresh.
    """
    import time as _time

    from django.conf import settings as _settings

    domain = request.query_params.get("domain") or "bajajlifeinsurance.com"
    force_refresh = request.query_params.get("refresh", "").lower() in ("1", "true", "yes")

    if not _settings.SEMRUSH.get("api_key"):
        return Response(
            {"available": False, "error": "SEMRUSH_API_KEY not set"}
        )
    if not _settings.COMPETITOR.get("enabled", True):
        return Response(
            {"available": False, "error": "COMPETITOR_ENABLED=false"}
        )

    # File-cache read-through. Stale or missing → fall through to rebuild.
    cache_path = _competitor_dashboard_cache_path(domain)
    ttl_sec = int(_settings.SEO_AI.get("competitor_dashboard_cache_ttl_sec", 7 * 86400))
    if not force_refresh and cache_path.exists():
        try:
            age_sec = _time.time() - cache_path.stat().st_mtime
            if age_sec < ttl_sec:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                cached["_cache"] = {
                    "hit": True,
                    "age_sec": int(age_sec),
                    "ttl_sec": ttl_sec,
                }
                return Response(cached)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("competitor dashboard cache read failed: %s", exc)

    # Build a one-off SEORun-less context. CompetitorAgent.build_facts
    # only uses the run for logging system events; we side-step that
    # by using a transient in-memory SEORun row.
    from .agents.competitor import CompetitorAgent
    from .models import SEORun

    transient: SEORun | None = None
    try:
        transient = SEORun(domain=domain, triggered_by="dashboard")
        transient.id = None
        transient.save()
        agent = CompetitorAgent(run=transient, step_index_start=0)
        facts = agent.build_facts(domain=domain)
    except SemrushError as exc:
        if transient is not None and transient.pk:
            transient.delete()
        return Response({"available": False, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - surface to client
        logger.warning("competitor dashboard failed: %s", exc)
        if transient is not None and transient.pk:
            transient.delete()
        return Response({"available": False, "error": str(exc)})
    # transient stays as audit log; periodic GC can prune later.

    payload = facts.get("competitor", {}) or {}
    payload["available"] = True
    payload["domain"] = domain

    # Best-effort cache write. If write fails the response still returns;
    # next request will just rebuild.
    try:
        cache_path.write_text(json.dumps(payload, default=str), encoding="utf-8")
    except OSError as exc:
        logger.warning("competitor dashboard cache write failed: %s", exc)

    payload["_cache"] = {"hit": False, "age_sec": 0, "ttl_sec": ttl_sec}
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


def _headings_tree_for_sample(sample: dict) -> list:
    """Compute the hierarchical headings tree on demand from a sample's
    flat ``headings`` list. Pre-Phase-I samples have no ``headings``
    field — return an empty tree without crashing."""
    try:
        from .services.custodian import headings_to_tree
        return headings_to_tree(sample.get("headings") or [])
    except Exception:  # noqa: BLE001
        return []


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


# ── BUG-031 fix: read competitor detail from CrawlerPageResult ─────
# Phase G's Scrapy walk writes to CrawlerPageResult / CompetitorPageHistory,
# not to GapDeepCrawl. The helpers below let competitor_detail_view +
# competitor_page_detail_view source from the live tables (5k+ rows)
# instead of the orphan GapDeepCrawl table (~34 stale rows). GapDeepCrawl
# remains the fallback when no CrawlerPageResult data exists for a domain,
# so legacy gap-pipeline outputs still render.


def _latest_competitor_snapshot_for(domain: str):
    """Most-recent COMPLETE competitor snapshot with rows for `domain`.

    Falls back to the latest complete snapshot regardless of pages_ok
    when none have rows (so an empty crawl still surfaces metadata
    instead of 404-ing). Returns None when nothing matches.
    """
    from apps.crawler.models import CrawlSnapshot

    normalized = _normalize_competitor_domain(domain)
    base = CrawlSnapshot.objects.filter(
        kind=CrawlSnapshot.Kind.COMPETITOR,
        status=CrawlSnapshot.Status.COMPLETE,
        target_domain__iexact=normalized,
    ).order_by("-started_at")
    with_pages = base.filter(pages_ok__gt=0).first()
    return with_pages or base.first()


def _h1_text_from_headings(headings_json) -> str:
    """First H1 text from the structural headings list, empty if none."""
    if not headings_json:
        return ""
    for h in headings_json:
        if isinstance(h, dict) and int(h.get("level") or 0) == 1:
            return (h.get("text") or "").strip()
    return ""


def _profile_from_page_results(pages) -> dict:
    """Aggregate CrawlerPageResult rows into the same profile shape that
    GapDeepCrawl.profile carried, so the frontend sees a consistent payload
    regardless of which storage track populated it."""
    pages = list(pages)
    n = len(pages)
    if n == 0:
        return {}

    def _ok(p) -> bool:
        try:
            code = int(p.status_code or 0)
        except (TypeError, ValueError):
            return False
        return 200 <= code < 400

    ok = sum(1 for p in pages if _ok(p))
    word_counts = [int(p.word_count or 0) for p in pages]
    word_counts_sorted = sorted(word_counts)
    response_times = [int(p.response_time_ms or 0) for p in pages if p.response_time_ms]
    has_schema_pages = sum(1 for p in pages if (p.jsonld_count or 0) > 0)
    h1_pages = sum(1 for p in pages if (p.h1_count or 0) > 0)

    page_types: dict[str, int] = {}
    schema_types_set: set[str] = set()
    for p in pages:
        pt = (p.page_type or "").strip() or "unknown"
        page_types[pt] = page_types.get(pt, 0) + 1
        for t in (p.jsonld_types or []):
            if t:
                schema_types_set.add(str(t))

    # PSI / CWV — prefer mobile_* (CrUX-backed), fall back to legacy *_ms.
    def _mobile_or_legacy(p, mobile_attr: str, legacy_attr: str):
        v = getattr(p, mobile_attr, None)
        if v is not None:
            return v
        return getattr(p, legacy_attr, None)

    pagespeed_vals = [
        _mobile_or_legacy(p, "mobile_pagespeed_score", "pagespeed_score")
        for p in pages
    ]
    pagespeed_vals = [v for v in pagespeed_vals if v is not None]
    lcp_vals = [_mobile_or_legacy(p, "mobile_lcp_ms", "lcp_ms") for p in pages]
    lcp_vals = [v for v in lcp_vals if v is not None]
    cls_vals = [_mobile_or_legacy(p, "mobile_cls", "cls") for p in pages]
    cls_vals = [v for v in cls_vals if v is not None]
    inp_vals = [_mobile_or_legacy(p, "mobile_inp_ms", "inp_ms") for p in pages]
    inp_vals = [v for v in inp_vals if v is not None]

    def _median(vs):
        if not vs:
            return 0
        s = sorted(vs)
        return s[len(s) // 2]

    pricing_signals = [p for p in pages if "/pricing" in (p.url or "").lower()]
    llms_signals = [p for p in pages if (p.url or "").lower().rstrip("/").endswith("/llms.txt")]

    return {
        "page_count": n,
        "ok_count": ok,
        "avg_word_count": round(sum(word_counts) / n) if n else 0,
        "median_word_count": word_counts_sorted[n // 2] if n else 0,
        "avg_response_ms": (
            round(sum(response_times) / len(response_times))
            if response_times else 0
        ),
        "schema_pct": round(100 * has_schema_pages / n) if n else 0,
        "h1_pct": round(100 * h1_pages / n) if n else 0,
        "page_types": page_types,
        "schema_types": sorted(schema_types_set)[:20],
        "has_pricing_page": bool(pricing_signals),
        "has_llms_txt": bool(llms_signals),
        # has_pricing_md isn't a direct CrawlerPageResult signal — preserve
        # the field for shape parity but leave it False unless a future
        # crawler stamps it explicitly.
        "has_pricing_md": False,
        # Simple AI-citability proxy: schema% + has_llms_txt + heading
        # coverage, scaled to 100. The original GapDeepCrawl figure used
        # a deeper scorer; this stand-in keeps the UI tile populated.
        "ai_citability_score": min(
            100,
            round(
                (has_schema_pages / n * 50 if n else 0)
                + (h1_pages / n * 30 if n else 0)
                + (20 if llms_signals else 0)
            ),
        ),
        "cwv_pages_count": len(pagespeed_vals),
        "avg_pagespeed_score": (
            round(sum(pagespeed_vals) / len(pagespeed_vals))
            if pagespeed_vals else 0
        ),
        "median_lcp_ms": _median(lcp_vals),
        "median_cls": round(_median(cls_vals), 3) if cls_vals else 0,
        "median_inp_ms": _median(inp_vals),
    }


def _slim_page_from_result(p) -> dict:
    """Sample-page summary derived from a CrawlerPageResult row.

    Mirrors the dict shape that _slim_sample_for_index used to build
    from the GapDeepCrawl JSON blob.
    """
    h1_text = _h1_text_from_headings(p.headings_json)
    return {
        "url": p.url,
        "url_b64": _b64url_encode(p.url or ""),
        "title": p.title or "",
        "meta_description": (p.meta_description or "")[:280],
        "page_type": p.page_type or "",
        "word_count": int(p.word_count or 0),
        "has_schema": bool(p.jsonld_count or 0),
        "schema_types": list(p.jsonld_types or []),
        "response_time_ms": int(p.response_time_ms or 0),
        "pagespeed_score": p.mobile_pagespeed_score or p.pagespeed_score,
        "lcp_ms": p.mobile_lcp_ms or p.lcp_ms,
        "cls": p.mobile_cls if p.mobile_cls is not None else p.cls,
        "inp_ms": p.mobile_inp_ms or p.inp_ms,
        "h1_text": h1_text,
        "internal_link_count": len(p.internal_links_json or []),
        "external_link_count": len(p.external_links_json or []),
    }


def _full_page_from_result(p, snap) -> dict:
    """Full per-URL detail derived from a CrawlerPageResult row.

    Mirrors the dict shape the legacy GapDeepCrawl-backed endpoint built.
    """
    headings = p.headings_json or []
    h1_texts = [
        (h.get("text") or "").strip()
        for h in headings
        if isinstance(h, dict) and int(h.get("level") or 0) == 1
    ]
    h2_texts = [
        (h.get("text") or "").strip()
        for h in headings
        if isinstance(h, dict) and int(h.get("level") or 0) == 2
    ]
    sample_for_tree = {"headings": headings}
    return {
        "domain": snap.target_domain,
        "url": p.url,
        "url_b64": _b64url_encode(p.url or ""),
        "title": p.title or "",
        "meta_description": p.meta_description or "",
        "h1_texts": h1_texts,
        "h2_texts": h2_texts,
        "schema_types": list(p.jsonld_types or []),
        "word_count": int(p.word_count or 0),
        "has_schema": bool(p.jsonld_count or 0),
        "page_type": p.page_type or "",
        "response_time_ms": int(p.response_time_ms or 0),
        "internal_link_count": len(p.internal_links_json or []),
        "external_link_count": len(p.external_links_json or []),
        "last_modified": "",
        "body_text": p.body_text or "",
        "pagespeed_score": p.mobile_pagespeed_score or p.pagespeed_score,
        "lcp_ms": p.mobile_lcp_ms or p.lcp_ms,
        "cls": p.mobile_cls if p.mobile_cls is not None else p.cls,
        "inp_ms": p.mobile_inp_ms or p.inp_ms,
        "headings": headings,
        "headings_tree": _headings_tree_for_sample(sample_for_tree),
        "internal_links": p.internal_links_json or [],
        "external_links": p.external_links_json or [],
        "images": p.images_json or [],
        "videos": getattr(p, "videos_json", None) or [],
        "run_id": str(snap.id),
        "run_started_at": (
            snap.started_at.isoformat() if snap.started_at else None
        ),
    }


@api_view(["GET"])
def competitor_keywords_semrush_view(_request, domain: str):
    """Authoritative ranking keywords for a competitor — pulled from
    Semrush ``domain_organic`` and disk-cached so repeat dashboard
    visits don't burn API credit.

    Returns ``{available, count, keywords: [{keyword, position, ...}]}``.
    Graceful on missing API key / Semrush outage — sets
    ``available: false`` with an explanatory ``error`` field instead of
    500-ing the dashboard tile.
    """
    from .adapters.semrush import SemrushAdapter, SemrushError

    target = _normalize_competitor_domain(domain)
    if not target:
        return Response({"error": "invalid domain"}, status=400)

    try:
        adapter = SemrushAdapter()
    except Exception as exc:  # noqa: BLE001 — config / key missing
        return Response({
            "available": False,
            "domain": target,
            "count": 0,
            "keywords": [],
            "error": f"semrush unavailable: {exc}",
        })

    try:
        rows = adapter.organic_keywords(target, limit=100)
    except SemrushError as exc:
        return Response({
            "available": False,
            "domain": target,
            "count": 0,
            "keywords": [],
            "error": f"semrush call failed: {exc}",
        })
    except Exception as exc:  # noqa: BLE001
        return Response({
            "available": False,
            "domain": target,
            "count": 0,
            "keywords": [],
            "error": f"semrush call crashed: {exc}",
        })

    keywords = [
        {
            "keyword": k.keyword,
            "position": k.position,
            "previous_position": k.previous_position,
            "search_volume": k.search_volume,
            "cpc": k.cpc,
            "competition": k.competition,
            "traffic_pct": k.traffic_pct,
            "url": k.url,
        }
        for k in rows
    ]
    return Response({
        "available": True,
        "domain": target,
        "count": len(keywords),
        "keywords": keywords,
    })


@api_view(["GET"])
def competitor_keywords_content_view(_request, domain: str):
    """Derived "what this competitor writes about" keywords — TF-IDF
    over their latest snapshot's CrawlerPageResult rows (plus rows from
    every subdomain that shares the same registrable parent, so the
    rollup matches the consolidated Crawled-competitors table).

    No external API. Pure rule-based / sklearn. Reasonable for first-
    minute dashboard loads — TF-IDF over 2000 pages runs in ~300ms.
    """
    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult
    from apps.crawler.util.host import apex
    from .keywords.content_keywords import extract_content_keywords

    target = _normalize_competitor_domain(domain)
    if not target:
        return Response({"error": "invalid domain"}, status=400)
    parent = apex(target)

    # Collect every competitor snapshot under the same parent brand. For
    # each subdomain, take only its latest snapshot so we don't double-
    # count historical revisions.
    candidates = (
        CrawlSnapshot.objects
        .filter(kind="competitor", parent_domain=parent)
        .exclude(status="failed")
        .order_by("target_domain", "-started_at")
    )
    seen_subs: set[str] = set()
    snapshot_ids: list[str] = []
    for snap in candidates:
        sub = (snap.target_domain or "").lower()
        if not sub or sub in seen_subs:
            continue
        seen_subs.add(sub)
        snapshot_ids.append(snap.id)

    if not snapshot_ids:
        return Response({
            "available": False,
            "domain": target,
            "parent_domain": parent,
            "count": 0,
            "keywords": [],
            "error": (
                "no snapshot found for this brand — run the competitor "
                "walk first"
            ),
        })

    rows_qs = (
        CrawlerPageResult.objects
        .filter(snapshot_id__in=snapshot_ids, status_code="200")
        .only(
            "url", "title", "meta_description",
            "headings_json", "body_text",
        )
    )
    rows = [
        {
            "url": r.url,
            "title": r.title or "",
            "meta_description": r.meta_description or "",
            "headings_json": r.headings_json or [],
            "body_text": r.body_text or "",
        }
        for r in rows_qs.iterator()
    ]

    try:
        keywords = extract_content_keywords(rows, top_k=50)
    except RuntimeError as exc:
        return Response({
            "available": False,
            "domain": target,
            "parent_domain": parent,
            "count": 0,
            "keywords": [],
            "error": f"content TF-IDF unavailable: {exc}",
        })

    return Response({
        "available": True,
        "domain": target,
        "parent_domain": parent,
        "subdomain_count": len(seen_subs),
        "page_count": len(rows),
        "count": len(keywords),
        "keywords": keywords,
    })


@api_view(["GET"])
def page_topic_sections_view(_request, snapshot_id: str, url_b64: str):
    """LLM-clustered topical sections WITHIN one page.

    Different from ``page_clusters_view`` (which clusters chunks of a
    page via KMeans on sentence-transformer vectors) and from
    ``competitor_page_structure_view`` (which clusters a brand's PAGES).

    This identifies the topical sections inside one page — Calculator
    widget, Tax-Benefits, FAQ block, Plan-Comparison table, CTAs — by
    asking the LLM to group the page's headings into 5-10 named
    sections, attaching the section's internal-links + image counts.

    Used by the Content Writer revamp page to render section-by-section
    comparison between our page and each matched competitor page.

    Disk-cached 24 h per (snapshot, url).
    """
    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult
    from .services.page_topic_sections import (
        _to_dict, build_page_topic_sections,
    )

    snap = CrawlSnapshot.objects.filter(id=snapshot_id).first()
    if snap is None:
        return Response(
            {"error": f"snapshot {snapshot_id} not found"},
            status=status.HTTP_404_NOT_FOUND,
        )
    decoded = _b64url_decode(url_b64)
    if decoded is None:
        return Response(
            {"error": "invalid base64url segment"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    page = CrawlerPageResult.objects.filter(
        snapshot=snap, url=decoded.strip(),
    ).first()
    if page is None:
        return Response(
            {"error": f"URL {decoded} not in snapshot {snapshot_id}"},
            status=status.HTTP_404_NOT_FOUND,
        )

    result = build_page_topic_sections(page=page)
    return Response(_to_dict(result))


@api_view(["GET"])
def competitor_page_structure_view(request, domain: str):
    """LLM-clustered view of a competitor's pages.

    Counterpart to ``page_clusters_view`` (which clusters chunks of ONE
    page) — this clusters all of a competitor's pages into 5-10 named
    topical groups using the LLM (not sentence-transformers). Each
    page in a cluster carries a ``source`` blob (snapshot id + kind +
    engine + started_at + crawl_mode) so the operator can see which
    crawl produced which row.

    Query params:
      max_pages    — top-N by word_count to send to the LLM (default 60).
      force        — '1' to bypass the 24-h disk cache.
    """
    from .services.competitor_clustering import (
        _to_dict, build_competitor_page_structure,
    )

    target = _normalize_competitor_domain(domain)
    if not target:
        return Response({"error": "invalid domain"}, status=400)

    try:
        max_pages = max(20, min(120, int(
            request.query_params.get("max_pages") or 60,
        )))
    except (TypeError, ValueError):
        max_pages = 60
    force = (request.query_params.get("force") or "").lower() in (
        "1", "true", "yes",
    )

    result = build_competitor_page_structure(
        domain=target, max_pages=max_pages, force_refresh=force,
    )
    return Response(_to_dict(result))


@api_view(["GET", "POST"])
def competitor_walk_pause_view(request):
    """GET/POST the competitor-walk pause toggle.

    GET returns ``{paused: bool, updated_at: <iso>}``. POST with body
    ``{"paused": true|false}`` flips the toggle. When paused, the
    03:00 IST ``walk_competitor_roster_task`` returns early instead of
    walking the roster — the dashboard "Pause crawls" switch hits this.
    """
    from apps.crawler.models import SystemSetting

    if request.method == "GET":
        row = SystemSetting.objects.filter(pk="competitor_walk_paused").first()
        paused = SystemSetting.get_bool(
            "competitor_walk_paused", default=False,
        )
        return Response({
            "paused": paused,
            "updated_at": (
                row.updated_at.isoformat() if row and row.updated_at else None
            ),
        })

    # POST — flip the flag.
    raw = request.data.get("paused")
    if raw is None:
        return Response(
            {"error": "body must include 'paused': true|false"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    new_value = bool(raw)
    SystemSetting.set_value("competitor_walk_paused", new_value)
    return Response({"paused": new_value})


@api_view(["GET"])
def competitor_crawls_list_view(_request):
    """List every competitor domain we've crawled (or are currently
    crawling) via the Phase G Scrapy walk. One row per ``target_domain``,
    freshest snapshot wins regardless of completion state.

    Includes both ``status='running'`` and ``status='complete'`` so the
    dashboard reflects live progress as pages stream in — the previous
    behaviour required ``status='complete'`` and showed nothing during
    active overnight crawls.

    Each row carries the *live* page count from CrawlerPageResult (not
    just ``snap.pages_attempted`` which only updates when the spider
    closes) so the operator sees real-time growth.

    Does NOT include the in-house Bajaj crawl (kind=BAJAJ).
    """
    from collections import defaultdict

    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult
    from django.db.models import Count

    from .models import CompetitorChangeEvent

    # Latest snapshot per target_domain — running OR complete. Failed
    # snapshots are excluded so a half-dead retry doesn't shadow a
    # successful older crawl.
    # Also exclude any row whose target_domain is bajajlifeinsurance.com
    # (or a subdomain of it) — historical crawls misclassified our own
    # site as kind='competitor', and the operator doesn't want to see
    # Bajaj in the competitor list.
    qs = (
        CrawlSnapshot.objects
        .filter(kind=CrawlSnapshot.Kind.COMPETITOR)
        .exclude(status=CrawlSnapshot.Status.FAILED)
        .exclude(parent_domain="bajajlifeinsurance.com")
        .order_by("-started_at")
    )

    latest_by_domain: dict[str, CrawlSnapshot] = {}
    for snap in qs:
        td = (snap.target_domain or "").strip().lower()
        if not td or td in latest_by_domain:
            continue
        latest_by_domain[td] = snap

    if not latest_by_domain:
        return Response({"competitors": [], "count": 0})

    snapshot_ids = [s.id for s in latest_by_domain.values()]

    # Live page count per snapshot — updated row-by-row as the spider
    # writes, so a running crawl ticks up in the UI poll.
    page_counts = dict(
        CrawlerPageResult.objects
        .filter(snapshot_id__in=snapshot_ids)
        .values_list("snapshot_id")
        .annotate(n=Count("id"))
    )

    # Change-event totals per competitor (across snapshot history).
    change_counts: dict[str, int] = defaultdict(int)
    for row in (
        CompetitorChangeEvent.objects
        .filter(competitor_domain__in=list(latest_by_domain.keys()))
        .values_list("competitor_domain")
        .annotate(n=Count("id"))
    ):
        change_counts[row[0]] = row[1]

    # Apex helper so the frontend can group `auth.hdfclife.com` etc. under
    # the parent `hdfclife.com`. Prefer the denormalized column written by
    # CrawlSnapshot.save(); fall back to recomputing for rows older than
    # the 0014 migration (defensive — the migration backfills, but a row
    # that hasn't been saved since could lag).
    from apps.crawler.util.host import apex

    rows = []
    for td, snap in sorted(latest_by_domain.items()):
        parent = (snap.parent_domain or "").strip().lower() or apex(td)
        rows.append({
            "domain": td,
            "parent_domain": parent,
            "snapshot_id": str(snap.id),
            "status": snap.status,
            "started_at": (
                snap.started_at.isoformat() if snap.started_at else None
            ),
            "finished_at": (
                snap.finished_at.isoformat()
                if getattr(snap, "finished_at", None) else None
            ),
            "pages_attempted": snap.pages_attempted,
            "pages_ok": snap.pages_ok,
            "pages_in_db": page_counts.get(snap.id, 0),
            "change_events": change_counts.get(td, 0),
            "notes": (snap.notes or "")[:160],
        })

    return Response({"competitors": rows, "count": len(rows)})


@api_view(["GET"])
def competitor_detail_view(_request, domain: str):
    """Per-competitor landing page payload.

    Sources from CrawlerPageResult first (Phase G Scrapy walk output) and
    falls back to the legacy GapDeepCrawl table when no CrawlerPageResult
    snapshot exists for the domain. Either way the response shape is
    identical so the frontend hook doesn't care which storage track served.

    Returns 404 only when neither storage has anything for the domain.
    """
    from apps.crawler.models import CrawlerPageResult

    snap = _latest_competitor_snapshot_for(domain)
    if snap is not None:
        pages = list(CrawlerPageResult.objects.filter(snapshot=snap))
        if pages:
            profile = _profile_from_page_results(pages)
            return Response({
                "domain": snap.target_domain,
                "is_us": False,
                "run_id": str(snap.id),
                "run_started_at": (
                    snap.started_at.isoformat() if snap.started_at else None
                ),
                "sitemap_url_count": (
                    len(snap.allowed_domains or [])
                    if hasattr(snap, "allowed_domains") else 0
                ),
                "pages_attempted": snap.pages_attempted,
                "pages_ok": snap.pages_ok,
                "profile_summary": profile,
                "sample_pages": [_slim_page_from_result(p) for p in pages],
                "sample_count": len(pages),
                "error": "",
            })

    # Fallback — legacy GapDeepCrawl path. Kept so old gap-pipeline runs
    # still render until they age out.
    crawl = _latest_deep_crawl_for(domain)
    if crawl is None:
        return Response(
            {
                "error": f"no crawl data for {domain}",
                "hint": (
                    "no CrawlSnapshot or GapDeepCrawl rows match this "
                    "domain — trigger the daily competitor walk or "
                    "/api/v1/seo/gap-pipeline/start/ to populate"
                ),
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


def _clean_chunk_preview(text: str, max_chars: int = 280) -> str:
    """Snap chunk text to word boundaries for human display.

    The embedder chunker splits on raw chars (intentional for cosine
    similarity), so chunks usually start mid-word ("olicy" instead of
    "Policy") and end mid-sentence. That's fine for vector math but
    ugly to read in the UI. We trim leading + trailing partial words
    so the preview looks like a clean snippet.
    """
    if not text:
        return ""
    t = text.strip()
    # Drop leading partial word: if first char is lowercase (likely a
    # cut-off mid-word) AND a space exists within the first 40 chars,
    # skip to that space. We keep proper-nouned starts intact.
    if t and t[0].islower():
        sp = t.find(" ")
        if 0 < sp < 40:
            t = t[sp + 1 :].lstrip()
    if len(t) > max_chars:
        cut = t[:max_chars]
        last_space = cut.rfind(" ")
        if last_space > max_chars * 0.6:
            t = cut[:last_space].rstrip()
        else:
            t = cut.rstrip()
        t += "…"
    return t


def _topic_cluster_chunks(chunks: list[dict], vectors: list[list[float]]) -> list[dict]:
    """Cluster a single page's chunks by topical similarity and label
    each cluster from its own dominant TF-IDF terms.

    The rule classifier (``classify_row``) labels each chunk by the
    page-level URL/title — so on a homepage every chunk inherits
    page_type="home" with no products, which is useless for "what does
    this page cover" analysis. We re-cluster the chunk vectors with
    KMeans and derive a label per cluster from its TF-IDF top terms.

    k is picked heuristically — ``n_chunks // 14``, clamped to [3, 10].
    Sufficient for a long homepage with ~100 chunks (yields ~7 clusters)
    and degrades gracefully on shorter pages (a 25-chunk product page
    gets k=3).
    """
    n = len(chunks)
    if n < 3:
        return []

    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.feature_extraction import _stop_words as _sw_module
    except ImportError:
        return []

    # Sanity-check vector shape — skip clustering if vectors are missing
    # or jagged (e.g. mid-migration data).
    if not vectors or not vectors[0]:
        return []
    try:
        X = np.asarray(vectors, dtype=np.float32)
    except (TypeError, ValueError):
        return []
    if X.ndim != 2 or X.shape[0] != n:
        return []

    k = max(3, min(10, n // 14))
    try:
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
    except Exception:  # noqa: BLE001
        return []
    labels = km.labels_

    # Build per-cluster TF-IDF over chunk text — gives us auto-derived
    # topic labels ("term insurance", "tax saving", "retirement
    # calculator") instead of relying on the page-level classifier.
    from .keywords.content_keywords import (
        DOMAIN_STOPWORDS, SEARCH_INTENT_TERMS,
    )
    stop = set(_sw_module.ENGLISH_STOP_WORDS) | DOMAIN_STOPWORDS

    docs_per_cluster: dict[int, list[str]] = {}
    indices_per_cluster: dict[int, list[int]] = {}
    for i, c in enumerate(chunks):
        cid = int(labels[i])
        docs_per_cluster.setdefault(cid, []).append(c["text"] or "")
        indices_per_cluster.setdefault(cid, []).append(i)

    # Discriminative TF-IDF: one document per cluster, not per chunk.
    # This surfaces terms UNIQUE to each cluster (high tf in this doc,
    # low df across all clusters), so labels don't all start with the
    # corpus-wide "insurance" / "plan" noise.
    cluster_ids = sorted(docs_per_cluster.keys())
    cluster_docs = [" ".join(docs_per_cluster[cid]) for cid in cluster_ids]
    cluster_term_ranking: dict[int, list[str]] = {cid: [] for cid in cluster_ids}
    if cluster_docs:
        try:
            cluster_vec = TfidfVectorizer(
                ngram_range=(1, 3),
                stop_words=list(stop),
                lowercase=True,
                token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]{1,}\b",
                max_features=400,
            )
            ctfidf = cluster_vec.fit_transform(cluster_docs)
        except ValueError:
            ctfidf = None
        else:
            cterms = cluster_vec.get_feature_names_out()
            for row, cid in enumerate(cluster_ids):
                arr = ctfidf.getrow(row).toarray().ravel()
                ranked = sorted(
                    zip(cterms, arr.tolist()),
                    key=lambda x: -x[1],
                )
                # Prefer search-intent-shaped terms but fall back when
                # none rank high.
                with_intent = [
                    t
                    for t, _s in ranked
                    if _s > 0
                    and any(tok in SEARCH_INTENT_TERMS for tok in t.split())
                ]
                fallback = [t for t, _s in ranked if _s > 0]
                cluster_term_ranking[cid] = (with_intent or fallback)[:8]

    out: list[dict] = []
    used_lead_tokens: set[str] = set()  # disambiguate labels across clusters
    for cid in cluster_ids:
        terms = cluster_term_ranking[cid]

        # Label picking with cross-cluster disambiguation: choose the
        # highest-ranked term whose primary token isn't already used
        # as the lead for another cluster. Prefer multi-word terms.
        sorted_terms = sorted(
            terms,
            key=lambda t: (
                # 1. Penalise terms whose tokens are already a lead.
                any(tok in used_lead_tokens for tok in t.split()),
                # 2. Prefer multi-word (more specific) labels.
                " " not in t,
                # 3. Stable original order.
                terms.index(t),
            ),
        )
        lead = sorted_terms[0] if sorted_terms else ""
        lead_tokens = set(lead.split())
        # Secondary: same logic but must not overlap the lead.
        secondary = ""
        for t in sorted_terms[1:]:
            t_tokens = set(t.split())
            if t_tokens & lead_tokens:
                continue
            secondary = t
            break

        used_lead_tokens.update(lead_tokens)
        label = (
            (lead + (" + " + secondary if secondary else "")).title()
            if lead
            else f"Cluster {cid}"
        )

        cluster_indices = indices_per_cluster[cid]
        cluster_vecs = X[cluster_indices]
        centroid = km.cluster_centers_[cid]
        dists = np.linalg.norm(cluster_vecs - centroid, axis=1)
        ordered = [cluster_indices[j] for j in dists.argsort()]

        out.append({
            "cluster_id": cid,
            "label": label,
            "keywords": terms,
            "chunk_count": len(cluster_indices),
            "pct": round(100.0 * len(cluster_indices) / n, 1),
            "sample_chunks": [
                {
                    "chunk_idx": chunks[idx]["chunk_idx"],
                    "text": _clean_chunk_preview(chunks[idx]["text"]),
                }
                for idx in ordered[:3]
            ],
            "chunk_indices": [chunks[idx]["chunk_idx"] for idx in cluster_indices],
        })
    out.sort(key=lambda c: -c["chunk_count"])
    return out


@api_view(["GET"])
def page_clusters_view(_request, snapshot_id: str, url_b64: str):
    """Per-URL content clusters — how this single page's chunks distribute
    across (a) rule-based page-type + product taxonomy, AND (b) auto-
    discovered topical clusters from semantic similarity. Counterpart of
    the corpus-wide content map (/content/map/3d), scoped to one URL.

    Reads PageEmbedding rows for the (snapshot, url) pair and returns:
      - chunks: [{chunk_idx, text, page_type, products, confidence,
                  coord_x, coord_y, coord_z, topic_cluster_id}]
      - page_type_breakdown: [{page_type, label, count, pct}]
      - product_breakdown:   [{product, label, count, pct}]
      - topic_clusters: [{cluster_id, label, keywords, chunk_count, pct,
                          sample_chunks}]  ← auto-discovered topics

    Returns 404 if the URL has no PageEmbedding rows yet (operator needs
    to run refresh_content_map for that snapshot first).
    """
    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult, PageEmbedding
    from apps.crawler.content.taxonomy import (
        PAGE_TYPE_LABELS, PRODUCT_LABELS,
    )

    snap = CrawlSnapshot.objects.filter(id=snapshot_id).first()
    if snap is None:
        return Response(
            {"error": f"snapshot {snapshot_id} not found"},
            status=status.HTTP_404_NOT_FOUND,
        )
    decoded = _b64url_decode(url_b64)
    if decoded is None:
        return Response(
            {"error": "invalid base64url segment"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    page = CrawlerPageResult.objects.filter(
        snapshot=snap, url=decoded.strip(),
    ).first()
    if page is None:
        return Response(
            {"error": f"URL {decoded} not in snapshot {snapshot_id}"},
            status=status.HTTP_404_NOT_FOUND,
        )

    chunks_qs = (
        PageEmbedding.objects
        .filter(page=page)
        .only(
            "chunk_idx", "chunk_text", "products", "page_type",
            "confidence", "coord_x", "coord_y", "coord_z",
            "embedding_json",
        )
        .order_by("chunk_idx")
    )

    # If there are no PageEmbedding rows yet, do a live embed inline
    # rather than asking the operator to run a management command. This
    # is the "fix this for live clustering" path: chunker + MiniLM run
    # synchronously, write rows, then we re-query and proceed. Costs
    # ~5-15 s on the cold path; subsequent loads are instant since the
    # rows now exist.
    if not chunks_qs.exists():
        try:
            from apps.crawler.content.embedder import embed_one_page_live
            wrote = embed_one_page_live(page)
        except Exception as exc:  # noqa: BLE001 — surface as fallback msg
            return Response(
                {
                    "error": (
                        "live embed failed; run `python manage.py "
                        "refresh_content_map` for snapshot "
                        f"{snapshot_id}: {exc}"
                    ),
                    "url": decoded,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if wrote == 0:
            return Response(
                {
                    "error": (
                        "page has no body text to chunk — nothing to "
                        "cluster. Re-crawl the URL first."
                    ),
                    "url": decoded,
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        chunks_qs = (
            PageEmbedding.objects
            .filter(page=page)
            .only(
                "chunk_idx", "chunk_text", "products", "page_type",
                "confidence", "coord_x", "coord_y", "coord_z",
                "embedding_json",
            )
            .order_by("chunk_idx")
        )

    chunks: list[dict] = []
    vectors: list[list[float]] = []
    pt_counter: dict[str, int] = {}
    prod_counter: dict[str, int] = {}
    for c in chunks_qs:
        text_preview = _clean_chunk_preview(c.chunk_text or "")
        products = list(c.products or [])
        chunks.append({
            "chunk_idx": c.chunk_idx,
            "text": text_preview,
            "page_type": c.page_type or "other",
            "products": products,
            "confidence": float(c.confidence or 0.0),
            "coord_x": c.coord_x,
            "coord_y": c.coord_y,
            "coord_z": c.coord_z,
            # Filled in below after clustering.
            "topic_cluster_id": None,
        })
        vectors.append(list(c.embedding_json or []))
        pt_counter[c.page_type or "other"] = (
            pt_counter.get(c.page_type or "other", 0) + 1
        )
        for prod in products:
            if isinstance(prod, dict):
                key = (prod.get("key") or prod.get("label") or "").strip().lower()
            else:
                key = str(prod).strip().lower()
            if key:
                prod_counter[key] = prod_counter.get(key, 0) + 1

    if not chunks:
        return Response(
            {
                "error": (
                    "page has no body text to chunk — live embed wrote "
                    "no rows. Re-crawl the URL first."
                ),
                "url": decoded,
                "snapshot_id": str(snap.id),
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    total = len(chunks)
    page_type_breakdown = [
        {
            "page_type": pt,
            "label": PAGE_TYPE_LABELS.get(pt, pt),
            "count": cnt,
            "pct": round(100.0 * cnt / total, 1),
        }
        for pt, cnt in sorted(pt_counter.items(), key=lambda x: -x[1])
    ]
    product_breakdown = [
        {
            "product": p,
            "label": PRODUCT_LABELS.get(p, p),
            "count": cnt,
            "pct": round(100.0 * cnt / total, 1),
        }
        for p, cnt in sorted(prod_counter.items(), key=lambda x: -x[1])
    ]

    # Auto-discovered topical clusters from chunk vectors. This is the
    # "what topics does this page actually cover" view — independent of
    # the page-level rule classifier (which often labels every chunk
    # identically e.g. as "home" on a sprawling homepage).
    topic_clusters = _topic_cluster_chunks(chunks, vectors)
    for tc in topic_clusters:
        for idx in tc["chunk_indices"]:
            # Find the chunk with this chunk_idx and stamp it.
            for ch in chunks:
                if ch["chunk_idx"] == idx:
                    ch["topic_cluster_id"] = tc["cluster_id"]
                    break

    return Response({
        "snapshot_id": str(snap.id),
        "snapshot_kind": snap.kind,
        "snapshot_domain": snap.target_domain or "",
        "url": decoded,
        "url_b64": url_b64,
        "page_title": page.title or "",
        "total_chunks": total,
        "chunks": chunks,
        "page_type_breakdown": page_type_breakdown,
        "product_breakdown": product_breakdown,
        "topic_clusters": topic_clusters,
    })


@api_view(["GET"])
def page_detail_view(_request, snapshot_id: str, url_b64: str):
    """Per-URL detail by snapshot — works for any kind (Bajaj / competitor / ad-hoc).

    The competitor variant (``competitor_page_detail_view``) carries the
    legacy GapDeepCrawl fallback and resolves "latest snapshot for this
    domain" by itself. This view is the snapshot-explicit cousin: the
    caller already knows the exact ``CrawlSnapshot.id`` (because they
    just listed the snapshot, or just kicked off an ad-hoc crawl), so
    we skip domain → snapshot resolution and the GapDeepCrawl fallback.

    Used by:
      * Bajaj Page Explorer (each row links here with the live Bajaj
        snapshot id) — same layout as the competitor page detail.
      * Phase 3 ad-hoc URL crawler — singleton ad-hoc snapshot per host.
      * Any future caller that wants "URL X from snapshot Y, full payload".
    """
    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult

    snap = CrawlSnapshot.objects.filter(id=snapshot_id).first()
    if snap is None:
        return Response(
            {"error": f"snapshot {snapshot_id} not found"},
            status=status.HTTP_404_NOT_FOUND,
        )
    decoded = _b64url_decode(url_b64)
    if decoded is None:
        return Response(
            {"error": "invalid base64url segment"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    page = CrawlerPageResult.objects.filter(
        snapshot=snap, url=decoded.strip(),
    ).first()
    if page is None:
        return Response(
            {
                "error": f"URL {decoded} not in snapshot {snapshot_id}",
                "snapshot_kind": snap.kind,
                "snapshot_domain": snap.target_domain or "",
            },
            status=status.HTTP_404_NOT_FOUND,
        )
    payload = _full_page_from_result(page, snap)
    # Decorate with snapshot kind so the frontend can swap breadcrumb
    # + brand badge between Bajaj / competitor / ad-hoc modes without
    # making a second request to look the snapshot up.
    payload["snapshot_kind"] = snap.kind
    payload["snapshot_domain"] = snap.target_domain or ""
    return Response(payload)


@api_view(["GET"])
def competitor_page_detail_view(_request, domain: str, url_b64: str):
    """Per-URL detail view payload.

    Sources from CrawlerPageResult first (matched on snapshot + url) and
    falls back to GapDeepCrawl when no CrawlerPageResult exists for the
    URL. Response shape is identical to the legacy path.
    """
    from apps.crawler.models import CrawlerPageResult

    decoded = _b64url_decode(url_b64)
    if decoded is None:
        return Response(
            {"error": "invalid base64url segment"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    snap = _latest_competitor_snapshot_for(domain)
    if snap is not None:
        page = CrawlerPageResult.objects.filter(
            snapshot=snap, url=decoded.strip(),
        ).first()
        if page is not None:
            return Response(_full_page_from_result(page, snap))

    crawl = _latest_deep_crawl_for(domain)
    if crawl is None:
        return Response(
            {
                "error": f"no crawl data for {domain}",
                "hint": (
                    "no CrawlSnapshot or GapDeepCrawl rows match this "
                    "domain — trigger the daily competitor walk first"
                ),
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
        # Phase 2A.5 — structural mirror payload for the Inspector UI.
        # Empty arrays on legacy GapDeepCrawl rows (built before this
        # field landed) — the UI is expected to gracefully degrade to
        # "rerun the deep crawl to capture this" rather than 500.
        "headings": sample.get("headings") or [],
        # Phase I — hierarchical heading tree (h1>h2>h3 nested) so the
        # UI can render the actual page outline, not just the flat list.
        "headings_tree": _headings_tree_for_sample(sample),
        "internal_links": sample.get("internal_links") or [],
        "external_links": sample.get("external_links") or [],
        "images": sample.get("images") or [],
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


# ── LLM pool monitoring ──────────────────────────────────────────────


@api_view(["GET"])
def llm_pool_stats(_request):
    """GET /api/v1/seo/llm/pool-stats — health of the Groq key pool.

    Returns one row per configured key with call count, 429 count,
    and remaining cooldown. Used by ops to confirm the pool is
    spreading load across keys (instead of hammering the first one).
    Key values are masked to the last 6 chars so logs don't leak.
    """
    from .llm.key_pool import get_groq_pool
    pool = get_groq_pool()
    if pool is None:
        return Response({
            "enabled": False,
            "message": (
                "No Groq keys configured. Set GROQ_API_KEYS=k1,k2,... in .env "
                "(or GROQ_API_KEY=k for a single-key fallback)."
            ),
        })
    return Response({
        "enabled": True,
        "key_count": len(pool),
        "keys": pool.stats(),
    })


# ── Content Writer ───────────────────────────────────────────────────


def _serialize_proposal(p) -> dict:
    """Wire shape for ContentRewriteProposal.

    We deliberately *omit* ``raw_proposal`` from the list endpoint and
    only include it on detail — the raw payload is ~5-10x the size of
    the filtered version and the list view is purely for picking which
    proposal to inspect.
    """
    return {
        "id": str(p.id),
        "our_url": p.our_url,
        "competitor_urls": p.competitor_urls or [],
        "target_keywords": p.target_keywords or [],
        "prompt_instructions": getattr(p, "prompt_instructions", "") or "",
        "competitor_matches": getattr(p, "competitor_matches", []) or [],
        "evidence_dict": p.evidence_dict or {},
        "generated_proposal": p.generated_proposal or {},
        "raw_proposal": p.raw_proposal or {},
        "critic_verdict": p.critic_verdict or {},
        "model_used": p.model_used or "",
        "tokens_in": p.tokens_in,
        "tokens_out": p.tokens_out,
        "cost_usd": p.cost_usd,
        "error": p.error or "",
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@api_view(["POST"])
def content_writer_revamp(request: Request):
    """POST /api/v1/seo/content-writer/revamp.

    Body:
        {"our_url": "https://www.bajajlifeinsurance.com/term-insurance-plans.html",
         "prompt": "focus on tax-saving angle, compare with hdfc"}  # optional

    The orchestrator:
      1. Live-crawls ``our_url`` (fresh body always — no stale DB read).
      2. Scans every competitor brand in the DB for a counterpart page
         using URL-slug + title overlap. ``prompt`` is parsed for a
         brand mention to restrict the scan.
      3. For each matched competitor: uses the DB row if it's fresh
         AND has body text, otherwise live-fetches it.
      4. PSI (mobile + desktop) for our URL + each counterpart in
         parallel; Semrush ranking keywords filtered to each URL.
      5. Builds the evidence dict, calls the RevampWriter agent, runs
         the deterministic critic, persists the proposal, returns the
         full payload + the competitor-matches list so the operator
         knows which competitors were compared.

    Synchronous; ~25-40 s wall time. The frontend renders a staged
    progress UI based on elapsed-time thresholds.
    """
    from .agents.revamp_writer import generate_revamp
    from .models import ContentRewriteProposal
    from .services.page_revamp import build_revamp_payload

    body = request.data or {}
    our_url = (body.get("our_url") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    if not our_url:
        return Response(
            {"error": "our_url is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        payload = build_revamp_payload(
            our_url=our_url,
            prompt=prompt,
            max_competitors=int(body.get("max_competitors") or 5),
            enable_psi=bool(body.get("enable_psi", True)),
            enable_semrush=bool(body.get("enable_semrush", True)),
        )
    except RuntimeError as exc:
        return Response(
            {"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY,
        )

    result = generate_revamp(payload=payload)

    competitor_matches = [
        {
            "brand": m.brand,
            "url": m.url,
            "title": m.title,
            "confidence": m.confidence,
            "source": m.source,
            "snapshot_id": m.snapshot_id,
            "word_count": m.word_count,
        }
        for m, _s in payload.counterparts
    ]

    proposal = ContentRewriteProposal.objects.create(
        our_url=result.our_url,
        competitor_urls=result.competitor_urls,
        target_keywords=[],  # not used in the revamp flow
        prompt_instructions=prompt,
        competitor_matches=competitor_matches,
        evidence_dict=result.evidence_dict,
        raw_proposal=result.raw_proposal,
        generated_proposal=result.filtered_proposal,
        critic_verdict=result.critic_verdict,
        model_used=result.model_used,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        error=result.error or "",
    )

    response = _serialize_proposal(proposal)
    # Surface the warnings + brand-scan telemetry from the assembly step
    # so the operator sees "we scanned 8 competitor brands, matched 4".
    response["telemetry"] = {
        "competitors_scanned": payload.competitors_scanned,
        "competitors_matched": payload.competitors_matched,
        "warnings": payload.warnings,
    }
    # Section-cluster outputs and the structured gap — frontend renders
    # these in dedicated panels above the rewrite.
    response["our_sections"] = payload.our_sections
    response["their_sections"] = [
        {"brand": b, "sections": s} for b, s in payload.their_sections
    ]
    response["gap"] = payload.gap
    return Response(response)


@api_view(["GET"])
def content_writer_our_pages(_request):
    """List crawled URLs the writer can rewrite.

    Sourced from the latest CrawlSnapshot's CrawlerPageResult rows so
    the UI selector only shows URLs that actually have the structural
    payload (headings_json, internal_links_json) the agent needs.
    """
    from django.db.models import Count

    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult

    # Pick the most recent snapshot that has a meaningful number of
    # rows — the very latest may still be mid-crawl with 0 or 1 row
    # (Phase C full crawl in progress can take hours during PSI). We
    # require ≥ 5 so we don't surface a single trailing PDF row from
    # an aborted run as "the dataset".
    snap = (
        CrawlSnapshot.objects.annotate(n=Count("pages"))
        .filter(n__gte=5)
        .order_by("-id")
        .first()
    )
    if snap is None:
        return Response({"snapshot_id": None, "pages": []})
    rows = (
        CrawlerPageResult.objects.filter(snapshot=snap)
        .exclude(status_code__in=["404", "500", "0"])
        .values("url", "title", "page_type", "word_count")
        .order_by("url")[:5000]
    )
    pages = [
        {
            "url": r["url"],
            "title": (r["title"] or "")[:200],
            "page_type": r["page_type"] or "",
            "word_count": r["word_count"] or 0,
        }
        for r in rows
    ]
    return Response({
        "snapshot_id": snap.id,
        "snapshot_date": (
            snap.started_at.isoformat() if snap.started_at else None
        ),
        "pages": pages,
    })


@api_view(["POST"])
def content_writer_generate(request: Request):
    """POST /api/v1/seo/content-writer/generate.

    Body:
        {
          "our_url": "https://.../...",
          "competitor_urls": ["...", "..."],   # optional
          "target_keywords": ["...", "..."]    # optional
        }

    Returns the full :class:`ContentRewriteProposal` serialisation
    immediately (synchronous — one LLM call, completes in 5-15 s).

    The proposal is persisted regardless of outcome: errors land in
    ``error`` so the operator can see what failed without losing the
    request context.
    """
    from .agents.content_writer import generate_rewrite
    from .models import ContentRewriteProposal

    body = request.data or {}
    our_url = (body.get("our_url") or "").strip()
    if not our_url:
        return Response(
            {"error": "our_url is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    competitor_urls = [
        (u or "").strip() for u in (body.get("competitor_urls") or [])
        if (u or "").strip()
    ]
    target_keywords = [
        (k or "").strip() for k in (body.get("target_keywords") or [])
        if (k or "").strip()
    ]

    result = generate_rewrite(
        our_url=our_url,
        competitor_urls=competitor_urls,
        target_keywords=target_keywords,
    )

    proposal = ContentRewriteProposal.objects.create(
        our_url=result.our_url,
        competitor_urls=result.competitor_urls,
        target_keywords=result.target_keywords,
        evidence_dict=result.evidence_dict,
        raw_proposal=result.raw_proposal,
        generated_proposal=result.filtered_proposal,
        critic_verdict=result.critic_verdict,
        model_used=result.model_used,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=result.cost_usd,
        error=result.error or "",
    )
    return Response(_serialize_proposal(proposal))


@api_view(["GET"])
def content_writer_proposal_detail(_request, proposal_id: str):
    """GET /api/v1/seo/content-writer/proposals/<uuid>."""
    from .models import ContentRewriteProposal

    try:
        proposal = ContentRewriteProposal.objects.get(id=proposal_id)
    except ContentRewriteProposal.DoesNotExist:
        return Response(
            {"error": f"proposal {proposal_id} not found"},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response(_serialize_proposal(proposal))


@api_view(["GET"])
def geo_score(request: Request):
    """GET /api/v1/seo/geo/score/.

    Unified Generative Engine Optimization rollup — citation density,
    E-E-A-T markup, AI-bot hit count, llms.txt presence, Reddit /
    Quora mentions, YouTube presence, Wikidata entity, brand-mention
    feed — composed into one weighted 0-100 score with suggestions.

    Query params:
      * ``brand`` (default: "Bajaj Life Insurance")
      * ``deep`` — set to ``false`` to skip the external SerpAPI +
        Wikidata calls (faster, page-signals only).
    """
    from dataclasses import asdict

    from .services.geo import compute_geo_score

    brand = (
        request.query_params.get("brand")
        or "Bajaj Life Insurance"
    ).strip()
    deep = (
        (request.query_params.get("deep") or "true").lower()
        not in ("0", "false", "no")
    )
    result = compute_geo_score(brand=brand, deep=deep)
    return Response(asdict(result))


@api_view(["POST"])
def design_brief_compose(request: Request):
    """POST /api/v1/seo/design-brief/compose.

    Body: ``{"figma_url": "https://www.figma.com/design/<key>/...",
              "frame_name": "Term Insurance Landing"}``.

    Returns the deterministic brief with the designer's frame
    summary (text + images + instances), competitor zone signals
    drawn from the LayoutAgent diff, and rule-based recommendations.

    Errors land in the ``error`` field so the UI degrades gracefully:
      * Missing FIGMA_TOKEN env → "set FIGMA_TOKEN in .env".
      * Bad Figma URL → "could not parse Figma file URL".
      * Frame name not found → "frame '<x>' not found in file".
    """
    from dataclasses import asdict

    from .services.design_brief import compose_brief

    body = request.data or {}
    figma_url = (body.get("figma_url") or "").strip()
    frame_name = (body.get("frame_name") or "").strip()
    if not figma_url:
        return Response(
            {"error": "figma_url required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    brief = compose_brief(figma_url=figma_url, frame_name=frame_name)
    payload = asdict(brief)
    return Response(payload)


@api_view(["POST"])
def visual_audit_capture(request: Request):
    """POST /api/v1/seo/visual-audit/capture.

    Body: ``{ "urls": ["https://...", ...], "snapshot_id": "manual",
              "viewport": "desktop"|"mobile" }``.

    Captures one PNG per URL via Playwright headless Chromium and
    returns the manifest. URLs that 404/timeout/bot-detect end up in
    the ``skipped`` list with their error reason.

    Storage: ``BASE_DIR/data/screenshots/<snapshot_id>/<urlhash>.png``.
    Subsequent captures of the same URL overwrite — dedupe by hash.
    """
    from dataclasses import asdict

    from .services.visual_audit import capture_page_screenshots

    body = request.data or {}
    urls = [u.strip() for u in (body.get("urls") or []) if isinstance(u, str) and u.strip()]
    if not urls:
        return Response(
            {"error": "urls (non-empty list) required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    snapshot_id = (body.get("snapshot_id") or "manual").strip()
    vw = (body.get("viewport") or "desktop").strip().lower()
    viewport = (375, 812) if vw == "mobile" else (1280, 800)

    result = capture_page_screenshots(
        urls,
        snapshot_id=snapshot_id,
        viewport=viewport,
    )
    return Response({
        "captured": [asdict(r) for r in result.captured],
        "skipped": result.skipped,
        "elapsed_sec": result.elapsed_sec,
        "error": result.error,
        "snapshot_id": snapshot_id,
        "viewport": f"{viewport[0]}x{viewport[1]}",
    })


@api_view(["GET"])
def orchestrator_v2_run(request: Request):
    """GET /api/v1/seo/orchestrate/.

    Orchestrator V2 — runs the full custodian pyramid synchronously
    and returns one unified report (~80-150 ms). The Custodians page
    consumes this; the future Briefings page renders the ``headline``
    block as a "this week's focus" card.

    Query params:
      * ``adobe`` — set to ``false`` to skip the Adobe call (use when
        credentials aren't configured to save the ~200ms IMS round-
        trip on every dashboard load).
      * ``structure`` — set to ``false`` to skip StructureAgent
        (no-op when competitor snapshots don't exist yet).
    """
    from .services.orchestrator_v2 import run_orchestration

    include_adobe = (
        (request.query_params.get("adobe") or "true").lower()
        not in ("0", "false", "no")
    )
    include_structure = (
        (request.query_params.get("structure") or "true").lower()
        not in ("0", "false", "no")
    )
    report = run_orchestration(
        include_adobe=include_adobe,
        include_structure_gaps=include_structure,
    )
    return Response(report)


@api_view(["GET"])
def custodian_structure_gaps(request: Request):
    """GET /api/v1/seo/custodians/structure-gaps/.

    StructureAgent output: internal-link patterns (page_type →
    target_kind tuples) that competitors systematically use but we
    don't. Lets the operator see "every ICICI term page links to a
    calculator from the hero; we only do that on 12 % of ours".

    Query params:
      * ``min_pct`` — required competitor coverage to count as a
        pattern (default 50.0).
    """
    from apps.crawler.models import CrawlSnapshot
    from django.db.models import Count

    from .services.custodian import link_pattern_gaps

    try:
        min_pct = float(request.query_params.get("min_pct") or 50.0)
    except ValueError:
        min_pct = 50.0

    our_snap = (
        CrawlSnapshot.objects.annotate(n=Count("pages"))
        .filter(kind="bajaj", n__gte=5)
        .order_by("-started_at")
        .first()
    )
    if our_snap is None:
        return Response(
            {"error": "no Bajaj crawl snapshot with data — crawl first"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Pick latest non-empty competitor snapshot per domain.
    comp_snap_ids: list[str] = []
    seen_domains: set[str] = set()
    competitor_snaps = (
        CrawlSnapshot.objects.annotate(n=Count("pages"))
        .filter(kind="competitor", n__gte=5)
        .order_by("-started_at")
    )
    for s in competitor_snaps:
        d = (s.target_domain or "").lower().lstrip("www.")
        if d in seen_domains:
            continue
        seen_domains.add(d)
        comp_snap_ids.append(str(s.id))

    gaps = link_pattern_gaps(
        our_snapshot_id=str(our_snap.id),
        competitor_snapshot_ids=comp_snap_ids,
        min_pct=min_pct,
    )
    return Response({
        "our_snapshot_id": str(our_snap.id),
        "competitor_snapshot_count": len(comp_snap_ids),
        "min_pct": min_pct,
        "gaps": gaps,
    })


@api_view(["GET"])
def custodian_layout(request: Request):
    """GET /api/v1/seo/custodians/layout/.

    LayoutAgent output: per-landmark-zone aggregates (header / nav /
    hero / main / aside / footer / other) for our latest Bajaj
    snapshot, plus the zone-level diff against each competitor that
    has a snapshot.

    Query params:
      * ``our_snapshot_id`` — override our snapshot (default = latest).

    Existing pre-Phase-H rows have no ``zone`` field — those entries
    appear in the ``unknown`` bucket. The 03:00 IST beat job
    repopulates with proper zones.
    """
    from apps.crawler.models import CrawlSnapshot
    from django.db.models import Count

    from .services.custodian import layout_diff, summarise_layout

    snap_override = request.query_params.get("our_snapshot_id")
    if snap_override:
        our_snap = CrawlSnapshot.objects.filter(id=snap_override).first()
    else:
        our_snap = (
            CrawlSnapshot.objects.annotate(n=Count("pages"))
            .filter(kind="bajaj", n__gte=5)
            .order_by("-started_at")
            .first()
        )
    if our_snap is None:
        return Response(
            {"error": "no Bajaj snapshot with data"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Pick latest non-empty snapshot per competitor domain.
    comp_snap_ids: list[str] = []
    seen_domains: set[str] = set()
    competitor_snaps = (
        CrawlSnapshot.objects.annotate(n=Count("pages"))
        .filter(kind="competitor", n__gte=5)
        .order_by("-started_at")
    )
    for s in competitor_snaps:
        d = (s.target_domain or "").lower().lstrip("www.")
        if d in seen_domains:
            continue
        seen_domains.add(d)
        comp_snap_ids.append(str(s.id))

    layout = summarise_layout(snapshot_id=str(our_snap.id))
    diff = layout_diff(str(our_snap.id), comp_snap_ids) if comp_snap_ids else {
        "our_snapshot_id": str(our_snap.id),
        "diffs_by_competitor": {},
    }
    return Response({
        "our_snapshot_id": str(our_snap.id),
        "competitor_snapshot_count": len(comp_snap_ids),
        "layout": layout,
        "diff": diff,
    })


@api_view(["GET"])
def custodian_adobe(_request):
    """GET /api/v1/seo/custodians/adobe/.

    AdobeAgent service-layer output: dashboard payload shaped for the
    custodian. Lookback defaults to 30 days. Returns
    ``{available: false, error: ...}`` when Adobe credentials aren't
    set — the UI degrades gracefully instead of 500-ing.
    """
    from .services.custodian import summarise_adobe_traffic

    return Response(summarise_adobe_traffic())


@api_view(["GET"])
def custodian_summary(request: Request):
    """GET /api/v1/seo/custodians/summary.

    Returns the OurDataCustodian view of bajajlifeinsurance.com
    side-by-side with TheirDataCustodian for every competitor in
    ``settings.COMPETITOR["roster"]``, plus the SiteDiffer report.

    No LLM is invoked — this is the data layer the LLM-driven agents
    (ContentWriter, SiteDifferAgent, etc.) consume. The frontend
    Custodians page renders the same JSON directly.

    Query params:
      * ``our`` — override the "our" domain (default
        ``bajajlifeinsurance.com``). Useful when this is deployed
        for another tenant.
      * ``compute_diff`` — set to ``false`` to skip the SiteDiffer
        block (saves ~5 ms on big rosters).
    """
    from dataclasses import asdict

    from .services.custodian import (
        compute_site_diff,
        summarise_competitor,
        summarise_our_domain,
    )

    our_domain = (
        request.query_params.get("our") or "bajajlifeinsurance.com"
    ).strip().lower()
    compute_diff = (
        request.query_params.get("compute_diff", "true").lower()
        not in ("0", "false", "no")
    )

    from django.conf import settings as dj_settings

    roster = list(getattr(dj_settings, "COMPETITOR", {}).get("roster") or [])
    ours = summarise_our_domain(domain=our_domain)
    theirs = [summarise_competitor(d) for d in roster]
    payload = {
        "our": asdict(ours),
        "competitors": [asdict(t) for t in theirs],
        "roster_size": len(roster),
    }
    if compute_diff:
        diff = compute_site_diff(ours, theirs)
        payload["diff"] = asdict(diff)
    return Response(payload)


@api_view(["GET"])
def competitor_changes(request: Request):
    """GET /api/v1/seo/competitor/changes — recent ChangeWatcher events.

    Query params (all optional):
      * ``domain`` — filter to one competitor (apex host).
      * ``kind`` — filter to one event kind (``new``/``title``/
        ``content``/``structure``/``removed``).
      * ``limit`` — default 100, max 500.

    The default 100-event feed is enough for the "what changed today"
    operator dashboard. For analytical replays use the model directly.
    """
    from .models import CompetitorChangeEvent

    qs = CompetitorChangeEvent.objects.all()
    domain = (request.query_params.get("domain") or "").strip().lower()
    if domain:
        qs = qs.filter(competitor_domain=domain.lstrip("www."))
    kind = (request.query_params.get("kind") or "").strip().lower()
    if kind in {c[0] for c in CompetitorChangeEvent.ChangeKind.choices}:
        qs = qs.filter(kind=kind)
    try:
        limit = int(request.query_params.get("limit") or 100)
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 500))
    rows = qs.order_by("-detected_at")[:limit]
    return Response({
        "count": len(rows),
        "events": [
            {
                "id": ev.id,
                "url": ev.url,
                "competitor_domain": ev.competitor_domain,
                "kind": ev.kind,
                "detected_at": (
                    ev.detected_at.isoformat() if ev.detected_at else None
                ),
                "delta": ev.delta or {},
            }
            for ev in rows
        ],
    })


@api_view(["GET"])
def competitor_page_history(request: Request):
    """GET /api/v1/seo/competitor/history?url=... — revision timeline
    for one URL. Used by the Inspector's "revisions" tab to show how a
    competitor's page has shifted across crawls.
    """
    from .models import CompetitorPageHistory

    url = (request.query_params.get("url") or "").strip()
    if not url:
        return Response(
            {"error": "url query param required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    rows = CompetitorPageHistory.objects.filter(url=url).order_by("-seen_at")[:50]
    return Response({
        "url": url,
        "revisions": [
            {
                "id": h.id,
                "seen_at": h.seen_at.isoformat() if h.seen_at else None,
                "title": h.title,
                "meta_description": h.meta_description,
                "word_count": h.word_count,
                "heading_count": h.heading_count,
                "internal_link_count": h.internal_link_count,
                "image_count": h.image_count,
                "title_hash": h.title_hash,
                "content_hash": h.content_hash,
                "structure_hash": h.structure_hash,
                "delta": h.delta or {},
            }
            for h in rows
        ],
    })


@api_view(["GET"])
def content_writer_proposals_list(_request):
    """GET /api/v1/seo/content-writer/proposals — recent rewrites."""
    from .models import ContentRewriteProposal

    rows = ContentRewriteProposal.objects.order_by("-created_at")[:50]
    return Response({
        "count": len(rows),
        "proposals": [
            {
                "id": str(p.id),
                "our_url": p.our_url,
                "model_used": p.model_used,
                "accepted": (p.critic_verdict or {}).get("accepted", 0),
                "rejected": (p.critic_verdict or {}).get("rejected", 0),
                "cost_usd": p.cost_usd,
                "error": p.error,
                "created_at": (
                    p.created_at.isoformat() if p.created_at else None
                ),
            }
            for p in rows
        ],
    })
