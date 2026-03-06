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
from urllib.parse import urljoin, urlparse

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
        log_session_event(
            self.session_id, "STARTED",
            f"Domain: {self.domain} | MaxDepth: {self.max_depth} | MaxURLs: {self.max_urls}",
        )

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
        homepage = self.domain.rstrip("/") + "/"
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

                    self.frontier.add(
                        url=normalized,
                        depth=1,
                        source=constants.SOURCE_SITEMAP,
                        priority=constants.PRIORITY_SITEMAP,
                    )

                    # Store sitemap entry for later reconciliation
                    self.result.sitemap_entries.append({
                        "page_url": normalized,
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
                return

            # ── Fetch ──────────────────────────────────────────
            try:
                fetch_result = await self.fetcher.fetch(url)
            except RobotsBlockedError:
                log_blocked_event(url)
                self.frontier.mark_failed(url)
                return
            except Exception as exc:
                log_error_event(url, "Fetch failed", str(exc))
                self.frontier.mark_failed(url)
                self.result.errors.append({
                    "url": url,
                    "type": "fetch_error",
                    "message": str(exc),
                })
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

                self.frontier.add(
                    url=link.target_url,
                    depth=new_depth,
                    source=constants.SOURCE_LINK,
                    parent_url=url,
                )

            # Also add canonical URL if different
            if metadata.canonical_url and metadata.canonical_url != url:
                canon_normalized = self.normalizer.normalize(metadata.canonical_url)
                if canon_normalized and self.normalizer.is_internal(canon_normalized):
                    self.frontier.add(
                        url=canon_normalized,
                        depth=new_depth,
                        source=constants.SOURCE_CANONICAL,
                    )

            # ── Log the crawl event ────────────────────────────
            log_crawl_event(
                url=url,
                depth=depth,
                status_code=fetch_result.status_code,
                links_found=len(extracted_links),
                latency_ms=fetch_result.latency_ms,
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
