"""Derive a GSC coverage CSV from already-pulled performance data + a
fresh sitemap.xml fetch.

Run after ``python backend/scripts/gsc_pull.py`` has populated
``backend/data/gsc/<site>/`` with at least the ``web__page.csv`` file::

    python manage.py gsc_build_coverage
    python manage.py gsc_build_coverage --sitemap https://www.example.com/sitemap.xml
    python manage.py gsc_build_coverage --backfill-sitemap

The ``--backfill-sitemap`` flag also rewrites the ``from_sitemap`` column
on every crawler CSV so existing rows (which were migrated as
``from_sitemap=unknown``) get the right boolean.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.crawler.storage import gsc_coverage_builder as builder


class Command(BaseCommand):
    help = ("Derive a GSC coverage CSV from existing performance data and "
            "live sitemap.xml; optionally backfill from_sitemap on crawler CSVs.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--sitemap",
            default=builder.DEFAULT_SITEMAP,
            help="Sitemap URL to fetch (default: %(default)s)",
        )
        parser.add_argument(
            "--backfill-sitemap",
            action="store_true",
            help="Rewrite from_sitemap column on existing crawler CSVs.",
        )

    def handle(self, *_args, **options):
        sitemap = options["sitemap"]
        self.stdout.write(self.style.NOTICE(f"Sitemap seed: {sitemap}"))

        coverage_summary = builder.build_coverage(sitemap_seed=sitemap)
        self.stdout.write(builder.format_summary(coverage_summary))

        if options.get("backfill_sitemap"):
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("Backfilling from_sitemap..."))
            backfill_summary = builder.backfill_from_sitemap(sitemap_seed=sitemap)
            self.stdout.write(builder.format_summary(backfill_summary))

        self.stdout.write(self.style.SUCCESS("Done."))
