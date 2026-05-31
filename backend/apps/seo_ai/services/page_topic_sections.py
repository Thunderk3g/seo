"""LLM-driven intra-page topic-section clustering.

Different from ``competitor_clustering.py`` (which clusters a brand's
PAGES into topical groups) and from ``page_clusters_view`` (which
clusters CHUNKS of one page via KMeans on sentence-transformer
embeddings): this clusters the CONTENT of ONE page into
operator-readable topical sections via the LLM.

Why this view exists:
* Operator says: "show me what THIS page covers — its calculator
  widget, its tax-benefits section, its FAQ block, its CTAs — so I
  can compare section-by-section with a competitor page."
* The page's headings JSON is the most reliable section signal — the
  competitor crawler stamps each internal link / image with a
  ``section`` field (= nearest preceding heading), so we already know
  which links/images live in which section.
* The LLM groups those headings + their attached links into 5–10
  topical sections, gives each a clear name ("Premium Calculator",
  "Tax Benefits Under 80C", "Claim Settlement FAQ"), and surfaces what
  topics each covers.

The result feeds the Content Writer revamp comparison: "competitor
HDFC has a 'Premium Calculator' section we don't; we should add one."
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("seo.ai.page_topic_sections")


# ── dataclasses ──────────────────────────────────────────────────────


@dataclass
class TopicSectionLink:
    anchor: str
    href: str
    kind: str = ""


@dataclass
class TopicSection:
    section_id: int
    name: str
    rationale: str
    topics_covered: list[str] = field(default_factory=list)
    heading_texts: list[str] = field(default_factory=list)
    internal_links: list[TopicSectionLink] = field(default_factory=list)
    image_count: int = 0
    word_count: int = 0  # approx — sum of words across the heading slices


@dataclass
class PageTopicSections:
    url: str
    title: str
    snapshot_id: str
    total_headings: int
    total_internal_links: int
    sections: list[TopicSection]
    model_used: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    cached: bool
    cached_at: str = ""
    error: str = ""


# ── disk cache ───────────────────────────────────────────────────────


def _cache_dir() -> Path:
    from django.conf import settings as dj_settings

    seo_ai_cfg = getattr(dj_settings, "SEO_AI", None) or {}
    data_dir = Path(seo_ai_cfg.get("data_dir") or "backend/data")
    path = data_dir / "_page_section_cache"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path


def _model_tag(model: str) -> str:
    """Short stable tag for a model id so the cache key is provider-aware
    — clustering output differs by model, and serving a Groq-clustered
    payload after switching to Claude would silently under-report cost
    and skip the Claude pass entirely."""
    import hashlib

    if not model:
        return "default"
    return hashlib.sha1(model.encode("utf-8")).hexdigest()[:8]


def _cache_path(snapshot_id: str, url_b64: str, model: str = "") -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in (snapshot_id or ""))[:48]
    safeb = url_b64[:48]
    return _cache_dir() / f"{safe}__{safeb}__{_model_tag(model)}.json"


def _cache_read(snapshot_id: str, url_b64: str, ttl_seconds: int, model: str = "") -> dict | None:
    p = _cache_path(snapshot_id, url_b64, model)
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            envelope = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    if time.time() - (envelope.get("written_at_unix") or 0) > ttl_seconds:
        return None
    return envelope.get("data")


def _cache_write(snapshot_id: str, url_b64: str, data: dict, model: str = "") -> None:
    p = _cache_path(snapshot_id, url_b64, model)
    try:
        with p.open("w", encoding="utf-8") as f:
            json.dump({"written_at_unix": time.time(), "data": data}, f)
    except OSError as exc:  # noqa: BLE001
        logger.info("page section cache write failed: %s", exc)


# ── LLM prompt ───────────────────────────────────────────────────────


_SYSTEM_PROMPT = """You analyze ONE web page (Indian life-insurance
domain) and group its content into 5–10 named topical sections.

You will receive:
- ``page_title`` + ``page_meta`` for context.
- ``headings`` — array of {id, level, text}. Each heading is a section
  boundary on the page.
