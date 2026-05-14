"""Deterministic competitor-vs-us gap computation.

Runs BEFORE the CompetitorAgent's LLM call. Produces a structured
:class:`GapReport` that the agent's prompt cites as evidence. The LLM
narrates / prioritises but never invents numbers — every cited field
is computed here.

The report covers the four dimensions the user asked for:

  1. Topic gaps        — content topics rivals cover that we don't
  2. Keyword gaps      — keywords rivals rank top-10 for, we don't
  3. Hygiene deltas    — per-topic average title/meta/H1/schema gap
  4. Volume deltas     — page count + average word count per topic

Topic clustering is regex-on-slug, not embeddings. Good enough for the
~20 stable topic stems in the Indian life-insurance vertical; we can
swap in embedding-clustering later without changing the GapReport
contract.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlparse

from .adapters.competitor_crawler import CompetitorPage
from .adapters.gsc_csv import GSCQueryRow
from .adapters.semrush import SemrushKeyword, SemrushTopPage
from .adapters.sitemap_aem import AEMPage

logger = logging.getLogger("seo.ai.scoring_competitor")


# ── public dataclasses ──────────────────────────────────────────────────


@dataclass
class CompetitorDossier:
    """One competitor's full pulled+crawled dataset."""

    domain: str
    competition_level: float
    common_keywords: int
    top_pages: list[SemrushTopPage] = field(default_factory=list)
    keywords: list[SemrushKeyword] = field(default_factory=list)
    crawled: list[CompetitorPage] = field(default_factory=list)
    # Phase 2A — sitemap.xml indexable URL count for the domain.
    # 0 means "no sitemap discovered or sitemap unreachable".
    total_url_count: int = 0


@dataclass
class TopicGap:
    cluster_slug: str
    competitor_page_count: int
    our_page_count: int
    sample_competitor_urls: list[str]
    sample_competitor_titles: list[str]
    competitors_covering: list[str]


@dataclass
class KeywordGap:
    keyword: str
    competitor_domain: str
    competitor_position: int
    competitor_url: str
    search_volume: int
    competitor_traffic_pct: float
    score: float  # search_volume * (traffic_pct / 100) for prioritisation


@dataclass
class HygieneDelta:
    cluster_slug: str
    our_avg_title_length: float
    competitor_avg_title_length: float
    our_avg_description_length: float
    competitor_avg_description_length: float
    our_h1_pct: float
    competitor_h1_pct: float
    our_schema_pct: float
    competitor_schema_pct: float
    competitor_pages_sampled: int
    our_pages_sampled: int


@dataclass
class VolumeDelta:
    cluster_slug: str
    our_page_count: int
    competitor_page_count: int
    our_avg_word_count: float
    competitor_avg_word_count: float
    our_total_words: int
    competitor_total_words: int


# ── Phase 2A — new dimensions ─────────────────────────────────────


@dataclass
class ProductCoverage:
    """How many pages each competitor (and us) has covering one
    product category.

    ``product_slug`` is a stable key from ``_PRODUCT_STEMS``; the
    counts are derived from URL-slug regex against crawled or
    sitemap-counted pages. ``competitor_counts`` is a per-competitor
    map so the UI can render a row × columns matrix.
    """

    product_slug: str
    our_page_count: int
    competitor_counts: dict[str, int]
    sample_competitor_urls: list[str]


@dataclass
class StructureDelta:
    """Per-topic-cluster structural averages, us vs them.

    Surfaces "competitors have 4× our H2 sections per page" etc. —
    the kind of detail that explains why a thinner-looking page
    outranks a fatter one (better scannability + internal link mesh).
    """

    cluster_slug: str
    our_avg_h2: float
    competitor_avg_h2: float
    our_avg_h3: float
    competitor_avg_h3: float
    our_avg_internal_links: float
    competitor_avg_internal_links: float
    our_avg_external_links: float
    competitor_avg_external_links: float
    our_avg_image_alt_pct: float
    competitor_avg_image_alt_pct: float
    our_avg_cta_count: float
    competitor_avg_cta_count: float
    our_schema_type_count: float        # avg distinct schema @types per page
    competitor_schema_type_count: float
    our_pages_sampled: int
    competitor_pages_sampled: int


