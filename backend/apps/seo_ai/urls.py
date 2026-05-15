from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    SEORunViewSet,
    chat_stream,
    competitor_dashboard,
    competitor_gap_detection,
    gap_pipeline_detail,
    gap_pipeline_latest,
    gap_pipeline_start,
    gap_pipeline_status,
    gsc_dashboard,
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
    path("chat/stream/", chat_stream, name="chat-stream"),
    path("", include(_router.urls)),
]
