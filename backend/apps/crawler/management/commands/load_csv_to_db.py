"""One-shot loader: imports crawl_results.csv into Postgres.

Workaround for the known dual-write bug — fetcher wrote CSV
successfully but Postgres rows failed with `'int' object is not
subscriptable`. This command creates a fresh snapshot and bulk-creates
CrawlerPageResult rows from the existing CSV.

Once the dual-write bug is fixed, this command is no longer needed —
nightly crawls will populate Postgres directly.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from ...conf import settings as crawler_settings
from ...models import CrawlSnapshot, CrawlerPageResult


# Map CSV row keys → CrawlerPageResult kwargs. We only load the
# columns we know the model has; the rest go into `extra` JSONB.
SAFE_STR_FIELDS = {
    "url", "final_url", "title", "meta_description", "canonical",
    "meta_robots", "subdomain", "page_type", "category_key",
    "content_type", "status", "status_code", "error_type", "error_message",
}
SAFE_INT_FIELDS = {"response_time_ms", "word_count"}
# Phase 2A.5 structural mirror — JSONField columns serialized by csv_writer
# as JSON strings. Parsed back via json.loads here. Empty / missing → [].
SAFE_JSON_LIST_FIELDS = {
    "headings_json", "internal_links_json",
    "external_links_json", "images_json",
}


class Command(BaseCommand):
    help = "Bulk-import crawl_results.csv into a new CrawlSnapshot."

    def add_arguments(self, parser):
        parser.add_argument("--csv", type=str, default="")
        parser.add_argument(
            "--seed-url", type=str,
            default="https://www.bajajlifeinsurance.com/",
        )

    def handle(self, *args, **options):
        csv_path = Path(
            options.get("csv") or crawler_settings.data_path / "crawl_results.csv"
        )
        if not csv_path.exists():
            self.stderr.write(f"missing {csv_path}")
            return

        snap = CrawlSnapshot.objects.create(
            engine=CrawlSnapshot.Engine.LEGACY,
            kind=CrawlSnapshot.Kind.BAJAJ,
            target_domain="bajajlifeinsurance.com",
            seed_url=options["seed_url"],
            allowed_domains=["bajajlifeinsurance.com", "www.bajajlifeinsurance.com"],
            status=CrawlSnapshot.Status.COMPLETE,
            notes="Loaded from CSV via load_csv_to_db (dual-write bypass).",
        )
        self.stdout.write(self.style.NOTICE(f"Created snapshot {snap.id}"))

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        created = 0
        for r in rows:
            kw = {}
            for field in SAFE_STR_FIELDS:
                v = r.get(field, "")
                if v is None:
                    v = ""
                kw[field] = str(v)[:2048] if field in ("url", "final_url") else str(v)[:1024]
            for field in SAFE_INT_FIELDS:
                try:
                    kw[field] = int(r.get(field) or 0)
                except (TypeError, ValueError):
                    kw[field] = 0
            # JSONB list field — jsonld_types might be stored as JSON string in CSV
            jt = r.get("jsonld_types", "")
            if jt:
                try:
                    parsed = json.loads(jt)
                    kw["jsonld_types"] = parsed if isinstance(parsed, list) else []
                except (TypeError, ValueError):
                    kw["jsonld_types"] = []
            else:
                kw["jsonld_types"] = []

            # Phase 2A.5 structural fields (headings / link / image inventories)
            for field in SAFE_JSON_LIST_FIELDS:
                raw = r.get(field, "")
                if not raw:
                    kw[field] = []
                    continue
                try:
                    parsed = json.loads(raw)
                    kw[field] = parsed if isinstance(parsed, list) else []
                except (TypeError, ValueError):
                    kw[field] = []

            # Skip empty/header rows
            if not kw.get("url"):
                continue

            CrawlerPageResult.objects.create(snapshot=snap, **kw)
            created += 1

        snap.pages_attempted = created
        snap.pages_ok = sum(
            1 for r in rows if (r.get("status_code") or "") == "200"
        )
        snap.save()
        self.stdout.write(self.style.SUCCESS(
            f"Loaded {created} rows ({snap.pages_ok} OK)."
        ))
