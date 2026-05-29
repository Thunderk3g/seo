"""RevampWriterAgent — rewrite ONE Bajaj URL to outperform N competitor versions.

Counterpart to the legacy ``content_writer.py`` agent (which took a fixed
"our + 1 competitor" shape). This one operates on a ``RevampPayload``
assembled by ``services/page_revamp.py``:

    - our:     live-crawled, full signals (title, meta, headings,
               internal_links, body excerpt, CWV, Semrush keywords).
    - them:    list of (CounterpartMatch, PageSignals) — one entry per
               competitor brand whose closest page was matched against
               ours by URL+title overlap.

The agent's job: produce a single ``RevampProposal`` that proposes a
new title / meta / heading outline / body sections / FAQ / CTAs / HTML
draft / internal-link recommendations / tech recommendations — each
generated string carrying a ``source_ref`` into the evidence dict so the
existing critic at ``agents/critic.py:verify_generation`` can drop any
unbacked hallucinations before the operator sees them.

Evidence-dict shape (flat, citable):

    our:title                          (str)
    our:meta_description               (str)
    our:url                            (str)
    our:body_excerpt                   (str, capped 4000)
    our:headings[<i>]                  ({level, text})
    our:internal_links[<i>]            ({anchor, href, kind, section})
    our:cwv:mobile                     ({lcp_ms, cls, inp_ms, pagespeed_score})
    our:cwv:desktop                    ({lcp_ms, cls, inp_ms, pagespeed_score})
    our:semrush:keywords[<i>]          ({keyword, position, search_volume, ...})
    their:<brand>:title                (str)
    their:<brand>:meta_description     (str)
    their:<brand>:url                  (str)
    their:<brand>:body_excerpt         (str)
    their:<brand>:headings[<i>]        ({level, text})
    their:<brand>:internal_links[<i>]  ({anchor, href, kind})
    their:<brand>:cwv:mobile           ({...})
    their:<brand>:cwv:desktop          ({...})
    their:<brand>:semrush:keywords[<i>] ({...})

A free-text ``prompt`` from the operator (optional) flows into the user
instruction verbatim so an operator can steer with "make it shorter",
"focus on tax benefits", "target term insurance for women" etc.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ..llm import LLMProvider, get_provider
from .critic import verify_generation

logger = logging.getLogger("seo.ai.agents.revamp_writer")


# ── public dataclass ──────────────────────────────────────────────────


@dataclass
class RevampResult:
    our_url: str
    competitor_urls: list[str]
    prompt: str
    evidence_dict: dict[str, Any]
    raw_proposal: dict[str, Any]
    filtered_proposal: dict[str, Any]
    critic_verdict: dict[str, Any]
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    error: str = ""


# ── prompts ───────────────────────────────────────────────────────────


_SYSTEM_PROMPT = """You are an SEO content rewriter for Bajaj Life Insurance
(rebranded from "Bajaj Allianz Life Insurance" — never emit the legacy
brand). Your job is to revamp ONE Bajaj page so it outperforms the
matched competitor pages on Indian life-insurance search.

You will be given:
1. ``our_page`` — our current page (URL, title, meta, headings, body
   excerpt, internal links, CWV scores, Semrush keywords we already rank for).
2. ``competitor_pages`` — a list of competitor counterparts. Each entry
   has the same shape plus a ``brand`` field. These are NOT identical
   topics — they're competitors' best-effort versions of the same page
   intent. Use their structure, depth, and topic coverage as inspiration.
3. ``operator_prompt`` — free-text steering from the operator. May be
   empty. If present, follow it as a soft override (e.g. "focus on tax",
   "shorten meta", "include FAQ for nominee changes").
4. ``evidence_patterns`` — describes the namespaces + array bounds for
   citable ``source_ref`` values. You construct refs by combining a
   scalar name (e.g. ``our:title``, ``their:hdfclife.com:meta_description``)
   or an array name + index (e.g. ``our:headings[3]``,
   ``their:hdfclife.com:internal_links[12]``). Array indices MUST be
   within the declared count. Refs outside the patterns are dropped by
   the critic — don't invent.

Output a JSON object with this exact shape:

