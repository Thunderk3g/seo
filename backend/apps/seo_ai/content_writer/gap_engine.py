"""Multi-dimensional gap computation: our page vs SERP competitors.

For each dimension we produce both a per-competitor delta and a
"competitor median" so the writer prompt can be told "you are short
by ~1200 words against the median ranking page" instead of being given
five raw numbers to reason over.

Dimensions
----------
* ``content_length``     — word count delta vs competitor median.
* ``content_size``       — body byte size delta (proxy for HTML depth).
* ``heading_breadth``    — H2 count delta (topical coverage breadth).
* ``heading_depth``      — H3+ count delta (sub-topic depth).
* ``internal_links``     — link-density delta + unique-target delta.
* ``external_links``     — unique-domain delta (citation breadth).
* ``images``             — image count + alt coverage delta.
* ``videos``             — video count delta.
* ``schema``             — set-difference of trusted JSON-LD types.
* ``faq``                — FAQ question-count delta.
* ``cta``                — CTA count delta.
* ``section_coverage``   — for each competitor section we don't cover,
                           emit a row with the competitor name + section
                           title. Source of truth for "topics they cover
                           that we don't".

Each dimension gets a ``priority`` 0..3:
  3 = critical (close immediately for parity)
  2 = high
  1 = medium
  0 = informational
Used by the writer prompt to weight rewrite focus.
"""
from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("seo.ai.content_writer.gap_engine")


# ── dataclasses ─────────────────────────────────────────────────────


@dataclass
class DimensionGap:
    dimension: str
    our_value: float
    competitor_median: float
    competitor_max: float
    delta_vs_median: float
    priority: int                       # 3 high → 0 informational
    headline: str                       # 1-line writer-facing summary
    per_competitor: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SectionGap:
    competitor_domain: str
    competitor_url: str
    section_title: str
    summary: str
    heading_path: list[str] = field(default_factory=list)
    priority: int = 2


@dataclass
class RevampGap:
    our_url: str
    competitor_count: int
    dimensions: list[DimensionGap] = field(default_factory=list)
    section_gaps: list[SectionGap] = field(default_factory=list)
    competitor_summary: list[dict[str, Any]] = field(default_factory=list)
    # Top-line summary the writer prompt and the UI both consume.
    top_priority_actions: list[str] = field(default_factory=list)


# ── helpers ─────────────────────────────────────────────────────────


def _median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _max(values: list[float]) -> float:
    return float(max(values)) if values else 0.0


