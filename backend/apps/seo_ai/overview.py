"""Dashboard overview payload.

The frontend Overview page needs three slices in one call:
- the latest completed grading run (score, sub-scores, exec summary),
- a GSC rollup (totals + top queries / top pages + daily time series),
- a crawler rollup (totals + error counts).

Three round-trips would be wasteful for what is effectively one
dashboard render. We bundle them here so the Overview page can paint
from a single ``useSeoOverview()`` query.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from django.conf import settings

from .adapters import CrawlerCSVAdapter, GSCCSVAdapter
from .models import SEORun, SEORunStatus

logger = logging.getLogger("seo.ai.overview")


def build_overview(domain: str) -> dict[str, Any]:
    return {
        "domain": domain,
        "latest_run": _latest_run_for(domain),
        "gsc": _gsc_payload(),
        "crawler": _crawler_payload(),
    }


# ── latest run ───────────────────────────────────────────────────────────


def _latest_run_for(domain: str) -> dict[str, Any] | None:
    qs = (
        SEORun.objects.filter(
            domain=domain,
            status__in=[SEORunStatus.COMPLETE, SEORunStatus.DEGRADED],
        )
        .order_by("-started_at")[:1]
    )
    run = qs.first()
    if run is None:
        return None
    narrative = (run.model_versions or {}).get("narrative") or {}
    findings_qs = run.findings.all().order_by("-priority")[:5]
    return {
        "id": str(run.id),
        "status": run.status,
        "overall_score": run.overall_score,
        "sub_scores": run.sub_scores or {},
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "executive_summary": narrative.get("executive_summary") or "",
        "top_action": narrative.get("top_action_this_week") or "",
        "top_findings": [
            {
                "id": str(f.id),
                "agent": f.agent,
                "severity": f.severity,
                "title": f.title,
                "category": f.category,
                "recommendation": f.recommendation,
                "priority": f.priority,
            }
            for f in findings_qs
        ],
        "total_cost_usd": run.total_cost_usd,
    }


# ── GSC ─────────────────────────────────────────────────────────────────


def _gsc_payload() -> dict[str, Any]:
    adapter = GSCCSVAdapter()
    try:
        summary = adapter.summary(sample_size=10)
    except Exception as exc:  # pragma: no cover - file system
        logger.warning("gsc summary failed: %s", exc)
        return {"available": False, "error": str(exc)}

    daily = read_daily_series(adapter)
    return {
        "available": True,
        "totals": {
            "queries": summary.total_queries,
            "pages": summary.total_pages,
            "clicks": summary.total_clicks,
            "impressions": summary.total_impressions,
            "avg_ctr": summary.avg_ctr,
            "avg_position": summary.avg_position,
        },
        "top_queries": [asdict(q) for q in summary.top_queries_by_clicks[:10]],
        "top_pages": [asdict(p) for p in summary.top_pages_by_clicks[:10]],
        "underperforming_queries": [
            asdict(q) for q in summary.underperforming_queries[:5]
        ],
        "daily_series": daily,  # last 90 days for the performance chart
    }


def read_daily_series(adapter: GSCCSVAdapter) -> list[dict[str, Any]]:
    """Read web__date.csv ordered ASC, return last 90 non-zero days.

    The performance chart shows clicks + impressions in dual-axis style
    over the rolling window. Zero-padded leading days are dropped so
    the chart starts where real data begins.
    """
    path: Path = adapter.site_dir / "web__date.csv"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                try:
                    clicks = int(float(r.get("clicks") or 0))
                    impressions = int(float(r.get("impressions") or 0))
                    if clicks == 0 and impressions == 0:
                        continue
                    rows.append(
                        {
                            "date": r["date"],
                            "clicks": clicks,
                            "impressions": impressions,
                            "ctr": float(r.get("ctr") or 0),
                            "position": float(r.get("position") or 0),
                        }
                    )
                except (KeyError, ValueError):
                    continue
    except OSError as exc:
        logger.warning("daily series read failed: %s", exc)
        return []
    return rows[-90:]


# ── crawler ─────────────────────────────────────────────────────────────


def _crawler_payload() -> dict[str, Any]:
    adapter = CrawlerCSVAdapter()
    try:
        summary = adapter.summary()
    except Exception as exc:  # pragma: no cover
        logger.warning("crawler summary failed: %s", exc)
        return {"available": False, "error": str(exc)}
    return {
        "available": True,
        "totals": {
            "pages": summary.total_pages,
            "ok": summary.ok_pages,
            "errors": summary.error_pages,
            "redirects": summary.redirect_pages,
            "404": summary.error_404_count,
            "5xx": summary.error_5xx_count,
            "orphan": summary.orphan_url_count,
            "thin_content": summary.thin_content_count,
        },
        "median_response_ms": summary.median_response_ms,
        "status_breakdown": summary.status_breakdown,
    }
