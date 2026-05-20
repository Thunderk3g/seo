"""Playwright JS rendering gate — Phase 3e.

The legacy fetcher returns raw HTML. SPAs (Angular / React / Vue
landing shells) serve a near-empty body on the first request and
populate the DOM via JS after hydration. Static fetches see those
pages as 19-word stubs — exactly what we saw on iciciprulife.com in
the 2026-05-21 data audit.

This middleware sits in the downloader chain and watches every HTML
response. When a 2xx HTML response has a body that's too thin to be
real content, it re-issues the same URL with
``meta={"playwright": True}`` so scrapy-playwright fetches it through
a headless Chromium. The rendered body lands in the spider's parse
callback exactly like a normal response would.

Cost: only triggered on the small subset of URLs that look like SPA
shells, so the Chromium fleet doesn't have to render every page.

Heuristics for "too thin":

  * Content-Type contains "html"
  * HTTP status 2xx
  * Body text after stripping <script>/<style>/<noscript>/<template>
    is shorter than ``MIN_TEXT_CHARS`` (default 500)
  * Request not already a Playwright re-issue (avoid infinite loop)

Side effects:

  * The re-issued Request carries ``meta["playwright_render_pass"]``
    so this middleware can short-circuit on the second pass.
  * On rendered responses we also stamp meta["static_word_count"] and
    meta["rendered_word_count"] so the spider's parse can record both
    in the CrawlerPageResult row.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Iterable

from scrapy.http import Request, Response

log = logging.getLogger("apps.crawler.middlewares.playwright_gate")

# Configurable via env. 500 covers the iciciprulife-class shell case
# (19 words) without firing on legitimately short pages.
MIN_TEXT_CHARS = int(os.environ.get("CRAWLER_PLAYWRIGHT_MIN_TEXT_CHARS", "500"))

_STRIP_TAGS = re.compile(
    r"<(script|style|noscript|template)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _visible_text_length(body: bytes) -> int:
    """Approximate the visible-text byte length without paying for a
    full BeautifulSoup parse. Strips scripts/styles + any remaining
    HTML tags, then collapses whitespace."""
    try:
        s = body.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return 0
    s = _STRIP_TAGS.sub("", s)
    s = _TAG.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return len(s)


def _is_html(headers) -> bool:
    ctype = (headers.get("Content-Type") or b"").decode("ascii", errors="ignore").lower()
    return "html" in ctype


class PlaywrightGateMiddleware:
    """Downloader middleware. Returning a new Request from
    ``process_response`` causes Scrapy to enqueue it as a follow-up
    fetch and discard the current response."""

    def __init__(self, *, enabled: bool = True, min_chars: int = MIN_TEXT_CHARS) -> None:
        self.enabled = enabled
        self.min_chars = min_chars
        self._stats = {"checked": 0, "rerouted": 0, "skipped_short": 0}

    @classmethod
    def from_crawler(cls, crawler):
        # Allow per-run override via Scrapy setting + env var.
        enabled = crawler.settings.getbool("PLAYWRIGHT_GATE_ENABLED", True)
        min_chars = crawler.settings.getint(
            "PLAYWRIGHT_GATE_MIN_CHARS", MIN_TEXT_CHARS,
        )
        return cls(enabled=enabled, min_chars=min_chars)

    def process_response(self, request: Request, response: Response, spider) -> Response | Request:
        if not self.enabled:
            return response
        # Don't re-process a Playwright-rendered response (the second pass).
        if request.meta.get("playwright_render_pass"):
            # Stamp metadata for the spider to record on the item.
            response.meta["playwright_render_pass"] = True
            return response
        # Only consider successful HTML pages.
        if not (200 <= response.status < 300):
            return response
        if not _is_html(response.headers):
            return response

        self._stats["checked"] += 1
        text_len = _visible_text_length(response.body)
        if text_len >= self.min_chars:
            return response

        # Thin static response — re-issue with Playwright.
        self._stats["rerouted"] += 1
        log.info(
            "playwright_gate: rerouting %s (static text len=%d < %d)",
            request.url, text_len, self.min_chars,
        )
        new_meta = dict(request.meta)
        new_meta["playwright"] = True
        new_meta["playwright_render_pass"] = True
        new_meta["static_text_length"] = text_len
        # scrapy-playwright wait-until "networkidle" gives JS a chance
        # to hydrate before we sample the DOM.
        new_meta["playwright_page_methods"] = [
            {"method": "wait_for_load_state", "args": ["networkidle"]},
        ]
        return Request(
            url=request.url,
            method=request.method,
            headers=request.headers,
            cookies=request.cookies,
            meta=new_meta,
            dont_filter=True,
            callback=request.callback,
            errback=request.errback,
            priority=request.priority,
        )