{
  "proposed_title":             {"text": "...", "source_ref": "<key>"},
  "proposed_meta_description":  {"text": "...", "source_ref": "<key>"},
  "proposed_headings": [
    {"level": 1, "text": "...", "source_ref": "<key>", "rationale": "..."},
    {"level": 2, "text": "...", "source_ref": "<key>", "rationale": "..."}
  ],
  "proposed_internal_links": [
    {"anchor": "...", "target_url": "...", "section": "...",
     "source_ref": "<key>", "rationale": "..."}
  ],
  "proposed_body_sections": [
    {"heading_text": "...", "paragraphs": ["...", "..."],
     "source_ref": "<key>", "rationale": "..."}
  ],
  "proposed_faq": [
    {"question": "...", "answer": "...",
     "source_ref": "<key>", "rationale": "..."}
  ],
  "proposed_ctas": [
    {"text": "Calculate premium", "placement": "after hero | end of body | sidebar",
     "source_ref": "<key>"}
  ],
  "tech_recommendations": [
    {"area": "lcp" | "cls" | "inp" | "pagespeed" | "schema",
     "current": "<our value>", "target": "<benchmark from competitors>",
     "suggestion": "<concrete fix>", "source_ref": "<key>"}
  ],
  "improved_html": "<full body HTML draft using your proposed_title as <h1>, proposed_headings as <h2>/<h3>, proposed_body_sections as <p> paragraphs under each heading, proposed_faq as a <section> with <details><summary> elements, proposed_ctas inline as <a class='cta'>. No <html> or <head> — body content only.>",
  "improved_markdown": "<same content but Markdown>",
  "competitor_gap_summary": [
    {"brand": "<name>", "gap": "<one-line: what they have we don't>"}
  ],
  "overall_rationale": "2-4 sentences on the rewrite strategy."
}

Rules — non-negotiable:

* ``source_ref`` MUST be a well-formed reference per ``evidence_patterns``
  (scalar name or array_name[idx] within bounds). The server's critic
  validates each ref against the canonical evidence dict — refs outside
  the patterns are dropped.
* For ``proposed_title`` and ``proposed_meta_description``, cite ``our:title``
  / ``our:meta_description`` as the source. The text is YOUR rewrite; the
  ref says "I'm rewriting THIS original."
* For ``proposed_headings``, ``proposed_body_sections``, and
  ``proposed_faq``, cite the competitor heading / body / FAQ entry whose
  topical intent you're drawing on. You may also cite ``our:headings[i]``
  if you're keeping our structure but improving the copy.
* For ``proposed_internal_links``, ``target_url`` MUST appear in
  ``our:internal_links[*].href`` or in a cited competitor's
  ``their:<brand>:internal_links[*].href``. Do not invent slugs.
* ``improved_html`` must be VALID HTML body content (no <html>, <head>,
  <body> wrapper). Use proper semantic tags. Include the FAQ as a
  ``<section class="faq">`` with ``<details>`` elements. Each CTA as
  ``<a class="cta" href="...">``. Inline the proposed_internal_links in
  the body paragraphs where natural.
* ``improved_markdown`` should mirror the HTML content but in clean
  Markdown — no source_ref pills, no rationale comments, just the
  publish-ready text.
* ``tech_recommendations`` are factual: if our LCP is 4500ms and the
  best competitor is 1800ms, the recommendation cites
  ``our:cwv:mobile`` AND a ``their:<brand>:cwv:mobile`` key.
