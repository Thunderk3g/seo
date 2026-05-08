"""Core Crawler Engine Service – Main Orchestrator.

This is the central engine that coordinates the complete crawl pipeline:
    Discover -> Crawl -> Render -> Parse -> Extract Signals -> Queue Next URLs

Implements the full High-Level Crawler Flow (Section 2) of the Web Crawler
Engine spec and integrates all Crawling Strategies:
    - BFS Traversal with Priority Frontier
    - Scheduled / Incremental / On-Demand crawl modalities
    - Robots.txt compliance
    - Sitemap reconciliation
    - Depth/budget management
    - Structured logging and metrics
"""

import asyncio
import time
from typing import Optional
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, parse_qsl, urlencode

from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.common import constants
from apps.common.exceptions import (
    CrawlBudgetExhaustedError,
    MaxURLsExceededError,
    RobotsBlockedError,
)
from apps.common.logging import (
    crawl_logger,
    log_crawl_event,
    log_skip_event,
    log_blocked_event,
    log_error_event,
    log_session_event,
)
from apps.crawler.services.fetcher import Fetcher, FetchResult
from apps.crawler.services.frontier_manager import FrontierManager
from apps.crawler.services.normalization import URLNormalizer
from apps.crawler.services.parser import HTMLParser
from apps.crawler.services.renderer import JSRenderer
from apps.crawler.services.robots_parser import RobotsParser
from apps.crawler.services.sitemap_crawler import SitemapCrawler
from apps.crawler.selectors.link_extractor import LinkExtractor
from apps.crawler.selectors.metadata_extractor import MetadataExtractor
from apps.crawler.selectors.schema_extractor import SchemaExtractor


class CrawlResult:
    """Aggregated result of a complete crawl session."""

    def __init__(self):
        self.pages: list[dict] = []
        self.links: list[dict] = []
        self.sitemap_entries: list[dict] = []
        self.structured_data: list[dict] = []
        self.classifications: list[dict] = []
        self.errors: list[dict] = []
        self.metrics: dict = {
            "total_urls_queued": 0,
            "total_urls_rendered": 0,
            "total_index_eligible": 0,
            "total_excluded": 0,
            "exclusion_breakdown": {},
        }

    @property
    def total_pages(self) -> int:
        return len(self.pages)

    @property
    def total_links(self) -> int:
        return len(self.links)


