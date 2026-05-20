"""BajajSpider — Scrapy port of the legacy BFS engine.

Single-spider, single-domain crawler scoped to the same configuration
the legacy engine uses (``apps.crawler.conf.settings.seed_url`` plus
``allowed_domains``). Mirrors legacy behaviour 1:1 at this stage:

  * Seed = ``settings.seed_url``
  * Allowed hosts = ``settings.allowed_domains``
  * Sitemap discovery: harvests ``/sitemap.xml`` + ``/sitemap_index.xml``
    + every sitemap declared in robots.txt at start
  * Depth + page caps from settings
  * URL normalisation + trap filtering via the existing
    ``engine.url_utils`` helpers — same dedupe/filter rules as legacy
  * Per-page parse: title, word_count, response_time_ms, content_type,
    plus the standard error_type/error_message bookkeeping
  * Output goes through the existing ``storage.csv_writer.append`` so
    the Phase 3c dual-write hook fires unchanged — Postgres tables
    populate the same way they would for legacy

What Scrapy gives us for free that legacy hand-rolled:

  * AutoThrottle (latency-adaptive throttle) — enabled in
    scrapy_settings.py
  * RFPDupeFilter (sha1 over canonicalised URL+method+body+headers)
  * RobotsTxtMiddleware
  * RetryMiddleware with exponential backoff
  * DepthMiddleware
  * Per-host concurrency control

What this skeleton does NOT do (Phase 3e additions):

  * Playwright JS rendering for thin static responses
  * Similar-URL collapse (Katana `-fsu` pattern)
  * JSONL event log pipeline
  * AutoscaledPool resource governor

Run it via:

    python manage.py crawl_scrapy [--max-pages N] [--seed URL]

The management command wires the snapshot lifecycle around the spider
so CrawlSnapshot rows get created at start and finalised at end with
status + Health Score.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy
from scrapy.http import Request, Response
from scrapy.spiders import Spider

from ..conf import settings as crawler_settings
from ..engine.url_utils import (
    has_skip_extension,
    is_allowed_domain,
    is_trap,
    normalize,
)


_DEFAULT_SITEMAP_GUESSES = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
)


def _wordcount_of(body: str) -> int:
    """Mirror engine.parser word-count behaviour."""
    if not body:
        return 0
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body, "html.parser")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        return len(text.split())
    except Exception:  # noqa: BLE001
        return 0


def _title_of(body: str) -> str:
    if not body:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body, "html.parser")
        t = soup.find("title")
        return (t.get_text(strip=True) if t else "")[:1024]
    except Exception:  # noqa: BLE001
        return ""


def _is_html(headers) -> bool:
    ctype = (headers.get("Content-Type") or b"").decode(
        "ascii", errors="ignore"
    ).lower()
    return "html" in ctype or "xml" in ctype


class BajajSpider(Spider):
    """The single Scrapy spider for our crawl.

    Custom-settings approach: instead of forcing a separate
    ``scrapy_settings.py`` import on the operator's PYTHONPATH, we
    declare every setting on the spider itself. That keeps the
    ``python manage.py crawl_scrapy`` UX boilerplate-free.
    """

    name = "bajaj"

    custom_settings = {
        # ── Identity ──────────────────────────────────────────────
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
            "BajajSEOBot/1.0 (+https://www.bajajlifeinsurance.com)"
        ),
        "ROBOTSTXT_OBEY": True,
        # ── Politeness ────────────────────────────────────────────
        "CONCURRENT_REQUESTS": 16,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 0.5,
        "AUTOTHROTTLE_MAX_DELAY": 10.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 4.0,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        # ── Retries ───────────────────────────────────────────────
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 3,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504, 408],
        # ── Limits ────────────────────────────────────────────────
        "DEPTH_LIMIT": 0,  # set by the management command at runtime
        "CLOSESPIDER_PAGECOUNT": 0,  # set by the management command
        "DOWNLOAD_TIMEOUT": 30,
        # ── Logging ───────────────────────────────────────────────
        "LOG_LEVEL": "INFO",
        # ── Pipelines (Phase 3d): single dual-write pipeline that
        #    funnels every successful row through storage.csv_writer
        #    so the Phase 3c dual-write to Postgres fires automatically. ──
        "ITEM_PIPELINES": {
            "apps.crawler.pipelines.csv_dual_write.CsvDualWritePipeline": 300,
        },
        # ── Memory / cache ────────────────────────────────────────
        "HTTPCACHE_ENABLED": False,
        "TELNETCONSOLE_ENABLED": False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._allowed_domains = list(crawler_settings.allowed_domains)
        self._seed_url = (
            kwargs.get("seed_url") or crawler_settings.seed_url
        )
        # Honor optional runtime overrides from the management command.
        max_pages_override = kwargs.get("max_pages")
        if max_pages_override:
            try:
                self.custom_settings["CLOSESPIDER_PAGECOUNT"] = int(max_pages_override)
            except (TypeError, ValueError):
                pass
        max_depth_override = kwargs.get("max_depth")
        if max_depth_override:
            try:
                self.custom_settings["DEPTH_LIMIT"] = int(max_depth_override)
            except (TypeError, ValueError):
                pass

        # Spider-level scrapy attribute. Must match allowed_domains
        # the legacy engine uses so OffsiteMiddleware behaves the same.
        self.allowed_domains = [d for d in self._allowed_domains if d]

    # ── start ──────────────────────────────────────────────────────
    def start_requests(self):
        """Seed = seed_url + every sitemap URL we can harvest at start.

        Mirrors ``engine._seed`` — we discover sitemap URLs and prime
        the frontier with them so Scrapy doesn't have to climb a deep
        link graph to find product pages.
        """
        seen: set[str] = set()
        # Seed the homepage itself.
        u = normalize(self._seed_url)
        if u:
            seen.add(u)
            yield Request(u, callback=self.parse, meta={"depth": 0})

        # Harvest sitemap entries — synchronous one-shot at start.
        for sm_url in self._discover_sitemap_urls():
            u = normalize(sm_url)
            if not u or u in seen:
                continue
            if not self._eligible(u):
                continue
            seen.add(u)
            # Sitemap-discovered URLs come in as depth=0 so they're
            # treated as priority seeds, not as link-walked pages.
            yield Request(
                u,
                callback=self.parse,
                meta={"depth": 0, "from_sitemap": True},
                dont_filter=False,
            )
        self.logger.info(
            "BajajSpider seeded %d URLs (1 seed + %d sitemap)",
            len(seen), len(seen) - 1,
        )

    def _discover_sitemap_urls(self) -> list[str]:
        """Read robots.txt + try common sitemap paths.

        Re-uses the same sitemap-discovery helpers the legacy engine
        uses so the seed set matches across both engines (an A/B diff
        smoke test relies on parity at the seed level).
        """
        try:
            import requests
            from ..engine import sitemap as sitemap_mod
        except ImportError:
            return []
        out: list[str] = []
        p = urlparse(self._seed_url)
        origin = f"{p.scheme}://{p.netloc}"
        # robots.txt-declared sitemaps
        try:
            r = requests.get(
                f"{origin}/robots.txt", timeout=10,
                headers={"User-Agent": self.custom_settings["USER_AGENT"]},
                verify=False,
            )
            robots_sitemaps = []
            for line in r.text.splitlines():
                line = line.strip()
                if line.lower().startswith("sitemap:"):
                    robots_sitemaps.append(line.split(":", 1)[1].strip())
        except Exception:  # noqa: BLE001
            robots_sitemaps = []
        # Common guesses
        candidates = robots_sitemaps + [origin + g for g in _DEFAULT_SITEMAP_GUESSES]
        seen: set[str] = set()
        for sm in candidates:
            if sm in seen:
                continue
            seen.add(sm)
            try:
                # Reuse the legacy sitemap harvester so XML/gzip parsing
                # stays identical; it returns a list of URLs.
                import requests as _rq
                session = _rq.Session()
                session.verify = False
                out.extend(sitemap_mod.harvest(sm, session))
            except Exception:  # noqa: BLE001
                continue
        return out

    # ── eligibility ────────────────────────────────────────────────
    def _eligible(self, url: str) -> bool:
        if not url:
            return False
        if not is_allowed_domain(url):
            return False
        if has_skip_extension(url):
            return False
        if is_trap(url):
            return False
        return True

    # ── parse ──────────────────────────────────────────────────────
    def parse(self, response: Response, **kwargs):
        """Per-URL extraction + link enqueue.

        Yields:
          * one dict-item per URL (passes to CsvDualWritePipeline)
          * one Request per discovered in-domain link the URL filters
            don't reject
        """
        url = response.url
        depth = response.meta.get("depth", 0)
        from_sitemap = "1" if response.meta.get("from_sitemap") else "0"
        # Try to convert response time from Scrapy metadata
        download_latency = response.meta.get("download_latency") or 0
        response_time_ms = int(download_latency * 1000) if download_latency else 0

        body_text = ""
        if _is_html(response.headers):
            try:
                body_text = response.text
            except Exception:  # noqa: BLE001
                body_text = ""

        word_count = _wordcount_of(body_text) if body_text else 0
        title = _title_of(body_text) if body_text else ""

        # Status mapping that mirrors legacy fetch result shape so
        # downstream consumers (Page Explorer, audit detectors) don't
        # care which engine produced the row.
        if response.status == 200:
            status_label = "OK"
        elif 300 <= response.status < 400:
            status_label = "Redirect"
        elif 400 <= response.status < 500:
            status_label = "ClientError"
        elif 500 <= response.status < 600:
            status_label = "ServerError"
        else:
            status_label = str(response.status)

        yield {
            "url": url,
            "status_code": str(response.status),
            "status": status_label,
            "title": title,
            "word_count": word_count,
            "response_time_ms": response_time_ms,
            "content_type": (
                response.headers.get("Content-Type") or b""
            ).decode("ascii", errors="ignore"),
            "error_type": "",
            "error_message": "",
            "from_sitemap": from_sitemap,
        }

        # Discover links — but only when this was an HTML 2xx
        # response. Non-200s or non-HTML get one parse + no link walk.
        if response.status != 200 or not body_text:
            return
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(body_text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                # Resolve relative to current URL
                try:
                    abs_url = response.urljoin(href)
                except ValueError:
                    continue
                abs_url = normalize(abs_url)
                if not self._eligible(abs_url):
                    continue
                yield Request(
                    abs_url,
                    callback=self.parse,
                    meta={"depth": depth + 1},
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("link extraction failed for %s: %s", url, exc)

    # ── error handling ─────────────────────────────────────────────
    def errback_default(self, failure):
        """Record fetch failures so they show up in the audit catalog
        the same way legacy engine errors do."""
        request = failure.request
        url = getattr(request, "url", "")
        err_type = type(failure.value).__name__
        err_msg = str(failure.value)[:1000]
        yield {
            "url": url,
            "status_code": "0",
            "status": "Failed",
            "title": "",
            "word_count": 0,
            "response_time_ms": 0,
            "content_type": "",
            "error_type": err_type,
            "error_message": err_msg,
            "from_sitemap": "0",
        }
