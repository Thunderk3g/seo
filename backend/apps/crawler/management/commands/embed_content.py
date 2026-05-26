"""Embed every page in the latest crawl snapshot.

Run:
    python manage.py embed_content
    python manage.py embed_content --snapshot <uuid>
    python manage.py embed_content --force      # re-embed even if rows exist
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Embed crawled page content into pgvector for similarity search."

    def add_arguments(self, parser):
        parser.add_argument("--snapshot", type=str, default="")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        from ...models import CrawlSnapshot
        from ...content.embedder import embed_snapshot

        if options.get("snapshot"):
            snap = CrawlSnapshot.objects.filter(id=options["snapshot"]).first()
        else:
            snap = CrawlSnapshot.objects.order_by("-started_at").first()
        if snap is None:
            self.stderr.write("No snapshots in DB — run a crawl first.")
            return

        self.stdout.write(self.style.NOTICE(
            f"Embedding snapshot {snap.id} ({snap.started_at})"
        ))
        t0 = time.time()
        counts = embed_snapshot(snap, force=options.get("force", False), verbose=True)
        elapsed = time.time() - t0
        self.stdout.write(self.style.SUCCESS(
            f"Done in {elapsed:.1f}s — {counts}"
        ))