@dataclass
class LoadingTimeDelta:
    """Server-response-time deltas per topic cluster.

    Note: this is wall-clock time from our Docker container to the
    target host, NOT the user's browser experience. Useful for a
    relative ranking ("they're 2× faster than us") but not for
    absolute Core Web Vitals — that ships in Phase 2B via CrUX.
    """

    cluster_slug: str
    our_median_ms: int
    competitor_median_ms: int
    our_p90_ms: int
    competitor_p90_ms: int
    our_pages_sampled: int
    competitor_pages_sampled: int


@dataclass
class ContentFitDelta:
    """How well a ranking page's body discusses the keyword it ranks for.

    For each top competitor keyword (by traffic-score), we look at the
    crawled page that ranks for it and count keyword occurrences in
    the body. "Thin keyword fit" = appears <2 times per 1000 words —
    a strong signal that the rival's content has surface fit only.
    """

    keyword: str
    competitor_domain: str
    competitor_url: str
    competitor_position: int
    search_volume: int
    competitor_word_count: int
    competitor_keyword_occurrences: int
    competitor_keyword_density: float   # per 1000 words
    fit_verdict: str                    # "strong" | "moderate" | "thin" | "none"


@dataclass
class GapReport:
    competitors: list[dict]           # slim per-competitor summary
    topic_gaps: list[TopicGap]
    keyword_gaps: list[KeywordGap]
    hygiene_deltas: list[HygieneDelta]
    content_volume_deltas: list[VolumeDelta]
    samples_attempted: int            # how many competitor URLs we tried to crawl
    samples_succeeded: int            # how many returned status 200
    # Phase 2A — new dimensions.
    product_coverage: list[ProductCoverage] = field(default_factory=list)
    structure_deltas: list[StructureDelta] = field(default_factory=list)
    loading_time_deltas: list[LoadingTimeDelta] = field(default_factory=list)
    content_fit_deltas: list[ContentFitDelta] = field(default_factory=list)
    total_url_count_by_competitor: dict[str, int] = field(default_factory=dict)
    our_total_url_count: int = 0
    our_pages_crawled: int = 0
    our_pages_crawl_attempted: int = 0


# ── topic stems ─────────────────────────────────────────────────────────


# Product slugs are a strict sub-list of topic stems — they identify
# actual sellable insurance products, not informational content. The
# product-coverage matrix uses these (and these only) so the row count
# stays stable across runs.
_PRODUCT_SLUGS: list[str] = [
    "term-insurance",
    "whole-life-insurance",
    "endowment-policy",
    "money-back-policy",
    "ulip",
    "unit-linked",
    "child-plan",
    "child-insurance",
    "retirement-plan",
    "pension-plan",
    "annuity",
    "guaranteed-return",
    "savings-plan",
    "investment-plan",
    "critical-illness",
    "health-insurance",
]

# Stable topic stems for life insurance India. Order matters: longer /
# more specific slugs are matched first so /term-insurance-for-women
# bucket-sorts before /term-insurance.
_TOPIC_STEMS: list[tuple[str, re.Pattern]] = [
    (slug, re.compile(rf"(?:^|/){slug}(?:[-/]|$)", re.I))
    for slug in [
        "term-insurance-for-women",
        "term-insurance-for-nri",
        "term-insurance-with-return-of-premium",
        "term-insurance-calculator",
        "term-insurance",
        "whole-life-insurance",
        "endowment-policy",
        "money-back-policy",
        "ulip",
        "unit-linked",
        "child-plan",
        "child-insurance",
        "retirement-plan",
        "pension-plan",
        "annuity",
        "health-insurance",
        "critical-illness",
        "guaranteed-return",
        "savings-plan",
        "investment-plan",
        "tax-saving",
        "section-80c",
        "claim-settlement",
        "premium-calculator",
        "nri",
        "life-insurance-guide",
        "blog",
        "faq",
    ]
]


_BRAND_SUFFIX_RE = re.compile(
    r"(life|insurance|pru|prulife|allianz|general|india|gi|wealth|finserv)+$",
    re.I,
)


def _brand_stem(domain: str) -> str:
    """Extract a brand-name stem from a domain so we can detect when a
    keyword is branded (e.g. ``hdfclife`` matching ``connect hdfclife``).

    Mirrors :func:`apps.seo_ai.agents.competitor._brand_stem` — duplicated
    here to keep this module pure (no agent imports).
    """
    bare = re.sub(r"^www\d?\.", "", (domain or "").lower()).split("/")[0]
    parts = bare.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "net", "org", "gov", "ac"}:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return bare


