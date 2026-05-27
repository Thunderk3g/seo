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


@require_GET
def health_check(_request):
    """GET /api/v1/health/ — liveness + readiness probe.

    Shape: ``{ok, checks: {db, redis, llm_pool}, version}``.

    * ``db``: SELECT 1 against the default connection.
    * ``redis``: PING against ``CELERY_BROKER_URL``.
    * ``llm_pool``: presence of at least one configured Groq key.

    Designed for k8s/ALB readiness probes: 200 means all three are
    green; 503 means at least one is red. Liveness-only callers can
    ignore the body and just look at the status code.
    """
    from django.conf import settings
    from django.db import connection

    checks: dict[str, dict] = {}
    overall_ok = True

    # ── DB ────────────────────────────────────────────────────────
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
            c.fetchone()
        checks["db"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["db"] = {"ok": False, "error": str(exc)[:200]}
        overall_ok = False

    # ── Redis (broker) ────────────────────────────────────────────
    try:
        import redis as _redis
        url = settings.CELERY_BROKER_URL
        client = _redis.from_url(url, socket_timeout=2)
        client.ping()
        checks["redis"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"ok": False, "error": str(exc)[:200]}
        overall_ok = False

    # ── LLM pool ──────────────────────────────────────────────────
    try:
        from apps.seo_ai.llm.key_pool import get_groq_pool
        pool = get_groq_pool()
        checks["llm_pool"] = {
            "ok": pool is not None,
            "key_count": len(pool) if pool else 0,
        }
        # llm_pool absent is NOT overall-fatal — the system works
        # without LLM (crawler + ChangeWatcher are deterministic).
    except Exception as exc:  # noqa: BLE001
        checks["llm_pool"] = {"ok": False, "error": str(exc)[:200]}

    payload = {
        "ok": overall_ok,
        "version": getattr(settings, "APP_VERSION", "unknown"),
        "checks": checks,
    }
    return JsonResponse(payload, status=200 if overall_ok else 503)


urlpatterns = [
    # Active crawler — the new file-backed engine.
    path("crawler/", include("apps.crawler.urls", namespace="crawler")),

    # SEO AI Agent System — Phase 0 grading endpoints.
    path("seo/", include("apps.seo_ai.urls", namespace="seo_ai")),

    # Liveness + readiness probe for k8s/ALB/uptime monitors.
    path("health/", health_check, name="health-check"),

    # Sidebar / topbar widget stubs (see module docstring).
    path("websites/", empty_websites_stub, name="websites-stub"),
    path("system/metrics/", empty_system_metrics_stub, name="system-metrics-stub"),
]
