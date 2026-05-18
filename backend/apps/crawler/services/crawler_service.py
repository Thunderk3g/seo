"""Orchestrates crawl lifecycle from the API layer."""
from __future__ import annotations

import threading

from .. import log_bus
from ..engine.engine import run_crawl
from ..logger import get_logger
from ..state import STATE

log = get_logger(__name__)


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
    STATE.reset()
    log_bus.reset()
    t = threading.Thread(target=run_crawl, daemon=True, name="crawl-engine")
    t.start()
    log.info("Crawl thread started")
    return True, "Crawl started."


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
