"""Central API layer URL routing.

After the crawler-engine migration, every live endpoint lives under
``/api/v1/crawler/`` and is served by ``apps.crawler``. The Lattice main
dashboard (sidebar's "Dashboard / Sessions / Pages / Issues / …" pages)
relied on viewsets backed by the deleted ``apps.crawl_sessions`` ORM
models, so those endpoints are gone.

The two ``/websites/`` and ``/system/metrics/`` stubs below exist purely
to keep the Lattice **sidebar + topbar widgets** quiet — they fire on
every page (including the Crawler Engine pages) and would otherwise
spam the console with 404s. They return empty payloads so the widgets
render in their "no data" state without errors.
"""
from django.http import JsonResponse
from django.urls import include, path
from django.views.decorators.http import require_GET


@require_GET
def empty_websites_stub(_request):
    """Stub for /api/v1/websites/ — sidebar project picker."""
    return JsonResponse({"count": 0, "next": None, "previous": None, "results": []})


@require_GET
def empty_system_metrics_stub(_request):
    """Stub for /api/v1/system/metrics/ — topbar host metrics card."""
    return JsonResponse({
        "host": {"cpu_percent": 0, "memory_percent": 0, "disk_percent": 0},
        "redis": {"available": False},
        "celery": {"workers": 0},
    })


urlpatterns = [
    # Active crawler — the new file-backed engine.
    path("crawler/", include("apps.crawler.urls", namespace="crawler")),

    # Sidebar / topbar widget stubs (see module docstring).
    path("websites/", empty_websites_stub, name="websites-stub"),
    path("system/metrics/", empty_system_metrics_stub, name="system-metrics-stub"),
]
