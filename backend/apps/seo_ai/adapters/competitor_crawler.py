"""Polite single-purpose HTML fetcher for competitor SEO inspection.

The in-house ``apps.crawler.engine`` is hard-gated to
``bajajlifeinsurance.com`` via ``allowed_domains`` (see
``apps/crawler/engine/conf.py`` and ``url_utils.is_allowed_domain``).
We need to inspect *other* domains for the competitor-gap agent, so we
ship a small standalone fetcher that:

- Groups URLs by hostname and enforces a per-host token-bucket
  throttle (≥1 second between requests by default).
- Lazily loads each host's ``robots.txt`` and skips disallowed paths.
  Robots fetch failure → allow-all + WARN, same policy as the
  in-house crawler.
- Disk-caches the raw HTML at
  ``{SEO_AI.data_dir}/_competitor_cache/{sha1(url)}.html`` with a
  sidecar ``.meta.json`` (status_code, fetched_at). TTL configurable
  via ``COMPETITOR_CACHE_TTL_SECONDS`` env var.
- TLS verification driven by ``COMPETITOR_SSL_VERIFY`` env var, parsed
  identically to ``SEMRUSH_SSL_VERIFY`` — needed inside the Docker
  image where the Debian trust store lacks the corp MITM root.
- 15-second soft timeout, no retries on 4xx/5xx (logged + skipped).
- Uses ``truststore`` on Windows hosts so corporate root CAs work
  without disabling verification.

We deliberately do NOT extend ``apps.crawler.engine.parser`` — keeping
this module self-contained means a competitor-fetch bug can't regress
the production crawler.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from django.conf import settings

# truststore so corp MITM proxies work on Windows hosts. Safe no-op
# on Linux containers and if the package isn't installed.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

logger = logging.getLogger("seo.ai.adapters.competitor_crawler")


@dataclass
class CompetitorPage:
    """One fetched + parsed competitor (or our own) page.

    A failed fetch still yields a CompetitorPage with ``status_code``
    set (0 for network errors, or the actual HTTP status for non-2xx)
    and an ``error`` string. Downstream scoring filters on
    ``status_code == 200``.

    The same dataclass is used for our-side pages in Phase 2A's
    symmetric crawl — all fields are computed from live HTML so the
    comparison is apples-to-apples on both sides.
    """

    url: str
    final_url: str = ""
    status_code: int = 0
    fetched_at: str = ""
    error: str = ""
    title: str = ""
    title_length: int = 0
    meta_description: str = ""
    meta_description_length: int = 0
    h1_texts: list[str] = field(default_factory=list)
    canonical: str = ""
    word_count: int = 0
    has_schema_org: bool = False
    # Phase 2A — symmetric structural metrics.
    response_time_ms: int = 0
    last_modified: str = ""            # HTTP Last-Modified header (RFC 1123)
    h2_count: int = 0
    h3_count: int = 0
    h2_texts: list[str] = field(default_factory=list)   # first 8 only
    internal_link_count: int = 0
    external_link_count: int = 0
    image_count: int = 0
    image_alt_pct: float = 0.0         # % of <img> with non-empty alt
    cta_count: int = 0                 # <a> whose text matches a CTA verb
    schema_types: list[str] = field(default_factory=list)  # JSON-LD @type values
    meta_robots: str = ""              # content of <meta name="robots">
    body_text: str = ""                # Phase 2A — for content-keyword-fit scoring

    # ── PSI / Core Web Vitals (populated by enrich_with_cwv) ────────
    # Captured separately because PSI calls cost 1-40s each and would
    # serialise the page-fetch loop. None = not yet measured. Mobile +
    # desktop are stored side-by-side; field metrics are CrUX p75
    # real-user numbers (28-day window) and only present for URLs with
    # enough Chrome traffic.
    cwv_mobile: dict[str, Any] = field(default_factory=dict)
    cwv_desktop: dict[str, Any] = field(default_factory=dict)

    # ── Structural mirror (Phase 2A.5 — for competitor page Inspector) ──
    # The "where things are placed" data the dashboard needs in order to
    # replicate a competitor's information architecture.
    #
    # headings:        ordered list of every H1–H6 in document order, with
    #                  position index. Drives the page-outline tree view.
    # internal_links:  every <a> pointing within the same host. Each entry
    #                  has anchor text, href, the nearest preceding heading
    #                  text (so the UI can group "calculator links in the
    #                  pricing section"), and a kind classification.
    # external_links:  same shape but off-domain — useful for citation /
    #                  partner-link analysis.
    # images:          every <img> with src + alt + dimensions for per-image
    #                  alt audit and design replication.
    # videos:          every <video> tag + YouTube/Vimeo <iframe> embed.
    #                  Each entry: {src, kind, poster, section, zone, width,
    #                  height}. ``kind`` ∈ {native, youtube, vimeo, other}.
    headings: list[dict[str, Any]] = field(default_factory=list)
    internal_links: list[dict[str, Any]] = field(default_factory=list)
    external_links: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    videos: list[dict[str, Any]] = field(default_factory=list)


# ── Internal-link kind classifier ─────────────────────────────────────
# Reused from deep_crawl._PAGE_TYPE_PATTERNS *plus* Bajaj-product-aware
# buckets so the Inspector UI can answer "where does this page link to a
# calculator?" without further client-side parsing.
_LINK_KIND_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("calculator",      re.compile(r"/(calculator|estimate|tool)s?/?", re.I)),
    ("product_term",    re.compile(r"/term[-_]?insurance", re.I)),
    ("product_ulip",    re.compile(r"/ulip", re.I)),
    ("product_savings", re.compile(r"/(savings|endowment)", re.I)),
    ("product_retire",  re.compile(r"/(retirement|pension)", re.I)),
    ("product_child",   re.compile(r"/child[-_]?(insurance|plan)", re.I)),
    ("product_group",   re.compile(r"/group[-_]?(insurance|plan)", re.I)),
    ("product_health",  re.compile(r"/(health|wellness|diabetes)", re.I)),
    ("nri",             re.compile(r"/nri", re.I)),
    ("fund",            re.compile(r"/funds?/", re.I)),
    ("blog",            re.compile(r"/(blog|insights|articles|guide|resources)s?/?", re.I)),
    ("faq",             re.compile(r"/(faq|faqs|help|support)/?", re.I)),
    ("claim",           re.compile(r"/claim", re.I)),
    ("contact",         re.compile(r"/contact", re.I)),
    ("legal",           re.compile(r"/(privacy|terms|disclaimer|policy)", re.I)),
)


def _classify_link_kind(href: str) -> str:
    for label, pat in _LINK_KIND_PATTERNS:
        if pat.search(href):
            return label
    return "other"


def _classify_zone(el) -> str:
    """LayoutAgent zone tagger.

    Walks up the DOM from ``el`` and returns the closest enclosing
    landmark zone (``header``, ``nav``, ``main``, ``aside``, ``footer``,
    ``hero``, or ``other``). The zone tells the dashboard "where on
    the page does this link/image/heading live" — load-bearing context
    for the LayoutAgent's "competitors always put the calculator CTA
    in the hero; you bury it in the footer" claim.

    Detection rules (first match wins):

    * <header> or class/id containing "header" / "site-header" / "top"
    * <nav>   or class/id containing "nav" / "menu"
    * .hero / #hero / class containing "hero" / "banner" / "above-fold"
    * <main> / <article> / class "content" / "main"
    * <aside> / class "sidebar" / "related"
    * <footer> / id/class "footer" / "site-footer"
    * fallback: "other"
    """
    # Climb up to 12 ancestors max — beyond that we're at <body> or
    # we have a pathological DOM, either way "other" is the right call.
    cur = el
    hops = 0
    while cur is not None and hops < 12:
        parent = getattr(cur, "parent", None)
        if parent is None or getattr(parent, "name", None) in (None, "[document]"):
            break
        name = (getattr(parent, "name", "") or "").lower()
        attrs = parent.attrs if hasattr(parent, "attrs") else {}
        cls = " ".join(attrs.get("class") or []).lower()
        pid = (attrs.get("id") or "").lower()
        role = (attrs.get("role") or "").lower()
        blob = f" {cls} {pid} {role} "

        if name == "header" or "site-header" in blob or " masthead " in blob:
            return "header"
        if name == "nav" or " navigation " in blob or " menu " in blob:
            return "nav"
        if " hero " in blob or " banner " in blob or " above-fold " in blob:
            return "hero"
        if name in ("main", "article") or " main " in blob or " content " in blob:
            return "main"
        if name == "aside" or " sidebar " in blob or " related " in blob:
            return "aside"
        if name == "footer" or " site-footer " in blob or " footer " in blob:
            return "footer"
        cur = parent
        hops += 1
    return "other"


def _extract_structured(soup, page_host: str, base_url: str) -> dict[str, list]:
    """Walk the parsed document in document order and capture the
    structural mirror data: ordered headings, per-link inventory tagged
    with its nearest preceding section heading + DOM zone, and per-image
    details.

    Single-pass, no DOM rewriting — safe to call after the body-text
    extraction (which decomposes <script>/<style>/etc.) since headings,
    anchors and images aren't in the decomposed tag set.

    Each emitted entry carries:
      * ``section`` — nearest preceding heading text (drives "where in
        the visual flow").
      * ``zone`` — landmark element the entry lives inside (drives
        "header CTA vs footer CTA").
    """
    headings: list[dict[str, Any]] = []
    internal_links: list[dict[str, Any]] = []
    external_links: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []

    current_section = ""   # nearest preceding heading text, drives "where"

    # ``descendants`` walks the DOM in document order — exactly what we need.
    for el in soup.descendants:
        name = getattr(el, "name", None)
        if not name:
            continue

        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            level = int(name[1])
            headings.append({
                "level": level,
                "text": text[:300],
                "idx": len(headings),
                "zone": _classify_zone(el),
            })
            current_section = text[:200]
            continue

        if name == "a":
            href = (el.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            anchor = el.get_text(" ", strip=True)[:200]
            absolute = urljoin(base_url, href)
            target_host = (_host(absolute) or "").lower().lstrip("www.")
            entry = {
                "anchor": anchor,
                "href": absolute[:1024],
                "section": current_section,
                "zone": _classify_zone(el),
                "kind": _classify_link_kind(absolute),
                "rel": " ".join(el.get("rel") or []) or "",
            }
            if not target_host or target_host == page_host or target_host.endswith("." + page_host):
                internal_links.append(entry)
            else:
                external_links.append(entry)
            continue

        if name == "img":
            src = (el.get("src") or "").strip()
            if not src:
                continue
            images.append({
                "src": urljoin(base_url, src)[:1024],
                "alt": (el.get("alt") or "").strip()[:300],
                "width": (el.get("width") or "").strip()[:8],
                "height": (el.get("height") or "").strip()[:8],
                "section": current_section,
                "zone": _classify_zone(el),
                "loading": (el.get("loading") or "").strip()[:16],
            })
            continue

        if name == "video":
            # Native HTML5 <video>. ``src`` is either on the tag itself or
            # on a child <source>; pick the first one we find.
            src = (el.get("src") or "").strip()
            if not src:
                source = el.find("source")
                if source is not None:
                    src = (source.get("src") or "").strip()
            if not src:
                continue
            videos.append({
                "src": urljoin(base_url, src)[:1024],
                "kind": "native",
                "poster": (el.get("poster") or "").strip()[:1024],
                "section": current_section,
                "zone": _classify_zone(el),
                "width": (el.get("width") or "").strip()[:8],
                "height": (el.get("height") or "").strip()[:8],
            })
            continue

        if name == "iframe":
            # YouTube / Vimeo / Wistia embeds. Classify by hostname so
            # the UI can render the right thumbnail / aspect ratio.
            src = (el.get("src") or "").strip()
            if not src:
                continue
            src_low = src.lower()
            if "youtube.com/embed" in src_low or "youtube-nocookie.com" in src_low or "youtu.be" in src_low:
                kind = "youtube"
            elif "vimeo.com" in src_low or "player.vimeo.com" in src_low:
                kind = "vimeo"
            elif "wistia.com" in src_low or "wistia.net" in src_low:
                kind = "wistia"
            else:
                # Skip non-video iframes (analytics, ads, maps, etc.).
                continue
            videos.append({
                "src": urljoin(base_url, src)[:1024],
                "kind": kind,
                "poster": "",
                "section": current_section,
                "zone": _classify_zone(el),
                "width": (el.get("width") or "").strip()[:8],
                "height": (el.get("height") or "").strip()[:8],
            })

    return {
        "headings": headings,
        "internal_links": internal_links,
        "external_links": external_links,
        "images": images,
        "videos": videos,
    }


class CompetitorCrawler:
    """Synchronous fetcher. Caller passes a list of URLs; we group by
    host and yield :class:`CompetitorPage` results in input order.

    Factory dispatch: when ``settings.COMPETITOR["engine"] == "scrapy"``,
    instantiating ``CompetitorCrawler`` returns the Scrapy-backed
    subclass (``CompetitorCrawlerScrapy``) instead. The Scrapy path
    persists every fetched page to ``CrawlerPageResult`` so per-
    competitor Health Score works without changing any caller — the
    six existing call sites (gap pipeline, agents, scoring) keep using
    ``CompetitorCrawler()`` exactly as before.
    """

    def __new__(cls, *args, **kwargs):
        # Only dispatch when the base class is the requested type — if
        # a subclass (CompetitorCrawlerScrapy) is being instantiated
        # directly we let normal MRO handle it.
        if cls is CompetitorCrawler:
            try:
                cfg = getattr(settings, "COMPETITOR", {}) or {}
                engine = str(cfg.get("engine", "legacy")).strip().lower()
            except Exception:  # noqa: BLE001
                engine = "legacy"
            if engine == "scrapy":
                try:
                    # Import lazily so a broken Scrapy install doesn't
                    # crash the legacy path.
                    from .competitor_crawler_scrapy import (
                        CompetitorCrawlerScrapy,
                    )
                except ImportError as exc:
                    logger.warning(
                        "COMPETITOR_ENGINE=scrapy requested but Scrapy "
                        "façade import failed (%s) — falling back to legacy",
                        exc,
                    )
                else:
                    return super().__new__(CompetitorCrawlerScrapy)
        return super().__new__(cls)

    def __init__(
        self,
        *,
        rate_limit_sec: float | None = None,
        timeout_sec: int | None = None,
        user_agent: str | None = None,
        cache_ttl_seconds: int | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        cfg = settings.COMPETITOR
        self.rate_limit_sec = (
            rate_limit_sec if rate_limit_sec is not None else cfg["rate_limit_sec"]
        )
        self.timeout_sec = (
            timeout_sec if timeout_sec is not None else cfg["timeout_sec"]
        )
        self.user_agent = user_agent or cfg["user_agent"]
        self.cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else cfg["cache_ttl_seconds"]
        )
        self.error_cache_ttl_seconds = int(
            cfg.get("error_cache_ttl_seconds", 3600)
        )
        # ``0`` (or any negative value) disables the cap — the streamed
        # read keeps going until the server closes the connection. The
        # 100 MB default is a soft safety net for pathological responses
        # (untrusted competitor host serving a multi-GB page); operators
        # who want full content from every rival should set
        # ``COMPETITOR_MAX_BODY_BYTES=0`` in .env.
        self.max_body_bytes = int(cfg.get("max_body_bytes", 100 * 1024 * 1024))
        self.retry_attempts = max(1, int(cfg.get("retry_attempts", 3)))
        self.fetch_concurrency = max(1, int(cfg.get("fetch_concurrency", 10)))
        self.cache_dir = (
            cache_dir
            if cache_dir
            else settings.SEO_AI["data_dir"] / "_competitor_cache"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._verify = _resolve_competitor_ssl_verify(cfg.get("ssl_verify", ""))
        # Optional proxy (default ""): routes blocked rivals (Akamai/CF)
        # through a residential / scraper-API endpoint. No-op when empty.
        self.proxy_url = (cfg.get("proxy_url") or "").strip()
        if self._verify is False:
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:  # noqa: BLE001
                pass

        self._sessions: dict[str, requests.Session] = {}
        self._session_lock = threading.Lock()
        self._last_fetch: dict[str, float] = {}
        self._throttle_lock = threading.Lock()
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = threading.Lock()

    # ── public API ───────────────────────────────────────────────────

    def fetch_pages(self, urls: list[str]) -> list[CompetitorPage]:
        """Fetch many URLs in parallel across hosts, sequentially within
        each host (so per-host rate limit holds). Result list preserves
        input order regardless of completion order.

        Concurrency = ``fetch_concurrency`` (default 10) capped at the
        number of unique hosts in the batch. A 1-rival 50-URL batch
        runs purely sequentially under the host's rate limit; a
        10-rival 50-each batch runs all 10 hosts in parallel.
        """
        if not urls:
            return []

        # Group URLs by host so each worker thread owns one host's
        # rate-limited stream of requests. Preserves input order.
        host_groups: dict[str, list[tuple[int, str]]] = {}
        for idx, url in enumerate(urls):
            host = _host(url) or ""
            host_groups.setdefault(host, []).append((idx, url))

        results: list[CompetitorPage | None] = [None] * len(urls)
        max_workers = min(self.fetch_concurrency, len(host_groups)) or 1

        def _run_host(group: list[tuple[int, str]]) -> None:
            for idx, url in group:
                results[idx] = self.fetch_one(url)

        if max_workers == 1:
            for group in host_groups.values():
                _run_host(group)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(_run_host, g) for g in host_groups.values()]
                for f in as_completed(futures):
                    # Re-raise any unexpected exception so it surfaces
                    # in logs — but fetch_one already swallows network
                    # errors into CompetitorPage(error=...) so this
                    # mostly catches programming bugs.
                    f.result()

        # No worker should leave a None slot, but defensively replace
        # any remaining gaps with an error page so caller code never
        # hits None.
        return [
            r if r is not None else CompetitorPage(url=urls[i], error="not fetched")
            for i, r in enumerate(results)
        ]

    def enrich_with_cwv(
        self,
        pages: list[CompetitorPage],
        *,
        strategies: tuple[str, ...] | None = None,
        max_urls: int | None = None,
        psi_workers: int | None = None,
    ) -> list[CompetitorPage]:
        """Attach Core Web Vitals (PSI) to each successfully-fetched
        page. Mutates and returns the same list.

        Runs PSI calls in parallel across a small thread pool so a
        competitor's full page sample finishes in roughly the time of
        a SINGLE serial PSI call, not the sum. PSI is still slow
        (mobile 1-3s, desktop 30-40s) but with 4 workers the typical
        50-page enrichment drops from ~25 min to ~3 min.

        Silently degrades if PSI is disabled or the SA file is
        missing — pages keep their empty ``cwv_mobile`` / ``cwv_desktop``
        dicts and downstream consumers treat that as "CWV unavailable".
        """
        from .cwv_psi import AdapterDisabledError, PSIAdapter

        try:
            psi = PSIAdapter()
        except AdapterDisabledError as exc:
            logger.info("psi enrichment skipped: %s", exc)
            return pages

        cfg = getattr(settings, "PSI", {}) or {}
        if strategies is None:
            strategies = tuple(cfg.get("strategies") or ("mobile", "desktop"))
        if max_urls is None:
            # 0 means unlimited; treat None and missing key the same.
            limit = int(cfg.get("max_urls_per_run", 0))
            max_urls = limit if limit > 0 else len(pages)
        if psi_workers is None:
            psi_workers = max(1, int(cfg.get("inline_workers", 4)))

        # Only enrich pages we actually fetched OK — running PSI on a
        # 404 burns quota for no signal.
        candidates = [p for p in pages if p.status_code == 200][:max_urls]
        if not candidates:
            return pages

        def _enrich_one(page: CompetitorPage) -> None:
            for strategy in strategies:
                try:
                    record = psi.fetch(page.url, strategy=strategy)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "competitor psi %s/%s failed: %s",
                        strategy, page.url, exc,
                    )
                    continue
                bucket = "cwv_mobile" if strategy == "mobile" else "cwv_desktop"
                if record.error:
                    setattr(
                        page,
                        bucket,
                        {"error": record.error, "fetched_at": record.fetched_at},
                    )
                    continue
                setattr(
                    page,
                    bucket,
                    {
                        "performance_score": record.performance_score,
                        "lab_lcp_ms": record.lab_lcp_ms,
                        "lab_cls": record.lab_cls,
                        "lab_fcp_ms": record.lab_fcp_ms,
                        "lab_tbt_ms": record.lab_tbt_ms,
                        "lab_si_ms": record.lab_si_ms,
                        "lab_ttfb_ms": record.lab_ttfb_ms,
                        "field_lcp_ms": record.field_lcp_ms,
                        "field_lcp_category": record.field_lcp_category,
                        "field_cls": record.field_cls,
                        "field_cls_category": record.field_cls_category,
                        "field_inp_ms": record.field_inp_ms,
                        "field_inp_category": record.field_inp_category,
                        "field_fcp_ms": record.field_fcp_ms,
                        "field_fcp_category": record.field_fcp_category,
                        "field_ttfb_ms": record.field_ttfb_ms,
                        "field_ttfb_category": record.field_ttfb_category,
                        "has_field_data": record.has_field_data,
                        "cached": record.cached,
                        "fetched_at": record.fetched_at,
                    },
                )

        workers = min(psi_workers, len(candidates)) or 1
        if workers == 1:
            for page in candidates:
                _enrich_one(page)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_enrich_one, p) for p in candidates]
                for f in as_completed(futures):
                    # _enrich_one swallows fetch errors into the per-page
                    # cwv_* dicts already; surface unexpected exceptions
                    # (programming bugs) via the future's result.
                    try:
                        f.result()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("competitor psi worker crash: %s", exc)
        return pages

    def fetch_one(self, url: str) -> CompetitorPage:
        cached = self._cache_read(url)
        if cached is not None:
            return cached

        host = _host(url)
        if not host:
            return CompetitorPage(url=url, error="invalid url")

        if not self._robots_ok(host, url):
            page = CompetitorPage(url=url, error="blocked by robots.txt")
            self._cache_write(url, page, html="", is_error=True)
            return page

        last_error = ""
        page: CompetitorPage | None = None
        for attempt in range(self.retry_attempts):
            self._throttle(host)
            page, retryable = self._fetch_once(url)
            if not retryable or page.status_code == 200:
                break
            last_error = page.error
            # Exponential backoff with jitter, capped at 30s, before
            # the next attempt. Don't sleep after the last attempt.
            if attempt < self.retry_attempts - 1:
                delay = min(30.0, 1.5 * (2 ** attempt))
                delay += random.uniform(0, delay * 0.25)
                logger.info(
                    "competitor retry %d/%d for %s after %.1fs (%s)",
                    attempt + 1, self.retry_attempts, url, delay,
                    last_error or page.status_code,
                )
                time.sleep(delay)

        assert page is not None  # loop runs at least once

        # Cache write: success → 7-day TTL via cache_ttl_seconds.
        # Error → short TTL (error_cache_ttl_seconds, default 1h) so a
        # transient 503 doesn't lock the URL out for a week.
        is_error = page.status_code != 200 or bool(page.error)
        html_body = ""
        if page.status_code == 200 and not page.error:
            html_body = getattr(page, "_raw_html", "") or ""
            # Strip the transient attribute before caching so it
            # doesn't leak into the cached meta.
            if hasattr(page, "_raw_html"):
                try:
                    delattr(page, "_raw_html")
                except AttributeError:
                    pass
        self._cache_write(url, page, html=html_body, is_error=is_error)
        return page

    def _fetch_once(self, url: str) -> tuple[CompetitorPage, bool]:
        """Single HTTP attempt with stream + body-size + content-type
        guards. Returns (page, retryable). ``retryable=True`` signals
        the caller may try again after backoff."""
        host = _host(url) or ""
        session = self._session_for(host)
        t0 = time.monotonic()
        try:
            resp = session.get(
                url,
                timeout=self.timeout_sec,
                verify=self._verify,
                allow_redirects=True,
                stream=True,
            )
        except requests.exceptions.Timeout as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return CompetitorPage(
                url=url,
                error=f"timeout: {exc}"[:200],
                response_time_ms=elapsed_ms,
            ), True
        except requests.exceptions.ConnectionError as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return CompetitorPage(
                url=url,
                error=f"connection: {exc}"[:200],
                response_time_ms=elapsed_ms,
            ), True
        except requests.RequestException as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.warning("competitor fetch %s failed: %s", url, exc)
            return CompetitorPage(
                url=url,
                error=str(exc)[:200],
                response_time_ms=elapsed_ms,
            ), False  # not retryable — bad URL / SSL / redirects

        # We have headers — decide whether to read body at all.
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        status = resp.status_code

        # Non-200: don't read body, retry on transient 5xx / 429.
        if status != 200:
            retryable = status in {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 524}
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
            return CompetitorPage(
                url=url,
                final_url=str(resp.url),
                status_code=status,
                response_time_ms=elapsed_ms,
                last_modified=resp.headers.get("Last-Modified", ""),
                error=f"http {status}",
            ), retryable

        # 200 with non-HTML body — don't parse, just record metadata.
        if "html" not in ctype and "xml" not in ctype:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
            return CompetitorPage(
                url=url,
                final_url=str(resp.url),
                status_code=200,
                response_time_ms=elapsed_ms,
                last_modified=resp.headers.get("Last-Modified", ""),
                error=f"non-html content-type: {ctype}"[:200],
            ), False

        # Body-size guard via Content-Length, then streamed read.
        # ``max_body_bytes <= 0`` disables the cap entirely — the read
        # keeps going until the server closes the connection. Operators
        # who want the *entire* body for content comparison (per the
        # AEM-vs-competitor matcher) should set COMPETITOR_MAX_BODY_BYTES=0.
        unlimited = self.max_body_bytes <= 0
        content_length = resp.headers.get("Content-Length")
        if (
            not unlimited
            and content_length
            and content_length.isdigit()
            and int(content_length) > self.max_body_bytes
        ):
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
            return CompetitorPage(
                url=url,
                final_url=str(resp.url),
                status_code=200,
                response_time_ms=elapsed_ms,
                last_modified=resp.headers.get("Last-Modified", ""),
                error=f"body too large: Content-Length={content_length}",
            ), False

        try:
            chunks: list[bytes] = []
            received = 0
            truncated = False
            for chunk in resp.iter_content(chunk_size=64 * 1024, decode_unicode=False):
                if not chunk:
                    continue
                received += len(chunk)
                if not unlimited and received > self.max_body_bytes:
                    truncated = True
                    break
                chunks.append(chunk)
            body_bytes = b"".join(chunks)
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

        if truncated:
            return CompetitorPage(
                url=url,
                final_url=str(resp.url),
                status_code=200,
                response_time_ms=elapsed_ms,
                last_modified=resp.headers.get("Last-Modified", ""),
                error=f"body exceeded {self.max_body_bytes} bytes",
            ), False

        encoding = resp.encoding or resp.apparent_encoding or "utf-8"
        try:
            body_text = body_bytes.decode(encoding, errors="replace")
        except (LookupError, TypeError):
            body_text = body_bytes.decode("utf-8", errors="replace")

        page = _parse_html(
            url=url, final_url=str(resp.url), status=200, body=body_text
        )
        page.response_time_ms = elapsed_ms
        page.last_modified = resp.headers.get("Last-Modified", "")
        # Stash raw HTML for the caller to persist (we don't keep it
        # on the dataclass long-term — _cache_write strips it).
        try:
            page._raw_html = body_text  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        return page, False

    # ── internals ────────────────────────────────────────────────────

    def _session_for(self, host: str) -> requests.Session:
        s = self._sessions.get(host)
        if s is None:
            with self._session_lock:
                # Double-check inside lock so two threads racing to
                # create the same host's session don't both succeed.
                s = self._sessions.get(host)
                if s is None:
                    s = requests.Session()
                    s.headers.update({"User-Agent": self.user_agent, "Accept": "text/html,*/*"})
                    if self.proxy_url:
                        s.proxies.update(
                            {"http": self.proxy_url, "https": self.proxy_url}
                        )
                    self._sessions[host] = s
        return s

    def _throttle(self, host: str) -> None:
        # Per-host rate limit. Multiple threads may hit the same host
        # concurrently if a caller hand-built a non-grouped batch — the
        # lock serialises them and enforces the throttle correctly.
        with self._throttle_lock:
            now = time.monotonic()
            last = self._last_fetch.get(host, 0.0)
            delta = now - last
            wait = self.rate_limit_sec - delta if delta < self.rate_limit_sec else 0.0
            self._last_fetch[host] = now + wait
        if wait > 0:
            time.sleep(wait)

    def _robots_ok(self, host: str, url: str) -> bool:
        # Fast path: already-known result (rp object or None for
        # allow-all). Then slow path under lock so concurrent threads
        # for the same host don't all re-fetch robots.txt.
        if host in self._robots:
            rp = self._robots[host]
            return True if rp is None else rp.can_fetch(self.user_agent, url)
        with self._robots_lock:
            if host in self._robots:
                rp = self._robots[host]
                return True if rp is None else rp.can_fetch(self.user_agent, url)
            rp: RobotFileParser | None = RobotFileParser()
            try:
                robots_url = f"https://{host}/robots.txt"
                session = self._session_for(host)
                self._throttle(host)
                resp = session.get(
                    robots_url, timeout=self.timeout_sec, verify=self._verify
                )
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    logger.info(
                        "robots.txt for %s returned %s — allow-all fallback",
                        host,
                        resp.status_code,
                    )
                    rp = None  # treat as allow-all
            except requests.RequestException as exc:
                logger.warning("robots.txt fetch %s failed: %s", host, exc)
                rp = None
            self._robots[host] = rp
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    # ── disk cache ───────────────────────────────────────────────────

    def _cache_path(self, url: str) -> tuple[Path, Path]:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.html", self.cache_dir / f"{h}.meta.json"

    def _cache_read(self, url: str) -> CompetitorPage | None:
        html_path, meta_path = self._cache_path(url)
        if not meta_path.exists():
            return None
        try:
            mtime = meta_path.stat().st_mtime
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        # Short TTL for cached error responses so a transient 5xx
        # doesn't lock out a competitor for the full 7-day window.
        is_error_entry = bool(meta.get("error")) or int(meta.get("status_code") or 0) != 200
        ttl = self.error_cache_ttl_seconds if is_error_entry else self.cache_ttl_seconds
        if (time.time() - mtime) > ttl:
            return None
        # Re-parse the cached HTML to get fresh extraction output.
        # Cheaper than caching the parsed CompetitorPage and lets us
        # evolve the parser without invalidating the cache.
        html_body = ""
        if html_path.exists():
            try:
                with html_path.open("r", encoding="utf-8") as f:
                    html_body = f.read()
            except OSError:
                html_body = ""
        if meta.get("status_code") != 200 or not html_body:
            page = CompetitorPage(
                url=url,
                final_url=meta.get("final_url", ""),
                status_code=int(meta.get("status_code") or 0),
                fetched_at=meta.get("fetched_at", ""),
                error=meta.get("error", ""),
                response_time_ms=int(meta.get("response_time_ms") or 0),
                last_modified=meta.get("last_modified", ""),
            )
            return page
        page = _parse_html(
            url=url,
            final_url=meta.get("final_url", url),
            status=200,
            body=html_body,
        )
        page.fetched_at = meta.get("fetched_at", page.fetched_at)
        # Pull the network-side fields from the cached sidecar (the HTML
        # cache doesn't carry them).
        page.response_time_ms = int(meta.get("response_time_ms") or 0)
        page.last_modified = meta.get("last_modified", "")
        return page

    def _cache_write(
        self, url: str, page: CompetitorPage, *, html: str, is_error: bool = False
    ) -> None:
        """Persist the cache entry atomically: write to .tmp, fsync,
        rename. Prevents a crash mid-write from leaving a corrupted
        cache file on disk. ``is_error`` flags the entry as
        short-TTL so the next read respects error_cache_ttl_seconds
        rather than the 7-day default."""
        html_path, meta_path = self._cache_path(url)
        try:
            if html:
                _atomic_write_text(html_path, html)
            meta = {
                "url": url,
                "final_url": page.final_url,
                "status_code": page.status_code,
                "fetched_at": page.fetched_at or _now_iso(),
                "error": page.error,
                "response_time_ms": page.response_time_ms,
                "last_modified": page.last_modified,
                "is_error": is_error,
            }
            _atomic_write_text(meta_path, json.dumps(meta))
        except OSError as exc:
            logger.warning("competitor cache write failed for %s: %s", url, exc)


# ── helpers ──────────────────────────────────────────────────────────────


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` via a temp file + atomic rename.
    A crash mid-write leaves either the old file intact or the new one
    fully written — never a half-written file. The Windows rename
    semantics overwrite the destination if it exists (Path.replace
    handles this on both POSIX and Windows)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        try:
            os.fsync(f.fileno())
        except (OSError, AttributeError):
            # fsync not supported on this fs / fileno not real
            # (e.g., wrapped streams) — best effort only.
            pass
    tmp.replace(path)


_WHITESPACE_RE = re.compile(r"\s+")
_CTA_VERB_RE = re.compile(
    r"\b(buy\s*now|get\s*(?:quote|started)|calculate|apply\s*now|register|"
    r"download|sign\s*up|book\s*now|start\s*free|try\s*free|request\s*(?:a\s*)?call|"
    r"compare\s*plans|view\s*plans|get\s*plan|enquire\s*now|subscribe)\b",
    re.I,
)


def _parse_html(*, url: str, final_url: str, status: int, body: str) -> CompetitorPage:
    page = CompetitorPage(
        url=url,
        final_url=final_url or url,
        status_code=status,
        fetched_at=_now_iso(),
    )
    if status != 200 or not body:
        return page

    soup = BeautifulSoup(body, "html.parser")

    # ── title / meta description / canonical / robots ───────────────
    title_tag = soup.find("title")
    page.title = (title_tag.get_text(strip=True) if title_tag else "")[:512]
    page.title_length = len(page.title)

    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta and meta.get("content"):
        page.meta_description = str(meta["content"]).strip()[:1024]
        page.meta_description_length = len(page.meta_description)

    meta_robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if meta_robots and meta_robots.get("content"):
        page.meta_robots = str(meta_robots["content"]).strip()[:256]

    canonical = soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)})
    if canonical and canonical.get("href"):
        page.canonical = str(canonical["href"]).strip()[:1024]

    # ── heading hierarchy ──────────────────────────────────────────
    page.h1_texts = [
        h.get_text(" ", strip=True)[:256]
        for h in soup.find_all("h1")
        if h.get_text(strip=True)
    ]
    h2_tags = [h for h in soup.find_all("h2") if h.get_text(strip=True)]
    h3_tags = [h for h in soup.find_all("h3") if h.get_text(strip=True)]
    page.h2_count = len(h2_tags)
    page.h3_count = len(h3_tags)
    # Sample first 8 h2 texts so the LLM has concrete section names to
    # cite without the payload growing on huge pages.
    page.h2_texts = [h.get_text(" ", strip=True)[:200] for h in h2_tags[:8]]

    # ── links + CTAs ───────────────────────────────────────────────
    page_host = (_host(final_url or url) or "").lower().lstrip("www.")
    internal = external = cta = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        a_host = ""
        if href.startswith("http"):
            a_host = (_host(href) or "").lower().lstrip("www.")
        if not a_host or a_host == page_host or a_host.endswith("." + page_host):
            internal += 1
        else:
            external += 1
        text = a.get_text(" ", strip=True)
        if text and _CTA_VERB_RE.search(text):
            cta += 1
    page.internal_link_count = internal
    page.external_link_count = external
    page.cta_count = cta

    # ── images ─────────────────────────────────────────────────────
    imgs = soup.find_all("img")
    page.image_count = len(imgs)
    if imgs:
        with_alt = sum(1 for i in imgs if (i.get("alt") or "").strip())
        page.image_alt_pct = round(100.0 * with_alt / len(imgs), 1)

    # ── Structural mirror (Phase 2A.5) ─────────────────────────────
    # Captures everything the Inspector UI needs to render a competitor's
    # page structure: every heading in document order, every internal
    # link with section + kind, every image with alt + dims. Done in a
    # single descendants() walk before body_text decomposition strips
    # script/style nodes — anchors / headings / imgs are unaffected.
    structured = _extract_structured(soup, page_host, final_url or url)
    # Reasonable caps so a single 10,000-link sitemap-style page doesn't
    # blow up JSONB rows. Practical limits: a typical article has <50
    # headings, <100 links, <30 images.
    page.headings = structured["headings"][:200]
    page.internal_links = structured["internal_links"][:500]
    page.external_links = structured["external_links"][:200]
    page.images = structured["images"][:200]

    # ── JSON-LD schema parse ──────────────────────────────────────
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
    # Dedupe preserving order, cap at 20 so wildly nested graphs don't
    # explode the payload.
    seen: set[str] = set()
    page.schema_types = [
        t for t in schema_types if not (t in seen or seen.add(t))
    ][:20]
    page.has_schema_org = bool(page.schema_types)

    # ── body text (for word-count + content-fit) ──────────────────
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    page.word_count = len(text.split()) if text else 0
    # Keep the body text for content-keyword-fit scoring AND for the
    # AEM-vs-competitor content comparison view. Cap is env-driven via
    # COMPETITOR_BODY_TEXT_MAX_CHARS; default 0 = unlimited, so every
    # word from navbar through footer reaches the profile JSON. Set a
    # positive value to clamp if JSONB rows grow unwieldy.
    body_cap = int(settings.COMPETITOR.get("body_text_max_chars", 0) or 0)
    page.body_text = text if body_cap <= 0 else text[:body_cap]

    return page


def _collect_schema_types(node, out: list[str]) -> None:
    """Walk a parsed JSON-LD structure and collect every ``@type`` value.

    Handles single dicts, ``@graph`` arrays, nested ``mainEntity`` /
    ``itemListElement`` / ``hasPart`` patterns, and string-or-list
    ``@type`` values. Skips silently on malformed nodes.
    """
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str) and t.strip():
            out.append(t.strip()[:64])
        elif isinstance(t, list):
            for v in t:
                if isinstance(v, str) and v.strip():
                    out.append(v.strip()[:64])
        # Recurse into common container keys + everything else.
        for v in node.values():
            if isinstance(v, (dict, list)):
                _collect_schema_types(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_schema_types(v, out)


def _host(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _now_iso() -> str:
    from datetime import datetime, timezone as tz

    return datetime.now(tz.utc).isoformat()


def _resolve_competitor_ssl_verify(raw: str) -> bool | str:
    """Same shape as ``_resolve_semrush_ssl_verify`` in
    :mod:`apps.seo_ai.adapters.semrush`.
    """
    import os.path

    value = (raw or "").strip()
    if not value or value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    if os.path.exists(value):
        return value
    logger.warning(
        "COMPETITOR_SSL_VERIFY=%r does not exist on disk — falling back to "
        "default (certifi) verification.",
        value,
    )
    return True
