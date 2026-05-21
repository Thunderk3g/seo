"""CompetitorSpider — Scrapy port of CompetitorCrawler.

One spider instance per competitor domain. Reuses the in-house
Playwright gate middleware (apps.crawler.middlewares.playwright_gate)
so SPA competitor sites that return thin static HTML get re-rendered
in headless Chromium — same path the Bajaj spider uses.

Yields one dict per URL with every CompetitorPage field the legacy
adapter exposes, plus full ``body_text``. The CompetitorDualWritePipeline
fans that into CrawlerPageResult rows tagged ``kind='competitor'``.

Behavioural parity with the legacy CompetitorCrawler:

  * Per-host throttle via DOWNLOAD_DELAY + AutoThrottle (latency-adaptive)
  * Robots.txt honoured (allow-all on fetch failure, same as legacy)
  * Retry on 408/429/500/502/503/504 with exponential backoff
  * Content-Type guard — non-HTML 200s recorded without body parsing
  * Body cap from COMPETITOR.max_body_bytes (0 = unlimited)

Run via the CompetitorCrawlerScrapy façade (synchronous, crochet-bridged)
or directly with scrapy.crawler.CrawlerRunner if you're inside Twisted.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Iterable
from urllib.parse import urlparse

import scrapy
from scrapy.http import Request, Response
from scrapy.spiders import Spider

log = logging.getLogger("apps.seo_ai.spiders.competitor")


_WHITESPACE_RE = re.compile(r"\s+")
_CTA_VERB_RE = re.compile(
    r"\b(buy\s*now|get\s*(?:quote|started)|calculate|apply\s*now|register|"
    r"download|sign\s*up|book\s*now|start\s*free|try\s*free|request\s*(?:a\s*)?call|"
    r"compare\s*plans|view\s*plans|get\s*plan|enquire\s*now|subscribe)\b",
    re.I,
)


def _is_html_headers(headers) -> bool:
    ctype = (headers.get("Content-Type") or b"").decode("ascii", errors="ignore").lower()
    return "html" in ctype or "xml" in ctype


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _collect_schema_types(node, out: list[str]) -> None:
    """Mirror of legacy adapter helper — walks JSON-LD for @type values."""
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str) and t.strip():
            out.append(t.strip()[:64])
        elif isinstance(t, list):
            for v in t:
                if isinstance(v, str) and v.strip():
                    out.append(v.strip()[:64])
        for v in node.values():
            if isinstance(v, (dict, list)):
                _collect_schema_types(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_schema_types(v, out)


class CompetitorSpider(Spider):
    """Scrapy spider for a single competitor domain.

    Constructor kwargs:
      * ``target_domain`` — apex host of this competitor (e.g.
        "iciciprulife.com"). Stamped on the CrawlSnapshot row.
      * ``urls`` — iterable of URLs to fetch. Pre-grouped by host
        upstream so every URL here matches target_domain.
      * ``body_text_max_chars`` — optional cap on body_text length.
        0 / negative / None = unlimited (matches COMPETITOR.body_text_max_chars).
    """

    name = "competitor"

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "CONCURRENT_REQUESTS": 16,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4,
        "DOWNLOAD_DELAY": 1.0,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 1.0,
        "AUTOTHROTTLE_MAX_DELAY": 15.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 2,
        "RETRY_HTTP_CODES": [408, 429, 500, 502, 503, 504, 520, 521, 522, 524],
        "DOWNLOAD_TIMEOUT": 30,
        "LOG_LEVEL": "INFO",
        "ITEM_PIPELINES": {
            "apps.seo_ai.pipelines.competitor_postgres.CompetitorDualWritePipeline": 300,
        },
        # Playwright gate — same middleware as BajajSpider, opt-in via
        # COMPETITOR_USE_PLAYWRIGHT_FALLBACK env (set on the spider in
        # __init__ via custom_settings update).
        "DOWNLOADER_MIDDLEWARES": {
            "apps.crawler.middlewares.playwright_gate.PlaywrightGateMiddleware": 850,
        },
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 30_000,
        "PLAYWRIGHT_MAX_PAGES_PER_CONTEXT": 4,
        "HTTPCACHE_ENABLED": False,
        "TELNETCONSOLE_ENABLED": False,
    }

    def __init__(
        self,
        *args,
        target_domain: str = "",
        urls: Iterable[str] | None = None,
        body_text_max_chars: int = 0,
        user_agent: str | None = None,
        playwright_enabled: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.target_domain = (target_domain or "").lower().lstrip("www.")
        self._urls: list[str] = list(urls or [])
        self.body_text_max_chars = int(body_text_max_chars or 0)
        # Spider-level allowed_domains so Scrapy's OffsiteMiddleware
        # doesn't drop www-vs-apex redirects.
        if self.target_domain:
            self.allowed_domains = [self.target_domain]
        # Per-instance custom settings tweaks — applied via from_crawler
        # path; here we just stash for the pipeline to read.
        self._user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        self._playwright_enabled = bool(playwright_enabled)
        # Items captured so the synchronous façade can return them. The
        # pipeline still persists to Postgres in parallel.
        self.captured_items: list[dict] = []

    # ── start ──────────────────────────────────────────────────────
    def start_requests(self):
        """Emit one Request per URL in the input list. No link walking
        — competitor URLs come pre-selected from the gap pipeline."""
        for url in self._urls:
            if not url:
                continue
            meta = {"download_latency_t0": time.monotonic()}
            yield Request(
                url,
                callback=self.parse,
                errback=self.errback_default,
                meta=meta,
                dont_filter=False,
                headers={"User-Agent": self._user_agent},
            )

    # ── parse ──────────────────────────────────────────────────────
    def parse(self, response: Response, **kwargs):
        url = response.url
        # Scrapy fills download_latency on every response.
        download_latency = response.meta.get("download_latency") or 0.0
        response_time_ms = int(download_latency * 1000) if download_latency else 0

        status = response.status
        status_str = str(status)
        last_modified = (
            response.headers.get("Last-Modified") or b""
        ).decode("ascii", errors="ignore")
        content_type = (
            response.headers.get("Content-Type") or b""
        ).decode("ascii", errors="ignore")

        # Non-200 → record metadata only, no body parse.
        if status != 200:
            yield self._error_item(
                url=url,
                final_url=response.url,
                status=status_str,
                response_time_ms=response_time_ms,
                content_type=content_type,
                last_modified=last_modified,
                error=f"http {status}",
            )
            return

        # 200 + non-HTML → record metadata, skip parse.
        if not _is_html_headers(response.headers):
            yield self._error_item(
                url=url,
                final_url=response.url,
                status=status_str,
                response_time_ms=response_time_ms,
                content_type=content_type,
                last_modified=last_modified,
                error=f"non-html content-type: {content_type}",
            )
            return

        body_text_raw = response.text or ""
        parsed = self._parse_html(
            url=url,
            final_url=response.url,
            body=body_text_raw,
        )
        parsed.update({
            "status_code": status_str,
            "status": "OK",
            "response_time_ms": response_time_ms,
            "content_type": content_type,
            "last_modified": last_modified,
            "playwright_used": bool(response.meta.get("playwright_render_pass")),
            "target_domain": self.target_domain,
            "error_type": "",
            "error_message": "",
            "error": "",
        })
        yield parsed

    # ── error item helpers ─────────────────────────────────────────
    def _error_item(
        self,
        *,
        url: str,
        final_url: str,
        status: str,
        response_time_ms: int,
        content_type: str,
        last_modified: str,
        error: str,
    ) -> dict:
        return {
            "url": url,
            "final_url": final_url,
            "status_code": status,
            "status": "HTTPError" if status != "0" else "Failed",
            "response_time_ms": response_time_ms,
            "content_type": content_type,
            "last_modified": last_modified,
            "title": "",
            "word_count": 0,
            "body_text": "",
            "title_length": 0,
            "meta_description": "",
            "meta_description_length": 0,
            "canonical": "",
            "meta_robots": "",
            "h1_texts": [],
            "h2_texts": [],
            "h2_count": 0,
            "h3_count": 0,
            "internal_link_count": 0,
            "external_link_count": 0,
            "image_count": 0,
            "image_alt_pct": 0.0,
            "cta_count": 0,
            "schema_types": [],
            "has_schema_org": False,
            "playwright_used": False,
            "target_domain": self.target_domain,
            "error_type": "HTTPError" if status not in ("0", "") else "NetworkError",
            "error_message": error,
            "error": error,
        }

    def errback_default(self, failure):
        request = failure.request
        url = getattr(request, "url", "")
        err_type = type(failure.value).__name__
        err_msg = str(failure.value)[:1000]
        yield self._error_item(
            url=url,
            final_url=url,
            status="0",
            response_time_ms=0,
            content_type="",
            last_modified="",
            error=f"{err_type}: {err_msg}",
        )

    # ── HTML parse ─────────────────────────────────────────────────
    def _parse_html(self, *, url: str, final_url: str, body: str) -> dict:
        """Extract every CompetitorPage field from HTML.

        Mirrors apps.seo_ai.adapters.competitor_crawler._parse_html so
        the dataclass downstream gets identical values regardless of
        which engine fetched it.
        """
        from bs4 import BeautifulSoup

        out: dict = {
            "url": url,
            "final_url": final_url or url,
        }
        if not body:
            out.update({
                "title": "", "title_length": 0,
                "meta_description": "", "meta_description_length": 0,
                "canonical": "", "meta_robots": "",
                "h1_texts": [], "h2_texts": [],
                "h2_count": 0, "h3_count": 0,
                "internal_link_count": 0, "external_link_count": 0,
                "image_count": 0, "image_alt_pct": 0.0, "cta_count": 0,
                "schema_types": [], "has_schema_org": False,
                "word_count": 0, "body_text": "",
            })
            return out

        soup = BeautifulSoup(body, "html.parser")

        # Title / meta description / canonical / robots
        title_tag = soup.find("title")
        title = (title_tag.get_text(strip=True) if title_tag else "")[:512]
        out["title"] = title
        out["title_length"] = len(title)

        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if meta_desc and meta_desc.get("content"):
            md = str(meta_desc["content"]).strip()[:1024]
            out["meta_description"] = md
            out["meta_description_length"] = len(md)
        else:
            out["meta_description"] = ""
            out["meta_description_length"] = 0

        meta_robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        out["meta_robots"] = (
            str(meta_robots["content"]).strip()[:256]
            if meta_robots and meta_robots.get("content") else ""
        )

        canonical = soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)})
        out["canonical"] = (
            str(canonical["href"]).strip()[:1024]
            if canonical and canonical.get("href") else ""
        )

        # Headings
        out["h1_texts"] = [
            h.get_text(" ", strip=True)[:256]
            for h in soup.find_all("h1")
            if h.get_text(strip=True)
        ]
        h2_tags = [h for h in soup.find_all("h2") if h.get_text(strip=True)]
        h3_tags = [h for h in soup.find_all("h3") if h.get_text(strip=True)]
        out["h2_count"] = len(h2_tags)
        out["h3_count"] = len(h3_tags)
        out["h2_texts"] = [h.get_text(" ", strip=True)[:200] for h in h2_tags[:8]]

        # Links + CTAs
        page_host = (_host(final_url or url) or "").lstrip("www.")
        internal = external = cta = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            a_host = ""
            if href.startswith("http"):
                a_host = (_host(href) or "").lstrip("www.")
            if not a_host or a_host == page_host or a_host.endswith("." + page_host):
                internal += 1
            else:
                external += 1
            text = a.get_text(" ", strip=True)
            if text and _CTA_VERB_RE.search(text):
                cta += 1
        out["internal_link_count"] = internal
        out["external_link_count"] = external
        out["cta_count"] = cta

        # Images
        imgs = soup.find_all("img")
        out["image_count"] = len(imgs)
        if imgs:
            with_alt = sum(1 for i in imgs if (i.get("alt") or "").strip())
            out["image_alt_pct"] = round(100.0 * with_alt / len(imgs), 1)
        else:
            out["image_alt_pct"] = 0.0

        # JSON-LD schema types
        schema_types: list[str] = []
        for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
            raw = script.string or script.get_text() or ""
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            _collect_schema_types(data, schema_types)
        seen: set[str] = set()
        out["schema_types"] = [
            t for t in schema_types if not (t in seen or seen.add(t))
        ][:20]
        out["has_schema_org"] = bool(out["schema_types"])

        # Body text — strip non-visible tags, collapse whitespace.
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        text = _WHITESPACE_RE.sub(" ", text).strip()
        out["word_count"] = len(text.split()) if text else 0
        cap = self.body_text_max_chars
        out["body_text"] = text if cap <= 0 else text[:cap]
        return out
