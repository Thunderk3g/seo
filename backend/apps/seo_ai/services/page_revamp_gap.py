"""Compute the structured gap between our page and N competitor pages.

The Content Writer revamp orchestrator clusters every page's sections
via the LLM (``page_topic_sections``) BEFORE asking the rewrite agent
to generate content. This module sits in the middle:

  our_page sections + [competitor_page sections per brand]
                       │
                       ▼
                  compute_gap()
                       │
                       ▼
   {sections_we_miss, sections_unique_to_us, size_diff,
    link_inventory_diff, footer_diff, topic_overlap}

The rewrite agent receives this object as primary structured input so
its output explicitly closes the identified gaps — rather than the
agent inferring gaps from raw evidence.

The UI also renders this object as the "Gap analysis" panel above the
rewrite, so the operator sees what the agent was told to fix.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("seo.ai.page_revamp_gap")


# ── dataclasses ──────────────────────────────────────────────────────


@dataclass
class SectionMissByUs:
    """A section that one or more competitors have, but we don't."""

    name: str                 # canonical name (lowercased, normalised)
    label: str                # operator-facing — first-seen casing
    brands_with_it: list[str] = field(default_factory=list)
    topics_aggregate: list[str] = field(default_factory=list)
    sample_headings: list[str] = field(default_factory=list)


@dataclass
class SectionUniqueToUs:
    name: str
    label: str
    sample_headings: list[str] = field(default_factory=list)


@dataclass
class SizeDiff:
    our_word_count: int
    median_their_word_count: int
    deficit: int              # negative if we're shorter
    our_heading_count: int
    median_their_heading_count: int
    our_image_count: int
    median_their_image_count: int


@dataclass
class LinkInventoryDiff:
    """Internal-link breakdown by ``kind`` classification."""

    our_total: int
    median_their_total: int
    our_by_kind: dict[str, int] = field(default_factory=dict)
    median_their_by_kind: dict[str, int] = field(default_factory=dict)
    kinds_we_lack: list[str] = field(default_factory=list)  # they have, we don't


@dataclass
class FooterDiff:
    """Approximate footer comparison from late-position internal links.

    The crawler stamps ``section`` on each link = nearest preceding
    heading text. We treat any link whose section name contains
    "footer" OR which appears after the last H1/H2 in document order
    as footer-ish for the purpose of this comparison.
    """

    our_footer_link_count: int
    median_their_footer_link_count: int


@dataclass
class TopicOverlap:
    overlap_pct: float        # 0..1 — Jaccard between our + their topic vocab
    our_unique_topics: list[str]
    their_aggregate_unique_topics: list[str]


@dataclass
class CompetitorGap:
    sections_we_miss: list[SectionMissByUs] = field(default_factory=list)
    sections_unique_to_us: list[SectionUniqueToUs] = field(default_factory=list)
    size_diff: SizeDiff | None = None
    link_inventory_diff: LinkInventoryDiff | None = None
    footer_diff: FooterDiff | None = None
    topic_overlap: TopicOverlap | None = None
    headline_recommendations: list[str] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────


_NAME_NORM_RE = re.compile(r"[^a-z0-9]+")
_FOOTER_HINTS = (
    "footer", "policy", "policies", "disclaimer", "sitemap",
    "privacy", "terms", "compliance", "irdai", "ombudsman",
    "social", "follow us", "investor relations", "corporate",
)


def _normalise_name(name: str) -> str:
    return _NAME_NORM_RE.sub(" ", (name or "").strip().lower()).strip()


def _topics_from_section(sec: dict) -> list[str]:
    """Pull `topics_covered` if present, else derive from heading_texts."""
    topics = [t for t in (sec.get("topics_covered") or []) if t]
    if topics:
        return [str(t).strip().lower() for t in topics]
    return [
        (h or "").strip().lower()
        for h in (sec.get("heading_texts") or [])
        if h
    ]


