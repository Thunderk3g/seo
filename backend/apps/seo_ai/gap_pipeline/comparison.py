"""Stage 6: comparison / gap diff.

Reads our ``GapDeepCrawl`` row + every competitor's ``GapDeepCrawl``
row for this run, and emits one ``GapComparison`` per dimension where
we lag the competitor median.

Dimensions surfaced (each ships its own severity + headline):

    content_depth         — avg / median word count
    schema_coverage       — % of pages with JSON-LD schema
    h1_coverage           — % of pages with at least one <h1>
    response_time         — median response time (ms)
    page_type_coverage    — pricing / comparison / calculator / faq counts
    machine_readable      — llms.txt + pricing.md presence
    ai_citability         — heuristic citability score
    llm_visibility        — % of LLM answers that mentioned our brand
    serp_visibility       — % of queries where we appeared top-10

Severity rules — applied per dimension based on the magnitude of the
gap. Defaults are deliberately conservative; tune by environment by
overriding ``SEO_AI.gap_pipeline_thresholds`` if needed.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import Any

from django.db.models import Count, Q

from ..models import (
    GapComparison,
    GapDeepCrawl,
    GapLLMResult,
    GapPipelineRun,
    GapSerpResult,
)

logger = logging.getLogger("seo.ai.gap_pipeline.comparison")


_SEVERITY_PRIORITY = {"critical": 95, "warning": 70, "notice": 45}


@dataclass
class _Row:
    """Helper for one gap candidate before persistence."""

    dimension: str
    severity: str
    headline: str
    our_value: dict[str, Any]
    competitor_median: dict[str, Any]
    delta: dict[str, Any]
    evidence: dict[str, Any]

    def to_priority(self) -> int:
        return _SEVERITY_PRIORITY.get(self.severity, 40)


def _median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _pct_delta(ours: float, theirs: float) -> float:
    """Signed percentage gap (negative when we're behind). Uses
    theirs as denominator so a missing-from-us value reads as -100%.
    """
    if theirs == 0:
        return 0.0
    return round((ours - theirs) / theirs * 100, 1)


def _severity_from_pct_gap(pct: float, *, critical_at: float, warning_at: float) -> str:
    """Map a negative percentage to a severity bucket."""
    if pct <= critical_at:
        return "critical"
    if pct <= warning_at:
        return "warning"
    return "notice"


def _content_depth_row(us: dict, comps: list[dict]) -> _Row | None:
    our_avg = float(us.get("avg_word_count") or 0)
    their_vals = [float(p.get("avg_word_count") or 0) for p in comps if p]
    if not their_vals or our_avg == 0:
        return None
    their_med = _median(their_vals)
    if their_med <= 0:
        return None
    pct = _pct_delta(our_avg, their_med)
    if pct >= -10:
        return None
    severity = _severity_from_pct_gap(pct, critical_at=-50, warning_at=-25)
    return _Row(
        dimension="content_depth",
        severity=severity,
        headline=(
            f"Average page is {abs(pct):.0f}% shorter than the rival median "
            f"({int(our_avg)} vs {int(their_med)} words)"
        ),
        our_value={"avg_word_count": int(our_avg)},
        competitor_median={"avg_word_count": int(their_med)},
        delta={"pct": pct, "abs": int(our_avg - their_med)},
        evidence={
            "rival_avg_word_counts": [int(v) for v in sorted(their_vals)[:10]]
        },
    )


def _schema_coverage_row(us: dict, comps: list[dict]) -> _Row | None:
    our = float(us.get("schema_pct") or 0)
    theirs = [float(p.get("schema_pct") or 0) for p in comps if p]
    if not theirs:
        return None
    their_med = _median(theirs)
    if their_med <= 0 and our <= 0:
        return None
    diff = our - their_med
    if diff >= -10:
        return None
    severity = "critical" if diff <= -40 else "warning" if diff <= -20 else "notice"
    # Schema-type set comparison — which types do they use that we don't?
    our_types = set(us.get("schema_types") or [])
    rival_types: set[str] = set()
    for p in comps:
        for t in (p or {}).get("schema_types") or []:
            rival_types.add(t)
    missing_types = sorted(rival_types - our_types)[:10]
    return _Row(
        dimension="schema_coverage",
        severity=severity,
        headline=(
            f"Schema coverage is {diff:.0f} pp behind the rival median "
            f"({our:.0f}% vs {their_med:.0f}%)"
        ),
        our_value={"schema_pct": our, "schema_types": sorted(our_types)[:10]},
        competitor_median={"schema_pct": their_med},
        delta={"pp": diff, "missing_schema_types": missing_types},
        evidence={"rival_schema_types_total": sorted(rival_types)[:20]},
    )


def _h1_coverage_row(us: dict, comps: list[dict]) -> _Row | None:
    our = float(us.get("h1_pct") or 0)
    theirs = [float(p.get("h1_pct") or 0) for p in comps if p]
    if not theirs:
        return None
    their_med = _median(theirs)
    diff = our - their_med
    if diff >= -10:
        return None
    severity = "warning" if diff <= -25 else "notice"
    return _Row(
        dimension="h1_coverage",
        severity=severity,
        headline=(
            f"H1 coverage is {diff:.0f} pp behind the rival median "
            f"({our:.0f}% vs {their_med:.0f}%)"
        ),
        our_value={"h1_pct": our},
        competitor_median={"h1_pct": their_med},
        delta={"pp": diff},
        evidence={"rival_h1_pcts": [round(t, 1) for t in sorted(theirs)[:10]]},
    )


def _response_time_row(us: dict, comps: list[dict]) -> _Row | None:
    our = float(us.get("avg_response_ms") or 0)
    theirs = [float(p.get("avg_response_ms") or 0) for p in comps if p]
    theirs = [v for v in theirs if v > 0]
    if not theirs or our == 0:
        return None
    their_med = _median(theirs)
    if our <= their_med:
        return None  # We're fast — no gap.
    delta = our - their_med
    severity = (
        "critical"
        if delta >= 2000 or our >= 4000
        else "warning" if delta >= 800 else "notice"
    )
    return _Row(
        dimension="response_time",
        severity=severity,
        headline=(
            f"Average page response is {int(delta)} ms slower than the "
            f"rival median ({int(our)} ms vs {int(their_med)} ms)"
        ),
        our_value={"avg_response_ms": int(our)},
        competitor_median={"avg_response_ms": int(their_med)},
        delta={"abs_ms": int(delta)},
        evidence={"rival_response_ms": [int(v) for v in sorted(theirs)[:10]]},
    )


def _page_type_row(us: dict, comps: list[dict]) -> _Row | None:
    """Flag page types they have at scale but we have ≤1 of."""
    our_pt = us.get("page_types") or {}
    rival_pt_med: dict[str, float] = {}
    for kind in ("pricing", "comparison", "calculator", "faq", "blog"):
        vals = [float((p or {}).get("page_types", {}).get(kind, 0)) for p in comps]
        if vals:
            rival_pt_med[kind] = _median(vals)
    gaps = {
        k: v
        for k, v in rival_pt_med.items()
        if v >= 2 and int(our_pt.get(k, 0)) <= 1
    }
    if not gaps:
        return None
    worst = sorted(gaps.items(), key=lambda x: x[1], reverse=True)
    severity = "warning" if len(gaps) >= 2 else "notice"
    return _Row(
        dimension="page_type_coverage",
        severity=severity,
        headline=(
            f"{len(gaps)} page type(s) rivals cover at scale but we don't: "
            + ", ".join(f"{k} (median {int(v)})" for k, v in worst[:3])
        ),
        our_value={"page_types": {k: int(our_pt.get(k, 0)) for k in rival_pt_med}},
        competitor_median={"page_types": {k: int(v) for k, v in rival_pt_med.items()}},
        delta={"missing_at_scale": list(gaps.keys())},
        evidence={"per_kind_median": rival_pt_med},
    )


def _machine_readable_row(us: dict, comps: list[dict]) -> _Row | None:
    rivals_with_llms = sum(1 for p in comps if (p or {}).get("has_llms_txt"))
    rivals_with_pricing_md = sum(1 for p in comps if (p or {}).get("has_pricing_md"))
    we_have_llms = bool(us.get("has_llms_txt"))
    we_have_pricing_md = bool(us.get("has_pricing_md"))
    gaps = []
    if rivals_with_llms >= 2 and not we_have_llms:
        gaps.append(f"llms.txt ({rivals_with_llms} rivals)")
    if rivals_with_pricing_md >= 2 and not we_have_pricing_md:
        gaps.append(f"pricing.md ({rivals_with_pricing_md} rivals)")
    if not gaps:
        return None
    return _Row(
        dimension="machine_readable",
        severity="notice",
        headline="Missing machine-readable signals: " + ", ".join(gaps),
        our_value={
            "has_llms_txt": we_have_llms,
            "has_pricing_md": we_have_pricing_md,
        },
        competitor_median={
            "rivals_with_llms_txt": rivals_with_llms,
            "rivals_with_pricing_md": rivals_with_pricing_md,
        },
        delta={"missing": gaps},
        evidence={},
    )


def _ai_citability_row(us: dict, comps: list[dict]) -> _Row | None:
    our = float(us.get("ai_citability_score") or 0)
    theirs = [float(p.get("ai_citability_score") or 0) for p in comps if p]
    if not theirs or our == 0:
        return None
    their_med = _median(theirs)
    diff = our - their_med
    if diff >= -5:
        return None
    severity = "critical" if diff <= -25 else "warning" if diff <= -15 else "notice"
    return _Row(
        dimension="ai_citability",
        severity=severity,
        headline=(
            f"AI citability score is {abs(diff):.0f} pts behind the rival "
            f"median ({our:.0f} vs {their_med:.0f})"
        ),
        our_value={"ai_citability_score": our},
        competitor_median={"ai_citability_score": their_med},
        delta={"pts": diff},
        evidence={"rival_scores": [round(t, 1) for t in sorted(theirs)[:10]]},
    )


def _llm_visibility_row(run: GapPipelineRun) -> _Row | None:
    """Aggregate LLM mention rate from the run's GapLLMResult rows."""
    rows = GapLLMResult.objects.filter(run=run, error="").aggregate(
        total=Count("id"),
        mentioned=Count("id", filter=Q(mentions_our_brand=True)),
    )
    total = rows["total"] or 0
    mentioned = rows["mentioned"] or 0
    if total == 0:
        return None
    rate = mentioned / total
    if rate >= 0.50:
        return None
    severity = (
        "critical" if rate < 0.15 else "warning" if rate < 0.30 else "notice"
    )
    return _Row(
        dimension="llm_visibility",
        severity=severity,
        headline=(
            f"Brand mentioned in {mentioned}/{total} LLM answers "
            f"({rate * 100:.0f}%)"
        ),
        our_value={"mentioned": mentioned, "total": total, "rate": round(rate, 3)},
        competitor_median={},
        delta={"rate": round(rate, 3)},
        evidence={},
    )


def _serp_visibility_row(run: GapPipelineRun) -> _Row | None:
    rows = GapSerpResult.objects.filter(run=run, error="")
    total = rows.count()
    if total == 0:
        return None
    in_top10 = rows.filter(our_position__isnull=False).count()
    rate = in_top10 / total if total else 0.0
    if rate >= 0.60:
        return None
    severity = (
        "critical" if rate < 0.20 else "warning" if rate < 0.40 else "notice"
    )
    return _Row(
        dimension="serp_visibility",
        severity=severity,
        headline=(
            f"In SERP top-10 for {in_top10}/{total} query-engine cells "
            f"({rate * 100:.0f}%)"
        ),
        our_value={"in_top10": in_top10, "total": total, "rate": round(rate, 3)},
        competitor_median={},
        delta={"rate": round(rate, 3)},
        evidence={},
    )


_PROFILE_GAP_BUILDERS = [
    _content_depth_row,
    _schema_coverage_row,
    _h1_coverage_row,
    _response_time_row,
    _page_type_row,
    _machine_readable_row,
    _ai_citability_row,
]


def execute(*, run: GapPipelineRun) -> dict[str, Any]:
    """Run stage 6. Persists ``GapComparison`` rows. Idempotent — wipes
    prior comparison rows for the run so re-runs of this stage produce
    a clean diff.
    """
    GapComparison.objects.filter(run=run).delete()

    our_crawl = GapDeepCrawl.objects.filter(run=run, is_us=True).first()
    rival_crawls = list(GapDeepCrawl.objects.filter(run=run, is_us=False))
    if our_crawl is None or not rival_crawls:
        logger.info(
            "comparison: no crawl data (us=%s, rivals=%s) — stage empty",
            our_crawl is not None,
            len(rival_crawls),
        )
        return {"status": "empty", "reason": "no crawl data"}

    our_profile = our_crawl.profile or {}
    rival_profiles = [c.profile or {} for c in rival_crawls if c.profile]

    rows: list[_Row] = []
    for builder in _PROFILE_GAP_BUILDERS:
        try:
            row = builder(our_profile, rival_profiles)
        except Exception as exc:  # noqa: BLE001 - one bad builder shouldn't kill stage
            logger.warning(
                "comparison: builder %s crashed: %s", builder.__name__, exc
            )
            continue
        if row is not None:
            rows.append(row)

    for fn in (_llm_visibility_row, _serp_visibility_row):
        try:
            row = fn(run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("comparison: builder %s crashed: %s", fn.__name__, exc)
            continue
        if row is not None:
            rows.append(row)

    # Persist.
    for r in rows:
        GapComparison.objects.create(
            run=run,
            dimension=r.dimension,
            severity=r.severity,
            headline=r.headline[:255],
            our_value=r.our_value,
            competitor_median=r.competitor_median,
            delta=r.delta,
            evidence=r.evidence,
            priority=r.to_priority(),
        )

    return {
        "status": "ok" if rows else "no_gaps_found",
        "gap_count": len(rows),
        "rival_count": len(rival_crawls),
    }
