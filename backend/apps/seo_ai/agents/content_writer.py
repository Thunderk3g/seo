"""ContentWriterAgent — proposes rewrites grounded in real evidence.

What it does
============
Given one of our URLs, optionally a list of competitor URLs to learn
from, and optionally a set of target keywords, the agent emits a
rewrite proposal: a new title, meta description, heading outline, and
suggested internal links. Every generated string carries a
``source_ref`` pointing into the evidence dict the agent was given.
Strings without a resolvable ``source_ref`` are dropped by the
:func:`critic.verify_generation` pass before the proposal is persisted.

Why "no fake generations" matters
---------------------------------
LLMs love to invent plausible-sounding URL slugs, statistics, and
section headings. For a regulated insurance domain the cost of a
hallucinated CTA targeting a calculator page that doesn't exist is
real (broken link, broken trust, SEO loss). The contract here is:

* We hand the writer a flat evidence dict whose keys look like
  ``our:title``, ``our:headings[3]``, ``their:icicilife.com:headings[2]``.
* The system prompt demands a ``source_ref`` for every string.
* A deterministic post-pass verifies each ref resolves; rejected
  strings get dropped + recorded.

Inputs
------
* ``our_url`` — our URL we want to rewrite.
* ``competitor_urls`` — optional list of competitor URLs to learn
  structure from. If omitted, evidence is "us only" and the writer
  is essentially polishing.
* ``target_keywords`` — optional list of keywords we want the page
  to rank for. These appear in the user instruction but are *not*
  citable (they're not facts to attribute).

Outputs
-------
A :class:`ContentRewriteResult` carrying the raw model output, the
critic verdict, the filtered proposal, the evidence dict, and cost
telemetry. The caller persists this as a :class:`ContentRewriteProposal`.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ..llm import LLMProvider, get_provider
from ..models import GapDeepCrawl
from .critic import verify_generation

logger = logging.getLogger("seo.ai.agents.content_writer")


# ── public dataclass ──────────────────────────────────────────────────


@dataclass
class ContentRewriteResult:
    our_url: str
    competitor_urls: list[str]
    target_keywords: list[str]
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

_SYSTEM_PROMPT = """You are an SEO content writer for Bajaj Life
Insurance (legally renamed from "Bajaj Allianz Life Insurance" — the
new brand is now Bajaj Life Insurance). You rewrite product/landing
pages so they outrank competitors on Indian life-insurance queries.

You will be given:
1. ``our_page``: our current page (URL, title, meta description, body
   text excerpt, ordered headings list, internal links list).
2. ``competitors``: zero or more competitor pages with the same shape.
3. ``target_keywords``: keywords we want the rewritten page to rank
   for.
4. ``evidence_keys``: the COMPLETE list of valid ``source_ref`` values
   you may cite. Every string you generate MUST reference one of these.

Output a JSON object with the following shape:

{
  "proposed_title":        {"text": "...", "source_ref": "<key>"},
  "proposed_meta_description": {"text": "...", "source_ref": "<key>"},
  "proposed_headings": [
    {"level": 1, "text": "...", "source_ref": "<key>", "rationale": "..."},
    {"level": 2, "text": "...", "source_ref": "<key>", "rationale": "..."},
    ...
  ],
  "proposed_internal_links": [
    {"anchor": "...", "target_url": "...", "section": "...",
     "source_ref": "<key>", "rationale": "..."},
    ...
  ],
  "overall_rationale": "1-3 sentences on the rewrite strategy."
}

Rules — non-negotiable:

* ``source_ref`` MUST be a string from ``evidence_keys``. If you
  cannot ground a string in evidence, OMIT that string. Do not
  invent.
* For ``proposed_title`` and ``proposed_meta_description``, the
  rewritten text should improve on ``our:title`` and
  ``our:meta_description`` — keep the underlying intent but compress
  or sharpen it. ``source_ref`` for these is typically ``our:title``
  or ``our:meta_description``; the *text* is your rewrite, the
  ``source_ref`` says "I'm rewriting THIS original".
