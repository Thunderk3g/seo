"""Crawl a single competitor domain via the Scrapy spider.

Invoked as a subprocess by ``CompetitorCrawlerScrapy.fetch_pages`` so
the Twisted reactor lifetime is bounded by the subprocess — the
parent Django/Celery process never installs a reactor of its own,
which keeps scrapy-playwright's AsyncioSelectorReactor requirement
from clashing with anything else running in the gap pipeline.

Inputs (file-based to keep the CLI clean):

    python manage.py crawl_competitor \
        --target-domain iciciprulife.com \
        --urls-file /tmp/competitor_urls_xyz.txt \
        --output-file /tmp/competitor_out_xyz.jsonl \
        [--playwright] [--body-cap 0] [--user-agent "..."]

The urls file is one URL per line. The output is JSONL (one item per
line) so the parent process can stream-read it.

The spider's pipeline still writes to Postgres (CrawlerPageResult +
CrawlSnapshot) so per-competitor Health Score is populated regardless
of how the parent process consumes the JSONL.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crawl one competitor domain via Scrapy. Subprocess of CompetitorCrawlerScrapy."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--target-domain", required=True)
        parser.add_argument("--urls-file", required=True)
        parser.add_argument("--output-file", required=True)
        parser.add_argument("--user-agent", default="")
        parser.add_argument("--body-cap", type=int, default=0)
        parser.add_argument(
            "--playwright", action="store_true",
            help="Enable Playwright JS-rendering gate.",
        )

    def handle(self, *args, **options) -> None:
        target_domain: str = options["target_domain"]
        urls_path = Path(options["urls_file"])
        out_path = Path(options["output_file"])
        user_agent: str = options.get("user_agent") or ""
        body_cap: int = int(options.get("body_cap") or 0)
        playwright_enabled: bool = bool(options.get("playwright"))

        if not urls_path.exists():
            raise SystemExit(f"urls-file not found: {urls_path}")

        urls = [
            line.strip()
            for line in urls_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if not urls:
            out_path.write_text("", encoding="utf-8")
            self.stdout.write(self.style.WARNING(
                f"no URLs to crawl for {target_domain} — wrote empty output"
            ))
            return

        # Import lazily so Django startup isn't slowed by Scrapy.
        try:
            from scrapy.crawler import CrawlerProcess
        except ImportError as exc:
            raise SystemExit(
                "Scrapy not installed. Add scrapy + scrapy-playwright to "
                f"requirements/base.txt and pip install: {exc}"
            )

        from apps.seo_ai.spiders import CompetitorSpider

        # Tee the spider's items into the output JSONL as they arrive.
        # We register a signal handler so the file gets flushed even if
        # Scrapy aborts mid-crawl (Ctrl-C, exception in pipeline, etc.).
        out_handle = out_path.open("w", encoding="utf-8")

        def _on_item_scraped(item, response, spider):
            try:
                out_handle.write(json.dumps(dict(item), ensure_ascii=False) + "\n")
                out_handle.flush()
            except Exception as exc:  # noqa: BLE001
                spider.logger.warning("output write failed: %s", exc)

        process_settings: dict = {}
        if not playwright_enabled:
            # Remove the Playwright middleware + download handlers so a
            # Scrapy install without scrapy-playwright still works.
            process_settings["DOWNLOADER_MIDDLEWARES"] = {}
            process_settings["DOWNLOAD_HANDLERS"] = {}
            # AsyncioSelectorReactor is required by scrapy-playwright;
            # without playwright we can stick with the default reactor.
            process_settings["TWISTED_REACTOR"] = (
                "twisted.internet.selectreactor.SelectReactor"
                if sys.platform == "win32"
                else "twisted.internet.epollreactor.EPollReactor"
            )

        process = CrawlerProcess(settings=process_settings)
        try:
            from scrapy import signals
            crawler = process.create_crawler(CompetitorSpider)
            crawler.signals.connect(_on_item_scraped, signal=signals.item_scraped)
            process.crawl(
                crawler,
                target_domain=target_domain,
                urls=urls,
                body_text_max_chars=body_cap,
                user_agent=user_agent or None,
                playwright_enabled=playwright_enabled,
            )
            process.start(stop_after_crawl=True)
        finally:
            try:
                out_handle.close()
            except Exception:  # noqa: BLE001
                pass

        self.stdout.write(self.style.SUCCESS(
            f"competitor crawl complete: {target_domain} -> {out_path}"
        ))
