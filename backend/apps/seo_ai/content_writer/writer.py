"""The writer agent — gap-driven, brand-aware, evidence-grounded.

Two-stage design (this is what makes full-length output reliable):

1. **Plan call** → a small JSON object: rewrite_strategy, title, meta, H1,
   a deep outline (8-14 H2s with H3s + estimated_words + closes_gaps),
   FAQs, internal-link plan, JSON-LD blocks, tech recommendations. Small
   and structured, so it always parses.

2. **Body call** → the COMPLETE page as raw HTML (header + every section
   with full copy + tables + footer with IRDAI/T&C). Plain HTML, NOT JSON
   — so a token-limit truncation just yields a slightly shorter (still
   valid) page instead of unparseable JSON, and the plan fields are never
   lost. This is why we left Groq: Claude (Sonnet, 200k ctx) writes the
   full 3000+ word page in one body call.

Both calls go through the content-writer-scoped Claude provider
(:func:`apps.seo_ai.llm.get_content_writer_provider`). Brand rules, IRDAI
compliance and gap-closing live in the shared prompt prefix.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("seo.ai.content_writer.writer")


# ── output dataclass ─────────────────────────────────────────────────


@dataclass
class WriterResult:
    our_url: str
    rewrite: dict[str, Any] = field(default_factory=dict)
    model_used: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    error: str = ""


# ── shared prompt prefix (brand / compliance / gap rules) ────────────


_WRITER_SHARED = """You are the senior SEO content strategist and
copywriter for **Bajaj Life Insurance** (legally renamed in 2024 from
"Bajaj Allianz Life Insurance" — you NEVER use the legacy name in new copy).

You are revamping ONE Bajaj Life Insurance page to out-rank the URLs Google
currently shows for the same search intent. You are given a JSON <facts>
block with:
* `target_query` — the search a real user types to land on a page like ours.
* `serp_snapshot` — People Also Ask, featured snippet, AI overview.
* `our_page` — current title, meta, H1, body excerpt, outline, internal-link
  list, counts, schema.
* `competitor_pages` — top SERP rivals, each with their outline + LLM-named
  topical sections + detected FAQs.
* `gap_report` — multi-dimensional deficits + per-competitor section gaps.
* `seo_overlay` — deterministic best-practice issues on our current page.
* `internal_link_pool` — the ONLY URLs you may link to (no invented slugs).
* `operator_steer` — optional free-text instruction from the operator.

NON-NEGOTIABLE RULES
1. Brand: always "Bajaj Life Insurance" / "Bajaj Life", NEVER "Bajaj
   Allianz". Voice: empathetic, expert, regulated — the calm advisor at a
   kitchen table, not marketing hype. No exclamation marks; no "#1" /
   "best in India" claims.
2. IRDAI compliance: never promise specific returns / payouts / "guaranteed
   wealth"; label illustrative figures "for example" / "illustrative"; tax
   language is "as per prevailing tax laws" (never a specific slab); keep
   "T&C apply" near benefit statements.
3. Depth: this is a COMPLETE, comprehensive page — the single best, most
   useful page on this topic in the Indian market. Target 3000+ words. Do
   NOT pad, but cover every subtopic the competitors cover AND the angles
   they miss.
4. Gap-closing: `gap_report.top_priority_actions` is your contract — every
   priority-3 dimension and every section covered by ≥2 competitors must be
   addressed. Match or exceed the deepest competitor.
5. FAQs: cover every People-Also-Ask question (top 8 if more). Answers
   50-120 words, conversational, referencing the relevant Bajaj Life product
   family by category (term / ULIP / savings / retirement / child) where it
   fits — never invent a specific product name not present in our_page.
6. Internal links: choose ONLY from `internal_link_pool` — never invent
   slugs. Spread 8-15 contextual links across sections.
7. Schema: WebPage + BreadcrumbList + Organization always; FAQPage when
   there are FAQs; FinancialProduct for plan / product pages (brand =
   "Bajaj Life Insurance").
""".strip()


# ── stage A: the plan (small JSON) ───────────────────────────────────


_PLAN_SYSTEM = _WRITER_SHARED + """

══════════════════════════════════════════════════════════════════════
TASK — PRODUCE THE REWRITE PLAN
══════════════════════════════════════════════════════════════════════
Output ONE JSON object (no body copy yet, no markdown fences, no prose).
Fill EVERY field. The outline MUST be deep — 8-14 H2 sections, each with
H3 sub-headings where useful — so the body can comfortably reach 3000+
words and close every priority gap.

