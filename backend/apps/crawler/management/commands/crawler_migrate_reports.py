"""Backfill the five enrichment columns onto every CSV in ``backend/data/``.

Use this after pulling new code if you already have crawl artefacts on disk
from before the category-segregated reports landed::

    python manage.py crawler_migrate_reports

Idempotent — re-running on an already-migrated file is a no-op. The first
run leaves a ``.bak`` next to each file so you can roll back if needed.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.crawler.storage import migrate_reports


class Command(BaseCommand):
    help = (
        "Backfill subdomain/page_type/category_key/from_sitemap/indexed_status "
        "columns onto existing crawler CSVs."
    )

    def handle(self, *_args, **_options):
        summary = migrate_reports.run()
        self.stdout.write(migrate_reports.format_summary(summary))
        migrated = sum(1 for v in summary.values() if v["status"] == "migrated")
        skipped = sum(1 for v in summary.values() if v["status"] == "skipped")
        errors = sum(1 for v in summary.values() if v["status"] == "error")
        msg = f"migrated={migrated} skipped={skipped} errors={errors}"
        if errors:
            self.stdout.write(self.style.WARNING(msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))