- ``internal_links`` — array of {id, anchor, href, section}. The
  ``section`` field is the nearest preceding heading text (the
  crawler stamps this at extract time).
- ``body_sample`` — first ~2500 chars of the page body for additional
  context.

Your job is to cluster the headings into 5–10 NAMED topical sections
that describe what the page covers. Cluster names should be operator-
readable, e.g. "Premium Calculator", "Tax Benefits Under 80C",
"Claim Settlement FAQ", "Plan Comparison Table", "Rider Add-ons",
"Customer Testimonials".

For each section also list ``topics_covered`` (2-5 short noun phrases)
and the ``heading_ids`` it contains. Reference internal_link ids that
naturally belong to that section so the operator sees which CTAs /
calculator widgets / sibling pages live there.

CRITICAL RULES:
1. EVERY heading id must appear in exactly ONE section's heading_ids.
2. internal_link_ids should reference ids that semantically belong to
   that section (use the ``section`` field as a strong signal).
3. heading_ids and internal_link_ids must be a JSON ARRAY of separate
   INTEGERS. DO NOT concatenate ids.
   CORRECT:  "heading_ids": [3, 7, 12]
   WRONG:    "heading_ids": [371225]
4. Produce 5–10 sections. Merge thin clusters.
5. Return ONLY this JSON object:

{
  "sections": [
    {
      "name": "<2-5 words>",
      "rationale": "<one short sentence>",
      "topics_covered": ["<noun phrase>", "<noun phrase>"],
      "heading_ids": [3, 7, 12],
      "internal_link_ids": [4, 9, 15]
    }
  ]
}

