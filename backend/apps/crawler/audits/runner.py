"""Audit engine runner — applies every detector in :mod:`.catalog` to the
current crawl results and produces a structured outcome.

Pure read-only pass over ``crawl_results.csv`` (via
``storage.repository.read_csv``). Safe to call from a web request — typical
runtime on 10 k rows is well under 500 ms because every detector is a
linear scan and the rows fit comfortably in memory at that scale.

The result powers:

  * ``services/health_score.py`` — Health Score formula uses
    ``urls_with_any_error / total_urls``.
  * ``/api/v1/crawler/issues`` — Issues triage inbox.
  * Excel "Issues Catalog" sheet.
  * Chat tool ``get_issues_summary``.

Future: Phase 3 will switch the data source to the ``crawler_pageresult``
ORM model; ``run_all`` takes ``rows`` as a parameter so the swap is a
one-line change at the call site.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from ..storage import repository as repo
from .catalog import ALL_ISSUES, IssueDef


@dataclass
class IssueOccurrence:
    """All URLs hit by a single issue type."""

    issue: IssueDef
    affected_urls: list[dict] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.affected_urls)

    def as_summary(self) -> dict:
        """Slim dict for the issues-list JSON response. Drops the full URL
        list — only metadata + count. Caller fetches the full list via the
        per-issue drill-in endpoint when the operator opens the issue."""
        return {
            "slug": self.issue.slug,
            "title": self.issue.title,
            "severity": self.issue.severity,
            "category": self.issue.category,
            "why": self.issue.why,
            "how_to_fix": self.issue.how_to_fix,
            "count": self.count,
        }


@dataclass
class AuditResult:
    """Outcome of one full audit run."""

    occurrences: list[IssueOccurrence]
    total_urls: int
    ok_urls: int
    urls_with_any_error: int
    started_at: str = ""
    finished_at: str = ""

    def by_severity(self) -> dict[str, list[IssueOccurrence]]:
        out: dict[str, list[IssueOccurrence]] = {
            "error": [], "warning": [], "notice": [],
        }
        for occ in self.occurrences:
            if occ.count == 0:
                continue
            out[occ.issue.severity].append(occ)
        return out

    def by_category(self) -> dict[str, list[IssueOccurrence]]:
        out: dict[str, list[IssueOccurrence]] = defaultdict(list)
        for occ in self.occurrences:
            if occ.count == 0:
                continue
            out[occ.issue.category].append(occ)
        return dict(out)

    def severity_counts(self) -> dict[str, int]:
        out = {"error": 0, "warning": 0, "notice": 0}
        for occ in self.occurrences:
            out[occ.issue.severity] += occ.count
        return out

    def issue_type_counts(self) -> dict[str, int]:
        """Counts of distinct issue types with at least one occurrence per
        severity. Used in dashboard tiles ("12 error types, 89 warnings…")."""
        out = {"error": 0, "warning": 0, "notice": 0}
        for occ in self.occurrences:
            if occ.count > 0:
                out[occ.issue.severity] += 1
        return out


# ── runner ──────────────────────────────────────────────────────────────
def _load_rows() -> list[dict]:
    """Read all crawl_results rows as dicts. ``repository.read_csv`` returns
    a {headers, rows} payload with rows as lists; we zip into dicts so
    detectors can use ``row.get("title")`` semantics."""
    payload = repo.read_csv("results")
    headers = payload.get("headers") or []
    out: list[dict] = []
    for r in payload.get("rows") or []:
        if not r:
            continue
        # Defensive: pad short rows so dict lookups don't KeyError.
        if len(r) < len(headers):
            r = list(r) + [""] * (len(headers) - len(r))
        out.append(dict(zip(headers, r)))
    return out


def run_all(rows: Iterable[dict] | None = None) -> AuditResult:
    """Run every catalogued detector. ``rows`` is optional — when ``None``
    we read fresh from ``crawl_results.csv``. Passing rows is useful for
    unit tests and for Phase 3's ORM swap."""
    started = datetime.now(timezone.utc).isoformat()
    row_list = list(rows) if rows is not None else _load_rows()
    total = len(row_list)
    ok = sum(1 for r in row_list if (r.get("status_code") or "").strip() == "200")

    occurrences: list[IssueOccurrence] = []
    urls_with_any_error: set[str] = set()

    for issue in ALL_ISSUES:
        try:
            matched = issue.detector(row_list) or []
        except Exception:  # noqa: BLE001 — never let one bad detector break the audit
            matched = []
        # Cap affected_urls list per issue to keep payloads bounded; the
        # full set is recoverable by re-running the detector on demand.
        capped = matched[:1000]
        occurrences.append(IssueOccurrence(issue=issue, affected_urls=capped))
        if issue.severity == "error":
            for r in matched:
                url = (r.get("url") or "").strip()
                if url:
                    urls_with_any_error.add(url)

    finished = datetime.now(timezone.utc).isoformat()
    return AuditResult(
        occurrences=occurrences,
        total_urls=total,
        ok_urls=ok,
        urls_with_any_error=len(urls_with_any_error),
        started_at=started,
        finished_at=finished,
    )
