"""Health Score service — Ahrefs-style single KPI for the dashboard.

Formula (Ahrefs-equivalent, transparent):

    Health Score = (URLs without any error-severity issue / total URLs) × 100

Tiering:

    91-100  Excellent
    71-90   Good
    31-70   Fair
    0-30    Weak

The formula uses ONLY error-severity issues (warnings and notices don't drag
the score down) so the number stays understandable: "How many of our crawled
URLs have NO blocking issue?". This matches Ahrefs' published Site Audit
behaviour.

Source of truth for which issues count as errors:
:mod:`apps.crawler.audits.catalog`.

Returns a structured :class:`HealthScore` dataclass that surfaces in:
  * ``/api/v1/crawler/health-score`` REST endpoint
  * Chat tool ``get_health_score``
  * Excel "Health Score" sheet
  * Frontend ``HealthScoreCard.tsx``
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..audits import run_all
from ..audits.runner import AuditResult

log = logging.getLogger("apps.crawler.services.health_score")


@dataclass
class HealthScore:
    """One snapshot of overall site health."""

    score: int                     # 0-100
    tier: str                      # "Excellent" | "Good" | "Fair" | "Weak"
    total_urls: int                # Denominator
    urls_without_error: int        # Numerator
    urls_with_any_error: int       # total - urls_without_error
    severity_counts: dict          # {error: N, warning: N, notice: N}
    issue_type_counts: dict        # {error: distinctTypes, warning: …}
    category_counts: dict          # {category: distinctTypes}
    top_errors: list = field(default_factory=list)
    # ↑ slim summaries of the top-5 error-severity occurrences by count
    formula: str = (
        "Health Score = (URLs without any error-severity issue / total URLs) × 100"
    )
    started_at: str = ""
    finished_at: str = ""

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "tier": self.tier,
            "total_urls": self.total_urls,
            "urls_without_error": self.urls_without_error,
            "urls_with_any_error": self.urls_with_any_error,
            "severity_counts": self.severity_counts,
            "issue_type_counts": self.issue_type_counts,
            "category_counts": self.category_counts,
            "top_errors": self.top_errors,
            "formula": self.formula,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _tier_for(score: int) -> str:
    if score >= 91:
        return "Excellent"
    if score >= 71:
        return "Good"
    if score >= 31:
        return "Fair"
    return "Weak"


def compute(audit: AuditResult | None = None) -> HealthScore:
    """Compute the current Health Score. Accepts a pre-built ``AuditResult``
    for callers that have already run the audit (avoids the double-scan).
    Otherwise runs the audit fresh from ``crawl_results.csv``."""
    a = audit if audit is not None else run_all()

    if a.total_urls == 0:
        return HealthScore(
            score=0,
            tier="Weak",
            total_urls=0,
            urls_without_error=0,
            urls_with_any_error=0,
            severity_counts={"error": 0, "warning": 0, "notice": 0},
            issue_type_counts={"error": 0, "warning": 0, "notice": 0},
            category_counts={},
            top_errors=[],
            started_at=a.started_at,
            finished_at=a.finished_at,
        )

    urls_without_error = max(0, a.total_urls - a.urls_with_any_error)
    score = round(urls_without_error / a.total_urls * 100)

    cat_counts: dict[str, int] = {}
    for occ in a.occurrences:
        if occ.count > 0:
            cat_counts[occ.issue.category] = cat_counts.get(occ.issue.category, 0) + 1

    top_errors = sorted(
        [occ for occ in a.occurrences if occ.issue.severity == "error" and occ.count > 0],
        key=lambda o: o.count,
        reverse=True,
    )[:5]

    return HealthScore(
        score=score,
        tier=_tier_for(score),
        total_urls=a.total_urls,
        urls_without_error=urls_without_error,
        urls_with_any_error=a.urls_with_any_error,
        severity_counts=a.severity_counts(),
        issue_type_counts=a.issue_type_counts(),
        category_counts=cat_counts,
        top_errors=[occ.as_summary() for occ in top_errors],
        started_at=a.started_at,
        finished_at=a.finished_at,
    )


def _pageresult_to_row(p) -> dict:
    """Adapt a CrawlerPageResult ORM row into the dict shape the
    detectors in ``audits/catalog.py`` expect. The detectors were
    originally written against ``crawl_results.csv`` rows, so they read
    string-typed CSV cells (status_code "200", from_sitemap "1"/"0",
    indexed_status "indexed"/"unknown", pagespeed_score "82"). Keep
    that contract here so the catalog code stays untouched."""
    return {
        "url": p.url,
        "status_code": (p.status_code or "").strip(),
        "title": p.title or "",
        "word_count": p.word_count or 0,
        "response_time_ms": p.response_time_ms or 0,
        "content_type": p.content_type or "",
        "subdomain": p.subdomain or "",
        "page_type": p.page_type or "",
        "category_key": p.category_key or "",
        "from_sitemap": "1" if p.from_sitemap else "0",
        "indexed_status": p.indexed_status or "unknown",
        "pagespeed_score": (
            str(p.pagespeed_score) if p.pagespeed_score is not None else ""
        ),
        "lcp_ms": str(p.lcp_ms) if p.lcp_ms is not None else "",
        "cls": str(p.cls) if p.cls is not None else "",
        "inp_ms": str(p.inp_ms) if p.inp_ms is not None else "",
    }


def compute_for_snapshot(snapshot_id: str) -> HealthScore | None:
    """Health Score scoped to a single CrawlSnapshot.

    Used by the competitor-side pipeline so each competitor crawl
    finalises with its own Health Score (and per-competitor trends
    work). Returns None if the snapshot has no rows or if the ORM is
    unavailable — the caller treats that as "score unknown".
    """
    try:
        from ..models import CrawlerPageResult
        rows_iter = CrawlerPageResult.objects.filter(
            snapshot_id=snapshot_id,
        ).iterator(chunk_size=500)
        rows = [_pageresult_to_row(p) for p in rows_iter]
    except Exception as exc:  # noqa: BLE001
        log.info(
            "compute_for_snapshot %s: ORM read failed (%s)",
            snapshot_id, exc,
        )
        return None

    if not rows:
        return None
    audit = run_all(rows=rows)
    return compute(audit=audit)