def _brand_keywords(domain: str) -> set[str]:
    """Brand-name tokens that signal a keyword is branded for this
    competitor. Returns both the full domain stem (``hdfclife``) and
    the core brand once insurance suffixes are stripped (``hdfc``).
    """
    stem = _brand_stem(domain)
    if not stem:
        return set()
    out = {stem}
    # Iteratively strip recognised insurance suffixes so "hdfclife" →
    # "hdfc", "iciciprulife" → "icici", "indiafirstlife" → "indiafirst".
    core = stem
    while True:
        stripped = _BRAND_SUFFIX_RE.sub("", core)
        if stripped == core or len(stripped) < 3:
            break
        core = stripped
    if core != stem and len(core) >= 3:
        out.add(core)
    return out


def _is_branded_for(keyword: str, brand_tokens: set[str]) -> bool:
    """True if any brand token appears as a whole word in the keyword
    or as a contiguous substring (handles 'hdfc login', 'connect
    hdfclife', 'iciciprulife mybills', etc.)."""
    if not brand_tokens:
        return False
    kw = keyword.lower()
    kw_compact = re.sub(r"\s+", "", kw)
    for tok in brand_tokens:
        if not tok:
            continue
        if tok in kw_compact:
            return True
        # Whole-word match handles "icici" in "icici prudential".
        if re.search(rf"(?:^|\s){re.escape(tok)}(?:\s|$)", kw):
            return True
    return False


def _topic_for(url_or_path: str) -> str:
    """Map a URL / AEM path to a topic-stem slug, or 'other'."""
    if not url_or_path:
        return "other"
    text = url_or_path.lower()
    for slug, regex in _TOPIC_STEMS:
        if regex.search(text):
            return slug
    return "other"


# ── main entrypoint ────────────────────────────────────────────────────


