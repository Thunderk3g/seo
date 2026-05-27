"""Classify the latest Bajaj crawl content into (products, page_type).

Run:
    python manage.py classify_content
    python manage.py classify_content --csv data/crawl_results.csv
    python manage.py classify_content --uncertain-only

Outputs two files in the project's data dir:
  * content_classification.json  — full per-page result + summary
  * content_classification.csv   — flat sheet for manual spot-check
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

from ...conf import settings as crawler_settings
from ...content.pipeline import classify_batch, aggregate_stats


class Command(BaseCommand):
    help = "Classify the latest crawl content using the Tier 1 rule-based classifier."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            type=str,
            default="",
            help="Override path to crawl_results.csv (defaults to crawler data dir).",
        )
        parser.add_argument(
            "--uncertain-only",
            action="store_true",
            help="In the report, include only pages flagged uncertain.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Process only the first N rows (debug aid).",
        )

    def handle(self, *args, **options):
        csv_path = Path(
            options.get("csv") or crawler_settings.data_path / "crawl_results.csv"
        )
        if not csv_path.exists():
            self.stderr.write(self.style.ERROR(f"crawl_results.csv not found at {csv_path}"))
            sys.exit(1)

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if options.get("limit"):
            rows = rows[: options["limit"]]

        self.stdout.write(self.style.NOTICE(
            f"Loaded {len(rows)} rows from {csv_path}"
        ))
        ok_rows = [r for r in rows if r.get("status_code") == "200"]
        self.stdout.write(f"  → {len(ok_rows)} OK pages to classify")

        classifications = classify_batch(ok_rows)
        stats = aggregate_stats(classifications)

        # Filter for uncertain-only output if requested
        report = classifications
        if options.get("uncertain_only"):
            report = [c for c in classifications if c.get("uncertain")]

        # Write outputs
        data_dir = crawler_settings.data_path
        data_dir.mkdir(parents=True, exist_ok=True)
        json_path = data_dir / "content_classification.json"
        csv_path_out = data_dir / "content_classification.csv"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"summary": stats, "rows": classifications}, f, indent=2)

        with open(csv_path_out, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "url", "title", "products", "primary_product",
                "page_type", "page_type_conf", "uncertain", "signals",
            ])
            for c in report:
                writer.writerow([
                    c.get("url", ""),
                    (c.get("title", "") or "")[:120],
                    ",".join(p["label"] for p in c.get("products", [])),
                    (c.get("products") or [{"label": ""}])[0]["label"],
                    c.get("page_type", ""),
                    c.get("page_type_confidence", 0),
                    "Y" if c.get("uncertain") else "",
                    ",".join((c.get("signals", []) or [])[:6]),
                ])

        # Console summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Classification summary ==="))
        self.stdout.write(f"  Pages classified:  {stats['total']}")
        self.stdout.write(
            f"  Uncertain:         {stats['uncertain']} "
            f"({stats['uncertain_pct']}%)"
        )
        self.stdout.write(f"  Avg page-type confidence: {stats['avg_page_type_confidence']}")
        self.stdout.write("")
        self.stdout.write("  By product:")
        for k, v in stats["by_product"].items():
            self.stdout.write(f"    {k:15s} {v}")
        self.stdout.write("")
        self.stdout.write("  By page type:")
        for k, v in stats["by_page_type"].items():
            self.stdout.write(f"    {k:18s} {v}")
        self.stdout.write("")
        self.stdout.write("  Products-per-page distribution:")
        for n, count in sorted(stats["products_per_page"].items()):
            self.stdout.write(f"    {n} product(s): {count} pages")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Wrote {json_path}"))
        self.stdout.write(self.style.SUCCESS(f"Wrote {csv_path_out}"))
