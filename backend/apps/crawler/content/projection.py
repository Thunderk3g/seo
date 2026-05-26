"""UMAP 3D projection of page embeddings — Phase 3.

UMAP reduces the 384-dim MiniLM vectors to 3D coordinates suitable for
plotting. We cache the projection on the PageEmbedding row (coord_x/y/z)
so the /content/map/3d API can stream pre-computed points.

Runtime: ~3-5 seconds for ~1000 chunks on CPU. Trivial for nightly batch.
"""
from __future__ import annotations

import logging
import numpy as np
from django.db import connection

log = logging.getLogger(__name__)


def project_snapshot_3d(snapshot, *, n_neighbors: int = 8, min_dist: float = 0.5,
                        target_radius: float = 8.0) -> int:
    """Run UMAP over every chunk embedding for a snapshot. Updates
    coord_x/y/z in-place. Returns the number of points projected.

    Looser defaults (min_dist=0.5, n_neighbors=8) deliberately spread
    clusters so the 3D scatter is readable. We also centre the resulting
    coords around (0,0,0) and rescale so the cloud fits within
    ``target_radius`` from the origin — that keeps the frontend camera
    at [target_radius * factor] able to frame the whole scene.
    """
    import umap  # lazy
    from ..models import PageEmbedding

    qs = PageEmbedding.objects.filter(page__snapshot=snapshot).order_by("id")
    points = list(qs.values_list("id", "embedding_json"))
    if len(points) < 5:
        log.warning("not enough points (%d) for UMAP — skipping", len(points))
        return 0

    ids = [p[0] for p in points]
    matrix = np.array([p[1] for p in points], dtype=np.float32)

    # n_neighbors must be < n_samples. Auto-shrink for small snapshots.
    nn = min(n_neighbors, max(2, len(points) - 1))

    reducer = umap.UMAP(
        n_components=3,
        n_neighbors=nn,
        min_dist=min_dist,
        spread=2.0,        # widens cluster separation
        metric="cosine",
        random_state=42,   # deterministic — same snapshot → same coords
    )
    coords = reducer.fit_transform(matrix)

    # Centre around origin then scale to target radius.
    centre = coords.mean(axis=0)
    coords = coords - centre
    max_extent = float(np.max(np.linalg.norm(coords, axis=1)) or 1.0)
    coords = coords * (target_radius / max_extent)

    # Batch update via raw SQL — single round-trip.
    with connection.cursor() as cur:
        for emb_id, (x, y, z) in zip(ids, coords):
            cur.execute(
                "UPDATE crawler_pageembedding SET coord_x=%s, coord_y=%s, coord_z=%s WHERE id=%s",
                [float(x), float(y), float(z), emb_id],
            )

    return len(points)


def get_3d_points(snapshot) -> list[dict]:
    """Return the 3D scatter dataset for the content map page."""
    from ..models import PageEmbedding

    qs = (
        PageEmbedding.objects
        .filter(
            page__snapshot=snapshot,
            coord_x__isnull=False,
        )
        .select_related("page")
    )
    points = []
    for emb in qs.iterator():
        page = emb.page
        points.append({
            "id": emb.id,
            "chunk_idx": emb.chunk_idx,
            "x": emb.coord_x,
            "y": emb.coord_y,
            "z": emb.coord_z,
            "url": page.url,
            "title": page.title or "",
            "products": emb.products or [],
            "page_type": emb.page_type,
            "confidence": emb.confidence,
        })
    return points
