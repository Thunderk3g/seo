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

from dataclasses import dataclass, field

from ..audits import run_all
from ..audits.runner import AuditResult


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