No prose, no markdown fences around the JSON.
""".strip()


def _truncate(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# ── core builder ─────────────────────────────────────────────────────


def _split_concatenated_ids(raw_id, valid: int, seen: set[int]) -> list[int]:
    """Same defensive parser used in competitor_clustering — the gpt-oss
    class occasionally emits page_ids as ``[371225]`` instead of
    ``[3, 7, 12, 25]``. Greedy split on 1-2 digit prefixes."""
    out: list[int] = []
    if isinstance(raw_id, str):
        for token in raw_id.replace(",", " ").split():
            try:
                t = int(token)
                if 0 <= t < valid and t not in seen:
                    out.append(t)
                    seen.add(t)
            except (TypeError, ValueError):
                continue
        return out
    try:
        idx = int(raw_id)
    except (TypeError, ValueError):
        return out
    if 0 <= idx < valid:
        if idx not in seen:
            out.append(idx)
            seen.add(idx)
        return out
    digits = str(idx)
    cursor = 0
    while cursor < len(digits):
        matched = False
        for take in (2, 1):
            if cursor + take > len(digits):
                continue
            cand = int(digits[cursor : cursor + take])
            if 0 <= cand < valid and cand not in seen:
                out.append(cand)
                seen.add(cand)
                cursor += take
                matched = True
                break
        if not matched:
            cursor += 1
    return out


def build_page_topic_sections(
    *,
    page,                       # CrawlerPageResult
    cache_ttl_seconds: int = 24 * 3600,
    force_refresh: bool = False,
    provider=None,
    model: str | None = None,
) -> PageTopicSections:
    """LLM-cluster one page's content into named topical sections.

    Disk-cached per (snapshot_id, url_b64, model) for 24 h. Cold call:
    ~10-15 s. ``provider``/``model`` let the content_writer route this
    through Claude (Haiku) without touching the global provider; the
    model is part of the cache key so a provider switch re-clusters.
    """
    import base64

    from ..llm import get_provider

    provider = provider or get_provider()
    resolved_model = model or getattr(provider, "model", "") or ""

    snapshot_id = str(page.snapshot_id)
    url_b64 = base64.urlsafe_b64encode(
        (page.url or "").encode("utf-8"),
    ).decode("ascii").rstrip("=")

    if not force_refresh:
        cached = _cache_read(snapshot_id, url_b64, cache_ttl_seconds, resolved_model)
        if cached is not None:
            cached["cached"] = True
            return _from_dict(cached)

    raw_headings = list(page.headings_json or [])
    raw_links = list(page.internal_links_json or [])
    raw_images = list(page.images_json or [])

    # Cap to keep the prompt within Groq's 8k TPM budget. The competitor
    # crawler stamps ``section`` on links/images = the nearest preceding
    # heading text, so even after the cap we keep meaningful
    # (section → link) ties.
    headings = [
        {
            "id": i,
            "level": int(h.get("level") or 0) if isinstance(h, dict) else 0,
            "text": _truncate(
                (h.get("text") if isinstance(h, dict) else str(h or "")), 80,
            ),
        }
        for i, h in enumerate(raw_headings[:40])
        if (isinstance(h, dict) and (h.get("text") or "").strip())
    ]
    internal_links = [
        {
            "id": i,
            "anchor": _truncate(l.get("anchor", ""), 50),
            "href": _truncate(l.get("href", ""), 80),
            "kind": l.get("kind", ""),
            "section": _truncate(l.get("section", ""), 50),
        }
        for i, l in enumerate(raw_links[:20])
        if isinstance(l, dict)
    ]

    if not headings:
        return PageTopicSections(
            url=page.url,
            title=page.title or "",
            snapshot_id=snapshot_id,
            total_headings=0,
            total_internal_links=len(raw_links),
            sections=[],
            model_used="",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            cached=False,
            error=(
                "page has no headings — cannot identify topical sections. "
                "Re-crawl the URL or check whether the page was rendered."
            ),
        )

    user_payload = {
        "page_title": _truncate(page.title or "", 160),
        "page_meta": _truncate(page.meta_description or "", 200),
        "page_url": page.url,
        "headings": headings,
        "internal_links": internal_links,
        "body_sample": _truncate((page.body_text or "").strip(), 1200),
    }

    user_content = (
        "Cluster the headings of this page into 5–10 named topical "
        "sections. Every heading id must appear in exactly one section.\n\n"
        "<facts>\n```json\n"
        + json.dumps(user_payload, default=str)
        + "\n```\n</facts>"
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        resp = provider.complete(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("page topic-section LLM call failed for %s", page.url)
        return PageTopicSections(
            url=page.url,
            title=page.title or "",
            snapshot_id=snapshot_id,
            total_headings=len(headings),
            total_internal_links=len(internal_links),
            sections=[],
            model_used=resolved_model,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            cached=False,
            error=f"LLM call failed: {exc}",
        )

    text = (resp.content or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return PageTopicSections(
            url=page.url,
            title=page.title or "",
            snapshot_id=snapshot_id,
            total_headings=len(headings),
            total_internal_links=len(internal_links),
            sections=[],
            model_used=resolved_model,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            cost_usd=resp.cost_usd,
            cached=False,
            error=f"LLM returned non-JSON: {exc}",
        )

    sections_raw = parsed.get("sections") or []
    sections: list[TopicSection] = []
    seen_h: set[int] = set()
    seen_l: set[int] = set()
    n_h = len(headings)
    n_l = len(internal_links)

    for i, s in enumerate(sections_raw):
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or f"Section {i+1}")[:80]
        rationale = str(s.get("rationale") or "")[:240]
        topics = [
            str(t)[:80]
            for t in (s.get("topics_covered") or [])[:6]
            if t
        ]

        h_ids: list[int] = []
        for raw in (s.get("heading_ids") or []):
            h_ids.extend(_split_concatenated_ids(raw, n_h, seen_h))
        l_ids: list[int] = []
        for raw in (s.get("internal_link_ids") or []):
            l_ids.extend(_split_concatenated_ids(raw, n_l, seen_l))

        if not h_ids:
            continue

        heading_texts = [headings[hi]["text"] for hi in h_ids]
        section_links = [
            TopicSectionLink(
                anchor=internal_links[li]["anchor"],
                href=internal_links[li]["href"],
                kind=internal_links[li]["kind"],
            )
            for li in l_ids
        ]
        sections.append(TopicSection(
            section_id=i,
            name=name,
            rationale=rationale,
            topics_covered=topics,
            heading_texts=heading_texts,
            internal_links=section_links,
            image_count=0,  # set below from raw_images section field
            word_count=0,
        ))

    # Catch-all for any heading ids the LLM dropped.
    unassigned = [i for i in range(n_h) if i not in seen_h]
    if unassigned:
        sections.append(TopicSection(
            section_id=len(sections),
            name="Other / Uncategorised",
            rationale=(
                "Headings the LLM didn't cluster — kept so the section "
                "list never silently drops page content."
            ),
            topics_covered=[],
            heading_texts=[headings[hi]["text"] for hi in unassigned],
            internal_links=[],
            image_count=0,
            word_count=0,
        ))

    # Approximate image_count per section using the ``section`` field on
    # raw_images = nearest preceding heading text. Cheap O(N * M) since
    # both arrays cap at ~60.
    for sec in sections:
        sec.image_count = sum(
            1
            for img in raw_images
            if isinstance(img, dict)
            and any(
                (img.get("section") or "").strip().lower()
                == (h or "").strip().lower()
                for h in sec.heading_texts
            )
        )

    result = PageTopicSections(
        url=page.url,
        title=page.title or "",
        snapshot_id=snapshot_id,
        total_headings=n_h,
        total_internal_links=n_l,
        sections=sections,
        model_used=getattr(provider, "model", "") or "",
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
        cost_usd=resp.cost_usd,
        cached=False,
    )

    payload = _to_dict(result)
    _cache_write(snapshot_id, url_b64, payload, resolved_model)
    return result


def _to_dict(r: PageTopicSections) -> dict:
    return {
        "url": r.url,
        "title": r.title,
        "snapshot_id": r.snapshot_id,
        "total_headings": r.total_headings,
        "total_internal_links": r.total_internal_links,
        "sections": [
            {
                "section_id": s.section_id,
                "name": s.name,
                "rationale": s.rationale,
                "topics_covered": s.topics_covered,
                "heading_texts": s.heading_texts,
                "internal_links": [
                    {"anchor": l.anchor, "href": l.href, "kind": l.kind}
                    for l in s.internal_links
                ],
                "image_count": s.image_count,
                "word_count": s.word_count,
            }
            for s in r.sections
        ],
        "model_used": r.model_used,
        "tokens_in": r.tokens_in,
        "tokens_out": r.tokens_out,
        "cost_usd": r.cost_usd,
        "cached": r.cached,
        "cached_at": r.cached_at,
        "error": r.error,
    }


def _from_dict(d: dict) -> PageTopicSections:
    sections: list[TopicSection] = []
    for s in d.get("sections") or []:
        links = [
            TopicSectionLink(
                anchor=l.get("anchor", ""),
                href=l.get("href", ""),
                kind=l.get("kind", ""),
            )
            for l in (s.get("internal_links") or [])
        ]
        sections.append(TopicSection(
            section_id=int(s.get("section_id") or 0),
            name=str(s.get("name") or ""),
            rationale=str(s.get("rationale") or ""),
            topics_covered=list(s.get("topics_covered") or []),
            heading_texts=list(s.get("heading_texts") or []),
            internal_links=links,
            image_count=int(s.get("image_count") or 0),
            word_count=int(s.get("word_count") or 0),
        ))
    return PageTopicSections(
        url=str(d.get("url") or ""),
        title=str(d.get("title") or ""),
        snapshot_id=str(d.get("snapshot_id") or ""),
        total_headings=int(d.get("total_headings") or 0),
        total_internal_links=int(d.get("total_internal_links") or 0),
        sections=sections,
        model_used=str(d.get("model_used") or ""),
        tokens_in=int(d.get("tokens_in") or 0),
        tokens_out=int(d.get("tokens_out") or 0),
        cost_usd=float(d.get("cost_usd") or 0.0),
        cached=bool(d.get("cached")),
        cached_at=str(d.get("cached_at") or ""),
        error=str(d.get("error") or ""),
    )
