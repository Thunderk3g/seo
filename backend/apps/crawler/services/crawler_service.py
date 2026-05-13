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
        return False, "A crawl is already running."
    STATE.reset()
    log_bus.reset()
    t = threading.Thread(target=run_crawl, daemon=True, name="crawl-engine")
    t.start()
    log.info("Crawl thread started")
    return True, "Crawl started."


def request_stop() -> tuple[bool, str]:
    if not STATE.is_running:
        return False, "No active crawl."
    STATE.should_stop = True
    log.info("Stop requested")
    return True, "Stop signal sent."
