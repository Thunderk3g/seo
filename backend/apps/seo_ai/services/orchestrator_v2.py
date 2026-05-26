"""Orchestrator V2 — custodian-pyramid synthesis.

The pyramid:

    ┌─────────────────────────────────────────────────────────────┐
    │  OrchestratorV2 — one synchronous call, one report           │
    └────┬────────────┬──────────────────────┬────────────────────┘
         │            │                      │
    OurDataCustodian  TheirDataCustodian(N)  AdobeAgent
    (crawler facts)   (competitor facts +    (traffic facts)
                       ChangeWatcher feed)
         │            │                      │
         └────┬───────┴──────────┬───────────┘
              │                  │
         SiteDiffer        StructureAgent
         (set deltas)      (link-pattern gaps)

Single entrypoint :func:`run_orchestration` returns a flat report dict.
No LLM — pure data synthesis. The (future) Narrator agent takes this
report and writes a paragraph; the dashboard renders it directly; the
ContentWriter consumes the gaps as targets.

Why now: every leaf in the pyramid exists as a pure-function service
(``custodian.py``, ``change_watcher.py``). The orchestrator just calls
them in the right order and stitches the output. Total run time is
~80-150 ms — fast enough to run on every page load of the dashboard.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

from django.conf import settings

from .custodian import (
    DomainSummary,
    compute_site_diff,
    link_pattern_gaps,
    summarise_adobe_traffic,
    summarise_competitor,
    summarise_our_domain,
)

log = logging.getLogger("seo.ai.services.orchestrator_v2")


def run_orchestration(
    *,
    our_domain: str = "bajajlifeinsurance.com",
    include_adobe: bool = True,
    include_structure_gaps: bool = True,
    structure_min_pct: float = 50.0,
) -> dict[str, Any]:
    """One-shot custodian-pyramid run.

    Returns the unified report dict shape::

        {
          "generated_at": <iso>,
          "elapsed_ms": <int>,
          "our": {<DomainSummary>},
          "competitors": [{<DomainSummary>}, ...],
          "diff": {<DiffReport>},
          "structure_gaps": [{...}, ...],
          "adobe": {<AdobeAgent summary>},
          "headline": {  # Operator's "what to do this week" surface
            "total_competitor_changes_7d": <int>,
            "schema_gap_count": <int>,
            "link_kind_gap_count": <int>,
            "structure_gap_count": <int>,
            "cwv_worse_than_competitors": [<domain>, ...],
            "biggest_change_signals": [<event>, ...],
          },
        }

    Skipping flags:
      * ``include_adobe=False`` — when the operator doesn't have
        Adobe credentials configured.
      * ``include_structure_gaps=False`` — when no competitor crawls
        exist yet (the beat job hasn't fired).
    """
    from datetime import datetime, timezone

    t0 = time.monotonic()

    roster = list(getattr(settings, "COMPETITOR", {}).get("roster") or [])
    ours: DomainSummary = summarise_our_domain(domain=our_domain)
    theirs: list[DomainSummary] = [summarise_competitor(d) for d in roster]
    diff = compute_site_diff(ours, theirs)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "our": asdict(ours),
        "competitors": [asdict(t) for t in theirs],
        "diff": asdict(diff),
    }

    if include_adobe:
        try:
            report["adobe"] = summarise_adobe_traffic()
        except Exception as exc:  # noqa: BLE001
            log.warning("AdobeAgent failed: %s", exc)
            report["adobe"] = {"available": False, "error": str(exc)}

    if include_structure_gaps:
        report["structure_gaps"] = _safe_structure_gaps(
            ours, theirs, min_pct=structure_min_pct,
        )
    else:
        report["structure_gaps"] = []

    report["headline"] = _build_headline(ours, theirs, diff, report["structure_gaps"])
    report["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return report


def _safe_structure_gaps(
    ours: DomainSummary,
    theirs: list[DomainSummary],
    *,
    min_pct: float,
) -> list[dict[str, Any]]:
    """Run StructureAgent without crashing on missing snapshots."""
    if not ours.snapshot_id:
        return []
    comp_snap_ids = [t.snapshot_id for t in theirs if t.snapshot_id]
    if not comp_snap_ids:
        return []
    try:
        return link_pattern_gaps(
            our_snapshot_id=ours.snapshot_id,
            competitor_snapshot_ids=comp_snap_ids,
            min_pct=min_pct,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("StructureAgent failed: %s", exc)
        return []


def _build_headline(
    ours: DomainSummary,
    theirs: list[DomainSummary],
    diff,
    structure_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Operator's "this week's focus" rollup — one number per concern."""
    total_changes_7d = sum(
        sum(t.recent_changes.values()) for t in theirs
    )
    schema_gap_count = sum(
        len(types) for types in diff.schema_only_theirs.values()
    )
    link_kind_gap_count = sum(
        len(kinds) for kinds in diff.link_kind_gaps.values()
    )

    # CWV: we're worse if their median LCP is < ours by > 200ms, OR
    # their PSI > ours by > 5 points.
    cwv_worse: list[str] = []
    for t in theirs:
        if t.median_lcp_ms is not None and ours.median_lcp_ms is not None:
            if t.median_lcp_ms + 200 < ours.median_lcp_ms:
                cwv_worse.append(t.domain)
                continue
        if t.avg_pagespeed_score is not None and ours.avg_pagespeed_score is not None:
            if t.avg_pagespeed_score - 5 > ours.avg_pagespeed_score:
                cwv_worse.append(t.domain)

    # Biggest change signals — most recent + most impactful (content >
    # structure > title > new > removed).
    kind_weight = {"content": 4, "structure": 3, "title": 2, "new": 1, "removed": 1}
    all_changes: list[dict[str, Any]] = []
    for t in theirs:
        for ev in t.recent_change_urls or []:
            all_changes.append({
                "competitor": t.domain,
                "kind": ev.get("kind"),
                "url": ev.get("url"),
                "detected_at": ev.get("detected_at"),
                "_w": kind_weight.get(ev.get("kind"), 0),
            })
    all_changes.sort(key=lambda c: (-c["_w"], c.get("detected_at") or ""))
    biggest = [
        {k: v for k, v in c.items() if k != "_w"}
        for c in all_changes[:10]
    ]

    return {
        "total_competitor_changes_7d": total_changes_7d,
        "schema_gap_count": schema_gap_count,
        "link_kind_gap_count": link_kind_gap_count,
        "structure_gap_count": len(structure_gaps),
        "cwv_worse_than_competitors": cwv_worse,
        "biggest_change_signals": biggest,
    }
