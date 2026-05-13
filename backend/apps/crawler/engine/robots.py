"""Robots.txt handler — fetch, parse, expose can_fetch + sitemap URLs."""
from __future__ import annotations

import urllib.robotparser
from urllib.parse import urlparse

import requests

from ..conf import settings
from ..logger import get_logger

log = get_logger(__name__)


def load(session: requests.Session) -> tuple[urllib.robotparser.RobotFileParser, list[str]]:
    """Return (parser, list-of-sitemap-urls)."""
    p = urlparse(settings.seed_url)
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    sitemaps: list[str] = []
    try:
        resp = session.get(robots_url, timeout=settings.request_timeout)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemaps.append(line.split(":", 1)[1].strip())
            log.info("Loaded robots.txt (%d sitemaps)", len(sitemaps))
        else:
            log.warning("robots.txt returned %s, allowing everything", resp.status_code)
            rp.parse(["User-agent: *", "Allow: /"])
    except Exception as exc:  # noqa: BLE001
        log.warning("robots.txt fetch failed (%s) — allowing everything", exc)
        rp.parse(["User-agent: *", "Allow: /"])
    return rp, sitemaps


def can_fetch(rp: urllib.robotparser.RobotFileParser, url: str) -> bool:
    if not settings.respect_robots:
        return True
    try:
        return rp.can_fetch(settings.user_agent, url)
    except Exception:
        return True


def crawl_delay(rp: urllib.robotparser.RobotFileParser) -> float:
    """Crawl-delay (seconds) declared for our UA in robots.txt, else 0.0."""
    if not settings.respect_crawl_delay:
        return 0.0
    try:
        d = rp.crawl_delay(settings.user_agent)
        return float(d) if d else 0.0
    except Exception:
        return 0.0
