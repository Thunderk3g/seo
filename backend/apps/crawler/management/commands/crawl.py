"""Headless crawl runner — replacement for ``crawler-engine/run.py``.

Usage::

    python manage.py crawl                # uses settings.seed_url etc.
    python manage.py crawl --no-resume    # ignore any saved crawl_state.json
    python manage.py crawl --report       # generate XLSX report after crawl

The crawl runs synchronously in the foreground (no API server needed),
so this is the way to drive the crawler from cron / CI / a shell.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.crawler.conf import settings as crawler_settings
from apps.crawler.engine.engine import run_crawl
from apps.crawler.services import report_service
from apps.crawler.state import STATE


class Command(BaseCommand):
    help = "Run a full BFS crawl in the foreground (no API server needed)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-resume",
            action="store_true",
            help="Ignore any existing crawl_state.json and start fresh.",
        )
        parser.add_argument(
            "--report",
            action="store_true",
            help="Generate the multi-sheet XLSX report once the crawl finishes.",
        )

    def handle(self, *args, **options):
        if options.get("no_resume"):
            # Mutate the singleton in-place so the engine sees the override.
            crawler_settings.resume = False

        self.stdout.write(self.style.NOTICE(
            f"Seed: {crawler_settings.seed_url}\n"
            f"Allowed domains: {', '.join(crawler_settings.allowed_domains)}\n"
            f"Max workers: {crawler_settings.max_workers}  "
            f"max_depth: {crawler_settings.max_depth}  "
            f"max_pages: {crawler_settings.max_pages}\n"
            f"Data dir: {crawler_settings.data_path}"
        ))

        STATE.reset()
        run_crawl()

        self.stdout.write(self.style.SUCCESS(
            f"Crawl finished — {STATE.stats.crawled} pages, "
            f"{STATE.stats.errors} errors"
        ))

        if options.get("report"):
            self.stdout.write("Generating XLSX report...")
            path = report_service.generate_xlsx()
            self.stdout.write(self.style.SUCCESS(f"Report written to {path}"))
