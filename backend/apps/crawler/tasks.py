"""Celery tasks for the in-house crawler.

The crawler is long-running (10-30 min for a full Bajaj sweep). Running
it in a request-thread inside the WSGI worker is unreliable in prod:
when the worker recycles for memory or after a deploy, the daemon
thread is killed mid-crawl.

The `run_crawl_task` here is the prod path. `crawler_service.start()`
calls `.delay()` to enqueue it onto Celery; the worker container picks
it up and runs `engine.run_crawl()` end-to-end (Phase 1 static crawl,
Phase 2 Playwright console capture, Phase 3 PSI CWV).

If the Celery broker is unreachable (dev without Redis, or boot order
issues), `crawler_service.start()` falls back to the legacy threading
path so local development still works without a worker container.
"""
from __future__ import annotations

from celery import shared_task

from .logger import get_logger

log = get_logger(__name__)


@shared_task(
    name="apps.crawler.tasks.run_crawl_task",
    max_retries=0,
    # Hard limit: 4 hours. A real Bajaj crawl finishes in <30 min;
    # 4 hours is a watchdog ceiling so a stuck PSI call can't lock up
    # the worker indefinitely.
    time_limit=4 * 3600,
    soft_time_limit=4 * 3600 - 60,
)
def run_crawl_task() -> dict:
    """Run a full crawl (Phase 1 static + Phase 2 console + Phase 3 PSI).

    No arguments — the crawler reads its seed URL, allowed domains, and
    all knobs from Django/Crawler settings. Returns a small summary
    dict for Celery's result backend; the real output is the CSVs the
    engine streams to disk.
    """
    # Import here, not at module top, so this file is import-safe even
    # if the crawler app isn't fully initialised when Celery loads the
    # task registry (autodiscover_tasks scans every installed app).
    from .engine.engine import run_crawl
    from .state import STATE

    log.info("celery: run_crawl_task starting")
    try:
        run_crawl()
    except Exception:
        log.exception("celery: run_crawl_task crashed")
        raise
    finally:
        with STATE.lock:
            stats = STATE.stats.as_dict()
            running = STATE.is_running

    return {"ok": True, "is_running": running, "stats": stats}
