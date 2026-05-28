from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SEORunViewSet,
    adobe_dashboard,
    adobe_seo_join,
    brand_mentions_dashboard,
    brand_mentions_refresh,
    chat_stream,
    competitor_dashboard,
    competitor_changes,
    competitor_crawls_list_view,
    competitor_detail_view,
    competitor_gap_detection,
    competitor_keywords_content_view,
    competitor_keywords_semrush_view,
    competitor_page_detail_view,
    competitor_page_history,
    competitor_walk_pause_view,
    page_detail_view,
    content_comparison,
    content_comparison_our_pages,
    content_writer_generate,
    content_writer_our_pages,
    content_writer_proposal_detail,
    content_writer_proposals_list,
    custodian_adobe,
    custodian_layout,
    custodian_structure_gaps,
    custodian_summary,
    design_brief_compose,
    geo_score,
    orchestrator_v2_run,
    visual_audit_capture,
    gap_pipeline_detail,
    gap_pipeline_latest,
    gap_pipeline_start,
    gap_pipeline_status,
    gsc_dashboard,
    llm_pool_stats,
    meta_ads_dashboard,
    overview,
    semrush_dashboard,
    sitemap_dashboard,
    sitemap_page_detail,
    start_grade,
)

app_name = "seo_ai"

_router = DefaultRouter()
_router.register(r"grade", SEORunViewSet, basename="grade")