def _median(values: list[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) // 2


def _link_kinds_breakdown(links: list[dict]) -> dict[str, int]:
    c: Counter = Counter()
    for l in links or []:
        if not isinstance(l, dict):
            continue
        kind = (l.get("kind") or "other").strip().lower()
        c[kind] += 1
    return dict(c)


def _classify_footer_links(
    internal_links: list[dict],
    headings: list[dict],
) -> int:
    """Count links that look footer-ish.

    Heuristic: a link is footer-ish if its ``section`` text mentions
    any of the footer hint words OR its ``kind`` is 'navigation'.
    Falls back to "links beyond the median heading idx" when section
    metadata is missing.
    """
    if not internal_links:
        return 0
    count = 0
    fallback_threshold = None
    if headings:
        # idx of the last document-order heading — links after this idx
        # are usually footer.
        idxs = [
            int(h.get("idx") or 0)
            for h in headings
            if isinstance(h, dict)
        ]
        if idxs:
            fallback_threshold = max(idxs) - 1  # last heading idx-ish
    for i, l in enumerate(internal_links):
        if not isinstance(l, dict):
            continue
        section = (l.get("section") or "").lower()
        kind = (l.get("kind") or "").lower()
        if (
            any(h in section for h in _FOOTER_HINTS)
            or "footer" in kind
            or kind == "navigation"
        ):
            count += 1
            continue
        # Position fallback only when no section hint available.
        if not section and fallback_threshold is not None and i > fallback_threshold:
            count += 1
    return count


# ── main entry point ─────────────────────────────────────────────────


def compute_gap(
    *,
    our_sections: list[dict],
    our_signals: dict,
    their_sections_by_brand: list[tuple[str, list[dict]]],
    their_signals_by_brand: list[tuple[str, dict]],
) -> CompetitorGap:
    """Compute the structured gap.

    ``our_sections`` / ``their_sections_by_brand`` are the output of
    ``page_topic_sections.build_page_topic_sections`` — each section
    has ``name``, ``heading_texts``, ``internal_links``,
    ``topics_covered``.

    ``our_signals`` / ``their_signals_by_brand`` are the
    ``PageSignals`` dataclasses cast to dicts (or accessed as objects;
    we tolerate both via .get() / getattr() pattern).
    """
    gap = CompetitorGap()
    if not their_sections_by_brand:
        return gap

    # ─ Section-name diff (Jaccard on normalised section names) ─
    our_section_names: dict[str, dict] = {}
    for s in (our_sections or []):
        norm = _normalise_name(s.get("name") or "")
        if norm:
            our_section_names[norm] = s

    competitor_section_index: dict[str, dict[str, Any]] = {}
    for brand, sections in their_sections_by_brand:
        for s in sections or []:
            norm = _normalise_name(s.get("name") or "")
            if not norm:
                continue
            entry = competitor_section_index.setdefault(
                norm,
                {
                    "label": s.get("name") or norm,
                    "brands": set(),
                    "topics": [],
                    "headings": [],
                },
            )
            entry["brands"].add(brand)
            entry["topics"].extend(_topics_from_section(s))
            entry["headings"].extend(
                (s.get("heading_texts") or [])[:3],
            )

    for norm, entry in competitor_section_index.items():
        if norm in our_section_names:
            continue
        # Pick the top-N topics for display.
        top_topics = [t for t, _c in Counter(entry["topics"]).most_common(6)]
        sample_h = list(dict.fromkeys(entry["headings"]))[:5]
        gap.sections_we_miss.append(SectionMissByUs(
            name=norm,
            label=str(entry["label"])[:80],
            brands_with_it=sorted(entry["brands"]),
            topics_aggregate=top_topics,
            sample_headings=sample_h,
        ))
    gap.sections_we_miss.sort(
        key=lambda s: -len(s.brands_with_it),  # most-shared first
    )

    for norm, sec in our_section_names.items():
        if norm in competitor_section_index:
            continue
        gap.sections_unique_to_us.append(SectionUniqueToUs(
            name=norm,
            label=str(sec.get("name") or norm)[:80],
            sample_headings=(sec.get("heading_texts") or [])[:4],
        ))

    # ─ Size diff ────────────────────────────────────────────────
    def _g(o, k, default=0):
        if isinstance(o, dict):
            return o.get(k, default)
        return getattr(o, k, default)

    our_wc = int(_g(our_signals, "word_count") or 0)
    their_wcs = [
        int(_g(s, "word_count") or 0) for _b, s in their_signals_by_brand
    ]
    their_med_wc = _median(their_wcs)
    our_h_count = len(_g(our_signals, "headings") or [])
    their_h_counts = [
        len(_g(s, "headings") or []) for _b, s in their_signals_by_brand
    ]
    their_med_h = _median(their_h_counts)
    our_img_count = len(_g(our_signals, "images") or [])
    their_img_counts = [
        len(_g(s, "images") or []) for _b, s in their_signals_by_brand
    ]
    their_med_img = _median(their_img_counts)
    gap.size_diff = SizeDiff(
        our_word_count=our_wc,
        median_their_word_count=their_med_wc,
        deficit=our_wc - their_med_wc,
        our_heading_count=our_h_count,
        median_their_heading_count=their_med_h,
        our_image_count=our_img_count,
        median_their_image_count=their_med_img,
    )

    # ─ Link inventory diff ──────────────────────────────────────
    our_links = _g(our_signals, "internal_links") or []
    our_kinds = _link_kinds_breakdown(our_links)
    their_kinds_lists: dict[str, list[int]] = {}
    their_totals: list[int] = []
    for _b, s in their_signals_by_brand:
        links = _g(s, "internal_links") or []
        kinds = _link_kinds_breakdown(links)
        their_totals.append(len(links))
        for k, n in kinds.items():
            their_kinds_lists.setdefault(k, []).append(n)
    median_their_by_kind = {
        k: _median(v) for k, v in their_kinds_lists.items()
    }
    kinds_we_lack = sorted([
        k for k, n in median_their_by_kind.items()
        if n > 0 and our_kinds.get(k, 0) == 0
    ])
    gap.link_inventory_diff = LinkInventoryDiff(
        our_total=len(our_links),
        median_their_total=_median(their_totals),
        our_by_kind=our_kinds,
        median_their_by_kind=median_their_by_kind,
        kinds_we_lack=kinds_we_lack,
    )

    # ─ Footer diff ──────────────────────────────────────────────
    our_footer = _classify_footer_links(
        our_links, _g(our_signals, "headings") or [],
    )
    their_footer_counts = [
        _classify_footer_links(
            _g(s, "internal_links") or [],
            _g(s, "headings") or [],
        )
        for _b, s in their_signals_by_brand
    ]
    gap.footer_diff = FooterDiff(
        our_footer_link_count=our_footer,
        median_their_footer_link_count=_median(their_footer_counts),
    )

    # ─ Topic vocab overlap ──────────────────────────────────────
    our_topics: set[str] = set()
    for s in (our_sections or []):
        our_topics.update(_topics_from_section(s))
    their_topics: set[str] = set()
    for _b, sections in their_sections_by_brand:
        for s in sections or []:
            their_topics.update(_topics_from_section(s))
    union = our_topics | their_topics
    overlap = (
        len(our_topics & their_topics) / max(1, len(union))
        if union else 0.0
    )
    gap.topic_overlap = TopicOverlap(
        overlap_pct=round(overlap, 3),
        our_unique_topics=sorted(our_topics - their_topics)[:12],
        their_aggregate_unique_topics=sorted(their_topics - our_topics)[:18],
    )

    # ─ Headline recommendations (rule-based, for prompt + UI) ───
    recs: list[str] = []
    if gap.size_diff and gap.size_diff.deficit < -500:
        recs.append(
            f"Expand body — competitors median {gap.size_diff.median_their_word_count:,} words, "
            f"we're at {gap.size_diff.our_word_count:,} (deficit {-gap.size_diff.deficit:,})."
        )
    for miss in gap.sections_we_miss[:5]:
        if len(miss.brands_with_it) >= 2:
            recs.append(
                f"Add a “{miss.label}” section — {len(miss.brands_with_it)} competitor"
                + ("s" if len(miss.brands_with_it) > 1 else "")
                + f" have it ({', '.join(miss.brands_with_it[:3])})."
            )
    if gap.link_inventory_diff and gap.link_inventory_diff.kinds_we_lack:
        recs.append(
            "Add internal-link coverage for these kinds: "
            + ", ".join(gap.link_inventory_diff.kinds_we_lack[:5])
            + "."
        )
    if (
        gap.size_diff
        and gap.size_diff.our_image_count < gap.size_diff.median_their_image_count - 5
    ):
        recs.append(
            f"Add visuals — competitors carry median "
            f"{gap.size_diff.median_their_image_count} images vs our "
            f"{gap.size_diff.our_image_count}."
        )
    gap.headline_recommendations = recs

    return gap


# ── serialisation ────────────────────────────────────────────────────


def to_dict(g: CompetitorGap) -> dict:
    return {
        "sections_we_miss": [
            {
                "name": s.name,
                "label": s.label,
                "brands_with_it": s.brands_with_it,
                "topics_aggregate": s.topics_aggregate,
                "sample_headings": s.sample_headings,
            }
            for s in g.sections_we_miss
        ],
        "sections_unique_to_us": [
            {
                "name": s.name,
                "label": s.label,
                "sample_headings": s.sample_headings,
            }
            for s in g.sections_unique_to_us
        ],
        "size_diff": (
            {
                "our_word_count": g.size_diff.our_word_count,
                "median_their_word_count": g.size_diff.median_their_word_count,
                "deficit": g.size_diff.deficit,
                "our_heading_count": g.size_diff.our_heading_count,
                "median_their_heading_count": g.size_diff.median_their_heading_count,
                "our_image_count": g.size_diff.our_image_count,
                "median_their_image_count": g.size_diff.median_their_image_count,
            }
            if g.size_diff else None
        ),
        "link_inventory_diff": (
            {
                "our_total": g.link_inventory_diff.our_total,
                "median_their_total": g.link_inventory_diff.median_their_total,
                "our_by_kind": g.link_inventory_diff.our_by_kind,
                "median_their_by_kind": g.link_inventory_diff.median_their_by_kind,
                "kinds_we_lack": g.link_inventory_diff.kinds_we_lack,
            }
            if g.link_inventory_diff else None
        ),
        "footer_diff": (
            {
                "our_footer_link_count": g.footer_diff.our_footer_link_count,
                "median_their_footer_link_count": g.footer_diff.median_their_footer_link_count,
            }
            if g.footer_diff else None
        ),
        "topic_overlap": (
            {
                "overlap_pct": g.topic_overlap.overlap_pct,
                "our_unique_topics": g.topic_overlap.our_unique_topics,
                "their_aggregate_unique_topics": g.topic_overlap.their_aggregate_unique_topics,
            }
            if g.topic_overlap else None
        ),
        "headline_recommendations": g.headline_recommendations,
    }