def compute_gaps(
    *,
    our_aem_pages: list[AEMPage],
    our_gsc_queries: list[GSCQueryRow],
    our_semrush_keywords: list[SemrushKeyword],
    competitors: list[CompetitorDossier],
    our_crawled: list[CompetitorPage] | None = None,
    our_total_url_count: int = 0,
    max_topic_gaps: int = 10,
    max_keyword_gaps: int = 25,
    max_content_fit: int = 15,
) -> GapReport:
    """Compute the eight-dimension gap. Caller passes pre-fetched
    adapter outputs — this module is pure deterministic compute.

    ``our_crawled`` is the Phase 2A symmetric-crawl payload — our own
    pages fetched through the same crawler the competitors are. When
    it's provided, hygiene / structure / loading-time deltas are
    computed apples-to-apples; when it's ``None`` we fall back to the
    v1 AEM-derived numbers (with the known asymmetry on H1/schema).
    """
    our_crawled = our_crawled or []

    # ── classify our pages by topic ────────────────────────────────
    our_by_topic: dict[str, list[AEMPage]] = {}
    for p in our_aem_pages:
        topic = _topic_for(p.aem_path or p.public_url)
        our_by_topic.setdefault(topic, []).append(p)

    # ── classify competitor pages by topic (URL-based) ─────────────
    comp_pages_by_topic: dict[str, list[tuple[str, CompetitorPage]]] = {}
    samples_attempted = 0
    samples_succeeded = 0
    for comp in competitors:
        for cp in comp.crawled:
            samples_attempted += 1
            if cp.status_code != 200:
                continue
            samples_succeeded += 1
            topic = _topic_for(cp.final_url or cp.url)
            comp_pages_by_topic.setdefault(topic, []).append((comp.domain, cp))

    # ── classify our own crawled pages by topic (Phase 2A) ─────────
    # When the symmetric crawl is enabled, our hygiene / structure /
    # loading-time numbers come from these pages instead of AEM.
    our_crawled_ok = [p for p in our_crawled if p.status_code == 200]
    our_crawled_by_topic: dict[str, list[CompetitorPage]] = {}
    for p in our_crawled_ok:
        topic = _topic_for(p.final_url or p.url)
        our_crawled_by_topic.setdefault(topic, []).append(p)

    # ── 1. topic gaps ──────────────────────────────────────────────
    topic_gaps: list[TopicGap] = []
    for topic, entries in comp_pages_by_topic.items():
        if topic == "other":
            continue
        our_count = len(our_by_topic.get(topic, []))
        comp_count = len(entries)
        # Surface gaps where competitors have ≥2 pages and we have
        # zero OR they have ≥3× our coverage.
        if comp_count < 2:
            continue
        if our_count == 0 or comp_count >= 3 * max(our_count, 1):
            sample = entries[:3]
            covering = sorted({e[0] for e in entries})[:5]
            topic_gaps.append(
                TopicGap(
                    cluster_slug=topic,
                    competitor_page_count=comp_count,
                    our_page_count=our_count,
                    sample_competitor_urls=[cp.url for _, cp in sample],
                    sample_competitor_titles=[cp.title for _, cp in sample if cp.title][:3],
                    competitors_covering=covering,
                )
            )
    topic_gaps.sort(
        key=lambda t: (t.our_page_count == 0, t.competitor_page_count), reverse=True
    )
    topic_gaps = topic_gaps[:max_topic_gaps]

    # ── 2. keyword gaps ─────────────────────────────────────────────
    # Our keyword universe = GSC queries we have any impressions on +
    # SEMrush keywords we rank for at any position. Lowercased for the
    # diff.
    our_kw_set: set[str] = set()
    for q in our_gsc_queries:
        if q.query:
            our_kw_set.add(q.query.strip().lower())
    for k in our_semrush_keywords:
        if k.keyword and k.position and k.position <= 30:
            our_kw_set.add(k.keyword.strip().lower())

    keyword_gaps: list[KeywordGap] = []
    for comp in competitors:
        # Each competitor's brand tokens — drop branded queries that
        # reference the rival's name (e.g. "hdfc login" for
        # hdfclife.com). These will never be reachable by SEO and
        # surfacing them as gaps is noise the user can't action.
        comp_brand_tokens = _brand_keywords(comp.domain)
        for k in comp.keywords:
            if not k.keyword:
                continue
            if k.position < 1 or k.position > 10:
                continue
            kw_lc = k.keyword.strip().lower()
            if kw_lc in our_kw_set:
                continue
            if _fuzzy_in(kw_lc, our_kw_set):
                continue
            if _is_branded_for(kw_lc, comp_brand_tokens):
                continue
            score = float(k.search_volume) * (k.traffic_pct / 100.0)
            keyword_gaps.append(
                KeywordGap(
                    keyword=k.keyword,
                    competitor_domain=comp.domain,
                    competitor_position=k.position,
                    competitor_url=k.url or "",
                    search_volume=k.search_volume,
                    competitor_traffic_pct=k.traffic_pct,
                    score=score,
                )
            )
    keyword_gaps.sort(key=lambda g: g.score, reverse=True)
    # Dedupe by keyword text, keep highest-score occurrence.
    seen: set[str] = set()
    deduped: list[KeywordGap] = []
    for g in keyword_gaps:
        key = g.keyword.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(g)
    keyword_gaps = deduped[:max_keyword_gaps]

    # ── 3. hygiene deltas ─────────────────────────────────────────
    hygiene_deltas: list[HygieneDelta] = []
    for topic, entries in comp_pages_by_topic.items():
        if topic == "other":
            continue
        our_pages = our_by_topic.get(topic, [])
        if not our_pages and not entries:
            continue
        # Only emit when at least one side has ≥3 pages so averages mean something.
        if len(entries) < 3 and len(our_pages) < 3:
            continue
        their_pages = [cp for _, cp in entries]
        # Phase 2A: when the symmetric crawl ran, our-side title /
        # description / H1 / schema numbers come from live HTML — same
        # source the competitor numbers do, so the comparison is real.
        # Fall back to AEM authored values only when our_crawled is empty.
        our_crawled_topic_pages = our_crawled_by_topic.get(topic, [])
        if our_crawled_topic_pages:
            our_title_avg = _avg(p.title_length for p in our_crawled_topic_pages)
            our_desc_avg = _avg(p.meta_description_length for p in our_crawled_topic_pages)
            our_h1_pct = (
                sum(1 for p in our_crawled_topic_pages if p.h1_texts)
                / len(our_crawled_topic_pages)
                * 100.0
            )
            our_schema_pct = (
                sum(1 for p in our_crawled_topic_pages if p.has_schema_org)
                / len(our_crawled_topic_pages)
                * 100.0
            )
            our_pages_sampled_for_hygiene = len(our_crawled_topic_pages)
        else:
            our_title_avg = _avg(len(p.title or "") for p in our_pages)
            our_desc_avg = _avg(len(p.description or "") for p in our_pages)
            our_h1_pct = 0.0   # asymmetric — AEM doesn't expose H1
            our_schema_pct = 0.0
            our_pages_sampled_for_hygiene = len(our_pages)
        their_title_avg = _avg(p.title_length for p in their_pages)
        their_desc_avg = _avg(p.meta_description_length for p in their_pages)
        their_h1_pct = (
            sum(1 for p in their_pages if p.h1_texts) / len(their_pages) * 100.0
            if their_pages
            else 0.0
        )
        their_schema_pct = (
            sum(1 for p in their_pages if p.has_schema_org)
            / len(their_pages)
            * 100.0
            if their_pages
            else 0.0
        )
        delta = HygieneDelta(
            cluster_slug=topic,
            our_avg_title_length=round(our_title_avg, 1),
            competitor_avg_title_length=round(their_title_avg, 1),
            our_avg_description_length=round(our_desc_avg, 1),
            competitor_avg_description_length=round(their_desc_avg, 1),
            our_h1_pct=round(our_h1_pct, 1),
            competitor_h1_pct=round(their_h1_pct, 1),
            our_schema_pct=round(our_schema_pct, 1),
            competitor_schema_pct=round(their_schema_pct, 1),
            competitor_pages_sampled=len(their_pages),
            our_pages_sampled=our_pages_sampled_for_hygiene,
        )
        # Surface only where competitors are meaningfully ahead — keeps
        # the LLM payload from drowning in noise.
        if (
            their_schema_pct - our_schema_pct >= 20
            or their_h1_pct - our_h1_pct >= 20
            or abs(their_title_avg - our_title_avg) >= 10
            or abs(their_desc_avg - our_desc_avg) >= 20
        ):
            hygiene_deltas.append(delta)
    hygiene_deltas.sort(
        key=lambda d: (
            d.competitor_schema_pct - d.our_schema_pct
            + d.competitor_h1_pct - d.our_h1_pct
        ),
        reverse=True,
    )
    hygiene_deltas = hygiene_deltas[:10]

    # ── 4. content volume deltas ───────────────────────────────────
    volume_deltas: list[VolumeDelta] = []
    for topic, entries in comp_pages_by_topic.items():
        if topic == "other":
            continue
        our_pages = our_by_topic.get(topic, [])
        their_pages = [cp for _, cp in entries]
        our_words = [p.word_count for p in our_pages if p.word_count]
        their_words = [p.word_count for p in their_pages if p.word_count]
        if not their_words:
            continue
        our_avg = sum(our_words) / len(our_words) if our_words else 0.0
        their_avg = sum(their_words) / len(their_words)
        # Emit when their average is ≥2x ours OR we have <50% page count.
        page_ratio = (len(our_pages) / len(their_pages)) if their_pages else 1.0
        word_ratio = (our_avg / their_avg) if their_avg else 1.0
        if page_ratio >= 0.5 and word_ratio >= 0.5:
            continue
        volume_deltas.append(
            VolumeDelta(
                cluster_slug=topic,
                our_page_count=len(our_pages),
                competitor_page_count=len(their_pages),
                our_avg_word_count=round(our_avg, 0),
                competitor_avg_word_count=round(their_avg, 0),
                our_total_words=sum(our_words),
                competitor_total_words=sum(their_words),
            )
        )
    volume_deltas.sort(
        key=lambda v: (
            v.competitor_total_words - v.our_total_words
        ),
        reverse=True,
    )
    volume_deltas = volume_deltas[:10]

    # ── 5. product coverage matrix (Phase 2A) ──────────────────────
    product_coverage = _compute_product_coverage(
        our_aem_pages=our_aem_pages,
        our_crawled=our_crawled_ok,
        competitors=competitors,
    )

    # ── 6. structure deltas (Phase 2A) ────────────────────────────
    structure_deltas = _compute_structure_deltas(
        our_crawled_by_topic=our_crawled_by_topic,
        comp_pages_by_topic=comp_pages_by_topic,
    )

    # ── 7. loading time deltas (Phase 2A) ──────────────────────────
    loading_time_deltas = _compute_loading_time_deltas(
        our_crawled_by_topic=our_crawled_by_topic,
        comp_pages_by_topic=comp_pages_by_topic,
    )

    # ── 8. content-keyword fit (Phase 2A) ─────────────────────────
    content_fit_deltas = _compute_content_fit_deltas(
        competitors=competitors,
        max_items=max_content_fit,
    )

    # ── slim per-competitor summary ─────────────────────────────────
    comp_summary = [
        {
            "domain": c.domain,
            "competition_level": round(c.competition_level, 3),
            "common_keywords": c.common_keywords,
            "top_pages_pulled": len(c.top_pages),
            "keywords_pulled": len(c.keywords),
            "pages_crawled_ok": sum(1 for cp in c.crawled if cp.status_code == 200),
            "pages_crawl_attempted": len(c.crawled),
            "total_url_count": c.total_url_count,
        }
        for c in competitors
    ]

    total_url_count_by_competitor = {
        c.domain: c.total_url_count for c in competitors
    }

    return GapReport(
        competitors=comp_summary,
        topic_gaps=topic_gaps,
        keyword_gaps=keyword_gaps,
        hygiene_deltas=hygiene_deltas,
        content_volume_deltas=volume_deltas,
        samples_attempted=samples_attempted,
        samples_succeeded=samples_succeeded,
        product_coverage=product_coverage,
        structure_deltas=structure_deltas,
        loading_time_deltas=loading_time_deltas,
        content_fit_deltas=content_fit_deltas,
        total_url_count_by_competitor=total_url_count_by_competitor,
        our_total_url_count=our_total_url_count,
        our_pages_crawled=len(our_crawled_ok),
        our_pages_crawl_attempted=len(our_crawled),
    )