* For ``proposed_headings``, cite the competitor heading or our own
  heading you are drawing the structural intent from. ``text`` is
  your rewrite; you may rephrase to match Bajaj voice, but the
  topical intent must come from the cited evidence.
* For ``proposed_internal_links``, ``target_url`` MUST be a URL that
  appears in our current ``internal_links`` list, or in the cited
  competitor's ``internal_links`` list, AND the ``source_ref`` MUST
  point at that exact link entry. Do not invent slugs.
* Output ONLY the JSON object. No prose, no markdown fences.
* All Bajaj branding is now "Bajaj Life Insurance" — the company
  rebranded from "Bajaj Allianz Life Insurance". Never emit the
  legacy "Bajaj Allianz Life" form in new copy. (Legacy mentions
  in third-party sources are tracked separately and are expected.)
""".strip()


_INSTRUCTION = (
    "Rewrite our_page so it outperforms the competitors on the given "
    "keywords. Cite an evidence_ref for every generated string. Omit "
    "anything you cannot ground."
)


# ── evidence-dict builder ─────────────────────────────────────────────


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _build_evidence_for_our_page(page: dict[str, Any]) -> dict[str, Any]:
    """Flatten our_page into ``our:*`` evidence keys."""
    ev: dict[str, Any] = {}
    if page.get("title"):
        ev["our:title"] = _truncate(page["title"], 300)
    if page.get("meta_description"):
        ev["our:meta_description"] = _truncate(page["meta_description"], 400)
    if page.get("url"):
        ev["our:url"] = page["url"]
    if page.get("body_excerpt"):
        ev["our:body_excerpt"] = _truncate(page["body_excerpt"], 1200)
    for i, h in enumerate(page.get("headings") or []):
        ev[f"our:headings[{i}]"] = {
            "level": h.get("level"),
            "text": _truncate(h.get("text") or "", 200),
        }
    for i, link in enumerate(page.get("internal_links") or []):
        ev[f"our:internal_links[{i}]"] = {
            "anchor": _truncate(link.get("anchor") or "", 200),
            "href": link.get("href"),
            "kind": link.get("kind"),
            "section": link.get("section"),
        }
    return ev


def _build_evidence_for_competitor(
    host: str, page: dict[str, Any],
) -> dict[str, Any]:
    """Flatten a competitor page into ``their:<host>:*`` evidence keys."""
    ev: dict[str, Any] = {}
    ns = f"their:{host}"
    if page.get("title"):
        ev[f"{ns}:title"] = _truncate(page["title"], 300)
    if page.get("meta_description"):
        ev[f"{ns}:meta_description"] = _truncate(page["meta_description"], 400)
    if page.get("url"):
        ev[f"{ns}:url"] = page["url"]
    if page.get("body_text"):
        ev[f"{ns}:body_excerpt"] = _truncate(page["body_text"], 1200)
    for i, h in enumerate(page.get("headings") or []):
        ev[f"{ns}:headings[{i}]"] = {
            "level": h.get("level"),
            "text": _truncate(h.get("text") or "", 200),
        }
    for i, link in enumerate(page.get("internal_links") or []):
        ev[f"{ns}:internal_links[{i}]"] = {
            "anchor": _truncate(link.get("anchor") or "", 200),
            "href": link.get("href"),
            "kind": link.get("kind"),
            "section": link.get("section"),
        }
    return ev


# ── loaders ───────────────────────────────────────────────────────────


def _load_our_page(our_url: str) -> dict[str, Any] | None:
    """Pull our latest CrawlerPageResult row for ``our_url`` and shape it
    for the agent. Returns ``None`` when we have never crawled this URL.
    """
    # Import inside fn to avoid a circular when this module is imported
    # before django.setup() has finished (e.g. by the management commands).
    from apps.crawler.models import CrawlerPageResult

    row = (
        CrawlerPageResult.objects.filter(url=our_url)
        .order_by("-snapshot_id")
        .first()
    )
    if row is None:
        return None
    return {
        "url": row.url,
        "title": row.title or "",
        "meta_description": row.meta_description or "",
        "body_excerpt": (row.body_text or "")[:4000],
        "word_count": row.word_count or 0,
        "headings": row.headings_json or [],
        "internal_links": row.internal_links_json or [],
        "images": row.images_json or [],
        "page_type": row.page_type or "",
    }


def _load_competitor_pages(
    competitor_urls: list[str],
) -> list[tuple[str, dict[str, Any]]]:
    """Return a list of ``(host, page_dict)`` for every URL that was
    captured by a recent gap-pipeline deep crawl.

    Pulls from the *latest* :class:`GapDeepCrawl` per host. URLs we have
    no sample for are silently skipped — the API surface returns a
    "missing" list separately so the UI can flag them.
    """
    if not competitor_urls:
        return []
    by_host: dict[str, list[str]] = {}
    for u in competitor_urls:
        host = (urlparse(u).hostname or "").lower().lstrip("www.")
        if not host:
            continue
        by_host.setdefault(host, []).append(u)

    out: list[tuple[str, dict[str, Any]]] = []
    for host, urls in by_host.items():
        crawl = (
            GapDeepCrawl.objects.filter(domain__icontains=host)
            .order_by("-id")
            .first()
        )
        if crawl is None or not crawl.profile:
            continue
        index = {
            (s.get("url") or "").strip(): s
            for s in (crawl.profile.get("sample_pages") or [])
        }
        for u in urls:
            sample = index.get(u.strip())
            if sample is not None:
                out.append((host, sample))
    return out


# ── main entry point ──────────────────────────────────────────────────


def generate_rewrite(
    *,
    our_url: str,
    competitor_urls: list[str] | None = None,
    target_keywords: list[str] | None = None,
    provider: LLMProvider | None = None,
) -> ContentRewriteResult:
    """Generate one ContentRewriteProposal-shaped result.

    All loading + prompting + critic verification happens inline. The
    caller is responsible for persisting the returned dataclass into
    :class:`ContentRewriteProposal`. We do NOT write to the DB here so
    the agent stays unit-testable.

    On any unrecoverable error (URL not crawled, LLM failure, JSON
    parse failure) the returned dataclass has ``error`` set and empty
    proposals — the caller still persists it so the UI can surface
    the failure to the operator.
    """
    competitor_urls = competitor_urls or []
    target_keywords = target_keywords or []
    provider = provider or get_provider()

    result = ContentRewriteResult(
        our_url=our_url,
        competitor_urls=competitor_urls,
        target_keywords=target_keywords,
        evidence_dict={},
        raw_proposal={},
        filtered_proposal={},
        critic_verdict={},
        model_used=getattr(provider, "model", "") or "",
    )

    our_page = _load_our_page(our_url)
    if our_page is None:
        result.error = (
            f"no CrawlerPageResult row for {our_url} — crawl it first"
        )
        return result

    competitor_pages = _load_competitor_pages(competitor_urls)

    # Build the flat evidence dict the writer cites against.
    evidence: dict[str, Any] = {}
    evidence.update(_build_evidence_for_our_page(our_page))
    for host, page in competitor_pages:
        evidence.update(_build_evidence_for_competitor(host, page))
    result.evidence_dict = evidence

    payload = {
        "our_page": our_page,
        "competitors": [
            {"host": h, **p} for h, p in competitor_pages
        ],
        "target_keywords": target_keywords,
        "evidence_keys": sorted(evidence.keys()),
    }

    user_content = (
        _INSTRUCTION
        + "\n\n<facts>\n```json\n"
        + json.dumps(payload, default=str, indent=2)
        + "\n```\n</facts>\n"
        "Every string in your output MUST cite an evidence_ref from "
        "<evidence_keys>. If you cannot ground something, OMIT it."
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
    except Exception as exc:  # noqa: BLE001 — surface all LLM failures
        logger.exception("content_writer LLM call failed")
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
        "content_writer ok in %.2fs: accepted=%d rejected=%d cost=$%.4f",
        time.time() - t0,
        verdict.get("accepted", 0),
        verdict.get("rejected", 0),
        result.cost_usd,
    )
    return result


def _parse_json(text: str) -> dict[str, Any]:
    """Tolerant JSON parser — strips ```json fences some models emit."""
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
