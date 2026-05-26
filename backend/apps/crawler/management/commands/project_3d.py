"""Run UMAP 3D projection over embedded pages."""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Project all PageEmbedding rows for the latest snapshot to 3D coords."

    def add_arguments(self, parser):
        parser.add_argument("--snapshot", type=str, default="")

    def handle(self, *args, **options):
        from ...models import CrawlSnapshot
        from ...content.projection import project_snapshot_3d

        if options.get("snapshot"):
            snap = CrawlSnapshot.objects.filter(id=options["snapshot"]).first()
        else:
            snap = CrawlSnapshot.objects.order_by("-started_at").first()
        if snap is None:
            self.stderr.write("No snapshots in DB.")
            return

        t0 = time.time()
        n = project_snapshot_3d(snap)
        elapsed = time.time() - t0
        self.stdout.write(self.style.SUCCESS(
            f"Projected {n} points in {elapsed:.1f}s for snapshot {snap.id}"
        ))