def _norm_title(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _section_titles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract section dicts from a section_clusterer payload.

    ``payload`` shape (from ``page_topic_sections._to_dict``):
        {"sections": [{"title": "...", "summary": "...", "headings": [...]}]}
    """
    out: list[dict[str, Any]] = []
    for s in payload.get("sections") or []:
        if not isinstance(s, dict):
            continue
        title = (s.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "summary": (s.get("summary") or "")[:300],
            "headings": [
                (h.get("text") or "").strip()
                for h in (s.get("headings") or [])
                if isinstance(h, dict) and (h.get("text") or "").strip()
            ][:8],
        })
    return out


def _dim(
    *,
    dimension: str,
    our_value: float,
    competitor_values: list[tuple[str, float]],
    headline_template: str,
    priority_thresholds: tuple[float, float, float],
) -> DimensionGap:
    """Compute one dimension. ``competitor_values`` is [(label, value), ...].

    ``priority_thresholds`` is ``(p1, p2, p3)`` — if abs(delta_vs_median)
    >= p3 → priority 3, >= p2 → priority 2, >= p1 → priority 1, else 0.
    """
    vals = [v for _l, v in competitor_values]
    median = _median(vals)
    delta = round(median - our_value, 2)
    abs_delta = abs(delta)
    if abs_delta >= priority_thresholds[2]:
        priority = 3
    elif abs_delta >= priority_thresholds[1]:
        priority = 2
    elif abs_delta >= priority_thresholds[0]:
        priority = 1
    else:
        priority = 0
    headline = headline_template.format(
        our=our_value, median=round(median, 2), delta=delta
    )
    return DimensionGap(
        dimension=dimension,
        our_value=float(our_value),
        competitor_median=round(median, 2),
        competitor_max=_max(vals),
        delta_vs_median=delta,
        priority=priority,
        headline=headline,
        per_competitor=[
            {"competitor": label, "value": float(value)}
            for label, value in competitor_values
        ],
    )


# ── public entry ────────────────────────────────────────────────────


def compute_revamp_gap(
    *,
    our_analysis,                      # PageAnalysis
    our_sections: dict[str, Any],     # section_clusterer payload
    competitor_analyses: list[tuple[str, Any]],   # [(domain, PageAnalysis)]
    competitor_sections: dict[str, dict[str, Any]],  # {url: section_payload}
) -> RevampGap:
    """Compute every gap dimension and section-coverage list.

    ``competitor_analyses`` ties each PageAnalysis to its source domain
    (so per-competitor rows carry a human label, not just a URL).
    ``competitor_sections`` is keyed by competitor URL — section coverage
    is matched URL→analysis.url to keep the wiring obvious.
    """
    out = RevampGap(
        our_url=our_analysis.url,
        competitor_count=len(competitor_analyses),
    )

    if not competitor_analyses:
        out.top_priority_actions.append(
            "no SERP competitors discovered — writer will polish our page in isolation"
        )
        return out

    def col(extractor) -> list[tuple[str, float]]:
        rows: list[tuple[str, float]] = []
        for label, a in competitor_analyses:
            try:
                rows.append((label, float(extractor(a))))
            except (TypeError, ValueError):
                continue
        return rows

    out.dimensions.append(_dim(
        dimension="content_length_words",
        our_value=float(our_analysis.word_count),
        competitor_values=col(lambda a: a.word_count),
        headline_template=(
            "Our {our:.0f} words vs competitor median {median:.0f} "
            "(short by {delta:.0f})."
        ),
        priority_thresholds=(200, 500, 1000),
    ))

    out.dimensions.append(_dim(
        dimension="content_size_kb",
        our_value=round(our_analysis.content_size_bytes / 1024, 1),
        competitor_values=col(lambda a: a.content_size_bytes / 1024),
        headline_template=(
            "HTML body {our:.1f}KB vs competitor median {median:.1f}KB "
            "(delta {delta:.1f}KB)."
        ),
        priority_thresholds=(20, 50, 100),
    ))

    out.dimensions.append(_dim(
        dimension="heading_breadth_h2",
        our_value=float(our_analysis.h2_count),
        competitor_values=col(lambda a: a.h2_count),
        headline_template=(
            "H2 sections {our:.0f} vs median {median:.0f} "
            "(short by {delta:.0f} top-level topics)."
        ),
        priority_thresholds=(2, 4, 6),
    ))

    out.dimensions.append(_dim(
        dimension="heading_depth_h3plus",
        our_value=float(our_analysis.h3_count + our_analysis.h4_plus_count),
        competitor_values=col(lambda a: a.h3_count + a.h4_plus_count),
        headline_template=(
            "Sub-headings {our:.0f} vs median {median:.0f} "
            "(short by {delta:.0f} depth markers)."
        ),
        priority_thresholds=(3, 6, 10),
    ))

    out.dimensions.append(_dim(
        dimension="internal_link_density",
        our_value=our_analysis.internal_link_density_per_1k_words,
        competitor_values=col(lambda a: a.internal_link_density_per_1k_words),
        headline_template=(
            "Internal-link density {our:.1f}/1k words vs median {median:.1f} "
            "(delta {delta:.1f})."
        ),
        priority_thresholds=(2, 5, 10),
    ))

    out.dimensions.append(_dim(
        dimension="internal_unique_targets",
        our_value=float(our_analysis.unique_internal_targets),
        competitor_values=col(lambda a: a.unique_internal_targets),
        headline_template=(
            "Unique internal targets {our:.0f} vs median {median:.0f} "
            "(short by {delta:.0f})."
        ),
        priority_thresholds=(5, 15, 30),
    ))

    out.dimensions.append(_dim(
        dimension="external_unique_domains",
        our_value=float(our_analysis.unique_external_domains),
        competitor_values=col(lambda a: a.unique_external_domains),
        headline_template=(
            "Unique cited external domains {our:.0f} vs median {median:.0f} "
            "(delta {delta:.0f})."
        ),
        priority_thresholds=(2, 4, 8),
    ))

    out.dimensions.append(_dim(
        dimension="images",
        our_value=float(our_analysis.image_count),
        competitor_values=col(lambda a: a.image_count),
        headline_template=(
            "Images {our:.0f} vs median {median:.0f} "
            "(short by {delta:.0f})."
        ),
        priority_thresholds=(3, 6, 12),
    ))

    out.dimensions.append(_dim(
        dimension="image_alt_coverage_pct",
        our_value=float(our_analysis.image_alt_coverage_pct),
        competitor_values=col(lambda a: a.image_alt_coverage_pct),
        headline_template=(
            "Image alt coverage {our:.0f}% vs median {median:.0f}% "
            "(delta {delta:.0f}%)."
        ),
        priority_thresholds=(10, 25, 50),
    ))

    out.dimensions.append(_dim(
        dimension="faq_question_count",
        our_value=float(our_analysis.faq_question_count),
        competitor_values=col(lambda a: a.faq_question_count),
        headline_template=(
            "FAQ entries {our:.0f} vs median {median:.0f} "
            "(short by {delta:.0f})."
        ),
        priority_thresholds=(2, 4, 8),
    ))

    out.dimensions.append(_dim(
        dimension="cta_count",
        our_value=float(our_analysis.cta_count),
        competitor_values=col(lambda a: a.cta_count),
        headline_template=(
            "CTAs {our:.0f} vs median {median:.0f} "
            "(delta {delta:.0f})."
        ),
        priority_thresholds=(1, 3, 5),
    ))

    # Schema gap is set-difference, not numeric.
    our_schema = set(our_analysis.trusted_schema_present or [])
    comp_schema_union: set[str] = set()
    schema_per_comp: list[tuple[str, float]] = []
    for label, a in competitor_analyses:
        comp_schema_union |= set(a.trusted_schema_present or [])
        schema_per_comp.append((label, float(len(a.trusted_schema_present or []))))
    missing_schema = sorted(comp_schema_union - our_schema)
    out.dimensions.append(DimensionGap(
        dimension="trusted_schema_set",
        our_value=float(len(our_schema)),
        competitor_median=_median([v for _l, v in schema_per_comp]),
        competitor_max=_max([v for _l, v in schema_per_comp]),
        delta_vs_median=round(len(comp_schema_union) - len(our_schema), 2),
        priority=3 if "FAQPage" in missing_schema else (
            2 if missing_schema else 0
        ),
        headline=(
            "Missing schema types: " + ", ".join(missing_schema)
            if missing_schema
            else "Schema coverage on par with competitors."
        ),
        per_competitor=[
            {"competitor": label, "value": value}
            for label, value in schema_per_comp
        ],
    ))

    # Section coverage — for each competitor, which of their sections we lack.
    our_section_titles = {
        _norm_title(s["title"]) for s in _section_titles(our_sections)
    }
    section_gaps: list[SectionGap] = []
    for label, a in competitor_analyses:
        comp_url = a.url
        comp_payload = competitor_sections.get(comp_url) or {}
        for s in _section_titles(comp_payload):
            if _norm_title(s["title"]) in our_section_titles:
                continue
            section_gaps.append(SectionGap(
                competitor_domain=label,
                competitor_url=comp_url,
                section_title=s["title"],
                summary=s["summary"],
                heading_path=s["headings"],
                priority=2,
            ))
    # If many competitors cover the same missing section, bump priority.
    title_counts: dict[str, int] = {}
    for sg in section_gaps:
        title_counts[_norm_title(sg.section_title)] = title_counts.get(_norm_title(sg.section_title), 0) + 1
    for sg in section_gaps:
        if title_counts.get(_norm_title(sg.section_title), 0) >= max(2, len(competitor_analyses) // 2):
            sg.priority = 3
    out.section_gaps = section_gaps

    # Per-competitor at-a-glance row.
    out.competitor_summary = [
        {
            "domain": label,
            "url": a.url,
            "title": a.title,
            "word_count": a.word_count,
            "h2_count": a.h2_count,
            "internal_links": a.internal_link_count,
            "images": a.image_count,
            "faq_questions": a.faq_question_count,
            "schema_types": a.trusted_schema_present,
        }
        for label, a in competitor_analyses
    ]

    # Top-priority actions — first 6 priority-3 items.
    actions: list[str] = []
    for d in sorted(out.dimensions, key=lambda d: -d.priority):
        if d.priority < 2:
            break
        actions.append(d.headline)
    for sg in sorted(out.section_gaps, key=lambda s: -s.priority)[:3]:
        actions.append(
            f"Cover '{sg.section_title}' — {sg.competitor_domain} treats this as a top-level topic."
        )
    out.top_priority_actions = actions[:8]

    return out


def to_dict(g: RevampGap) -> dict[str, Any]:
    return {
        "our_url": g.our_url,
        "competitor_count": g.competitor_count,
        "top_priority_actions": list(g.top_priority_actions),
        "dimensions": [d.__dict__ for d in g.dimensions],
        "section_gaps": [s.__dict__ for s in g.section_gaps],
        "competitor_summary": list(g.competitor_summary),
    }
