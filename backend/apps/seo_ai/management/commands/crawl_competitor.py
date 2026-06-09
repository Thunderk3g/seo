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
import os
import sys
from pathlib import Path

# Scrapy-playwright runs on the AsyncioSelectorReactor. Django's ORM
# detects that and raises ``SynchronousOnlyOperation`` when the
# pipeline tries to write rows. This subprocess is the only one that
# does sync ORM from inside the reactor; we know it's safe (the
# pipeline calls happen in worker threads, not the reactor thread).
# Set the escape hatch BEFORE Django imports so connection setup
# picks it up.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

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
        parser.add_argument(
            "--mode", choices=("urls", "walk"), default="urls",
            help="urls = fetch only seeds (default). walk = follow "
                 "internal <a> links from each seed up to --max-depth.",
        )
        parser.add_argument(
            "--max-depth", type=int, default=2,
            help="Walk mode: link depth from each seed. Ignored for urls mode.",
        )
        parser.add_argument(
            "--max-pages", type=int, default=0,
            help="Walk mode: hard cap on followed pages (0 = unlimited).",
        )
        parser.add_argument(
            "--snapshot-kind", choices=("competitor", "content"),
            default="competitor",
            help="CrawlSnapshot.kind the dual-write pipeline stamps. "
                 "'content' = own-site content crawl (Content page).",
        )
        parser.add_argument(
            "--allowed-host", default="",
            help="Exact host scope (e.g. www.example.com). Responses on "
                 "any other host (redirect targets included) are dropped. "
                 "Empty = apex-wide.",
        )

    def handle(self, *args, **options) -> None:
        target_domain: str = options["target_domain"]
        urls_path = Path(options["urls_file"])
        out_path = Path(options["output_file"])
        user_agent: str = options.get("user_agent") or ""
        body_cap: int = int(options.get("body_cap") or 0)
        playwright_enabled: bool = bool(options.get("playwright"))
        mode: str = options.get("mode") or "urls"
        max_depth: int = int(options.get("max_depth") or 2)
        max_pages: int = int(options.get("max_pages") or 0)
        snapshot_kind: str = options.get("snapshot_kind") or "competitor"
        allowed_host: str = (options.get("allowed_host") or "").strip().lower()

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
            # Without Playwright we must STILL provide a non-empty
            # DOWNLOAD_HANDLERS map — earlier we wiped it to {} hoping
            # Scrapy would fall back to defaults, but CrawlerProcess
            # settings override base settings AND spider custom_settings,
            # leaving Scrapy with no handlers at all (0 pages crawled).
            # Explicitly point at Scrapy's built-in HTTP handlers.
            process_settings["DOWNLOAD_HANDLERS"] = {
                "http": "scrapy.core.downloader.handlers.http.HTTPDownloadHandler",
                "https": "scrapy.core.downloader.handlers.http.HTTPDownloadHandler",
            }
            # Drop the Playwright downloader-middleware — its only job
            # is the JS-render gate, which is meaningless without the
            # handler above.
            process_settings["DOWNLOADER_MIDDLEWARES"] = {
                "apps.crawler.middlewares.playwright_gate.PlaywrightGateMiddleware": None,
            }
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
                mode=mode,
                max_depth=max_depth,
                max_pages=max_pages,
                snapshot_kind=snapshot_kind,
                allowed_host=allowed_host,
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
