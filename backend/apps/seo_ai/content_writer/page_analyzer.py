"""Structural fingerprint of one page — the analyzer.

Takes a :class:`page_crawler.CrawledPage` and computes everything the
gap engine + writer prompt need:

* Heading outline tree (H1 → H2 → H3 nesting).
* Heading-count by level + duplicate H1 detection.
* Internal-link density (links per 1000 words) + anchor diversity.
* External-link count (citation signal — competitors that cite trusted
  sources tend to rank better for YMYL queries like insurance).
* Image count + alt-text coverage % (accessibility + image-search SEO).
* Video / iframe count.
* JSON-LD schema presence (FAQ, Article, Product, FinancialProduct, ...).
* FAQ presence — detected either via FAQPage schema OR via an H2/H3 list
  of question-formatted strings ("What is X?", "How does Y work?").
* Content size: word count + body byte size.
* CTA detection: count of buttons / links whose anchor matches
  insurance-CTA vocabulary ("buy", "get quote", "calculate premium").
* Reading-time estimate (200 wpm).
* Title / meta-description length (against SEO best-practice ranges).

This is deterministic — pure Python over the crawled HTML/JSON. No LLM
call here. The LLM-driven section clustering lives in
``section_clusterer.py``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("seo.ai.content_writer.page_analyzer")


# ── small helpers ────────────────────────────────────────────────────


_FAQ_QUESTION_RE = re.compile(
    r"^(what|why|how|when|who|where|which|can|does|do|is|are|should|"
    r"will|would|could|may)\b",
    re.IGNORECASE,
)


_CTA_VOCAB: frozenset[str] = frozenset({
    "buy", "buy now", "get quote", "get a quote", "request quote",
    "calculate premium", "calculate", "check premium", "premium calculator",
    "apply now", "apply", "explore plan", "view plan", "view details",
    "compare plans", "compare", "talk to advisor", "call back",
    "request callback", "get started", "start now", "renew now",
    "renew policy", "file claim", "claim now", "download brochure",
    "download policy", "know more", "learn more",
})


_TRUST_SCHEMA_TYPES: frozenset[str] = frozenset({
    "FAQPage", "Article", "NewsArticle", "BlogPosting",
    "Product", "FinancialProduct", "Service", "InsuranceAgency",
    "Organization", "BreadcrumbList", "WebPage", "WebSite",
    "HowTo", "Review", "AggregateRating", "Person",
})


# ── output dataclasses ───────────────────────────────────────────────


@dataclass
class HeadingNode:
    level: int
    text: str
    children: list["HeadingNode"] = field(default_factory=list)


@dataclass
class PageAnalysis:
    url: str
    title: str
    title_length: int
    meta_description: str
    meta_description_length: int
    word_count: int
    reading_time_minutes: float
    content_size_bytes: int

    h1_count: int
    h2_count: int
    h3_count: int
    h4_plus_count: int
    heading_outline: list[HeadingNode] = field(default_factory=list)
    heading_outline_text: list[str] = field(default_factory=list)

    internal_link_count: int = 0
    internal_link_density_per_1k_words: float = 0.0
    unique_internal_targets: int = 0
    external_link_count: int = 0
    unique_external_domains: int = 0

    image_count: int = 0
    image_alt_coverage_pct: float = 0.0
    video_count: int = 0

    jsonld_types: list[str] = field(default_factory=list)
    trusted_schema_present: list[str] = field(default_factory=list)
    has_faq_schema: bool = False
    has_organization_schema: bool = False
    has_breadcrumb_schema: bool = False

    detected_faq_questions: list[str] = field(default_factory=list)
    faq_question_count: int = 0

    cta_count: int = 0
    detected_ctas: list[str] = field(default_factory=list)

    # Best-practice flags filled by seo_overlay; analyzer leaves them None.
    seo_flags: dict[str, Any] = field(default_factory=dict)


# ── outline building ─────────────────────────────────────────────────


def _build_outline(headings: list[dict[str, Any]]) -> list[HeadingNode]:
    """Build a nested tree from the flat ``[{level, text}, ...]`` list.

    Resilient to skipped levels (H1 → H3 with no H2) — promotes the H3
    under the most recent shallower node. Matches the structural picture
    the writer cares about.
    """
    roots: list[HeadingNode] = []
    stack: list[HeadingNode] = []
    for h in headings:
        if not isinstance(h, dict):
            continue
        try:
            level = int(h.get("level") or 0)
        except (TypeError, ValueError):
            level = 0
        text = (h.get("text") or "").strip()
        if level < 1 or not text:
            continue
        node = HeadingNode(level=level, text=text)
        while stack and stack[-1].level >= level:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1].children.append(node)
        stack.append(node)
    return roots


def _outline_text_lines(nodes: list[HeadingNode], indent: int = 0) -> list[str]:
    out: list[str] = []
    prefix = "  " * indent
    for n in nodes:
        out.append(f"{prefix}H{n.level} {n.text}")
        if n.children:
            out.extend(_outline_text_lines(n.children, indent + 1))
    return out


# ── link / image / schema analysis ──────────────────────────────────


def _internal_link_metrics(links: list[dict[str, Any]], word_count: int) -> tuple[int, float, int]:
    n = len(links)
    targets: set[str] = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        href = (link.get("href") or "").strip()
        if href:
            targets.add(href.split("#", 1)[0])
    density = (n / max(word_count, 1)) * 1000
    return n, round(density, 2), len(targets)


def _external_link_metrics(links: list[dict[str, Any]]) -> tuple[int, int]:
    n = len(links)
    domains: set[str] = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        href = (link.get("href") or "").strip()
        m = re.match(r"^https?://([^/]+)/?", href)
        if m:
            d = m.group(1).lower().lstrip("www.")
            domains.add(d)
    return n, len(domains)


def _image_metrics(images: list[dict[str, Any]]) -> tuple[int, float]:
    n = len(images)
    if n == 0:
        return 0, 0.0
    with_alt = sum(
        1 for img in images
        if isinstance(img, dict) and (img.get("alt") or "").strip()
    )
    return n, round(with_alt / n * 100, 1)


def _schema_metrics(jsonld_types: list[str]) -> tuple[list[str], bool, bool, bool]:
    types_norm = [str(t).strip() for t in jsonld_types if t]
    trusted = [t for t in types_norm if t in _TRUST_SCHEMA_TYPES]
    return (
        sorted(set(trusted)),
        any(t == "FAQPage" for t in types_norm),
        any(t == "Organization" for t in types_norm),
        any(t == "BreadcrumbList" for t in types_norm),
    )


def _faq_detection(
    headings: list[dict[str, Any]],
    has_faq_schema: bool,
    body_text: str,
) -> tuple[list[str], int]:
    """Return ``(detected_questions, count)``.

    Two signals: H2/H3 strings shaped like questions; FAQ schema.
    The schema bit dominates count — when schema is present, every
    question-shaped heading is a likely FAQ entry.
    """
    questions: list[str] = []
    for h in headings or []:
        if not isinstance(h, dict):
            continue
        try:
            level = int(h.get("level") or 0)
        except (TypeError, ValueError):
            level = 0
        text = (h.get("text") or "").strip()
        if level not in (2, 3, 4) or not text:
            continue
        if _FAQ_QUESTION_RE.match(text) or text.endswith("?"):
            questions.append(text[:200])
    # Body-level question scan when schema says we should have an FAQ but
    # we didn't detect them in headings (some sites put the FAQ in an
    # accordion that emits <p> not <h*>).
    if has_faq_schema and not questions and body_text:
        body_qs = re.findall(
            r"(?:^|\n)\s*((?:What|Why|How|When|Who|Where|Which|Can|Does|"
            r"Do|Is|Are|Should|Will)[^\n?]{5,180}\?)",
            body_text, flags=re.MULTILINE,
        )
        questions = [q.strip()[:200] for q in body_qs[:15]]
    return questions[:30], len(questions)


def _cta_detection(
    internal_links: list[dict[str, Any]],
    external_links: list[dict[str, Any]],
) -> tuple[int, list[str]]:
    """Count distinct CTA-like anchors. Looks at internal + external both
    because some sites send conversions to a separate (sub)domain."""
    found: list[str] = []
    for link_list in (internal_links, external_links):
        for link in link_list:
            if not isinstance(link, dict):
                continue
            anchor = (link.get("anchor") or "").strip().lower()
            if not anchor:
                continue
            if anchor in _CTA_VOCAB or any(v in anchor for v in _CTA_VOCAB):
                found.append(anchor[:80])
    # Dedupe preserving order.
    seen: set[str] = set()
    deduped = [a for a in found if not (a in seen or seen.add(a))]
    return len(deduped), deduped[:20]


# ── public entry ────────────────────────────────────────────────────


def analyze_page(page) -> PageAnalysis:
    """Run the deterministic structural analysis on one CrawledPage.

    Accepts either a :class:`page_crawler.CrawledPage` or a CrawlerPageResult
    ORM row — both expose the same attribute surface.
    """
    headings = list(getattr(page, "headings", None) or getattr(page, "headings_json", None) or [])
    internal_links = list(
        getattr(page, "internal_links", None)
        or getattr(page, "internal_links_json", None)
        or []
    )
    external_links = list(
        getattr(page, "external_links", None)
        or getattr(page, "external_links_json", None)
        or []
    )
    images = list(
        getattr(page, "images", None)
        or getattr(page, "images_json", None)
        or []
    )
    videos = list(
        getattr(page, "videos", None)
        or getattr(page, "videos_json", None)
        or []
    )
    jsonld_types = list(
        getattr(page, "jsonld_types", None)
        or []
    )
    word_count = int(getattr(page, "word_count", 0) or 0)
    title = (getattr(page, "title", "") or "").strip()
    meta = (getattr(page, "meta_description", "") or "").strip()
    body = getattr(page, "body_text", "") or ""
    content_size_bytes = int(
        getattr(page, "content_size_bytes", 0)
        or getattr(page, "content_bytes", 0)
        or 0
    )

    h1_count = sum(1 for h in headings if isinstance(h, dict) and int(h.get("level") or 0) == 1)
    h2_count = sum(1 for h in headings if isinstance(h, dict) and int(h.get("level") or 0) == 2)
    h3_count = sum(1 for h in headings if isinstance(h, dict) and int(h.get("level") or 0) == 3)
    h4_plus = sum(1 for h in headings if isinstance(h, dict) and int(h.get("level") or 0) >= 4)

    outline = _build_outline(headings)
    int_n, int_density, int_unique = _internal_link_metrics(internal_links, word_count)
    ext_n, ext_unique = _external_link_metrics(external_links)
    img_n, alt_pct = _image_metrics(images)
    trusted, has_faq, has_org, has_brd = _schema_metrics(jsonld_types)
    faq_qs, faq_n = _faq_detection(headings, has_faq, body)
    cta_n, cta_list = _cta_detection(internal_links, external_links)

    return PageAnalysis(
        url=getattr(page, "url", ""),
        title=title,
        title_length=len(title),
        meta_description=meta,
        meta_description_length=len(meta),
        word_count=word_count,
        reading_time_minutes=round(word_count / 200, 1) if word_count else 0.0,
        content_size_bytes=content_size_bytes,
        h1_count=h1_count,
        h2_count=h2_count,
        h3_count=h3_count,
        h4_plus_count=h4_plus,
        heading_outline=outline,
        heading_outline_text=_outline_text_lines(outline),
        internal_link_count=int_n,
        internal_link_density_per_1k_words=int_density,
        unique_internal_targets=int_unique,
        external_link_count=ext_n,
        unique_external_domains=ext_unique,
        image_count=img_n,
        image_alt_coverage_pct=alt_pct,
        video_count=len(videos),
        jsonld_types=sorted(set(jsonld_types)),
        trusted_schema_present=trusted,
        has_faq_schema=has_faq,
        has_organization_schema=has_org,
        has_breadcrumb_schema=has_brd,
        detected_faq_questions=faq_qs,
        faq_question_count=faq_n,
        cta_count=cta_n,
        detected_ctas=cta_list,
    )


def to_dict(a: PageAnalysis) -> dict[str, Any]:
    def _node(n: HeadingNode) -> dict[str, Any]:
        return {
            "level": n.level,
            "text": n.text,
            "children": [_node(c) for c in n.children],
        }
    return {
        "url": a.url,
        "title": a.title,
        "title_length": a.title_length,
        "meta_description": a.meta_description,
        "meta_description_length": a.meta_description_length,
        "word_count": a.word_count,
        "reading_time_minutes": a.reading_time_minutes,
        "content_size_bytes": a.content_size_bytes,
        "h1_count": a.h1_count,
        "h2_count": a.h2_count,
        "h3_count": a.h3_count,
        "h4_plus_count": a.h4_plus_count,
        "heading_outline": [_node(n) for n in a.heading_outline],
        "heading_outline_text": a.heading_outline_text,
        "internal_link_count": a.internal_link_count,
        "internal_link_density_per_1k_words": a.internal_link_density_per_1k_words,
        "unique_internal_targets": a.unique_internal_targets,
        "external_link_count": a.external_link_count,
        "unique_external_domains": a.unique_external_domains,
        "image_count": a.image_count,
        "image_alt_coverage_pct": a.image_alt_coverage_pct,
        "video_count": a.video_count,
        "jsonld_types": a.jsonld_types,
        "trusted_schema_present": a.trusted_schema_present,
        "has_faq_schema": a.has_faq_schema,
        "has_organization_schema": a.has_organization_schema,
        "has_breadcrumb_schema": a.has_breadcrumb_schema,
        "detected_faq_questions": a.detected_faq_questions,
        "faq_question_count": a.faq_question_count,
        "cta_count": a.cta_count,
        "detected_ctas": a.detected_ctas,
        "seo_flags": a.seo_flags,
    }


def to_structure_dict(a: PageAnalysis, page) -> dict[str, Any]:
    """Raw per-page structure for the UI 'page structure' dropdown.

    ``to_dict`` carries counts + the heading outline, but NOT the actual
    internal-link / image arrays. This adds them (trimmed) so the
    frontend can render a replica of each competitor's — and our own —
    page structure: heading hierarchy, internal-linking layout, and the
    images each page uses. The orchestrator adds a ``clusters`` key from
    the LLM section payload.
    """
    def _node(n: HeadingNode) -> dict[str, Any]:
        return {
            "level": n.level,
            "text": n.text,
            "children": [_node(c) for c in n.children],
        }

    def _t(s: Any, n: int) -> str:
        s = (str(s) if s is not None else "").strip()
        return s if len(s) <= n else s[: n - 1] + "…"

    internal_links_raw = list(
        getattr(page, "internal_links", None)
        or getattr(page, "internal_links_json", None)
        or []
    )
    images_raw = list(
        getattr(page, "images", None)
        or getattr(page, "images_json", None)
        or []
    )

    internal_links: list[dict[str, Any]] = []
    seen_hrefs: set[str] = set()
    for link in internal_links_raw:
        if not isinstance(link, dict):
            continue
        href = (link.get("href") or "").strip()
        if not href or href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        internal_links.append({
            "anchor": _t(link.get("anchor") or "", 120),
            "href": _t(href, 300),
            "section": _t(link.get("section") or "", 100),
        })
        if len(internal_links) >= 120:
            break

    images: list[dict[str, Any]] = []
    for img in images_raw:
        if not isinstance(img, dict):
            continue
        images.append({
            "src": _t(img.get("src") or img.get("url") or "", 300),
            "alt": _t(img.get("alt") or "", 200),
            "section": _t(img.get("section") or "", 100),
        })
        if len(images) >= 60:
            break

    return {
        "url": a.url,
        "title": a.title,
        "word_count": a.word_count,
        "heading_counts": {
            "h1": a.h1_count, "h2": a.h2_count,
            "h3": a.h3_count, "h4_plus": a.h4_plus_count,
        },
        "heading_outline": [_node(n) for n in a.heading_outline],
        "internal_link_count": a.internal_link_count,
        "unique_internal_targets": a.unique_internal_targets,
        "internal_link_density_per_1k_words": a.internal_link_density_per_1k_words,
        "internal_links": internal_links,
        "image_count": a.image_count,
        "image_alt_coverage_pct": a.image_alt_coverage_pct,
        "images": images,
        "external_link_count": a.external_link_count,
        "unique_external_domains": a.unique_external_domains,
        "trusted_schema_present": a.trusted_schema_present,
        # ``clusters`` is added by the orchestrator from the LLM section
        # payload so the dropdown shows the smart topical clustering too.
        "clusters": [],
    }