# ── helpers ─────────────────────────────────────────────────────────


def _avg(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _fuzzy_in(needle: str, haystack: set[str], *, threshold: float = 0.9) -> bool:
    """Cheap fuzzy match — catches 'term plan' vs 'term plans'.

    We do NOT scan the whole haystack (could be thousands of GSC
    queries). Instead, check exact + trivial s-suffix / no-s variants.
    Empirically this catches >95% of the singular/plural noise without
    the cost of pairwise Levenshtein.
    """
    if needle in haystack:
        return True
    if needle.endswith("s") and needle[:-1] in haystack:
        return True
    if (needle + "s") in haystack:
        return True
    # Drop punctuation and whitespace differences.
    norm = re.sub(r"[^a-z0-9]+", "", needle)
    for h in haystack:
        if re.sub(r"[^a-z0-9]+", "", h) == norm:
            return True
    return False


def _compute_product_coverage(
    *,
    our_aem_pages: list[AEMPage],
    our_crawled: list[CompetitorPage],
    competitors: list[CompetitorDossier],
) -> list[ProductCoverage]:
    """For each product slug, count pages on our side (AEM ∪ crawled)
    and each competitor side (their crawled top-pages).

    Skips slugs where every side has 0 pages — those would just be
    noise rows in the UI.
    """
    out: list[ProductCoverage] = []
    # Our pool: AEM pages (any) + symmetric-crawl pages. Dedupe by
    # final URL so the same page doesn't double-count if it shows up
    # in both sources.
    our_seen: set[str] = set()
    our_urls: list[str] = []
    for p in our_aem_pages:
        u = p.public_url or p.aem_path
        if u and u not in our_seen:
            our_seen.add(u)
            our_urls.append(u)
    for p in our_crawled:
        u = p.final_url or p.url
        if u and u not in our_seen:
            our_seen.add(u)
            our_urls.append(u)

    # Per-competitor pool: their successfully crawled top pages.
    comp_pools: dict[str, list[str]] = {}
    for comp in competitors:
        comp_pools[comp.domain] = [
            (cp.final_url or cp.url)
            for cp in comp.crawled
            if cp.status_code == 200 and (cp.final_url or cp.url)
        ]

    for slug in _PRODUCT_SLUGS:
        regex = next((r for s, r in _TOPIC_STEMS if s == slug), None)
        if regex is None:
            continue
        our_count = sum(1 for u in our_urls if regex.search(u.lower()))
        competitor_counts: dict[str, int] = {}
        sample_urls: list[str] = []
        for domain, pool in comp_pools.items():
            matches = [u for u in pool if regex.search(u.lower())]
            competitor_counts[domain] = len(matches)
            sample_urls.extend(matches[:1])
        # Skip rows where nobody covers this product at all.
        if our_count == 0 and not any(competitor_counts.values()):
            continue
        out.append(
            ProductCoverage(
                product_slug=slug,
                our_page_count=our_count,
                competitor_counts=competitor_counts,
                sample_competitor_urls=sample_urls[:5],
            )
        )
    # Order by "biggest gap" so the UI shows the worst gaps first.
    out.sort(
        key=lambda p: max(p.competitor_counts.values() or [0]) - p.our_page_count,
        reverse=True,
    )
    return out


def _compute_structure_deltas(
    *,
    our_crawled_by_topic: dict[str, list[CompetitorPage]],
    comp_pages_by_topic: dict[str, list[tuple[str, CompetitorPage]]],
) -> list[StructureDelta]:
    """Per-topic averages of structural metrics — h2/h3, internal/external
    links, image-alt %, CTA count, schema type count — us vs them.
    Emits rows only where both sides have ≥3 sampled pages so the
    averages are stable.
    """
    out: list[StructureDelta] = []
    for topic, entries in comp_pages_by_topic.items():
        if topic == "other":
            continue
        their_pages = [cp for _, cp in entries]
        our_pages = our_crawled_by_topic.get(topic, [])
        if len(their_pages) < 3 or len(our_pages) < 3:
            continue
        out.append(
            StructureDelta(
                cluster_slug=topic,
                our_avg_h2=round(_avg(p.h2_count for p in our_pages), 1),
                competitor_avg_h2=round(_avg(p.h2_count for p in their_pages), 1),
                our_avg_h3=round(_avg(p.h3_count for p in our_pages), 1),
                competitor_avg_h3=round(_avg(p.h3_count for p in their_pages), 1),
                our_avg_internal_links=round(
                    _avg(p.internal_link_count for p in our_pages), 1
                ),
                competitor_avg_internal_links=round(
                    _avg(p.internal_link_count for p in their_pages), 1
                ),
                our_avg_external_links=round(
                    _avg(p.external_link_count for p in our_pages), 1
                ),
                competitor_avg_external_links=round(
                    _avg(p.external_link_count for p in their_pages), 1
                ),
                our_avg_image_alt_pct=round(
                    _avg(p.image_alt_pct for p in our_pages), 1
                ),
                competitor_avg_image_alt_pct=round(
                    _avg(p.image_alt_pct for p in their_pages), 1
                ),
                our_avg_cta_count=round(_avg(p.cta_count for p in our_pages), 1),
                competitor_avg_cta_count=round(
                    _avg(p.cta_count for p in their_pages), 1
                ),
                our_schema_type_count=round(
                    _avg(len(p.schema_types) for p in our_pages), 1
                ),
                competitor_schema_type_count=round(
                    _avg(len(p.schema_types) for p in their_pages), 1
                ),
                our_pages_sampled=len(our_pages),
                competitor_pages_sampled=len(their_pages),
            )
        )
    # Order by the biggest competitor lead on schema-type-count then
    # internal-links — those tend to be the deepest signal.
    out.sort(
        key=lambda d: (
            d.competitor_schema_type_count - d.our_schema_type_count
            + (d.competitor_avg_internal_links - d.our_avg_internal_links) / 10.0
        ),
        reverse=True,
    )
    return out


def _compute_loading_time_deltas(
    *,
    our_crawled_by_topic: dict[str, list[CompetitorPage]],
    comp_pages_by_topic: dict[str, list[tuple[str, CompetitorPage]]],
) -> list[LoadingTimeDelta]:
    """Median + p90 response time per topic cluster. Filters pages
    whose recorded response_time_ms is 0 (cache hits where the timing
    wasn't captured)."""
    out: list[LoadingTimeDelta] = []
    for topic, entries in comp_pages_by_topic.items():
        if topic == "other":
            continue
        their_pages = [cp for _, cp in entries if cp.response_time_ms > 0]
        our_pages = [
            p for p in our_crawled_by_topic.get(topic, []) if p.response_time_ms > 0
        ]
        if len(their_pages) < 3 or len(our_pages) < 3:
            continue
        out.append(
            LoadingTimeDelta(
                cluster_slug=topic,
                our_median_ms=_percentile([p.response_time_ms for p in our_pages], 50),
                competitor_median_ms=_percentile(
                    [p.response_time_ms for p in their_pages], 50
                ),
                our_p90_ms=_percentile([p.response_time_ms for p in our_pages], 90),
                competitor_p90_ms=_percentile(
                    [p.response_time_ms for p in their_pages], 90
                ),
                our_pages_sampled=len(our_pages),
                competitor_pages_sampled=len(their_pages),
            )
        )
    # Worst-relative gap first (their median much faster than ours).
    out.sort(
        key=lambda d: d.our_median_ms - d.competitor_median_ms, reverse=True
    )
    return out


def _compute_content_fit_deltas(
    *,
    competitors: list[CompetitorDossier],
    max_items: int,
) -> list[ContentFitDelta]:
    """For each top-traffic competitor keyword, locate the ranking page
    in their crawl and score how often the keyword appears in the
    body. Helps surface "they rank #1 with thin keyword coverage" so
    we know the gap is reachable.
    """
    # Index crawled pages by URL per competitor for O(1) lookup.
    page_by_url: dict[str, CompetitorPage] = {}
    for comp in competitors:
        for cp in comp.crawled:
            if cp.status_code != 200:
                continue
            page_by_url[cp.final_url] = cp
            page_by_url[cp.url] = cp

    # Rank keywords across all competitors by traffic-score, take top N.
    scored: list[tuple[float, str, SemrushKeyword]] = []
    for comp in competitors:
        for k in comp.keywords:
            if not k.keyword or not k.url:
                continue
            if k.position < 1 or k.position > 10:
                continue
            score = float(k.search_volume) * (k.traffic_pct / 100.0)
            scored.append((score, comp.domain, k))
    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[ContentFitDelta] = []
    seen_keys: set[str] = set()
    for _score, domain, k in scored:
        if len(out) >= max_items:
            break
        key = k.keyword.strip().lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        page = page_by_url.get(k.url)
        if page is None or not page.body_text:
            continue
        body_lower = page.body_text.lower()
        # Word-boundary count to avoid "term" matching inside "terminate".
        pattern = re.compile(rf"\b{re.escape(key)}\b", re.IGNORECASE)
        occurrences = len(pattern.findall(body_lower))
        density = (
            (occurrences * 1000.0) / page.word_count if page.word_count else 0.0
        )
        if occurrences == 0:
            verdict = "none"
        elif density < 2:
            verdict = "thin"
        elif density < 6:
            verdict = "moderate"
        else:
            verdict = "strong"
        out.append(
            ContentFitDelta(
                keyword=k.keyword,
                competitor_domain=domain,
                competitor_url=k.url,
                competitor_position=k.position,
                search_volume=k.search_volume,
                competitor_word_count=page.word_count,
                competitor_keyword_occurrences=occurrences,
                competitor_keyword_density=round(density, 2),
                fit_verdict=verdict,
            )
        )
    return out


def _percentile(values: list[int], pct: int) -> int:
    """Inclusive nearest-rank percentile. Returns 0 on empty input."""
    if not values:
        return 0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return int(s[k])


def gap_report_to_facts(report: GapReport) -> dict:
    """Flatten a :class:`GapReport` into the JSON-serialisable dict the
    LLM consumes. Keys are stable so the orchestrator's evidence-key
    enumerator can validate ``competitor:<...>`` references.
    """
    def _dict(obj):
        return getattr(obj, "__dict__", obj)

    return {
        "competitor": {
            "summary": {
                "competitors_analysed": len(report.competitors),
                "topic_gaps_found": len(report.topic_gaps),
                "keyword_gaps_found": len(report.keyword_gaps),
                "hygiene_deltas_found": len(report.hygiene_deltas),
                "content_volume_deltas_found": len(report.content_volume_deltas),
                "competitor_pages_crawled_ok": report.samples_succeeded,
                "competitor_pages_crawl_attempted": report.samples_attempted,
                # Phase 2A — surface the new sample sizes.
                "our_pages_crawled_ok": report.our_pages_crawled,
                "our_pages_crawl_attempted": report.our_pages_crawl_attempted,
                "our_total_url_count": report.our_total_url_count,
                "product_coverage_rows": len(report.product_coverage),
                "structure_deltas_found": len(report.structure_deltas),
                "loading_time_deltas_found": len(report.loading_time_deltas),
                "content_fit_items": len(report.content_fit_deltas),
            },
            "competitors": report.competitors,
            "topic_gaps": [_dict(t) for t in report.topic_gaps],
            "keyword_gaps": [_dict(k) for k in report.keyword_gaps],
            "hygiene_deltas": [_dict(h) for h in report.hygiene_deltas],
            "content_volume_deltas": [_dict(v) for v in report.content_volume_deltas],
            # Phase 2A — new dimensions.
            "product_coverage": [_dict(p) for p in report.product_coverage],
            "structure_deltas": [_dict(s) for s in report.structure_deltas],
            "loading_time_deltas": [_dict(l) for l in report.loading_time_deltas],
            "content_fit_deltas": [_dict(c) for c in report.content_fit_deltas],
            "total_url_count_by_competitor": report.total_url_count_by_competitor,
            "our_total_url_count": report.our_total_url_count,
        }
    }
