"""Orchestrates crawl lifecycle from the API layer."""
from __future__ import annotations

import os
import threading

from .. import log_bus
from ..conf import settings as crawler_settings
from ..engine.engine import run_crawl
from ..logger import get_logger
from ..state import STATE

log = get_logger(__name__)


# Files wiped on every Start click so clicking Start always means "crawl
# from scratch". Caches (semrush, psi, competitor HTML) are deliberately
# NOT in this list — they're keyed by URL and survive across runs to
# avoid re-billing third-party APIs for unchanged data.
_RUN_OUTPUTS = [
    "crawl_state.json",
    "crawl_results.csv",
    "crawl_errors.csv",
    "crawl_404_errors.csv",
    "crawl_errors_httperror.csv",
    "crawl_console_log.csv",
    "crawl_discovered.csv",
]


def _wipe_for_fresh_crawl() -> int:
    """Delete the previous run's outputs so the next crawl writes fresh.

    The append-only streaming CSV design means a click on Start would
    otherwise no-op (resume sees everything as already-visited). Wiping
    state + outputs guarantees each Start click produces a full crawl
    with overwritten CSV rows.
    """
    d = crawler_settings.data_path
    removed = 0
    for fname in _RUN_OUTPUTS:
        p = d / fname
        if p.exists():
            try:
                p.unlink()
                removed += 1
            except OSError as exc:
                log.warning("wipe: cannot delete %s: %s", p, exc)
    return removed


def start() -> tuple[bool, str]:
    if STATE.is_running:
        # Auto-recover: if the flag says "running" but there are no active
        # workers AND the queue is empty, the previous thread died without
        # clearing the flag (engine try/finally fixes this going forward,
        # but historical pickled state can still get stuck across upgrades).
        # Detect that and reset so the operator isn't blocked.
        if (STATE.stats.active_workers == 0
                and len(STATE.queue) == 0
                and not _thread_alive("crawl-engine")):
            log.warning(
                "start: detected stale is_running flag with no live "
                "thread + empty queue — resetting and starting fresh"
            )
            STATE.is_running = False
        else:
            return False, "A crawl is already running."
    # Fresh-crawl semantics: every click on Start wipes the previous
    # run's state + CSVs so the new run discovers and writes from zero
    # instead of resuming an already-complete state (which would be a
    # silent no-op on the visible CSV).
    removed = _wipe_for_fresh_crawl()
    log.info("start: wiped %d previous-run output file(s)", removed)
    STATE.reset()
    log_bus.reset()

    # Prefer Celery so the crawl survives WSGI worker recycles in prod.
    # Fall back to a daemon thread when:
    #  - The broker is unreachable (dev without Redis), or
    #  - CRAWLER_USE_CELERY=false is set explicitly (debugging / local
    #    runs where you want stack traces in the request shell).
    use_celery = os.environ.get("CRAWLER_USE_CELERY", "true").lower() in (
        "1", "true", "yes", "on",
    )
    if use_celery:
        try:
            from ..tasks import run_crawl_task
            run_crawl_task.delay()
            log.info("Crawl queued on Celery")
            return True, "Crawl queued on Celery."
        except Exception as exc:  # noqa: BLE001 — broker may be down in dev
            log.warning(
                "celery enqueue failed (%s) — falling back to in-process thread",
                exc,
            )

    t = threading.Thread(target=run_crawl, daemon=True, name="crawl-engine")
    t.start()
    log.info("Crawl thread started (in-process fallback)")
    return True, "Crawl started (in-process)."


def _thread_alive(name: str) -> bool:
    """Return True if any thread with the given name is alive."""
    for t in threading.enumerate():
        if t.name == name and t.is_alive():
            return True
    return False


def request_stop() -> tuple[bool, str]:
    if not STATE.is_running:
        return False, "No active crawl."
    STATE.should_stop = True
    log.info("Stop requested")
    return True, "Stop signal sent."
