"""Crawler audit engine.

Reads ``crawl_results.csv`` (and friends) and applies a typed catalogue of
detectors that classify each URL with zero or more issues. Output feeds:

  * The Health Score KPI (``services/health_score.py``).
  * The ``/api/v1/crawler/issues`` endpoint (the Issues triage inbox).
  * The Excel "Issues Catalog" sheet.
  * Chat tools ``get_health_score`` and ``get_issues_summary``.

Detectors are pure functions over the existing CSV rows — no new schema
required for Phase 1. Later phases (4) will add ~120 more detectors over
new fields (hreflang, security headers, schema validation, etc.).
"""
from __future__ import annotations

from .catalog import ALL_ISSUES, CATEGORIES, ISSUES_BY_SLUG, SEVERITY_ORDER, IssueDef
from .runner import AuditResult, IssueOccurrence, run_all

__all__ = [
    "ALL_ISSUES",
    "CATEGORIES",
    "ISSUES_BY_SLUG",
    "SEVERITY_ORDER",
    "IssueDef",
    "AuditResult",
    "IssueOccurrence",
    "run_all",
]
