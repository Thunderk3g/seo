"""Headless Scrapy crawl runner — Phase 3d.

Usage::

    python manage.py crawl_scrapy                       # full crawl
    python manage.py crawl_scrapy --max-pages 500       # cap pages
    python manage.py crawl_scrapy --max-depth 3         # cap depth
    python manage.py crawl_scrapy --seed https://...    # override seed
    python manage.py crawl_scrapy --report              # XLSX after crawl

Runs the Scrapy port of the legacy BFS engine in the foreground (no
API server / Celery / threading). Snapshot lifecycle, CSV writes, and
Postgres dual-write all happen via the pipeline ``CsvDualWritePipeline``,
so the resulting data is indistinguishable from a legacy crawl as far
as Page Explorer + Health Score + Issues are concerned.

This command does NOT replace ``python manage.py crawl``. Legacy stays
as the default engine until the operator flips ``CRAWLER_ENGINE=scrapy``
in .env after a successful A/B parity check (Phase 3e).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.crawler.conf import settings as crawler_settings
from apps.crawler.services import report_service


class Command(BaseCommand):
    help = (
        "Run the Scrapy port of the crawler in the foreground. "
        "Behind the CRAWLER_ENGINE flag — does not replace `crawl`."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--seed",
            type=str,
            default="",
            help="Override settings.seed_url for this run only.",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=0,
            help=(
                "Stop after N pages crawled. 0 = no cap. Defaults to "
                "settings.max_pages (also typically 0 = unlimited)."
            ),
        )
        parser.add_argument(
            "--max-depth",
            type=int,
            default=0,
            help=(
                "Cap BFS depth from the seed. 0 = no cap. Mirrors "
                "settings.max_depth."
            ),
        )
        parser.add_argument(
            "--report",
            action="store_true",
            help="Generate the XLSX bundle once the crawl finishes.",
        )

    def handle(self, *args, **options) -> None:
        # Import here so a missing Scrapy install only blocks THIS
        # command rather than every Django startup.
        try:
            from scrapy.crawler import CrawlerProcess
            from scrapy.utils.project import get_project_settings  # noqa: F401
        except ImportError as exc:
            raise SystemExit(
                "Scrapy not installed. Add scrapy + scrapy-playwright to "
                f"requirements/base.txt and run pip install: {exc}"
            )

        from apps.crawler.spiders import BajajSpider

        seed = options.get("seed") or crawler_settings.seed_url
        max_pages = options.get("max_pages") or 0
        max_depth = options.get("max_depth") or 0

        self.stdout.write(self.style.NOTICE(
            f"Scrapy crawl starting\n"
            f"  Seed:    {seed}\n"
            f"  Allowed: {', '.join(crawler_settings.allowed_domains)}\n"
            f"  Max pages: {max_pages or 'unlimited'}\n"
            f"  Max depth: {max_depth or 'unlimited'}\n"
            f"  Data dir:  {crawler_settings.data_path}\n"
        ))

        # Build the per-run Scrapy settings dict. We let BajajSpider's
        # custom_settings drive most of the defaults; the only thing
        # we override here is runtime caps the operator passed.
        process_settings = {}
        if max_pages:
            process_settings["CLOSESPIDER_PAGECOUNT"] = max_pages
        if max_depth:
            process_settings["DEPTH_LIMIT"] = max_depth

        process = CrawlerProcess(settings=process_settings)
        process.crawl(
            BajajSpider,
            seed_url=seed,
            max_pages=max_pages,
            max_depth=max_depth,
        )
        process.start(stop_after_crawl=True)

        self.stdout.write(self.style.SUCCESS("Scrapy crawl finished."))

        # Snapshot + Postgres totals.
        try:
            from apps.crawler.models import CrawlSnapshot, CrawlerPageResult
            snap = (
                CrawlSnapshot.objects.filter(engine=CrawlSnapshot.Engine.SCRAPY)
                .order_by("-started_at")
                .first()
            )
            if snap:
                page_count = CrawlerPageResult.objects.filter(snapshot=snap).count()
                self.stdout.write(self.style.SUCCESS(
                    f"  Snapshot {snap.id}: status={snap.status} "
                    f"pages_ok={snap.pages_ok} pages_errored={snap.pages_errored} "
                    f"health_score={snap.health_score} ({snap.health_tier})\n"
                    f"  CrawlerPageResult rows for this snapshot: {page_count}"
                ))
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(
                f"  (Postgres summary unavailable: {exc})"
            ))

        if options.get("report"):
            self.stdout.write("Generating XLSX report...")
            path = report_service.generate_xlsx()
            self.stdout.write(self.style.SUCCESS(f"Report written to {path}"))