class CrawlerEngine:
    """Production-grade BFS web crawler engine.

    Orchestrates the complete cycle:
    1. Seed inputs (domain, sitemaps, manual)
    2. Robots.txt fetch and compliance
    3. Sitemap crawling for exhaustive discovery
    4. BFS traversal with priority frontier
    5. Page fetching (static + JS rendering)
    6. HTML parsing and signal extraction
    7. Link extraction and frontier feeding
    8. Metrics tracking and structured logging

    Usage:
        engine = CrawlerEngine(
            domain="https://example.com",
            max_depth=7,
            max_urls=50000,
        )
        result = await engine.run()
    """

    def __init__(
        self,
        domain: str,
        max_depth: int = constants.DEFAULT_MAX_DEPTH,
        max_urls: int = constants.DEFAULT_MAX_URLS_PER_SESSION,
        concurrency: int = constants.DEFAULT_CONCURRENCY,
        request_delay: float = constants.DEFAULT_REQUEST_DELAY,
        request_timeout: int = constants.DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = constants.DEFAULT_MAX_RETRIES,
        enable_js_rendering: bool = False,
        respect_robots: bool = True,
        include_subdomains: bool = False,
        user_agent: str = constants.CRAWLER_USER_AGENT,
        target_path_prefix: str = "",
        session_id: str = "",
        flush_interval_s: float = 1.0,
        excluded_paths: Optional[list[str]] = None,
        excluded_params: Optional[list[str]] = None,
    ):
        self.domain = domain
        self.max_depth = max_depth
        self.max_urls = max_urls
        self.concurrency = concurrency
        self.request_delay = request_delay
        self.enable_js_rendering = enable_js_rendering
        self.respect_robots = respect_robots
        self.include_subdomains = include_subdomains
        self.user_agent = user_agent
        self.target_path_prefix = target_path_prefix
        self.session_id = session_id
        self.flush_interval_s = flush_interval_s

        # ── User-configured URL filters (CrawlConfig.excluded_*) ──
        # Stored on self so producers can call _is_excluded_path /
        # _strip_excluded_params at link-extraction time. Both default
        # to empty lists; whitespace/empty entries are filtered out and
        # path entries are normalized to start with "/" so user-friendly
        # values like "admin" behave the same as "/admin".
        self.excluded_paths: list[str] = self._normalize_excluded_paths(
            excluded_paths or []
        )
        self.excluded_params: list[str] = [
            p for p in (excluded_params or []) if isinstance(p, str) and p.strip()
        ]

        # ── Live activity feed plumbing (Phase 2.5 #19) ────────
        # Producers append dicts here; the flusher coroutine drains
        # the queue every `flush_interval_s` seconds and bulk-inserts
        # CrawlEvent rows so the dashboard's polling feed sees progress
        # while the crawl is still running. Best-effort — exceptions in
        # the flusher MUST NOT break the crawl.
        self._event_queue: list[dict] = []
        self._stopping: bool = False

        # ── Live Page row persistence cursor ───────────────────
        # ``self.result.pages`` is a list[dict] that producers in
        # ``_process_url`` append to. The same flusher coroutine that
        # drains ``_event_queue`` ALSO slices any pages added since the
        # last tick and bulk-creates them as ``Page`` rows so the
        # frontend's Pages/URLs page populates live during a crawl
        # instead of staying empty until end-of-crawl.
        #
        # Strategy: ignore_conflicts. ``Page`` has a unique constraint
        # on (crawl_session, url) — see ``crawl_sessions.models.Page``
        # ``unique_session_url`` (UniqueConstraint at models.py:211).
        # ``persist_crawl_results`` already passes ``ignore_conflicts=True``
        # to its bulk_create, so any rows we insert live here will be
        # silently skipped at end-of-crawl rather than raising
        # IntegrityError. We still track a cursor so we don't re-attempt
        # the same rows on every tick (cheaper, simpler diagnostics).
        #
        # Cursor advances even on DB error — see ``_flush_pages_sync``
        # docstring for rationale.
        self._page_persist_cursor: int = 0

        # Running counter of URLs we've explicitly skipped (excluded path
        # / excluded canonical). Mirrors the KIND_SKIP events we push into
        # _event_queue, but survives the queue drain so live aggregate
        # flushes always see the cumulative total. Robots-blocked URLs
        # are tracked under the frontier's failed bucket, NOT here.
        self._skipped_count: int = 0

        # ── Initialize subsystems ──────────────────────────────
        self.normalizer = URLNormalizer(domain)
        self.frontier = FrontierManager(
            max_depth=max_depth,
            max_urls=max_urls,
        )
        self.fetcher = Fetcher(
            user_agent=user_agent,
            timeout=request_timeout,
            max_retries=max_retries,
            request_delay=request_delay,
        )
        self.parser = HTMLParser(base_url=domain)
        self.renderer: Optional[JSRenderer] = None
        self.robots = RobotsParser(user_agent=user_agent)
        self.sitemap_crawler = SitemapCrawler(fetcher=self.fetcher)
        self.link_extractor = LinkExtractor(
            normalizer=self.normalizer,
            include_subdomains=include_subdomains,
        )
        self.metadata_extractor = MetadataExtractor()
        self.schema_extractor = SchemaExtractor()

        # ── Crawl result accumulator ───────────────────────────
        self.result = CrawlResult()

        # ── Timing ─────────────────────────────────────────────
        self._start_time: float = 0.0
        self._response_times: list[float] = []

    async def run(self) -> CrawlResult:
        """Execute the complete crawl pipeline.

        1. Fetch robots.txt
        2. Seed URLs (domain + sitemaps)
        3. BFS crawl loop
        4. Compile metrics
        5. Cleanup
        """
        self._start_time = time.monotonic()
        self._stopping = False
        log_session_event(
            self.session_id, "STARTED",
            f"Domain: {self.domain} | MaxDepth: {self.max_depth} | MaxURLs: {self.max_urls}",
        )

        # ── Launch live activity-feed flusher ──────────────────
        # Only start if we have a session_id to attach events to;
        # otherwise the flusher would no-op every tick.
        flusher_task: Optional[asyncio.Task] = None
        if self.session_id:
            flusher_task = asyncio.create_task(self._flush_events_periodically())

        try:
            # ── Phase 1: Robots.txt ────────────────────────────
            if self.respect_robots:
                await self._fetch_robots()

            # ── Phase 2: JS Renderer (if enabled) ──────────────
            if self.enable_js_rendering:
                self.renderer = JSRenderer(user_agent=self.user_agent)
                await self.renderer.start()

            # ── Phase 3: Seed URLs ─────────────────────────────
            await self._seed_frontier()

            # ── Phase 4: BFS Crawl Loop ────────────────────────
            await self._crawl_loop()

            # ── Phase 5: Compile Metrics ───────────────────────
            self._compile_metrics()

            log_session_event(
                self.session_id, "COMPLETED",
                f"Pages: {self.result.total_pages} | "
                f"Links: {self.result.total_links} | "
                f"Duration: {time.monotonic() - self._start_time:.1f}s",
            )

        except Exception as exc:
            crawl_logger.error("Crawl engine error: %s", exc)
            self.result.errors.append({
                "type": "engine_error",
                "message": str(exc),
            })
            log_session_event(self.session_id, "FAILED", str(exc))

        finally:
            # ── Stop the activity-feed flusher cleanly ─────────
            # Order matters: signal stopping → let the flusher loop
            # observe the flag and exit on its next tick → drain any
            # tail events the loop missed because they landed after
            # its last queue swap. Cancel only if the task hangs.
            self._stopping = True
            if flusher_task is not None:
                try:
                    await asyncio.wait_for(
                        flusher_task,
                        timeout=max(self.flush_interval_s * 4, 2.0),
                    )
                except asyncio.TimeoutError:
                    flusher_task.cancel()
                    try:
                        await flusher_task
                    except (asyncio.CancelledError, Exception):
                        pass
                except Exception as exc:
                    crawl_logger.error("Flusher task error: %s", exc)

            # Final drain — pick up anything pushed after the last
            # flusher tick. Best-effort: errors are logged, never raised.
            await self._final_flush()

            await self._cleanup()

        return self.result

    # ────────────────────────────────────────────────────────────
    # Phase 1: Robots.txt
    # ────────────────────────────────────────────────────────────

    async def _fetch_robots(self):
        """Fetch and parse robots.txt before any page requests."""
        crawl_logger.info("Fetching robots.txt for %s", self.domain)
        robots_content = await self.fetcher.fetch_robots_txt(self.domain)
        if robots_content:
            self.robots.parse(robots_content)

            # Use robots.txt declared sitemaps as seed sources
            for sitemap_url in self.robots.sitemap_urls:
                crawl_logger.info("Robots.txt sitemap: %s", sitemap_url)

            # Apply crawl-delay if specified
            if self.robots.crawl_delay and self.robots.crawl_delay > self.request_delay:
                crawl_logger.info(
                    "Applying robots.txt crawl-delay: %.1fs",
                    self.robots.crawl_delay,
                )
                self.fetcher.request_delay = self.robots.crawl_delay

    # ────────────────────────────────────────────────────────────
    # Phase 3: Seeding
    # ────────────────────────────────────────────────────────────

    async def _seed_frontier(self):
        """Seed the frontier with initial URLs from multiple sources.

        Seeds from (Section 3 of spec):
        1. Primary domain homepage
        2. Sitemaps (from robots.txt + common paths)
        3. Manual seeds
        """
        # ── Primary homepage ───────────────────────────────────
        # Param-strip applies to all URLs including the seed. Path-skip
        # is *advisory* on the seed itself: if the user has banned their
        # own homepage, log a warning but still proceed — the user's
        # explicit seed wins over their own deny-list.
        homepage = self.domain.rstrip("/") + "/"
        homepage = self._strip_excluded_params(homepage)
        seed_excluded = self._is_excluded_path(homepage)
        if seed_excluded:
            crawl_logger.warning(
                "Seed URL %s matches excluded_paths prefix '%s'; "
                "proceeding anyway (seed overrides exclusion).",
                homepage, seed_excluded,
            )
        self.frontier.add(
            url=homepage,
            depth=0,
            source=constants.SOURCE_SEED,
            priority=constants.PRIORITY_HOME_NAVIGATION,
        )

        # ── Sitemap discovery ──────────────────────────────────
        sitemap_urls = list(self.robots.sitemap_urls)

        # Try common sitemap paths if none from robots.txt
        if not sitemap_urls:
            common_sitemaps = [
                urljoin(self.domain, "/sitemap.xml"),
                urljoin(self.domain, "/sitemap_index.xml"),
            ]
            sitemap_urls = common_sitemaps

        # Crawl sitemaps and add entries to frontier
        try:
            sitemap_result = await self.sitemap_crawler.crawl_sitemaps(sitemap_urls)
            for entry in sitemap_result.entries:
                normalized = self.normalizer.normalize(entry.url)
                if normalized and self.normalizer.is_internal(normalized, self.include_subdomains):
                    # Apply path prefix filter for sectional crawls
                    if self.target_path_prefix:
                        path = urlparse(normalized).path
                        if not path.startswith(self.target_path_prefix):
                            continue

                    # User-configured filters: strip params first (so
                    # the cleaned form is what gets dedup'd / persisted),
                    # then drop the URL entirely if the path is banned.
                    cleaned = self._strip_excluded_params(normalized)
                    matched = self._is_excluded_path(cleaned)
                    if matched:
                        self._enqueue_event(
                            "skip", cleaned,
                            f"Skipped (excluded path: {matched})",
                            {
                                "reason": "excluded_path",
                                "matched_prefix": matched,
                                "source": constants.SOURCE_SITEMAP,
                            },
                        )
                        continue

                    self.frontier.add(
                        url=cleaned,
                        depth=1,
                        source=constants.SOURCE_SITEMAP,
                        priority=constants.PRIORITY_SITEMAP,
                    )

                    # Store sitemap entry for later reconciliation
                    self.result.sitemap_entries.append({
                        "page_url": cleaned,
                        "sitemap_source": entry.sitemap_source,
                        "lastmod": entry.lastmod.isoformat() if entry.lastmod else None,
                        "changefreq": entry.changefreq,
                        "priority": entry.priority,
                    })

            if sitemap_result.errors:
                for err in sitemap_result.errors:
                    crawl_logger.warning("Sitemap issue: %s", err)

        except Exception as exc:
            crawl_logger.warning("Sitemap crawling failed: %s", exc)

        crawl_logger.info(
            "Frontier seeded: %d URLs (%d from sitemaps)",
            self.frontier.total_discovered,
            len(self.result.sitemap_entries),
        )

    # ────────────────────────────────────────────────────────────
    # Phase 4: BFS Crawl Loop
    # ────────────────────────────────────────────────────────────

    async def _crawl_loop(self):
        """Main BFS crawl loop.

        Pops URLs from the frontier in priority order, fetches each page,
        parses it, extracts links, and feeds them back into the frontier.
        Uses a semaphore for concurrency control.
        """
        semaphore = asyncio.Semaphore(self.concurrency)
        active_tasks: list[asyncio.Task] = []

        while not self.frontier.is_empty or active_tasks:
            # Fill up active tasks to concurrency limit
            while not self.frontier.is_empty and len(active_tasks) < self.concurrency:
                entry = self.frontier.pop()
                if entry is None:
                    break

                task = asyncio.create_task(
                    self._process_url(entry.url, entry.depth, entry.source, semaphore)
                )
                active_tasks.append(task)

            if not active_tasks:
                break

            # Wait for at least one task to complete
            done, pending = await asyncio.wait(
                active_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            active_tasks = list(pending)

            # Process completed tasks
            for task in done:
                try:
                    task.result()
                except Exception as exc:
                    crawl_logger.error("Task error: %s", exc)

    async def _process_url(
        self,
        url: str,
        depth: int,
        source: str,
        semaphore: asyncio.Semaphore,
    ):
        """Process a single URL through the full pipeline.

        Steps:
        1. Robots.txt check
        2. Fetch (HTTP or JS render)
        3. Parse HTML
        4. Extract metadata, links, schema
        5. Classify URL
        6. Feed new links to frontier
        """
        async with semaphore:
            # ── Robots.txt compliance ──────────────────────────
            if self.respect_robots and not self.robots.is_allowed(url):
                log_blocked_event(url)
                self.frontier.mark_failed(url)
                self._add_classification(
                    url, constants.CLASSIFICATION_BLOCKED_ROBOTS,
                    "Blocked by robots.txt",
                )
                self._enqueue_event(
                    "blocked", url,
                    "Blocked by robots.txt",
                    {"depth": depth, "source": source},
                )
                return

            # ── Fetch ──────────────────────────────────────────
            try:
                fetch_result = await self.fetcher.fetch(url)
            except RobotsBlockedError:
                log_blocked_event(url)
                self.frontier.mark_failed(url)
                self._enqueue_event(
                    "blocked", url,
                    "Blocked by robots.txt",
                    {"depth": depth, "source": source},
                )
                return
            except Exception as exc:
                log_error_event(url, "Fetch failed", str(exc))
                self.frontier.mark_failed(url)
                self.result.errors.append({
                    "url": url,
                    "type": "fetch_error",
                    "message": str(exc),
                })
                self._enqueue_event(
                    "error", url,
                    f"Fetch failed: {exc}",
                    {"depth": depth, "source": source, "type": "fetch_error"},
                )
                return

            self._response_times.append(fetch_result.latency_ms)

            # ── Handle non-success ─────────────────────────────
            if fetch_result.error:
                self.frontier.mark_failed(url)
                self.result.errors.append({
                    "url": url,
                    "type": "fetch_error",
                    "message": fetch_result.error,
                })
                self._enqueue_event(
                    "error", url,
                    f"Fetch error: {fetch_result.error}",
                    {
                        "depth": depth,
                        "source": source,
                        "status_code": fetch_result.status_code,
                        "type": "fetch_error",
                    },
                )
                return

            self.frontier.mark_crawled(url)

            # ── JS Rendering (if enabled and page is HTML) ─────
            html = fetch_result.html
            if self.enable_js_rendering and self.renderer and fetch_result.is_html:
                render_result = await self.renderer.render(url)
                if render_result.is_success:
                    html = render_result.rendered_html

            # ── Parse HTML ─────────────────────────────────────
            parse_result = self.parser.parse(html, page_url=url)

            # ── Extract Metadata ───────────────────────────────
            metadata = self.metadata_extractor.extract(parse_result)

            # ── Extract Links ──────────────────────────────────
            extracted_links = self.link_extractor.extract(
                parse_result.raw_links, source_url=url,
            )

            # ── Extract Structured Data ────────────────────────
            schema_items = self.schema_extractor.extract(parse_result.json_ld)

            # ── Classify URL ───────────────────────────────────
            classification = self._classify_url(
                url=url,
                fetch_result=fetch_result,
                metadata=metadata,
                parse_result=parse_result,
            )
            lifecycle_state = classification.get("lifecycle_state", constants.LIFECYCLE_STATE_DISCOVERED)
            self._add_classification(
                url, 
                classification["type"], 
                classification["reason"],
                lifecycle_state,
            )

            # ── Build Page Record ──────────────────────────────
            page_record = self._build_page_record(
                url=url,
                fetch_result=fetch_result,
                metadata=metadata,
                depth=depth,
                source=source,
                links_count=len(extracted_links),
                lifecycle_state=classification.get("lifecycle_state", constants.LIFECYCLE_STATE_DISCOVERED),
            )
            self.result.pages.append(page_record)

            # ── Build Link Records ─────────────────────────────
            for link in extracted_links:
                self.result.links.append({
                    "source_url": link.source_url,
                    "target_url": link.target_url,
                    "link_type": link.link_type,
                    "anchor_text": link.anchor_text,
                    "rel_attributes": link.rel_attributes,
                    "is_navigation": link.is_navigation,
                })

            # ── Build Structured Data Records ──────────────────
            for schema in schema_items:
                self.result.structured_data.append({
                    "page_url": url,
                    "schema_type": schema.schema_type,
                    "raw_json": schema.raw_json,
                    "is_valid": schema.is_valid,
                    "error_message": schema.error_message,
                })

            # Classification was done and stored above.

            # ── Feed new internal links to frontier ────────────
            crawlable = self.link_extractor.filter_crawlable(extracted_links)
            new_depth = depth + 1
            for link in crawlable:
                # Apply path prefix filter for sectional crawls
                if self.target_path_prefix:
                    path = urlparse(link.target_url).path
                    if not path.startswith(self.target_path_prefix):
                        continue

                # User-configured URL hygiene: strip excluded params
                # FIRST so dedup hashes work on the cleaned form, then
                # short-circuit BEFORE frontier.add so we never emit
                # both KIND_DISCOVERY and KIND_SKIP for the same URL.
                target = self._strip_excluded_params(link.target_url)
                matched = self._is_excluded_path(target)
                if matched:
                    self._enqueue_event(
                        "skip", target,
                        f"Skipped (excluded path: {matched})",
                        {
                            "reason": "excluded_path",
                            "matched_prefix": matched,
                            "depth": new_depth,
                            "source": constants.SOURCE_LINK,
                            "parent_url": url,
                        },
                    )
                    continue

                # frontier.add() returns True only when the URL is genuinely
                # new (not a duplicate / not over depth or URL caps). Push a
                # KIND_DISCOVERY event only on first discovery so the feed
                # doesn't get spammed with re-encounters of the same URL.
                added = self.frontier.add(
                    url=target,
                    depth=new_depth,
                    source=constants.SOURCE_LINK,
                    parent_url=url,
                )
                if added:
                    self._enqueue_event(
                        "discovery", target,
                        f"Discovered from {url}",
                        {
                            "depth": new_depth,
                            "source": constants.SOURCE_LINK,
                            "parent_url": url,
                        },
                    )

            # Also add canonical URL if different
            if metadata.canonical_url and metadata.canonical_url != url:
                canon_normalized = self.normalizer.normalize(metadata.canonical_url)
                if canon_normalized and self.normalizer.is_internal(canon_normalized):
                    canon_normalized = self._strip_excluded_params(canon_normalized)
                    canon_matched = self._is_excluded_path(canon_normalized)
                    if canon_matched:
                        self._enqueue_event(
                            "skip", canon_normalized,
                            f"Skipped canonical (excluded path: {canon_matched})",
                            {
                                "reason": "excluded_path",
                                "matched_prefix": canon_matched,
                                "depth": new_depth,
                                "source": constants.SOURCE_CANONICAL,
                                "parent_url": url,
                            },
                        )
                    else:
                        added_canon = self.frontier.add(
                            url=canon_normalized,
                            depth=new_depth,
                            source=constants.SOURCE_CANONICAL,
                        )
                        if added_canon:
                            self._enqueue_event(
                                "discovery", canon_normalized,
                                f"Discovered via canonical from {url}",
                                {
                                    "depth": new_depth,
                                    "source": constants.SOURCE_CANONICAL,
                                    "parent_url": url,
                                },
                            )

            # ── Log the crawl event ────────────────────────────
            log_crawl_event(
                url=url,
                depth=depth,
                status_code=fetch_result.status_code,
                links_found=len(extracted_links),
                latency_ms=fetch_result.latency_ms,
            )

            # ── Push live activity-feed events ─────────────────
            # Emit a KIND_REDIRECT event when the fetch followed any
            # hops; otherwise emit KIND_CRAWL. Both render with their
            # own pill in the dashboard's activity widget.
            if fetch_result.redirect_chain:
                self._enqueue_event(
                    "redirect", url,
                    f"Redirected via {len(fetch_result.redirect_chain)} hop(s) "
                    f"to {fetch_result.final_url}",
                    {
                        "depth": depth,
                        "status_code": fetch_result.status_code,
                        "final_url": fetch_result.final_url,
                        "hops": len(fetch_result.redirect_chain),
                        "latency_ms": fetch_result.latency_ms,
                    },
                )
            else:
                self._enqueue_event(
                    "crawl", url,
                    f"Crawled {url} [{fetch_result.status_code}]",
                    {
                        "depth": depth,
                        "status_code": fetch_result.status_code,
                        "links_found": len(extracted_links),
                        "latency_ms": fetch_result.latency_ms,
                    },
                )

    # ────────────────────────────────────────────────────────────
    # Record Building
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_directory_segment(url: str) -> str:
        """Extract the top-level directory segment from a URL."""
        try:
            from urllib.parse import urlparse
            path = urlparse(url).path
            if not path or path == "/":
                return "/"
            parts = [p for p in path.split("/") if p]
            return f"/{parts[0]}/" if parts else "/"
        except Exception:
            return "/"

    @staticmethod
    def _build_page_record(
        url: str,
        fetch_result: FetchResult,
        metadata,
        depth: int,
        source: str,
        links_count: int,
        lifecycle_state: str = "",
    ) -> dict:
        """Build a page data dict for session storage."""
        directory = CrawlerEngine._extract_directory_segment(url)
        return {
            "url": url,
            "normalized_url": url,
            "http_status_code": fetch_result.status_code,
            "final_url": fetch_result.final_url,
            "redirect_chain": fetch_result.redirect_chain,
            "title": metadata.title,
            "meta_description": metadata.meta_description,
            "h1": metadata.h1,
            "h2_list": metadata.h2_list,
            "h3_list": metadata.h3_list,
            "canonical_url": metadata.canonical_url,
            "canonical_resolved": metadata.canonical_url or url, # Basic resolution for now
            "canonical_match": metadata.canonical_url in ("", url),
            "robots_meta": metadata.robots_meta,
            "crawl_depth": depth,
            "load_time_ms": fetch_result.latency_ms,
            "content_size_bytes": metadata.content_size_bytes,
            "word_count": metadata.word_count,
            "is_https": fetch_result.is_https,
            "page_hash": metadata.page_hash,
            "source": source,
            "discovery_source_first": source,
            "discovery_sources_all": [source],
            "directory_segment": directory,
            "page_template": "default", # Will group later
            "lifecycle_state": lifecycle_state,
            "total_images": metadata.total_images,
            "images_without_alt": metadata.images_without_alt,
        }

    # ────────────────────────────────────────────────────────────
    # URL Classification (GSC-style)
    # ────────────────────────────────────────────────────────────

    def _classify_url(
        self,
        url: str,
        fetch_result: FetchResult,
        metadata,
        parse_result,
    ) -> dict:
        """Classify a URL into a GSC-style coverage bucket."""
        status = fetch_result.status_code

        # Server errors
        if status >= 500:
            return {
                "type": constants.CLASSIFICATION_SERVER_ERROR,
                "lifecycle_state": constants.LIFECYCLE_STATE_SERVER_ERROR,
                "reason": f"Server returned {status}",
            }

        # Not found
        if status == 404:
            return {
                "type": constants.CLASSIFICATION_NOT_FOUND,
                "lifecycle_state": constants.LIFECYCLE_STATE_NOT_FOUND,
                "reason": "Page returned 404 Not Found",
            }

        # Soft 404 detection
        if self.metadata_extractor.detect_soft_404(parse_result, status):
            return {
                "type": constants.CLASSIFICATION_SOFT_404,
                "lifecycle_state": constants.LIFECYCLE_STATE_SOFT_404,
                "reason": "Page appears to be a soft 404 (200 status but error content)",
            }

        # Redirected
        if fetch_result.redirect_chain:
            return {
                "type": constants.CLASSIFICATION_REDIRECTED,
                "lifecycle_state": constants.LIFECYCLE_STATE_REDIRECT,
                "reason": f"Redirected via {len(fetch_result.redirect_chain)} hop(s) to {fetch_result.final_url}",
            }

        # Noindex
        if metadata.is_noindex:
            return {
                "type": constants.CLASSIFICATION_NOINDEX,
                "lifecycle_state": constants.LIFECYCLE_STATE_NOINDEX,
                "reason": "Page has noindex meta directive",
            }

        # Duplicate without canonical
        if metadata.has_canonical and metadata.canonical_url != url:
            return {
                "type": constants.CLASSIFICATION_ALTERNATE_CANONICAL,
                "lifecycle_state": constants.LIFECYCLE_STATE_ALTERNATE_CANONICAL,
                "reason": f"Canonical points to {metadata.canonical_url}",
            }

        # Success: Indexed candidate
        if 200 <= status < 300:
            return {
                "type": constants.CLASSIFICATION_INDEXED,
                "lifecycle_state": constants.LIFECYCLE_STATE_INDEX_ELIGIBLE,
                "reason": "Valid indexable page",
            }

        # Fallback
        return {
            "type": constants.CLASSIFICATION_CRAWLED_NOT_INDEXED,
            "lifecycle_state": constants.LIFECYCLE_STATE_CRAWLED,
            "reason": f"Status {status} – classification uncertain",
        }

    def _add_classification(self, url: str, cls_type: str, reason: str, lifecycle_state: str = ""):
        """Store a URL classification record."""
        self.result.classifications.append({
            "url": url,
            "classification": cls_type,
            "reason": reason,
            "lifecycle_state": lifecycle_state,
        })

    # ────────────────────────────────────────────────────────────
    # Metrics
    # ────────────────────────────────────────────────────────────

    def _compile_metrics(self):
        """Compile crawl session metrics."""
        frontier_metrics = self.frontier.get_metrics()
        
        avg_response = 0.0
        if self._response_times:
            avg_response = sum(self._response_times) / len(self._response_times)

        # Depth distribution
        depth_dist: dict[int, int] = {}
        for page in self.result.pages:
            d = page.get("crawl_depth", 0)
            depth_dist[d] = depth_dist.get(d, 0) + 1

        # Error summary
        error_types: dict[str, int] = {}
        for err in self.result.errors:
            err_type = err.get("type", "unknown")
            error_types[err_type] = error_types.get(err_type, 0) + 1

        # Status code distribution
        status_dist: dict[int, int] = {}
        for page in self.result.pages:
            sc = page.get("http_status_code", 0)
            status_dist[sc] = status_dist.get(sc, 0) + 1

        # GSC Coverage metrics
        total_index_eligible = 0
        total_excluded = 0
        exclusion_breakdown: dict[str, int] = {}
        
        for cls in self.result.classifications:
            state = cls.get("lifecycle_state")
            if state == constants.LIFECYCLE_STATE_INDEX_ELIGIBLE:
                total_index_eligible += 1
            elif state != constants.LIFECYCLE_STATE_DISCOVERED:
                # Anything crawled but not eligible is excluded
                total_excluded += 1
                if state:
                    exclusion_breakdown[state] = exclusion_breakdown.get(state, 0) + 1

        self.result.metrics = {
            "total_urls_discovered": frontier_metrics["total_discovered"],
            "total_urls_crawled": frontier_metrics["total_crawled"],
            "total_urls_failed": frontier_metrics["total_failed"],
            "total_urls_queued": frontier_metrics["queue_size"],
            "total_urls_rendered": 0, # To be implemented when Playwright integrates
            "total_index_eligible": total_index_eligible,
            "total_excluded": total_excluded,
            "exclusion_breakdown": exclusion_breakdown,
            "total_pages_stored": len(self.result.pages),
            "total_links_stored": len(self.result.links),
            "total_sitemap_entries": len(self.result.sitemap_entries),
            "total_structured_data": len(self.result.structured_data),
            "avg_response_time_ms": round(avg_response, 2),
            "max_depth_reached": max(depth_dist.keys(), default=0),
            "depth_distribution": depth_dist,
            "status_code_distribution": status_dist,
            "error_summary": error_types,
            "duration_seconds": round(time.monotonic() - self._start_time, 2),
            "frontier_final_queue_size": frontier_metrics["queue_size"],
        }

    # ────────────────────────────────────────────────────────────
    # User-configured URL filters (CrawlConfig.excluded_*)
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_excluded_paths(raw: list[str]) -> list[str]:
        """Coerce config entries into canonical "/foo" form.

        Skips empty / whitespace-only entries. Prepends a leading "/"
        if the user wrote "admin" instead of "/admin". Trailing slashes
        are preserved intact — "/admin/" and "/admin" are equivalent
        for the prefix check (see ``_is_excluded_path``).
        """
        out: list[str] = []
        for entry in raw:
            if not isinstance(entry, str):
                continue
            stripped = entry.strip()
            if not stripped:
                continue
            if not stripped.startswith("/"):
                stripped = "/" + stripped
            out.append(stripped)
        return out

    def _is_excluded_path(self, url: str) -> Optional[str]:
        """Return the matching prefix if *url*'s path is excluded, else None.

        Path-prefix match: stripped path either equals the prefix or
        starts with ``prefix + "/"``. We strip a single trailing slash
        from both sides before comparing so "/admin/" excludes
        "/admin/users" the same as "/admin" does, and "/admincats"
        is NOT matched by "/admin".
        """
        if not self.excluded_paths:
            return None
        try:
            path = urlsplit(url).path or "/"
        except Exception:
            return None

        path_stripped = path.rstrip("/") or "/"
        for prefix in self.excluded_paths:
            prefix_stripped = prefix.rstrip("/") or "/"
            if path_stripped == prefix_stripped:
                return prefix
            # "/admin" excludes "/admin/x" but NOT "/admincats".
            if path_stripped.startswith(prefix_stripped + "/"):
                return prefix
        return None

    def _strip_excluded_params(self, url: str) -> str:
        """Return *url* with any query keys matching ``self.excluded_params``
        removed.

        Matching rule: case-sensitive **prefix** match on the key name,
        per the spec. So ``excluded_params=["utm"]`` strips ``utm_source``
        AND ``utm_campaign`` — useful for the canonical UTM use-case.
        Values are never matched. If no params are stripped, the original
        URL is returned unchanged so dedup hashes stay stable.
        """
        if not self.excluded_params or "?" not in url:
            return url
        try:
            parts = urlsplit(url)
            if not parts.query:
                return url
            # keep_blank_values so "?foo=" round-trips correctly.
            pairs = parse_qsl(parts.query, keep_blank_values=True)
            filtered = [
                (k, v) for (k, v) in pairs
                if not any(k.startswith(prefix) for prefix in self.excluded_params)
            ]
            if len(filtered) == len(pairs):
                return url
            new_query = urlencode(filtered, doseq=True)
            return urlunsplit((
                parts.scheme, parts.netloc, parts.path, new_query, parts.fragment,
            ))
        except Exception:  # pragma: no cover — defensive
            return url

    # ────────────────────────────────────────────────────────────
    # Live Activity Feed (Phase 2.5 follow-up #19)
    # ────────────────────────────────────────────────────────────

    def _enqueue_event(
        self,
        kind: str,
        url: str,
        message: str = "",
        metadata: Optional[dict] = None,
    ) -> None:
        """Push a CrawlEvent payload onto the in-memory queue.

        Wrapped in try/except so a malformed event payload can never break
        the crawl pipeline. List append is atomic under CPython's GIL, so
        no lock is required even though this is called from many concurrent
        coroutines and the flusher swaps the list out.
        """
        if not self.session_id:
            return
        try:
            self._event_queue.append({
                "kind": kind,
                "url": url or "",
                "message": message or "",
                "metadata": metadata or {},
            })
            # Maintain a cumulative skip counter for the live aggregate
            # flush. The event queue itself gets drained by the flusher,
            # so it can't be the source of truth — we need a running tally
            # that survives the swap.
            if kind == "skip":
                self._skipped_count += 1
        except Exception as exc:  # pragma: no cover — defensive
            crawl_logger.error("Failed to enqueue activity event: %s", exc)

    async def _flush_events_periodically(self) -> None:
        """Periodically drain ``self._event_queue`` into CrawlEvent rows.

        Runs as a sibling task to the BFS crawl loop, started in ``run()``.
        On every tick:
          1. Sleep ``flush_interval_s`` seconds.
          2. Atomically swap the queue (safe under GIL).
          3. If the batch is non-empty, hand it off to a thread-pool sync
             call that does a single ``CrawlEvent.objects.bulk_create``.
          4. Exit when ``self._stopping`` is True AND the queue is empty.
        """
        while True:
            try:
                await asyncio.sleep(self.flush_interval_s)
            except asyncio.CancelledError:
                # Honour cancellation; the finally block in run() will do
                # one last drain via _final_flush().
                return

            # Atomic swap — list reassignment is GIL-safe.
            batch, self._event_queue = self._event_queue, []

            if batch:
                try:
                    await sync_to_async(
                        self._flush_batch_sync, thread_sensitive=False,
                    )(batch)
                except Exception as exc:
                    # Best-effort: log and discard the batch. Activity feed
                    # must never break a crawl. We do NOT re-queue — that
                    # could grow unbounded if the DB stays broken.
                    crawl_logger.error(
                        "Failed to flush %d activity events: %s", len(batch), exc,
                    )

            # Live KPI tick: write current in-memory counts back to the
            # CrawlSession aggregate columns so the dashboard's KPI strip /
            # health gauge update during the run instead of only at end-of-
            # crawl. Wrapped in its own try so a failure here can't shadow
            # the events flush above. Skipped when there's no session row
            # to update.
            if self.session_id:
                try:
                    await sync_to_async(
                        self._flush_session_aggregates_sync,
                        thread_sensitive=False,
                    )()
                except Exception as exc:
                    crawl_logger.warning(
                        "Failed to flush session aggregates: %s", exc,
                    )

            # Live Page row persist tick: bulk-create any new dicts in
            # ``self.result.pages`` that haven't been written yet so the
            # frontend Pages/URLs page populates live instead of waiting
            # until ``persist_crawl_results`` runs at end-of-crawl. Order:
            # events → aggregates → pages. Wrapped in its own try; failures
            # are logged in ``_flush_pages_sync`` and the cursor advances
            # there as well, so a single broken batch doesn't block forward
            # progress.
            if self.session_id:
                try:
                    await sync_to_async(
                        self._flush_pages_sync,
                        thread_sensitive=False,
                    )()
                except Exception as exc:
                    crawl_logger.warning(
                        "Failed to flush live pages: %s", exc,
                    )

            # Exit condition: stopping flag set and the queue is drained.
            # Re-check the queue after the swap to avoid losing tail events
            # that were appended between the swap and this check; the next
            # iteration's swap will pick them up.
            if self._stopping and not self._event_queue:
                return

    def _flush_batch_sync(self, batch: list[dict]) -> None:
        """Sync helper: bulk-insert a batch of activity events.

        Called from a thread pool via ``sync_to_async`` because the Django
        ORM is sync-only. Uses a FK-id pass-through (``crawl_session_id``)
        so we never trigger a read query for the session row.
        """
        # Local import to avoid circular imports at module load.
        from apps.crawl_sessions.models import CrawlEvent

        rows = [
            CrawlEvent(
                crawl_session_id=self.session_id,
                kind=item.get("kind", CrawlEvent.KIND_CRAWL),
                url=item.get("url", "") or "",
                message=item.get("message", "") or "",
                metadata=item.get("metadata") or {},
            )
            for item in batch
        ]
        CrawlEvent.objects.bulk_create(rows)

    def _flush_session_aggregates_sync(self) -> None:
        """Sync helper: write current live KPI counts onto the session row.

        Mirrors the formulas in ``_compile_metrics`` so live values converge
        on the canonical end-of-crawl values byte-for-byte. Uses ``.update()``
        scoped to the explicit ``update_fields`` set we care about so we
        never accidentally overwrite columns owned by ``persist_crawl_results``
        (e.g. ``total_excluded`` / ``exclusion_breakdown``).

        Best-effort: any exception is swallowed by the caller; the next
        flusher tick will retry. ``persist_crawl_results`` overwrites the
        canonical fields anyway right after ``run()`` returns, so a momentary
        off-by-one during the live phase doesn't pollute the final record.

        Note: ``total_urls_skipped`` is NOT in ``persist_crawl_results``'s
        ``update_fields``, so the live value here is the source of truth
        for the lifetime of the session row.
        """
        from apps.crawl_sessions.models import CrawlSession

        # Discovered: same source as _compile_metrics (frontier.total_discovered).
        discovered = self.frontier.total_discovered
        # Crawled: same source as _compile_metrics (frontier.total_crawled).
        crawled = self.frontier.total_crawled
        # Failed: frontier.get_metrics()["total_failed"] == len(frontier._failed),
        # which is also what _compile_metrics uses. Captures fetch errors,
        # robots-blocked URLs, and any other mark_failed() callers.
        failed = self.frontier.get_metrics().get("total_failed", 0)
        # Skipped: cumulative counter bumped on every KIND_SKIP enqueue.
        skipped = self._skipped_count
        # Max depth observed among successfully crawled pages (matches
        # _compile_metrics' depth_distribution max).
        max_depth = max(
            (p.get("crawl_depth", 0) for p in self.result.pages),
            default=0,
        )
        # Avg response time across observed fetches; rounded to match the
        # final compiled metric (avoids needless decimal jitter on the UI).
        if self._response_times:
            avg_response = round(
                sum(self._response_times) / len(self._response_times), 2,
            )
        else:
            avg_response = 0.0

        CrawlSession.objects.filter(pk=self.session_id).update(
            total_urls_discovered=discovered,
            total_urls_crawled=crawled,
            total_urls_failed=failed,
            total_urls_skipped=skipped,
            max_depth_reached=max_depth,
            avg_response_time_ms=avg_response,
        )

    def _dict_to_page_kwargs(self, page_data: dict) -> dict:
        """Map a ``CrawlResult.pages`` dict to ``Page(**kwargs)`` form.

        Mirrors ``persist_crawl_results``'s page construction (see
        ``apps.crawl_sessions.services.session_manager`` lines 199-230)
        verbatim, including the ``lifecycle_state`` → ``url_lifecycle_state``
        rename and every ``.get(default)`` fallback. Keeps the live-flushed
        rows byte-identical to the canonical end-of-crawl rows so
        ``ignore_conflicts=True`` at end-of-crawl is a true no-op rather
        than a silent column-level discrepancy.

        FK is passed by id (``crawl_session_id=self.session_id``) to skip
        the FK row read — same pattern as ``_flush_batch_sync``.
        """
        return dict(
            crawl_session_id=self.session_id,
            url=page_data["url"],
            normalized_url=page_data.get("normalized_url", page_data["url"]),
            http_status_code=page_data.get("http_status_code"),
            final_url=page_data.get("final_url", ""),
            redirect_chain=page_data.get("redirect_chain", []),
            title=page_data.get("title", ""),
            meta_description=page_data.get("meta_description", ""),
            h1=page_data.get("h1", ""),
            h2_list=page_data.get("h2_list", []),
            h3_list=page_data.get("h3_list", []),
            canonical_url=page_data.get("canonical_url", ""),
            canonical_resolved=page_data.get("canonical_resolved", ""),
            canonical_match=page_data.get("canonical_match", True),
            robots_meta=page_data.get("robots_meta", ""),
            crawl_depth=page_data.get("crawl_depth", 0),
            load_time_ms=page_data.get("load_time_ms"),
            content_size_bytes=page_data.get("content_size_bytes", 0),
            word_count=page_data.get("word_count", 0),
            is_https=page_data.get("is_https", False),
            page_hash=page_data.get("page_hash", ""),
            source=page_data.get("source", constants.SOURCE_LINK),
            discovery_source_first=page_data.get("discovery_source_first", ""),
            discovery_sources_all=page_data.get("discovery_sources_all", []),
            directory_segment=page_data.get("directory_segment", ""),
            page_template=page_data.get("page_template", ""),
            url_lifecycle_state=page_data.get(
                "lifecycle_state", constants.LIFECYCLE_STATE_DISCOVERED,
            ),
            total_images=page_data.get("total_images", 0),
            images_without_alt=page_data.get("images_without_alt", 0),
        )

    def _flush_pages_sync(self) -> int:
        """Bulk-create ``Page`` rows added since the last flush.

        Returns the number of dicts handed to ``bulk_create`` (not
        the number actually inserted — Postgres doesn't expose that
        through ``ignore_conflicts``).

        Best-effort: any DB error is logged and swallowed; the cursor
        still advances so the same broken rows don't retry forever.
        Such rows will be picked up by ``persist_crawl_results``'s
        ``ignore_conflicts=True`` retry at end-of-crawl, or stay
        un-inserted if they're genuinely malformed (the failed batch
        is logged so it's visible in operations dashboards).

        The cursor is captured ONCE before slicing
        (``end = len(self.result.pages)``) so concurrent producer
        appends after the slice don't race the cursor forward; those
        late additions get picked up on the next tick.

        Local import of ``Page`` to avoid pulling
        ``apps.crawl_sessions`` into module load time of the crawler
        (mirrors ``_flush_batch_sync`` / ``_flush_session_aggregates_sync``).
        """
        if not self.session_id:
            return 0

        # Snapshot the cursor end ONCE so concurrent appends from
        # ``_process_url`` don't get sliced+missed in the same call.
        end = len(self.result.pages)
        start = self._page_persist_cursor
        if end <= start:
            return 0

        new_pages = self.result.pages[start:end]

        # Local import — see docstring rationale.
        from apps.crawl_sessions.models import Page

        objs = [Page(**self._dict_to_page_kwargs(pd)) for pd in new_pages]

        try:
            Page.objects.bulk_create(objs, ignore_conflicts=True)
        except Exception as exc:
            crawl_logger.error(
                "Live page flush failed for %d rows: %s", len(objs), exc,
            )
            # Fall through — cursor still advances below so we don't
            # retry the same broken batch on every subsequent tick.

        self._page_persist_cursor = end
        return len(objs)

    async def _final_flush(self) -> None:
        """Drain any tail events / pages left after the flusher exits.

        Called from ``run()``'s finally block, after the flusher task has
        exited. Best-effort — exceptions are logged, never re-raised.

        Two independent drains run unconditionally (gated only on
        ``session_id``):
          * Events drain — pick up CrawlEvent dicts appended after the
            flusher's last queue swap.
          * Page drain — pick up Page dicts appended after the flusher's
            last ``_flush_pages_sync`` call. Critical: this MUST run even
            if ``self._event_queue`` is empty, otherwise a crawl whose
            tail events all happened to flush in the last periodic tick
            would leave its tail pages unflushed until
            ``persist_crawl_results`` runs. The two drains are therefore
            sequenced rather than gated on each other.
        """
        if not self.session_id:
            return

        # ── Tail events drain ──────────────────────────────────
        if self._event_queue:
            batch, self._event_queue = self._event_queue, []
            try:
                await sync_to_async(
                    self._flush_batch_sync, thread_sensitive=False,
                )(batch)
            except Exception as exc:
                crawl_logger.error(
                    "Final flush of %d activity events failed: %s",
                    len(batch), exc,
                )

        # ── Tail pages drain ───────────────────────────────────
        # Independent of the events drain above. ``_flush_pages_sync``
        # is a no-op when the cursor is caught up.
        try:
            await sync_to_async(
                self._flush_pages_sync, thread_sensitive=False,
            )()
        except Exception as exc:
            crawl_logger.error(
                "Final flush of live pages failed: %s", exc,
            )

    # ────────────────────────────────────────────────────────────
    # Cleanup
    # ────────────────────────────────────────────────────────────

    async def _cleanup(self):
        """Close all async resources."""
        await self.fetcher.close()
        if self.renderer:
            await self.renderer.stop()

    # ────────────────────────────────────────────────────────────
    # Single URL Inspection
    # ────────────────────────────────────────────────────────────

    async def inspect_url(self, url: str) -> dict:
        """Inspect a single URL (URL Inspection mode).

        Returns a complete analysis of one URL without full-site crawling.
        Useful for validating fixes (e.g., 404 resolution).
        """
        log_session_event(self.session_id, "URL_INSPECTION", f"URL: {url}")

        try:
            # Fetch
            fetch_result = await self.fetcher.fetch(url)

            # JS Render if enabled
            html = fetch_result.html
            if self.enable_js_rendering and self.renderer:
                await self.renderer.start()
                render_result = await self.renderer.render(url)
                if render_result.is_success:
                    html = render_result.rendered_html

            # Parse
            parse_result = self.parser.parse(html, page_url=url)
            metadata = self.metadata_extractor.extract(parse_result)
            links = self.link_extractor.extract(
                parse_result.raw_links, source_url=url,
            )
            schemas = self.schema_extractor.extract(parse_result.json_ld)
            classification = self._classify_url(
                url, fetch_result, metadata, parse_result,
            )

            return {
                "url": url,
                "status_code": fetch_result.status_code,
                "final_url": fetch_result.final_url,
                "redirect_chain": fetch_result.redirect_chain,
                "latency_ms": fetch_result.latency_ms,
                "title": metadata.title,
                "meta_description": metadata.meta_description,
                "h1": metadata.h1,
                "canonical_url": metadata.canonical_url,
                "robots_meta": metadata.robots_meta,
                "word_count": metadata.word_count,
                "page_hash": metadata.page_hash,
                "links_found": len(links),
                "internal_links": sum(1 for l in links if l.link_type == "internal"),
                "external_links": sum(1 for l in links if l.link_type == "external"),
                "structured_data": [s.schema_type for s in schemas],
                "classification": classification,
                "is_https": fetch_result.is_https,
                "total_images": metadata.total_images,
                "images_without_alt": metadata.images_without_alt,
            }

        finally:
            await self._cleanup()
