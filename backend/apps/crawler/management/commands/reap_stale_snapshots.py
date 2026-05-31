"""Mark orphaned 'running' crawl snapshots + gap-pipeline runs as failed.

A competitor crawl opens a CrawlSnapshot (status='running') and the Scrapy
pipeline's close_spider marks it complete/failed. If the worker is killed,
recycled, or the task is redelivered mid-crawl, close_spider never runs and
the snapshot is stuck 'running' forever — which is exactly the "running for
days" symptom the operator saw.

This reaper flips any snapshot/run that has been 'running' longer than
``--hours`` to 'failed' and stamps finished_at. It deletes NO data — only a
status flip — so all crawled pages and history are preserved.

Usage:
  python manage.py reap_stale_snapshots --hours 6
  python manage.py reap_stale_snapshots --hours 6 --dry-run
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Mark stale 'running' CrawlSnapshots and GapPipelineRuns as failed (no data deleted)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours", type=int, default=6,
            help="Age (hours) past which a 'running' row is considered orphaned.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be reaped without writing.",
        )

    def handle(self, *args, **opts):
        hours = int(opts["hours"])
        dry = bool(opts["dry_run"])
        cutoff = timezone.now() - timedelta(hours=hours)
        now = timezone.now()

        from apps.crawler.models import CrawlSnapshot

        snaps = CrawlSnapshot.objects.filter(status="running", started_at__lt=cutoff)
        n_snaps = snaps.count()
        self.stdout.write(f"stale CrawlSnapshots (>{hours}h running): {n_snaps}")
        for s in snaps.order_by("started_at")[:50]:
            self.stdout.write(f"  - {s.kind} {s.target_domain or '(blank)'} since {s.started_at}")
        if not dry and n_snaps:
            snaps.update(status="failed", finished_at=now)
            self.stdout.write(self.style.SUCCESS(f"  -> flipped {n_snaps} snapshots to failed"))

        # Gap-pipeline runs (separate app/table).
        try:
            from apps.seo_ai.models import GapPipelineRun

            runs = GapPipelineRun.objects.filter(status="running", started_at__lt=cutoff)
            n_runs = runs.count()
            self.stdout.write(f"stale GapPipelineRuns (>{hours}h running): {n_runs}")
            for r in runs.order_by("started_at")[:50]:
                self.stdout.write(f"  - {r.domain} since {r.started_at}")
            if not dry and n_runs:
                runs.update(status="failed", finished_at=now)
                self.stdout.write(self.style.SUCCESS(f"  -> flipped {n_runs} gap runs to failed"))
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(f"gap-run reap skipped: {exc}")

        self.stdout.write(self.style.SUCCESS("reap_stale_snapshots done"))
