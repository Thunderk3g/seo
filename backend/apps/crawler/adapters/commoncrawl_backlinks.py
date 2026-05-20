"""Common Crawl WAT-derived backlink adapter — stub + read side.

Common Crawl publishes a monthly snapshot of ~3 billion URLs along
with WAT (Web Archive Transformation) files exposing every outbound
link from every crawled page. By stream-filtering WAT and keeping
only edges whose target_domain matches Bajaj or a tracked competitor,
we get a poor-mans backlink index without buying Ahrefs / Majestic.

Operationally:
  * The full WAT pull is monthly + heavyweight (100s of GB streamed).
    A Celery Beat task runs ``pull_release(release_id)`` and writes
    matching edges into ``Backlink``. That live pipeline is a separate
    workstream (~16h) that the operator will wire when the first
    monthly cadence is approved.
  * This file ships the **target list + read side + dry-run pull stub**
    so the model is exercised, the endpoint is callable, and the chat
    tool returns deterministic data even when no real WAT pull has
    happened yet. The dry-run loads ``data/backlinks_seed.csv`` if
    present (operator can drop a hand-curated seed file there to
    bootstrap the dashboard).

Reference: https://commoncrawl.org/get-started
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


TARGET_DOMAINS: tuple[str, ...] = (
    "bajajlifeinsurance.com",
    "www.bajajlifeinsurance.com",
    "branch.bajajlifeinsurance.com",
    # Tracked competitors — extend as needed.
    "hdfclife.com", "iciciprulife.com", "maxlifeinsurance.com",
    "tataaia.com", "sbilife.co.in", "kotaklife.com", "licindia.in",
)


def _seed_path() -> Path:
    from django.conf import settings
    base = Path(getattr(settings, "BASE_DIR", "."))
    return base / "data" / "backlinks_seed.csv"


def pull_release(release_id: str, *, dry_run: bool = True) -> dict[str, Any]:
    """Pull one Common Crawl release into the Backlink table.

    Live mode (``dry_run=False``) streams WAT files for the given
    release, filtering on TARGET_DOMAINS — not implemented here, this
    is the seam where the heavyweight pipeline plugs in. Dry-run
    instead loads ``data/backlinks_seed.csv`` if present so the
    /backlinks endpoint has something real to show before the
    monthly pipeline lands.
    """
    if not dry_run:
        return {
            "ok": False,
            "error": (
                "live Common Crawl pull not wired yet — see "
                "commoncrawl_backlinks.py docstring. Use dry_run=True "
                "to load data/backlinks_seed.csv instead."
            ),
            "release_id": release_id,
        }

    try:
        from ..models import Backlink
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "Backlink model not available"}

    seed = _seed_path()
    if not seed.exists():
        return {
            "ok": True,
            "dry_run": True,
            "release_id": release_id,
            "note": (
                f"No seed at {seed}. Drop a CSV with header "
                "source_url,target_url,anchor_text,rel to bootstrap "
                "the table before the monthly WAT pipeline lands."
            ),
            "inserted": 0,
            "updated": 0,
        }

    inserted = 0
    updated = 0
    with seed.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            src = (row.get("source_url") or "").strip()
            tgt = (row.get("target_url") or "").strip()
            if not src or not tgt:
                continue
            tgt_domain = _domain_of(tgt)
            if tgt_domain not in TARGET_DOMAINS:
                continue
            anchor = (row.get("anchor_text") or "")[:1024]
            rel = (row.get("rel") or "")[:64]
            obj, created = Backlink.objects.update_or_create(
                source_url=src,
                target_url=tgt,
                defaults={
                    "source_domain": _domain_of(src),
                    "target_domain": tgt_domain,
                    "anchor_text": anchor,
                    "rel": rel,
                    "nofollow": "nofollow" in rel.lower(),
                    "discovered_in": release_id or "manual",
                },
            )
            if created:
                inserted += 1
            else:
                updated += 1
    return {
        "ok": True,
        "dry_run": True,
        "release_id": release_id,
        "inserted": inserted,
        "updated": updated,
    }


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse
    return (urlparse(url).netloc or "").lower()


# ── Read side ─────────────────────────────────────────────────────────────


def recent_backlinks(limit: int = 100) -> list[dict[str, Any]]:
    try:
        from ..models import Backlink
        rows = Backlink.objects.order_by("-last_seen").values(
            "id", "source_url", "source_domain", "target_url",
            "target_domain", "anchor_text", "rel", "nofollow",
            "discovered_in", "first_seen", "last_seen",
        )[:limit]
        return [
            {
                "id": str(r["id"]),
                "source_url": r["source_url"],
                "source_domain": r["source_domain"],
                "target_url": r["target_url"],
                "target_domain": r["target_domain"],
                "anchor_text": r["anchor_text"][:200],
                "rel": r["rel"],
                "nofollow": r["nofollow"],
                "discovered_in": r["discovered_in"],
                "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
            }
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        return []


def summary() -> dict[str, Any]:
    try:
        from django.db.models import Count
        from ..models import Backlink
        total = Backlink.objects.count()
        per_target = list(
            Backlink.objects.values("target_domain")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        )
        per_source_domain = (
            Backlink.objects.values("source_domain")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        )
        return {
            "total": total,
            "per_target_domain": list(per_target),
            "top_referring_domains": list(per_source_domain),
        }
    except Exception:  # noqa: BLE001
        return {"total": 0, "per_target_domain": [], "top_referring_domains": []}