{
  "rewrite_strategy": "2-3 sentences on the gap-closing approach.",
  "target_word_count": 3200,
  "title": {"text": "50-60 chars, primary keyword + Bajaj Life", "char_count": 57, "rationale": "..."},
  "meta_description": {"text": "140-160 chars, keyword + CTA", "char_count": 155, "rationale": "..."},
  "h1": {"text": "...", "rationale": "..."},
  "outline": [
    {"level": 2, "heading": "H2 section name", "estimated_words": 340,
     "rationale": "why this section is here",
     "closes_gaps": ["section:Tax Benefits", "dimension:heading_breadth_h2"],
     "sub_headings": [{"level": 3, "heading": "H3 sub-section"}]}
  ],
  "faqs": [{"question": "ends in ?", "answer": "50-120 words", "source": "paa|detected|new"}],
  "internal_links_plan": [
    {"anchor": "anchor text", "target_url": "<from internal_link_pool>",
     "section": "H2 name where it appears", "rationale": "..."}
  ],
  "tech_recommendations": ["actionable technical-SEO fix", "..."]
}

Do NOT emit JSON-LD / schema — it is generated separately. Keep every
`rationale` to ONE short clause and FAQ answers to 50-90 words so the JSON
stays compact.

Self-check: title 50-60 chars? meta 140-160? outline closes every
priority-3 gap? every internal_links_plan.target_url is from the pool?
"Bajaj Life Insurance" used, "Bajaj Allianz" absent? Emit ONLY the JSON.
""".strip()


# ── stage B: the body (raw HTML) ─────────────────────────────────────


_BODY_SYSTEM = _WRITER_SHARED + """

══════════════════════════════════════════════════════════════════════
TASK — WRITE THE COMPLETE PAGE BODY AS RAW HTML
══════════════════════════════════════════════════════════════════════
You are given the approved <plan> (title, H1, outline, FAQs, internal
links) plus the <facts>. Write the FULL, publish-ready page — not a
summary. Produce, in order:

1. `<header>` — a Bajaj Life Insurance brand bar + simple nav
   (Home / Plans / About / Contact) and the `<h1>`.
2. The article — an intro paragraph, then EVERY H2 and H3 from the plan's
   outline with full copy (each H2 300-600 words, 2-4 paragraphs and/or a
   `<ul>`/`<ol>` with concrete items), and at least one `<table>` where a
   comparison / eligibility / premium-illustration fits. Place the planned
   internal links as inline `<a href="...">` anchors in the right sections.
   Render every planned FAQ in a "Frequently Asked Questions" `<section>`.
3. `<footer>` — Bajaj Life Insurance footer with quick links, the IRDAI
   registration line, and a "T&C apply / tax benefits as per prevailing
   laws / read the sales brochure carefully before concluding a sale"
   compliance disclosure.

