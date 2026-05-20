"""Daily metrics snapshot — manual trigger.

Usage::

    python manage.py snapshot_metrics
    python manage.py snapshot_metrics --engine scrapy
    python manage.py snapshot_metrics --notes "post-fix verification"

In production this fires nightly via Celery beat. The management
command lets the operator backfill / re-run for the current day.
Idempotent: re-running updates the existing (date, engine) row.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Capture today's Health Score + per-category metrics into MetricSnapshot."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--engine",
            type=str,
            default="legacy",
            help="Engine label for the snapshot (default 'legacy'). "
                 "Use 'scrapy' to track the Scrapy port separately.",
        )
        parser.add_argument(
            "--notes",
            type=str,
            default="",
            help="Optional free-form note saved with the snapshot.",
        )

    def handle(self, *args, **options) -> None:
        from apps.crawler.services.snapshot_runner import take_snapshot

        engine = options.get("engine") or "legacy"
        notes = options.get("notes") or ""

        self.stdout.write(self.style.NOTICE(
            f"Capturing MetricSnapshot for today (engine={engine})..."
        ))
        result = take_snapshot(engine=engine, notes=notes)
        action = "CREATED" if result.get("was_created") else "UPDATED"
        self.stdout.write(self.style.SUCCESS(
            f"{action} snapshot {result['recorded_date']} engine={result['engine']}\n"
            f"  Health Score: {result['health_score']} ({result['health_tier']})\n"
            f"  Errors / Warnings / Notices: "
            f"{result['errors']} / {result['warnings']} / {result['notices']}\n"
            f"  Pages: {result['pages_ok']:,}/{result['pages_attempted']:,} OK\n"
            f"  PageRank nodes: {result['pagerank_node_count']:,} "
            f"({result['pagerank_orphan_count']:,} orphans)\n"
            f"  Near-dup clusters: {result['near_dup_cluster_count']:,} "
            f"({result['near_dup_total_dupes']:,} total dupes)"
        ))