* All branding is "Bajaj Life Insurance" — NEVER "Bajaj Allianz".
* Output ONLY the JSON object. No prose, no markdown fences around the JSON.
""".strip()


_INSTRUCTION = (
    "Revamp our_page so it closes structural + content + technical gaps "
    "vs the competitor_pages, while retaining what we already do well. "
    "Cite an evidence_ref for every generated string. Omit anything you "
    "cannot ground."
)


# ── evidence-dict builder ────────────────────────────────────────────


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _build_evidence_for_our_signals(s) -> dict[str, Any]:
    """Flatten our PageSignals → ``our:*`` evidence keys."""
    ev: dict[str, Any] = {}
    if s.title:
        ev["our:title"] = _truncate(s.title, 300)
    if s.meta_description:
        ev["our:meta_description"] = _truncate(s.meta_description, 400)
    if s.url:
        ev["our:url"] = s.url
    if s.body_excerpt:
        ev["our:body_excerpt"] = _truncate(s.body_excerpt, 1500)
    for i, h in enumerate(s.headings[:40]):
        ev[f"our:headings[{i}]"] = {
            "level": h.get("level") if isinstance(h, dict) else None,
            "text": _truncate(
                h.get("text") if isinstance(h, dict) else str(h or ""), 200,
            ),
        }
    for i, link in enumerate(s.internal_links[:60]):
        if not isinstance(link, dict):
            continue
        ev[f"our:internal_links[{i}]"] = {
            "anchor": _truncate(link.get("anchor") or "", 200),
            "href": link.get("href"),
            "kind": link.get("kind"),
            "section": link.get("section"),
        }
    if any(v is not None for v in (s.cwv_mobile or {}).values()):
        ev["our:cwv:mobile"] = s.cwv_mobile
    if any(v is not None for v in (s.cwv_desktop or {}).values()):
        ev["our:cwv:desktop"] = s.cwv_desktop
    for i, k in enumerate((s.semrush_keywords or [])[:25]):
        ev[f"our:semrush:keywords[{i}]"] = k
    return ev


def _brand_slug(brand: str) -> str:
    """Normalise brand for use in evidence keys ('hdfclife.com' stays as
    is — keys are namespaced enough)."""
    return (brand or "competitor").strip().lower()


def _build_evidence_for_competitor(
    match, s,
) -> dict[str, Any]:
    """Flatten one competitor's PageSignals into ``their:<brand>:*`` keys."""
    brand = _brand_slug(match.brand)
    ns = f"their:{brand}"
    ev: dict[str, Any] = {}
    if s.title:
        ev[f"{ns}:title"] = _truncate(s.title, 300)
    if s.meta_description:
        ev[f"{ns}:meta_description"] = _truncate(s.meta_description, 400)
    if s.url:
        ev[f"{ns}:url"] = s.url
    if s.body_excerpt:
        ev[f"{ns}:body_excerpt"] = _truncate(s.body_excerpt, 1500)
    for i, h in enumerate(s.headings[:30]):
        ev[f"{ns}:headings[{i}]"] = {
            "level": h.get("level") if isinstance(h, dict) else None,
            "text": _truncate(
                h.get("text") if isinstance(h, dict) else str(h or ""), 200,
            ),
        }
    for i, link in enumerate(s.internal_links[:30]):
        if not isinstance(link, dict):
            continue
        ev[f"{ns}:internal_links[{i}]"] = {
            "anchor": _truncate(link.get("anchor") or "", 200),
            "href": link.get("href"),
            "kind": link.get("kind"),
        }
    if any(v is not None for v in (s.cwv_mobile or {}).values()):
        ev[f"{ns}:cwv:mobile"] = s.cwv_mobile
    if any(v is not None for v in (s.cwv_desktop or {}).values()):
        ev[f"{ns}:cwv:desktop"] = s.cwv_desktop
    for i, k in enumerate((s.semrush_keywords or [])[:15]):
        ev[f"{ns}:semrush:keywords[{i}]"] = k
    return ev


# ── main entry point ──────────────────────────────────────────────────


