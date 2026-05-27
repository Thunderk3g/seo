"""Phase E — Re-embed + re-project the latest snapshot in one shot.

Run::

    python manage.py refresh_content_map [--snapshot <uuid>] [--force]

The 3D content map UI consumes ``PageEmbedding`` rows produced by
``embed_content``, projected to 3D coords by ``project_3d``. Both
need to run after every fresh crawl or the map shows stale dots.

This command chains them with sensible defaults so the operator
runs ONE thing instead of remembering both. ``--snapshot`` defaults
to the latest non-empty Bajaj snapshot; ``--force`` re-embeds even
when PageEmbedding rows already exist for that snapshot (use after
fixing classifier rules or upgrading the model).

Wired into Celery later via :func:`apps.seo_ai.tasks.run_refresh_content_map_task`
so the daily 02:00 IST Bajaj crawl can re-embed automatically.
"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db.models import Count


class Command(BaseCommand):
    help = "Re-embed + re-project the latest snapshot's pages for the 3D map."

    def add_arguments(self, parser):
        parser.add_argument(
            "--snapshot", type=str, default="",
            help="UUID of the snapshot to refresh. Default: latest non-empty "
                 "Bajaj snapshot.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Re-embed even when PageEmbedding rows already exist.",
        )
        parser.add_argument(
            "--skip-embed", action="store_true",
            help="Skip the embedding step (use when only re-projection is needed).",
        )
        parser.add_argument(
            "--skip-project", action="store_true",
            help="Skip the UMAP 3D projection step.",
        )
        parser.add_argument(
            "--include-competitors", action="store_true",
            help="After refreshing the Bajaj snapshot, also embed + project "
                 "the latest non-empty COMPLETE competitor snapshot for "
                 "every domain seen in CrawlSnapshot (kind=competitor). "
                 "Each competitor gets its own PageEmbedding rows / 3D "
                 "projection — content maps stay isolated per domain.",
        )
        parser.add_argument(
            "--competitor-domain", type=str, default="",
            help="Only refresh this one competitor domain (skips Bajaj + "
                 "every other competitor). Useful for one-off rebuilds.",
        )

    def handle(self, *args, **options) -> None:
        from ...models import CrawlSnapshot
        from ...content.embedder import embed_snapshot
        from ...content.projection import project_snapshot_3d

        snap_id = (options.get("snapshot") or "").strip()
        competitor_domain = (options.get("competitor_domain") or "").strip().lower()
        include_competitors = bool(options.get("include_competitors"))

        # Single competitor mode bypasses the Bajaj refresh entirely.
        if competitor_domain:
            self._refresh_one_competitor(
                competitor_domain,
                CrawlSnapshot,
                embed_snapshot,
                project_snapshot_3d,
                options,
            )
            return

        # ── Bajaj snapshot (default behaviour, backwards compatible) ──
        if snap_id:
            snap = CrawlSnapshot.objects.filter(id=snap_id).first()
        else:
            snap = (
                CrawlSnapshot.objects.annotate(n=Count("pages"))
                .filter(kind="bajaj", n__gte=5)
                .order_by("-started_at")
                .first()
            )
        if snap is None:
            self.stderr.write(self.style.ERROR(
                "No suitable Bajaj snapshot found. Run a crawl first.",
            ))
            # Even without a Bajaj snapshot we may still want to refresh
            # competitors — fall through if --include-competitors is set.
            if not include_competitors:
                return
        else:
            self._refresh_one(
                snap, embed_snapshot, project_snapshot_3d, options,
            )

        # ── Competitor snapshots ──────────────────────────────────
        if include_competitors:
            self.stdout.write(self.style.NOTICE("\n── Competitor content maps ──"))
            domains = (
                CrawlSnapshot.objects
                .filter(kind="competitor", status="complete")
                .values_list("target_domain", flat=True)
                .distinct()
            )
            for td in sorted(d for d in domains if d):
                self._refresh_one_competitor(
                    td, CrawlSnapshot, embed_snapshot, project_snapshot_3d,
                    options,
                )

    def _refresh_one_competitor(
        self, domain, CrawlSnapshot, embed_snapshot, project_snapshot_3d,
        options,
    ) -> None:
        """Pick the latest non-empty snapshot for ``domain`` and refresh
        its content map. Each competitor's map is isolated from the
        others because every PageEmbedding row carries snapshot_id."""
        snap = (
            CrawlSnapshot.objects.annotate(n=Count("pages"))
            .filter(
                kind="competitor",
                status="complete",
                target_domain__iexact=domain,
                n__gte=3,
            )
            .order_by("-started_at")
            .first()
        )
        if snap is None:
            self.stdout.write(
                f"  {domain}: no snapshot with >=3 pages, skipping",
            )
            return
        self.stdout.write(self.style.NOTICE(
            f"  {domain}: refreshing snapshot {snap.id} "
            f"(started {snap.started_at})",
        ))
        self._refresh_one(
            snap, embed_snapshot, project_snapshot_3d, options,
        )

    def _refresh_one(self, snap, embed_snapshot, project_snapshot_3d,
                    options) -> None:
        """Embed + project one snapshot — Bajaj or competitor, same flow."""
        self.stdout.write(self.style.NOTICE(
            f"Refreshing content map for snapshot {snap.id} "
            f"[{snap.kind}/{snap.engine}] started {snap.started_at}",
        ))

        # ── Embed step ────────────────────────────────────────────
        if not options.get("skip_embed"):
            t0 = time.time()
            self.stdout.write("  Embedding pages…")
            try:
                counts = embed_snapshot(
                    snap,
                    force=options.get("force", False),
                    verbose=True,
                )
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(
                    f"  Embedding failed: {exc}",
                ))
                counts = {"error": str(exc)}
            self.stdout.write(self.style.SUCCESS(
                f"  Embed done in {time.time() - t0:.1f}s → {counts}",
            ))
        else:
            self.stdout.write("  Skipping embed step (--skip-embed).")

        # ── Project step ─────────────────────────────────────────
        if not options.get("skip_project"):
            t0 = time.time()
            self.stdout.write("  Projecting to 3D (UMAP)…")
            try:
                n = project_snapshot_3d(snap)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(self.style.ERROR(
                    f"  Projection failed: {exc}",
                ))
                return
            self.stdout.write(self.style.SUCCESS(
                f"  Projected {n} points in {time.time() - t0:.1f}s",
            ))
        else:
            self.stdout.write("  Skipping projection step (--skip-project).")
