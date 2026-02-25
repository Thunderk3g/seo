"""JS Rendering Layer using Playwright.

Implements Section 9 (JavaScript Rendering Layer) of the
Web Crawler Engine spec:
- Full JS rendering for SPAs (React, Next.js, Vue)
- DOM capture of dynamically injected links and content
- Lazy loading: scroll to trigger lazy-loaded content
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from apps.common.logging import parse_logger
from apps.common.constants import CRAWLER_USER_AGENT


@dataclass
class RenderResult:
    """Result of a JavaScript rendering operation."""
    url: str
    rendered_html: str = ""
    final_url: str = ""
    status_code: int = 0
    error: Optional[str] = None
    render_time_ms: float = 0.0

    @property
    def is_success(self) -> bool:
        return bool(self.rendered_html) and not self.error


class JSRenderer:
    """Playwright-based JavaScript renderer for dynamic websites.

    Handles SPAs and JS-heavy sites by executing JavaScript
    and capturing the fully rendered DOM, including:
    - Dynamically injected links
    - Lazy-loaded content (via scrolling)
    - Client-side rendered markup
    """

    def __init__(
        self,
        user_agent: str = CRAWLER_USER_AGENT,
        timeout_ms: int = 30000,
        enable_scroll: bool = True,
    ):
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self.enable_scroll = enable_scroll
        self._browser = None
        self._playwright = None

    async def start(self):
        """Initialize Playwright browser instance."""
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            parse_logger.info("Playwright browser started for JS rendering")
        except ImportError:
            parse_logger.warning(
                "Playwright not installed. JS rendering disabled. "
                "Install with: pip install playwright && playwright install chromium"
            )
        except Exception as exc:
            parse_logger.error("Failed to start Playwright: %s", exc)

    async def stop(self):
        """Close Playwright browser and cleanup."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None

    async def render(self, url: str) -> RenderResult:
        """Render a URL with full JavaScript execution.

        Process:
        1. Navigate to URL
        2. Wait for network idle
        3. Optionally scroll to trigger lazy loading
        4. Capture rendered DOM
        """
        import time

        result = RenderResult(url=url)

        if not self._browser:
            result.error = "Browser not initialized. Call start() first."
            return result

        page = None
        try:
            context = await self._browser.new_context(
                user_agent=self.user_agent,
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()

            start_time = time.monotonic()

            # Navigate and wait for network idle
            response = await page.goto(
                url,
                wait_until="networkidle",
                timeout=self.timeout_ms,
            )

            if response:
                result.status_code = response.status
                result.final_url = response.url

            # ── Lazy Loading: Scroll to trigger content ────────
            if self.enable_scroll:
                await self._scroll_page(page)

            # ── Wait a bit more for any async content ──────────
            await page.wait_for_timeout(2000)

            # ── Capture rendered DOM ───────────────────────────
            result.rendered_html = await page.content()
            result.render_time_ms = (time.monotonic() - start_time) * 1000

            parse_logger.info(
                "Rendered %s in %.0fms (status: %d)",
                url, result.render_time_ms, result.status_code,
            )

        except Exception as exc:
            result.error = str(exc)
            parse_logger.error("JS rendering failed for %s: %s", url, exc)

        finally:
            if page:
                await page.close()

        return result

    @staticmethod
    async def _scroll_page(page):
        """Scroll the page to trigger lazy-loaded content."""
        try:
            # Get page height
            page_height = await page.evaluate("document.body.scrollHeight")
            viewport_height = await page.evaluate("window.innerHeight")

            # Scroll in increments
            scroll_position = 0
            while scroll_position < page_height:
                scroll_position += viewport_height
                await page.evaluate(f"window.scrollTo(0, {scroll_position})")
                await page.wait_for_timeout(500)

                # Re-check height (lazy loading may add content)
                new_height = await page.evaluate("document.body.scrollHeight")
                if new_height > page_height:
                    page_height = new_height

            # Scroll back to top
            await page.evaluate("window.scrollTo(0, 0)")

        except Exception as exc:
            parse_logger.debug("Scroll error (non-fatal): %s", exc)

    async def render_batch(
        self,
        urls: list[str],
        concurrency: int = 3,
    ) -> list[RenderResult]:
        """Render multiple URLs with concurrency control."""
        semaphore = asyncio.Semaphore(concurrency)

        async def _render_with_semaphore(url: str) -> RenderResult:
            async with semaphore:
                return await self.render(url)

        tasks = [_render_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return list(results)
