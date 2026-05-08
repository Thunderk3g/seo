"""Central API layer URL routing."""

from django.urls import path, include

from apps.crawler.views import settings_view
from apps.crawler.views_insights import insights_view
from apps.crawler.views_system_metrics import system_metrics_view
from .routers import router

urlpatterns = [
    # /api/v1/settings/?website=<uuid> — standalone, not a ViewSet.
    path("settings/", settings_view, name="settings"),
    # /api/v1/system/metrics/ — host/redis/celery snapshot (Spec §4.2).
    path("system/metrics/", system_metrics_view, name="system-metrics"),
    # /api/v1/sessions/<uuid>/insights/ — standalone (Day 5). Bypasses the
    # router so it does not collide with CrawlSessionViewSet @action methods.
    path(
        "sessions/<uuid:session_id>/insights/",
        insights_view,
        name="session-insights",
    ),
    path("", include(router.urls)),
]
