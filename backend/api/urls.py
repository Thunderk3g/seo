"""Central API layer URL routing."""

from django.urls import path, include

from apps.crawler.views import settings_view
from .routers import router

urlpatterns = [
    # /api/v1/settings/?website=<uuid> — standalone, not a ViewSet.
    path("settings/", settings_view, name="settings"),
    path("", include(router.urls)),
]
