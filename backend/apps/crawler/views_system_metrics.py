"""Standalone view for the System Metrics endpoint (Spec §4.2 / §5.4.1).

Lives outside ``views.py`` to keep the @action surface of CrawlSessionViewSet
clean and to avoid edit-conflicts with other in-flight Day-N agents on
``views.py``. The path is wired in ``backend/api/urls.py`` next to the
existing standalone ``settings_view``.

Returns a snapshot of *system* signals (host CPU/memory, Redis broker queue
depth, Celery worker activity) — distinct from *crawl* performance metrics
(avg/p95 response time, depth) which continue to live in
``OverviewService`` and surface via ``/sessions/<id>/overview/``.

Failure mode: each of the three sub-collectors swallows its own errors and
returns zeros + ``connected=False``. A flaky Redis or a no-worker
deployment must NOT 500 the dashboard — the card has to render even when
the supporting infrastructure is partly degraded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import psutil
import redis as redis_lib
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

logger = logging.getLogger(__name__)


@api_view(["GET"])
def system_metrics_view(request):
    """Return a single system-metrics snapshot.

    Always 200 with the documented payload shape. Sub-collectors degrade
    gracefully so the frontend can render even with no Redis or no
    Celery workers attached.
    """
    return Response({
        "host": _host_metrics(),
        "redis": _redis_metrics(),
        "celery": _celery_metrics(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    })


# ─────────────────────────────────────────────────────────────
# Sub-collectors
# ─────────────────────────────────────────────────────────────
def _host_metrics() -> dict:
    """psutil-based host snapshot.

    ``cpu_percent(interval=None)`` is non-blocking — it returns the load
    since the previous call (0.0 on the very first invocation per
    process). That's acceptable for a dashboard that polls every 5s.
    """
    try:
        proc = psutil.Process()
        vm = psutil.virtual_memory()
        return {
            "cpu_percent": float(psutil.cpu_percent(interval=None)),
            "memory_percent": float(vm.percent),
            "memory_used_mb": int(vm.used / 1024 / 1024),
            "memory_total_mb": int(vm.total / 1024 / 1024),
            "thread_count": int(proc.num_threads()),
        }
    except Exception as exc:  # pragma: no cover — psutil is mandatory
        logger.warning("system_metrics: host collector failed: %s", exc)
        return {
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "memory_used_mb": 0,
            "memory_total_mb": 0,
            "thread_count": 0,
        }


def _redis_metrics() -> dict:
    """Sum LLEN across known queue keys; ping to detect connectivity."""
    try:
        url = (
            getattr(settings, "CELERY_BROKER_URL", None)
            or getattr(settings, "REDIS_URL", "redis://redis:6379/0")
        )
        r = redis_lib.from_url(url, socket_connect_timeout=1.0)
        # Celery's default queue is "celery". The crawler stream uses
        # "crawl" for its task routing; extend this list if more named
        # queues are introduced.
        queues = ["celery", "crawl"]
        depth = sum((r.llen(q) or 0) for q in queues)
        r.ping()
        return {"queue_depth": int(depth), "connected": True}
    except Exception as exc:
        logger.warning("system_metrics: redis collector failed: %s", exc)
        return {"queue_depth": 0, "connected": False}


def _celery_metrics() -> dict:
    """Celery control-plane inspect — bounded to 1s so a missing worker
    can't stall the request."""
    try:
        from celery import current_app

        insp = current_app.control.inspect(timeout=1.0)
        active = insp.active() or {}
        scheduled = insp.scheduled() or {}
        return {
            "active_tasks": sum(len(v) for v in active.values()),
            "scheduled_tasks": sum(len(v) for v in scheduled.values()),
            "workers_online": len(active),
        }
    except Exception as exc:
        logger.warning("system_metrics: celery collector failed: %s", exc)
        return {
            "active_tasks": 0,
            "scheduled_tasks": 0,
            "workers_online": 0,
        }