def generate_revamp(
    *,
    payload,  # RevampPayload from services/page_revamp.py
    provider: LLMProvider | None = None,
) -> RevampResult:
    """Run the rewrite. The payload's `prompt` flows verbatim into the
    user instruction so the operator can steer."""
    provider = provider or get_provider()

    result = RevampResult(
        our_url=payload.our.url,
        competitor_urls=[m.url for m, _ in payload.counterparts],
        prompt=payload.prompt or "",
        evidence_dict={},
        raw_proposal={},
        filtered_proposal={},
        critic_verdict={},
        model_used=getattr(provider, "model", "") or "",
    )

    evidence: dict[str, Any] = {}
    evidence.update(_build_evidence_for_our_signals(payload.our))
    for match, signals in payload.counterparts:
        evidence.update(_build_evidence_for_competitor(match, signals))
    result.evidence_dict = evidence

    # Hard token budget. Groq's on_demand tier caps TPM at 8000 across
    # the fallback chain, so even at full retry depth we cannot exceed
    # roughly 6 KB of payload before the system prompt (~3 KB) blows it.
    # Everything below is deliberately tiny — the agent still produces
    # a useful rewrite because (a) the canonical evidence dict is
    # captured server-side for citation validation, and (b) the prompt
    # patterns below ("their:<brand>:headings[*]") let the agent emit
    # well-formed refs without needing the exhaustive list of keys.
    competitor_payload = [
        {
            "brand": _brand_slug(m.brand),
            "url": s.url,
            "title": s.title[:120],
            "meta": s.meta_description[:160],
            "h2_top": s.h2[:4],
            "wc": s.word_count,
            "schema": s.jsonld_types[:6],
            "lcp_mobile": (s.cwv_mobile or {}).get("lcp_ms"),
            "pagespeed_mobile": (s.cwv_mobile or {}).get("pagespeed_score"),
            "semrush_top": [
                {
                    "kw": k.get("keyword", ""),
                    "pos": k.get("position"),
                    "vol": k.get("search_volume"),
                }
                for k in (s.semrush_keywords or [])[:3]
            ],
        }
        for m, s in payload.counterparts
    ]

    # Compact evidence key reference — list namespaces + array counts
    # rather than the full ~350-entry list. Saves ~8 KB; the agent can
    # generate well-formed refs like `our:headings[3]` from the pattern.
    ours = payload.our
    evidence_patterns = {
        "ours": {
            "scalars": ["our:title", "our:meta_description", "our:url"],
            "arrays": {
                "our:headings": min(len(ours.headings), 40),
                "our:internal_links": min(len(ours.internal_links), 60),
                "our:semrush:keywords": min(len(ours.semrush_keywords or []), 25),
            },
        },
        "competitors": [
            {
                "brand": _brand_slug(m.brand),
                "scalars": [
                    f"their:{_brand_slug(m.brand)}:title",
                    f"their:{_brand_slug(m.brand)}:meta_description",
                    f"their:{_brand_slug(m.brand)}:url",
                ],
                "arrays": {
                    f"their:{_brand_slug(m.brand)}:headings": min(len(s.headings), 30),
                    f"their:{_brand_slug(m.brand)}:internal_links": min(len(s.internal_links), 30),
                },
            }
            for m, s in payload.counterparts
        ],
    }

    user_payload = {
        "our_page": {
            "url": ours.url,
            "title": ours.title[:200],
            "meta": ours.meta_description[:200],
            "wc": ours.word_count,
            "h1": ours.h1[:2],
            "h2_top": ours.h2[:6],
            "schema": ours.jsonld_types[:8],
            "lcp_mobile": (ours.cwv_mobile or {}).get("lcp_ms"),
            "pagespeed_mobile": (ours.cwv_mobile or {}).get("pagespeed_score"),
            "semrush_top": [
                {
                    "kw": k.get("keyword", ""),
                    "pos": k.get("position"),
                    "vol": k.get("search_volume"),
                }
                for k in (ours.semrush_keywords or [])[:6]
            ],
        },
        "competitor_pages": competitor_payload,
        "operator_prompt": payload.prompt or "",
        "evidence_patterns": evidence_patterns,
    }

    user_content = (
        _INSTRUCTION
        + "\n\n<facts>\n```json\n"
        + json.dumps(user_payload, default=str)  # compact: no indent
        + "\n```\n</facts>\n"
        "Every string in your output MUST cite a well-formed "
        "source_ref per evidence_patterns. If you cannot ground "
        "something, OMIT it."
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    t0 = time.time()
    try:
        resp = provider.complete(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("revamp_writer LLM call failed")
        result.error = f"LLM call failed: {exc}"
        return result

    result.tokens_in = resp.tokens_in
    result.tokens_out = resp.tokens_out
    result.cost_usd = resp.cost_usd

    try:
        raw = _parse_json(resp.content)
    except ValueError as exc:
        result.error = f"model returned non-JSON: {exc}"
        return result
    result.raw_proposal = raw

    verdict = verify_generation(raw, evidence)
    result.filtered_proposal = verdict.pop("filtered", {})
    result.critic_verdict = verdict
    logger.info(
        "revamp_writer ok in %.1fs: accepted=%d rejected=%d cost=$%.4f",
        time.time() - t0,
        verdict.get("accepted", 0),
        verdict.get("rejected", 0),
        result.cost_usd,
    )
    return result


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
