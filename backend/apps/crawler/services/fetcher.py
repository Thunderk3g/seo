"""HTTP Fetcher Module – Page Downloader.

Implements Section 8 (Fetcher Module) of the Web Crawler Engine spec:
- HTTP/HTTPS full support
- Redirect handling (follows chain, records hops)
- Timeout management and retry logic
- Captured data: status codes, final URL, headers, HTML, latency
- Robots.txt compliance before any page requests
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from apps.common import constants
from apps.common.exceptions import FetchError, RobotsBlockedError
from apps.common.logging import fetch_logger, log_error_event


@dataclass
class FetchResult:
    """Result of a single page fetch operation."""
    url: str
    final_url: str = ""
    status_code: int = 0
    html: str = ""
    headers: dict = field(default_factory=dict)
    redirect_chain: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    content_size: int = 0
    is_https: bool = False
    error: Optional[str] = None
    content_type: str = ""

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def is_redirect(self) -> bool:
        return 300 <= self.status_code < 400

    @property
    def is_html(self) -> bool:
        return "text/html" in self.content_type.lower()


class Fetcher:
    """Async HTTP Fetcher with resilience features.

    Features:
    - Async HTTP requests via aiohttp for non-blocking architecture
    - Automatic redirect following with chain recording
    - Configurable timeout, retries, and backoff
    - Domain-based rate limiting / request delay
    - Robots.txt compliance checking
    """

    def __init__(
        self,
        user_agent: str = constants.CRAWLER_USER_AGENT,
        timeout: int = constants.DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = constants.DEFAULT_MAX_RETRIES,
        backoff_factor: float = constants.DEFAULT_BACKOFF_FACTOR,
        request_delay: float = constants.DEFAULT_REQUEST_DELAY,
        robots_checker=None,
    ):
        self.user_agent = user_agent
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.request_delay = request_delay
        self.robots_checker = robots_checker

        # Track last request time per domain for politeness
        self._last_request_time: dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the shared aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "keep-alive",
                },
            )
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch(self, url: str) -> FetchResult:
        """Fetch a single URL with retries and backoff.

        Implements full fetch pipeline:
        1. Robots.txt check
        2. Politeness delay
        3. HTTP GET with redirect following
        4. Response signal capture
        5. Retry on transient failures
        """
        # ── Robots.txt Compliance ──────────────────────────────
        if self.robots_checker and not self.robots_checker.is_allowed(url):
            raise RobotsBlockedError(
                f"Blocked by robots.txt: {url}", url=url,
            )

        result = FetchResult(url=url, is_https=url.startswith("https"))
        last_error: Optional[str] = None
        delay = 1.0

        for attempt in range(self.max_retries + 1):
            try:
                result = await self._do_fetch(url)
                if result.is_success or result.is_redirect:
                    return result

                # Server errors (5xx) → retry
                if result.status_code >= 500:
                    last_error = f"Server error {result.status_code}"
                    if attempt < self.max_retries:
                        fetch_logger.warning(
                            "Retry %d/%d for %s (status %d)",
                            attempt + 1, self.max_retries, url, result.status_code,
                        )
                        await asyncio.sleep(delay)
                        delay *= self.backoff_factor
                        continue

                # Client errors (4xx) → no retry
                return result

            except asyncio.TimeoutError:
                last_error = "Timeout"
                log_error_event(url, "Timeout")
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
                    delay *= self.backoff_factor

            except aiohttp.ClientError as exc:
                last_error = str(exc)
                log_error_event(url, "Connection error", str(exc))
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
                    delay *= self.backoff_factor

            except Exception as exc:
                last_error = str(exc)
                log_error_event(url, "Unexpected error", str(exc))
                break

        result.error = last_error
        result.status_code = 0
        return result

    async def _do_fetch(self, url: str) -> FetchResult:
        """Execute the actual HTTP GET request."""
        # ── Politeness Delay ───────────────────────────────────
        await self._apply_delay(url)

        session = await self._get_session()
        start_time = time.monotonic()
        redirect_chain: list[str] = []

        try:
            async with session.get(
                url,
                allow_redirects=True,
                max_redirects=10,
            ) as response:
                # Capture redirect chain from history
                for hist_resp in response.history:
                    redirect_chain.append(str(hist_resp.url))

                # Read response body
                html = ""
                content_type = response.headers.get("Content-Type", "")
                if "text/html" in content_type.lower() or "application/xhtml" in content_type.lower():
                    html = await response.text(errors="replace")

                latency_ms = (time.monotonic() - start_time) * 1000

                return FetchResult(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status,
                    html=html,
                    headers=dict(response.headers),
                    redirect_chain=redirect_chain,
                    latency_ms=latency_ms,
                    content_size=len(html.encode("utf-8", errors="replace")),
                    is_https=str(response.url).startswith("https"),
                    content_type=content_type,
                )

        except Exception:
            raise

    async def _apply_delay(self, url: str):
        """Apply politeness delay per domain."""
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ""

        now = time.monotonic()
        last_time = self._last_request_time.get(domain, 0)
        elapsed = now - last_time

        if elapsed < self.request_delay:
            wait = self.request_delay - elapsed
            await asyncio.sleep(wait)

        self._last_request_time[domain] = time.monotonic()

    async def fetch_batch(
        self,
        urls: list[str],
        concurrency: int = constants.DEFAULT_CONCURRENCY,
    ) -> list[FetchResult]:
        """Fetch multiple URLs concurrently with throttling.

        Uses a semaphore to limit concurrent requests per the
        crawl config concurrency setting.
        """
        semaphore = asyncio.Semaphore(concurrency)
        results: list[FetchResult] = []

        async def _fetch_with_semaphore(url: str) -> FetchResult:
            async with semaphore:
                try:
                    return await self.fetch(url)
                except RobotsBlockedError:
                    return FetchResult(url=url, error="Blocked by robots.txt")
                except Exception as exc:
                    return FetchResult(url=url, error=str(exc))

        tasks = [_fetch_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def fetch_robots_txt(self, domain_url: str) -> Optional[str]:
        """Fetch the robots.txt file for a domain.

        Called before any page requests as per Section 6
        of the Web Crawler Engine spec.
        """
        from urllib.parse import urljoin
        robots_url = urljoin(domain_url, "/robots.txt")

        try:
            result = await self.fetch(robots_url)
            if result.status_code == 200:
                return result.html
        except Exception as exc:
            fetch_logger.warning("Failed to fetch robots.txt: %s", exc)

        return None

    async def fetch_sitemap(self, sitemap_url: str) -> Optional[str]:
        """Fetch a sitemap XML file."""
        try:
            session = await self._get_session()
            async with session.get(sitemap_url, allow_redirects=True) as response:
                if response.status == 200:
                    return await response.text(errors="replace")
        except Exception as exc:
            fetch_logger.warning("Failed to fetch sitemap %s: %s", sitemap_url, exc)

        return None
