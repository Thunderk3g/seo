"""Snapshot service — manages the in-flight CrawlSnapshot row.

Phase 3 lifecycle:

  1. ``start_snapshot(engine, seed_url, allowed_domains, config)``
     Creates a CrawlSnapshot row with status='running' and stashes it
     in a module-level slot so csv_writer.append() can find it.
  2. CSV writes happen as usual. The dual-write hook in csv_writer
     reads ``current_snapshot()`` and writes a CrawlerPageResult row
     keyed by the snapshot.
  3. ``finish_snapshot(status='complete')`` closes out the row with
     final counters + Health Score and clears the slot.

Designed to be fully non-blocking: if Postgres is down (the operator
is running standalone without docker-compose) every helper logs once
and returns None — the legacy CSV path keeps working untouched.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

log = logging.getLogger("apps.crawler.services.snapshot")


_current_lock = threading.Lock()
_current_snapshot_id: str | None = None


def start_snapshot(
    *,
    engine: str = "legacy",
    seed_url: str = "",
    allowed_domains: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Create a CrawlSnapshot row and remember its id. Returns the id
    or None if Postgres isn't reachable."""
    global _current_snapshot_id
    try:
        from ..models import CrawlSnapshot
        snap = CrawlSnapshot.objects.create(
            engine=engine,
            seed_url=seed_url,
            allowed_domains=list(allowed_domains or []),
            config_snapshot=dict(config or {}),
            status=CrawlSnapshot.Status.RUNNING,
        )
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        log.info(
            "snapshot: start failed (%s) — continuing without Postgres",
            type(exc).__name__,
        )
        return None
    with _current_lock:
        _current_snapshot_id = str(snap.id)
    log.info("snapshot: started %s engine=%s", snap.id, engine)
    return str(snap.id)


def current_snapshot_id() -> str | None:
    """Return the id of the in-flight CrawlSnapshot, if any."""
    with _current_lock:
        return _current_snapshot_id


def finish_snapshot(
    *,
    status: str = "complete",
    pages_attempted: int = 0,
    pages_ok: int = 0,
    pages_errored: int = 0,
    health_score: int | None = None,
    health_tier: str = "",
    notes: str = "",
) -> None:
    """Close out the in-flight snapshot."""
    global _current_snapshot_id
    snap_id = current_snapshot_id()
    if snap_id is None:
        return
    try:
        from django.utils import timezone as dj_tz
        from ..models import CrawlSnapshot
        CrawlSnapshot.objects.filter(pk=snap_id).update(
            status=status,
            finished_at=dj_tz.now(),
            pages_attempted=pages_attempted,
            pages_ok=pages_ok,
            pages_errored=pages_errored,
            health_score=health_score,
            health_tier=health_tier,
            notes=notes[:4000] if notes else "",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("snapshot: finish failed for %s (%s)", snap_id, exc)
    finally:
        with _current_lock:
            _current_snapshot_id = None
    log.info("snapshot: finished %s status=%s", snap_id, status)


def latest_completed_snapshot_id() -> str | None:
    """Most recent COMPLETED snapshot id. Used by Page Explorer /
    Health Score when CRAWLER_ENGINE=scrapy reads from ORM and there's
    no in-flight crawl."""
    try:
        from ..models import CrawlSnapshot
        snap = (
            CrawlSnapshot.objects
            .filter(status=CrawlSnapshot.Status.COMPLETE)
            .order_by("-started_at")
            .values_list("id", flat=True)
            .first()
        )
        return str(snap) if snap else None
    except Exception:  # noqa: BLE001
        return None