Use semantic tags (`<section>`, `<h2>`, `<h3>`, `<p>`, `<ul>`, `<table>`,
`<a>`). Output ONLY raw HTML — NO JSON, NO markdown code fences, NO
commentary before or after. Aim for 3000+ words of genuinely useful copy.
""".strip()


# ── input shaping ────────────────────────────────────────────────────


def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _shape_our_page(our_analysis, our_page_row, our_sections) -> dict[str, Any]:
    return {
        "url": our_analysis.url,
        "title": our_analysis.title,
        "title_length": our_analysis.title_length,
        "meta_description": our_analysis.meta_description,
        "meta_description_length": our_analysis.meta_description_length,
        "h1": [
            (h.get("text") or "").strip()
            for h in (getattr(our_page_row, "headings_json", None) or [])
            if isinstance(h, dict) and int(h.get("level") or 0) == 1
        ][:1],
        "body_excerpt": _truncate(
            getattr(our_page_row, "body_text", "") or "", 3000,
        ),
        "word_count": our_analysis.word_count,
        "content_size_kb": round(our_analysis.content_size_bytes / 1024, 1),
        "outline": our_analysis.heading_outline_text,
        "internal_link_count": our_analysis.internal_link_count,
        "internal_link_density_per_1k_words": our_analysis.internal_link_density_per_1k_words,
        "image_count": our_analysis.image_count,
        "image_alt_coverage_pct": our_analysis.image_alt_coverage_pct,
        "trusted_schema_present": our_analysis.trusted_schema_present,
        "faq_question_count": our_analysis.faq_question_count,
        "detected_faq_questions": our_analysis.detected_faq_questions,
        "sections": [
            {
                "title": s.get("title"),
                "summary": _truncate(s.get("summary") or "", 200),
            }
            for s in (our_sections.get("sections") or [])
        ],
    }


def _shape_competitor(domain: str, a, sections_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "domain": domain,
        "url": a.url,
        "title": a.title,
        "meta_description": _truncate(a.meta_description, 200),
        "word_count": a.word_count,
        "content_size_kb": round(a.content_size_bytes / 1024, 1),
        "h1": a.heading_outline_text[:1] if a.heading_outline_text else [],
        "outline": a.heading_outline_text[:40],
        "internal_link_count": a.internal_link_count,
        "external_unique_domains": a.unique_external_domains,
        "image_count": a.image_count,
        "image_alt_coverage_pct": a.image_alt_coverage_pct,
        "faq_question_count": a.faq_question_count,
        "detected_faq_questions": a.detected_faq_questions[:10],
        "trusted_schema_present": a.trusted_schema_present,
        "cta_count": a.cta_count,
        "sections": [
            {
                "title": s.get("title"),
                "summary": _truncate(s.get("summary") or "", 200),
                "headings": [
                    (h.get("text") or "").strip()
                    for h in (s.get("headings") or [])
                ][:5],
            }
            for s in (sections_payload.get("sections") or [])
        ],
    }


def _shape_internal_link_pool(our_page_row) -> list[dict[str, Any]]:
    links = list(getattr(our_page_row, "internal_links_json", None) or [])
    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        href = (link.get("href") or "").strip()
        if not href or href in seen:
            continue
        seen.add(href)
        pool.append({
            "anchor": _truncate(link.get("anchor") or "", 80),
            "target_url": href,
            "section": _truncate(link.get("section") or "", 60),
        })
        if len(pool) >= 80:
            break
    return pool


# ── helpers ──────────────────────────────────────────────────────────


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    """Parse a JSON object, tolerating a ```json fence and trailing prose."""
    text = (raw or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _build_json_ld(plan: dict[str, Any], our_url: str) -> list[dict[str, Any]]:
    """Deterministically build the JSON-LD blocks from the plan. Mechanical
    and always-valid — far more reliable (and token-cheaper) than asking the
    model to emit nested schema. Covers WebPage, BreadcrumbList,
    Organization, FAQPage (when FAQs exist) and FinancialProduct for
    plan/product pages."""
    title = ((plan.get("title") or {}).get("text") or "Bajaj Life Insurance").strip()
    meta = ((plan.get("meta_description") or {}).get("text") or "").strip()
    org = {
        "@type": "Organization",
        "name": "Bajaj Life Insurance",
        "url": "https://www.bajajlifeinsurance.com/",
    }
    blocks: list[dict[str, Any]] = [
        {"type": "WebPage", "json_ld": {
            "@context": "https://schema.org", "@type": "WebPage",
            "name": title, "description": meta, "url": our_url,
        }},
        {"type": "BreadcrumbList", "json_ld": {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home",
                 "item": "https://www.bajajlifeinsurance.com/"},
                {"@type": "ListItem", "position": 2, "name": title, "item": our_url},
            ],
        }},
        {"type": "Organization", "json_ld": {"@context": "https://schema.org", **org}},
    ]
    faqs = plan.get("faqs") or []
    if faqs:
        blocks.append({"type": "FAQPage", "json_ld": {
            "@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f.get("question", ""),
                 "acceptedAnswer": {"@type": "Answer", "text": f.get("answer", "")}}
                for f in faqs if isinstance(f, dict) and f.get("question")
            ],
        }})
    low = (our_url or "").lower()
    if any(tok in low for tok in ("-plan", "-plans", "-insurance", "ulip", "term", "savings", "retirement", "child")):
        blocks.append({"type": "FinancialProduct", "json_ld": {
            "@context": "https://schema.org", "@type": "FinancialProduct",
            "name": title, "description": meta, "url": our_url,
            "provider": {"@type": "Organization", "name": "Bajaj Life Insurance"},
        }})
    return blocks


def _strip_html_fence(raw: str) -> str:
    """Drop a leading ```html / ``` fence and trailing ``` the model may add."""
    text = (raw or "").strip()
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


# ── public entry ────────────────────────────────────────────────────


def generate_revamp(
    *,
    our_url: str,
    our_analysis,                    # PageAnalysis
    our_page_row,                    # CrawlerPageResult
    our_sections: dict[str, Any],
    competitor_analyses: list[tuple[str, Any]],
    competitor_sections: dict[str, dict[str, Any]],
    gap_report_dict: dict[str, Any],
    seo_overlay_dict: dict[str, Any],
    serp_snapshot: dict[str, Any],
    operator_prompt: str = "",
    provider=None,
) -> WriterResult:
    """Run the two-stage writer. Returns a :class:`WriterResult`.

    Stage A (plan) is a small JSON call; stage B (body) is a raw-HTML call.
    Costs/tokens from both stages are summed onto the result.
    """
    from django.conf import settings

    from ..llm import get_content_writer_provider

    provider = provider or get_content_writer_provider()
    cw = getattr(settings, "CONTENT_WRITER", None) or {}
    writer_max_tokens = int(cw.get("writer_max_tokens", 16000))
    result = WriterResult(our_url=our_url, model_used=getattr(provider, "model", "") or "")

    payload = {
        "target_query": serp_snapshot.get("primary_query", ""),
        "serp_snapshot": {
            "people_also_ask": serp_snapshot.get("people_also_ask") or [],
            "featured_snippet": serp_snapshot.get("featured_snippet"),
            "ai_overview": serp_snapshot.get("ai_overview"),
        },
        "operator_steer": operator_prompt or "",
        "our_page": _shape_our_page(our_analysis, our_page_row, our_sections),
        "competitor_pages": [
            _shape_competitor(
                domain, a, competitor_sections.get(a.url) or {"sections": []},
            )
            for domain, a in competitor_analyses
        ],
        "gap_report": {
            "top_priority_actions": gap_report_dict.get("top_priority_actions") or [],
            "dimensions": [
                {
                    "dimension": d.get("dimension"),
                    "our_value": d.get("our_value"),
                    "competitor_median": d.get("competitor_median"),
                    "delta_vs_median": d.get("delta_vs_median"),
                    "priority": d.get("priority"),
                    "headline": d.get("headline"),
                }
                for d in (gap_report_dict.get("dimensions") or [])
            ],
            "section_gaps": [
                {
                    "competitor": sg.get("competitor_domain"),
                    "section_title": sg.get("section_title"),
                    "summary": sg.get("summary"),
                    "priority": sg.get("priority"),
                }
                for sg in (gap_report_dict.get("section_gaps") or [])
            ][:20],
        },
        "seo_overlay": {
            "score": seo_overlay_dict.get("score"),
            "counts": seo_overlay_dict.get("counts"),
            "issues": [
                {
                    "code": i.get("code"),
                    "severity": i.get("severity"),
                    "message": i.get("message"),
                    "target": i.get("target"),
                }
                for i in (seo_overlay_dict.get("issues") or [])
            ],
        },
        "internal_link_pool": _shape_internal_link_pool(our_page_row),
    }
    facts = (
        "<facts>\n```json\n"
        + json.dumps(payload, indent=2, default=str)
        + "\n```\n</facts>\n"
    )

    t0 = time.time()

    # ── Stage A: plan (small JSON) ───────────────────────────────────
    try:
        plan_resp = provider.complete(
            messages=[
                {"role": "system", "content": _PLAN_SYSTEM},
                {"role": "user", "content": "Produce the rewrite PLAN as one JSON object.\n\n" + facts},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
            # Generous ceiling — a deep outline + FAQs + link plan can run
            # several thousand tokens; truncation here breaks the JSON.
            max_tokens=12000,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("writer plan call failed")
        result.error = f"LLM call failed (plan): {exc}"
        result.latency_seconds = round(time.time() - t0, 2)
        return result

    result.tokens_in += plan_resp.tokens_in
    result.tokens_out += plan_resp.tokens_out
    result.cost_usd += plan_resp.cost_usd
    result.model_used = plan_resp.model or result.model_used

    plan = _parse_json_object(plan_resp.content or "")
    if plan is None:
        result.error = "plan returned non-JSON"
        result.latency_seconds = round(time.time() - t0, 2)
        return result

    # JSON-LD is built deterministically from the plan — reliable + cheap.
    plan["json_ld_blocks"] = _build_json_ld(plan, our_url)

    # ── Stage B: body (raw HTML) ─────────────────────────────────────
    plan_for_body = {
        k: plan.get(k)
        for k in ("title", "h1", "outline", "faqs", "internal_links_plan", "target_word_count")
    }
    body_user = (
        "Write the complete page body as raw HTML following this approved "
        "plan. Output ONLY HTML.\n\n<plan>\n```json\n"
        + json.dumps(plan_for_body, indent=2, default=str)
        + "\n```\n</plan>\n\n"
        + facts
    )
    try:
        body_resp = provider.complete(
            messages=[
                {"role": "system", "content": _BODY_SYSTEM},
                {"role": "user", "content": body_user},
            ],
            temperature=0.5,
            max_tokens=writer_max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        # The plan is intact — return it without a body rather than failing
        # the whole revamp.
        logger.exception("writer body call failed")
        result.rewrite = plan
        result.error = f"LLM call failed (body): {exc}"
        result.latency_seconds = round(time.time() - t0, 2)
        return result

    result.tokens_in += body_resp.tokens_in
    result.tokens_out += body_resp.tokens_out
    result.cost_usd += body_resp.cost_usd

    body_html = _strip_html_fence(body_resp.content or "")
    plan["body_html"] = body_html
    if not body_html:
        result.error = "body call returned empty HTML"
    result.rewrite = plan
    result.latency_seconds = round(time.time() - t0, 2)
    return result
