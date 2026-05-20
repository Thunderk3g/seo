"""Daily MetricSnapshot runner — Phase 5a.

Captures the Health Score + per-category counts + PageRank/near-dup
summary for the current day so the trends UI can render a Health Score
trajectory over time.

Two entry points:

  1. Celery beat — wires ``run_daily_snapshot`` to fire nightly at
     03:00 IST (after any nightly crawler has had time to finish).
     The beat schedule registration lives in ``config/celery.py``;
     this module just exposes the callable.

  2. Management command ``snapshot_metrics`` — manual trigger for
     testing or backfill. Idempotent: re-running for today's date
     updates the existing row instead of inserting a duplicate.

The snapshot intentionally re-derives every metric from the canonical
sources (audit engine + pagerank + near_dup services). It does NOT
read from CrawlSnapshot.health_score — that field reflects the engine
that LAST ran, which might be the wrong source if multiple engines
ran on the same day. Re-computing keeps the trend signal clean.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger("apps.crawler.services.snapshot_runner")


def take_snapshot(
    *,
    engine: str = "legacy",
    notes: str = "",
) -> dict[str, Any]:
    """Compute today's metrics and upsert one MetricSnapshot row.

    Returns the saved row's slim dict shape so the management command
    can echo it to stdout. Always uses today's date in the local TZ —
    callers wanting historical backfill should call the model directly.
    """
    from django.utils import timezone as dj_tz
    from ..audits import run_all
    from ..models import MetricSnapshot
    from ..services.health_score import compute as compute_health
    from ..services import pagerank as pagerank_svc
    from ..services import near_dup as near_dup_svc

    today = dj_tz.localdate()

    try:
        audit = run_all()
    except Exception as exc:  # noqa: BLE001 — never block snapshot on audit
        log.warning("snapshot_runner: run_all failed (%s)", exc)
        audit = None

    hs = None
    if audit is not None:
        try:
            hs = compute_health(audit)
        except Exception as exc:  # noqa: BLE001
            log.warning("snapshot_runner: compute_health failed (%s)", exc)

    # Issue counts as { slug: affected_url_count } so trend drill-ins
    # can show how a specific issue (e.g., duplicate_title) moved over
    # time.
    issue_counts: dict[str, int] = {}
    if audit is not None:
        for occ in audit.occurrences:
            if occ.count > 0:
                issue_counts[occ.issue.slug] = occ.count

    try:
        pr_summary = pagerank_svc.summary()
    except Exception:  # noqa: BLE001
        pr_summary = {"node_count": 0, "orphan_count": 0}

    try:
        nd_summary = near_dup_svc.summary()
    except Exception:  # noqa: BLE001
        nd_summary = {"cluster_count": 0, "total_dupes": 0}

    sev = audit.severity_counts() if audit else {"error": 0, "warning": 0, "notice": 0}

    snap, created = MetricSnapshot.objects.update_or_create(
        recorded_date=today,
        engine=engine,
        defaults={
            "health_score": hs.score if hs else None,
            "health_tier": hs.tier if hs else "",
            "pages_attempted": audit.total_urls if audit else 0,
            "pages_ok": audit.ok_urls if audit else 0,
            "pages_errored": (audit.total_urls - audit.ok_urls) if audit else 0,
            "errors": sev.get("error", 0),
            "warnings": sev.get("warning", 0),
            "notices": sev.get("notice", 0),
            "issue_counts": issue_counts,
            "category_counts": hs.category_counts if hs else {},
            "pagerank_node_count": int(pr_summary.get("node_count") or 0),
            "pagerank_orphan_count": int(pr_summary.get("orphan_count") or 0),
            "near_dup_cluster_count": int(nd_summary.get("cluster_count") or 0),
            "near_dup_total_dupes": int(nd_summary.get("total_dupes") or 0),
            "notes": notes[:4000] if notes else "",
        },
    )

    log.info(
        "snapshot_runner: %s %s (%s) score=%s",
        "created" if created else "updated", today, engine, hs.score if hs else None,
    )
    return _snapshot_dict(snap, created=created)


def latest(*, engine: str = "", limit: int = 90) -> list[dict[str, Any]]:
    """Return the last N daily snapshots (default 90, cap 365).

    When ``engine`` is set, filters to that engine; otherwise returns
    every engine's rows interleaved by date (the chart layer chooses
    how to series them).
    """
    from ..models import MetricSnapshot

    capped = max(1, min(int(limit), 365))
    qs = MetricSnapshot.objects.all()
    if engine:
        qs = qs.filter(engine=engine)
    rows = list(qs.order_by("-recorded_date")[:capped])
    # Reverse so the response is chronologically ascending — easier
    # for chart libraries that expect oldest-first.
    rows.reverse()
    return [_snapshot_dict(r) for r in rows]


def _snapshot_dict(snap, *, created: bool | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "recorded_date": snap.recorded_date.isoformat(),
        "engine": snap.engine,
        "health_score": snap.health_score,
        "health_tier": snap.health_tier,
        "pages_attempted": snap.pages_attempted,
        "pages_ok": snap.pages_ok,
        "pages_errored": snap.pages_errored,
        "errors": snap.errors,
        "warnings": snap.warnings,
        "notices": snap.notices,
        "issue_counts": snap.issue_counts,
        "category_counts": snap.category_counts,
        "pagerank_node_count": snap.pagerank_node_count,
        "pagerank_orphan_count": snap.pagerank_orphan_count,
        "near_dup_cluster_count": snap.near_dup_cluster_count,
        "near_dup_total_dupes": snap.near_dup_total_dupes,
    }
    if created is not None:
        out["was_created"] = created
    return out
