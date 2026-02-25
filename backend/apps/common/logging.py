"""Centralized logging configuration and helpers for the crawler engine.

Provides structured console logging following the format defined in the
Web Crawler Engine spec:

    [CRAWL] URL: /blog | Depth: 2 | Status: 200 | Links: 28 | Time: 640ms
    [DISCOVERY] Added 12 new URLs to frontier
    [SKIP] Blocked by robots.txt: /admin
    [ERROR] Timeout: /products?page=10
"""

import logging
import sys
from typing import Optional


def get_crawler_logger(name: str = "crawler") -> logging.Logger:
    """Get or create a logger configured for structured crawler output."""
    logger = logging.getLogger(f"seo.{name}")

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

    return logger


# ─────────────────────────────────────────────────────────────
# Pre-configured loggers for each subsystem
# ─────────────────────────────────────────────────────────────
crawl_logger = get_crawler_logger("crawler.engine")
frontier_logger = get_crawler_logger("crawler.frontier")
fetch_logger = get_crawler_logger("crawler.fetcher")
parse_logger = get_crawler_logger("crawler.parser")
discovery_logger = get_crawler_logger("crawler.discovery")
session_logger = get_crawler_logger("crawler.session")
robots_logger = get_crawler_logger("crawler.robots")


# ─────────────────────────────────────────────────────────────
# Structured Log Helpers
# ─────────────────────────────────────────────────────────────
def log_crawl_event(
    url: str,
    depth: int,
    status_code: int,
    links_found: int,
    latency_ms: float,
):
    """Log a structured crawl event."""
    crawl_logger.info(
        "[CRAWL] URL: %s | Depth: %d | Status: %d | Links: %d | Time: %.0fms",
        url, depth, status_code, links_found, latency_ms,
    )


def log_discovery_event(new_urls_count: int):
    """Log a URL discovery batch event."""
    discovery_logger.info(
        "[DISCOVERY] Added %d new URLs to frontier", new_urls_count,
    )


def log_skip_event(url: str, reason: str):
    """Log a skipped URL with reason."""
    crawl_logger.warning("[SKIP] %s: %s", reason, url)


def log_error_event(url: str, error: str, detail: Optional[str] = None):
    """Log a crawl error."""
    msg = f"[ERROR] {error}: {url}"
    if detail:
        msg += f" | Detail: {detail}"
    crawl_logger.error(msg)


def log_blocked_event(url: str):
    """Log a robots.txt block."""
    robots_logger.warning("[SKIP] Blocked by robots.txt: %s", url)


def log_session_event(session_id: str, event: str, detail: str = ""):
    """Log a crawl session lifecycle event."""
    msg = f"[SESSION:{session_id[:8]}] {event}"
    if detail:
        msg += f" | {detail}"
    session_logger.info(msg)
