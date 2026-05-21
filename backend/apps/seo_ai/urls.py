from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SEORunViewSet,
    adobe_dashboard,
    adobe_seo_join,
    chat_stream,
    competitor_dashboard,
    competitor_detail_view,
    competitor_gap_detection,
    competitor_page_detail_view,
    content_comparison,
    content_comparison_our_pages,
    gap_pipeline_detail,
    gap_pipeline_latest,
    gap_pipeline_start,
    gap_pipeline_status,
    gsc_dashboard,
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
    path("chat/stream/", chat_stream, name="chat-stream"),
    path("", include(_router.urls)),
]
