"""Deterministic scoring math.

Industry-grade choice: the LLM never produces the user-facing score.
It produces narrative; the number comes from this module. That makes
score deltas auditable — a drop from 78 → 73 is always attributable
to a concrete change in one of the inputs, not to model temperature.

Weights and formulas mirror ``docs/SEO_AI_Agents_Plan.md`` §10. They
are versioned in the run row's ``weights`` JSON so historical scores
remain comparable to the formula in force at the time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Weight matrix from the plan. Keep summing to 1.0 — assertions in
# ``compute_overall`` will catch a misedit.
DEFAULT_WEIGHTS: dict[str, float] = {
    "technical": 0.25,
    "content": 0.25,
    "backlinks": 0.15,
    "core_web_vitals": 0.10,
    "internal_linking": 0.10,
    "serp_ctr": 0.05,
    "structured_data": 0.05,
    "indexability": 0.05,
}


@dataclass
class SubScores:
    technical: float
    core_web_vitals: float
    internal_linking: float
    structured_data: float
    indexability: float
    serp_ctr: float
    content: float
    backlinks: float

    def as_dict(self) -> dict[str, float]:
        return {
            "technical": self.technical,
            "core_web_vitals": self.core_web_vitals,
            "internal_linking": self.internal_linking,
            "structured_data": self.structured_data,
            "indexability": self.indexability,
            "serp_ctr": self.serp_ctr,
            "content": self.content,
            "backlinks": self.backlinks,
        }


# ── per-factor formulas ──────────────────────────────────────────────────


def technical_score(crawler_summary: dict[str, Any]) -> float:
    """Composite of error rate, thin content, missing titles.

    Starts at 100 and subtracts a penalty per problem class scaled by
    its prevalence. Capped to 0–100.
    """
    total = max(int(crawler_summary.get("total_pages") or 0), 1)
    errors = int(crawler_summary.get("error_pages") or 0)
    e404 = int(crawler_summary.get("error_404_count") or 0)
    e5xx = int(crawler_summary.get("error_5xx_count") or 0)
    title_missing = int(crawler_summary.get("title_missing_count") or 0)
    thin = int(crawler_summary.get("thin_content_count") or 0)

    error_rate = errors / total
    p404 = e404 / total
    p5xx = e5xx / total
    p_title = title_missing / total
    p_thin = thin / total

    penalty = (
        error_rate * 40
        + p404 * 25
        + p5xx * 35
        + p_title * 20
        + p_thin * 15
    )
    return _clip(100 - penalty * 100)


def internal_linking_score(crawler_summary: dict[str, Any]) -> float:
    """Penalty proportional to orphan share."""
    total = max(int(crawler_summary.get("total_pages") or 0), 1)
    orphan = int(crawler_summary.get("orphan_url_count") or 0)
    share = orphan / total
    return _clip(100 - share * 200)  # 1% orphans → -2 pts


def indexability_score(crawler_summary: dict[str, Any]) -> float:
    """Share of pages returning 200 vs. crawled total."""
    total = max(int(crawler_summary.get("total_pages") or 0), 1)
    ok = int(crawler_summary.get("ok_pages") or 0)
    return _clip(ok / total * 100)


def cwv_score(crawler_summary: dict[str, Any]) -> float:
    """Proxy: % of pages with response_time_ms ≤ 800 ms.

    True CWV requires PageSpeed Insights / CrUX — this is the live-crawl
    stand-in. Replaced in Phase 3 by the real LCP/CLS/INP rollup.
    """
    total = max(int(crawler_summary.get("total_pages") or 0), 1)
    median = float(crawler_summary.get("median_response_ms") or 0)
    fat = int(crawler_summary.get("fat_response_count") or 0)
    # Bonus for being fast in the median; penalty for the long tail.
    speed_bonus = max(0, 1 - median / 1500) * 60
    tail_penalty = (fat / total) * 60
    return _clip(40 + speed_bonus - tail_penalty)


def structured_data_score(aem_summary: dict[str, Any]) -> float:
    """Proxy from AEM: share of pages with a description.

    Replaced in Phase 2 by JSON-LD validity from the crawler parser.
    """
    total = max(int(aem_summary.get("total_pages") or 0), 1)
    with_desc = int(aem_summary.get("pages_with_description") or 0)
    return _clip(with_desc / total * 100)


def serp_ctr_score(gsc_summary: dict[str, Any]) -> float:
    """Site CTR vs. industry curve.

    Approximation: compare actual average CTR to the expected CTR at
    the site's weighted average position. 100 = on the curve, drops as
    actual CTR underperforms expectation.
    """
    avg_pos = float(gsc_summary.get("avg_position") or 0)
    avg_ctr = float(gsc_summary.get("avg_ctr") or 0)
    if avg_pos <= 0:
        return 50.0  # no signal → neutral
    expected = _expected_ctr_for_position(avg_pos)
    if expected <= 0:
        return 50.0
    ratio = avg_ctr / expected
    return _clip(min(100.0, ratio * 100))


def content_score(_aem_summary: dict[str, Any], _crawler_summary: dict[str, Any]) -> float:
    """Phase 0 placeholder.

    Real content scoring needs the Content Analyzer (Phase 2) and
    semantic embeddings. For now we approximate from metadata hygiene
    and word-count distribution so the overall score is not a stub.
    """
    avg_wc = float(_crawler_summary.get("avg_word_count") or 0)
    # Sweet spot 800–2500 words for editorial; landing pages excluded
    # from this heuristic in v2.
    if avg_wc <= 0:
        wc_component = 30
    elif avg_wc < 300:
        wc_component = 30
    elif avg_wc < 800:
        wc_component = 50
    elif avg_wc < 2500:
        wc_component = 80
    else:
        wc_component = 70  # over-long is its own problem

    aem_total = max(int(_aem_summary.get("total_pages") or 0), 1)
    desc_share = int(_aem_summary.get("pages_with_description") or 0) / aem_total
    title_problems = (
        int(_aem_summary.get("pages_with_short_title") or 0)
        + int(_aem_summary.get("pages_with_long_title") or 0)
    ) / aem_total
    meta_component = (desc_share * 80) + (1 - title_problems) * 20
    return _clip(wc_component * 0.6 + meta_component * 0.4)


def backlinks_score(semrush_overview: dict[str, Any] | None) -> float:
    """Quick proxy from SEMrush ``rank`` until we wire backlink reports.

    SEMrush rank: smaller = better. We map rank deciles in the IN DB to
    a 0–100 score; ``rank ≤ 5 000`` → 90+, ``rank ≤ 50 000`` → 70+,
    etc. Real backlink quality needs the dedicated SEMrush ``backlinks``
    endpoint and a toxic-link filter (Phase 2).
    """
    if not semrush_overview:
        return 50.0
    rank = int(semrush_overview.get("rank") or 0)
    if rank <= 0:
        return 50.0
    if rank <= 5_000:
        return 92.0
    if rank <= 20_000:
        return 80.0
    if rank <= 100_000:
        return 65.0
    if rank <= 500_000:
        return 50.0
    return 35.0


# ── overall ──────────────────────────────────────────────────────────────


def compute_sub_scores(
    *,
    crawler_summary: dict[str, Any],
    aem_summary: dict[str, Any],
    gsc_summary: dict[str, Any],
    semrush_overview: dict[str, Any] | None,
) -> SubScores:
    return SubScores(
        technical=technical_score(crawler_summary),
        core_web_vitals=cwv_score(crawler_summary),
        internal_linking=internal_linking_score(crawler_summary),
        structured_data=structured_data_score(aem_summary),
        indexability=indexability_score(crawler_summary),
        serp_ctr=serp_ctr_score(gsc_summary),
        content=content_score(aem_summary, crawler_summary),
        backlinks=backlinks_score(semrush_overview),
    )


def compute_overall(
    sub: SubScores,
    weights: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    w = dict(weights or DEFAULT_WEIGHTS)
    total_w = sum(w.values())
    assert abs(total_w - 1.0) < 1e-6, f"weights must sum to 1.0, got {total_w}"
    d = sub.as_dict()
    score = sum(d[k] * w[k] for k in w)
    return round(score, 2), w


# ── utility ──────────────────────────────────────────────────────────────


def _clip(x: float) -> float:
    return float(max(0.0, min(100.0, x)))


# duplicated from gsc_csv to avoid the agent depending on adapter internals
_CTR_CURVE = [
    0.0, 0.395, 0.184, 0.108, 0.073, 0.053, 0.040, 0.032,
    0.026, 0.022, 0.019, 0.016, 0.014, 0.012, 0.010, 0.008,
]


def _expected_ctr_for_position(position: float) -> float:
    if position <= 1:
        return _CTR_CURVE[1]
    if position >= 15:
        return _CTR_CURVE[15]
    low = int(position)
    frac = position - low
    return _CTR_CURVE[low] * (1 - frac) + _CTR_CURVE[low + 1] * frac