urlpatterns = [
    path("overview/", overview, name="overview"),
    path("grade/start/", start_grade, name="start-grade"),
    path("gsc/", gsc_dashboard, name="gsc-dashboard"),
    path("semrush/", semrush_dashboard, name="semrush-dashboard"),
    path("adobe/", adobe_dashboard, name="adobe-dashboard"),
    path("adobe/seo-join/", adobe_seo_join, name="adobe-seo-join"),
    # Brand mentions — third-party sites talking about Bajaj.
    # Pulls from RSS + SerpAPI daily (+ CC monthly in v2). Same
    # vendor-pattern as Adobe/Meta-Ads — adapter → view → page.
    path("brand-mentions/", brand_mentions_dashboard, name="brand-mentions"),
    path(
        "brand-mentions/refresh/",
        brand_mentions_refresh,
        name="brand-mentions-refresh",
    ),
    # Meta Ad Library — competitor ad intel via Apify scraper.
    # Surfaces in the existing Competitor section (CompetitorDetailPage)
    # and the CompetitorsPage overview — NOT in the Data Sources rail.
    path("meta-ads/", meta_ads_dashboard, name="meta-ads-dashboard"),
    path("sitemap/", sitemap_dashboard, name="sitemap-dashboard"),
    path("sitemap/page/", sitemap_page_detail, name="sitemap-page-detail"),
    path("competitor/", competitor_dashboard, name="competitor-dashboard"),
    path(
        "competitor/gap/",
        competitor_gap_detection,
        name="competitor-gap-detection",
    ),
    # Phase-3 gap detection pipeline — transparent multi-stage flow that
    # the new UI section renders panel-by-panel.
    path(
        "gap-pipeline/start/",
        gap_pipeline_start,
        name="gap-pipeline-start",
    ),
    path(
        "gap-pipeline/latest/",
        gap_pipeline_latest,
        name="gap-pipeline-latest",
    ),
    path(
        "gap-pipeline/<uuid:run_id>/status/",
        gap_pipeline_status,
        name="gap-pipeline-status",
    ),
    path(
        "gap-pipeline/<uuid:run_id>/",
        gap_pipeline_detail,
        name="gap-pipeline-detail",
    ),
    # Content comparison — AEM page vs topically-closest competitor page.
    # No LLM required; pure-string matcher under gap_pipeline/page_pairing.py.
    path(
        "content-comparison/our-pages/",
        content_comparison_our_pages,
        name="content-comparison-our-pages",
    ),
    path(
        "content-comparison/",
        content_comparison,
        name="content-comparison",
    ),
    # Day 3 — Orchestrator V2 (custodian pyramid synthesis).
    path(
        "orchestrate/",
        orchestrator_v2_run,
        name="orchestrate",
    ),
    # VisualAuditAgent — Playwright screenshot capture + (optional)
    # multimodal LLM review. The capture step is unconditional;
    # analysis is gated on VISUAL_LLM_PROVIDER env.
    path(
        "visual-audit/capture/",
        visual_audit_capture,
        name="visual-audit-capture",
    ),
    # DesignBriefAgent — Figma file URL + frame name → competitor-
    # grounded design notes. Gated on FIGMA_TOKEN env.
    path(
        "design-brief/compose/",
        design_brief_compose,
        name="design-brief-compose",
    ),
    # GEO (Generative Engine Optimization) — unified 0-100 score with
    # per-factor breakdown (citation density, E-E-A-T, AI-bot hits,
    # llms.txt, Reddit/Quora, YouTube, Wikidata, brand mentions).
    path(
        "geo/score/",
        geo_score,
        name="geo-score",
    ),
    # Day 3 — DataCustodians + SiteDiffer + StructureAgent + AdobeAgent.
    path(
        "custodians/summary/",
        custodian_summary,
        name="custodian-summary",
    ),
    path(
        "custodians/structure-gaps/",
        custodian_structure_gaps,
        name="custodian-structure-gaps",
    ),
    path(
        "custodians/adobe/",
        custodian_adobe,
        name="custodian-adobe",
    ),
    path(
        "custodians/layout/",
        custodian_layout,
        name="custodian-layout",
    ),
    # Phase G — ChangeWatcher: cross-snapshot competitor changes.
    # ``/changes`` lists recent events (filter by domain / kind /
    # limit). ``/history`` shows per-URL revision timeline.
    path(
        "competitor/changes/",
        competitor_changes,
        name="competitor-changes",
    ),
    path(
        "competitor/history/",
        competitor_page_history,
        name="competitor-page-history",
    ),
    # Flat list of every competitor we've crawled (Phase G Scrapy walks).
    # Must come BEFORE the <str:domain> catch-all below or Django will
    # route /competitor/crawls/ into competitor_detail_view with
    # domain="crawls".
    path(
        "competitor/crawls/",
        competitor_crawls_list_view,
        name="competitor-crawls-list",
    ),
    # Phase 2 — per-competitor landing + per-URL detail. Replaces the
    # inline DeepCrawlPanel "dropdown" view. URL segments are
    # base64url-encoded so any URL round-trips through routing.
    path(
        "competitor/<str:domain>/",
        competitor_detail_view,
        name="competitor-detail",
    ),
    path(
        "competitor/<str:domain>/pages/<str:url_b64>/",
        competitor_page_detail_view,
        name="competitor-page-detail",
    ),
    # Snapshot-explicit per-URL detail — works for Bajaj, competitor, and
    # ad-hoc snapshots. Same response shape as competitor-page-detail.
    # Used by the unified PageDetailPage component on the frontend so all
    # three sources render with one layout. Phase 2.
    path(
        "page/<uuid:snapshot_id>/<str:url_b64>/",
        page_detail_view,
        name="page-detail",
    ),
    # Pause toggle for the 03:00 IST walk-competitors-daily cron.
    # GET returns current state; POST {paused: bool} flips it.
    path(
        "competitor/walk/pause/",
        competitor_walk_pause_view,
        name="competitor-walk-pause",
    ),
    # Phase 7 — per-competitor keyword intelligence. Two sources:
    # Semrush organic ranking keywords (authoritative, cached on disk),
    # and in-house TF-IDF over the crawl corpus ("what they write
    # about" — free, no API quota).
    path(
        "competitor/<str:domain>/keywords/semrush/",
        competitor_keywords_semrush_view,
        name="competitor-keywords-semrush",
    ),
    path(
        "competitor/<str:domain>/keywords/content/",
        competitor_keywords_content_view,
        name="competitor-keywords-content",
    ),
    path("chat/stream/", chat_stream, name="chat-stream"),
    # LLM pool monitoring — Groq key pool health.
    path("llm/pool-stats/", llm_pool_stats, name="llm-pool-stats"),
    # Content Writer — LLM rewrites grounded in real evidence.
    path(
        "content-writer/our-pages/",
        content_writer_our_pages,
        name="content-writer-our-pages",
    ),
    path(
        "content-writer/generate/",
        content_writer_generate,
        name="content-writer-generate",
    ),
    path(
        "content-writer/proposals/",
        content_writer_proposals_list,
        name="content-writer-proposals-list",
    ),
    path(
        "content-writer/proposals/<uuid:proposal_id>/",
        content_writer_proposal_detail,
        name="content-writer-proposal-detail",
    ),
    path("", include(_router.urls)),
]
