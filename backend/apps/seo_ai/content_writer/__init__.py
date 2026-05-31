"""Content Writer — page-revamp pipeline grounded in live SERP discovery.

Goal: take ONE Bajaj Life Insurance URL (+ optional free-text steer) and
produce a publish-ready rewrite that closes structural and semantic gaps
versus the pages that *actually rank* on Google for the same intent.

Why a separate package
----------------------
The existing ``apps.seo_ai.services.page_revamp`` pipeline compares us
against a fixed DB roster of competitor brands. That's fine for portfolio
intel, but for a page-revamp the question is "who is Google ranking right
now for this intent, and what do those pages do?". This package answers
the second question — competitors are *discovered* per-page via SERP,
not assumed.

Pipeline
--------
1. ``serp_discovery``   — LLM synthesizes the page's target query from
                          its URL + body, hits SerpAPI/Google for the
                          top organic results, drops Bajaj domains.
2. ``page_crawler``     — fetches each discovered URL exactly once
                          (single-page deep crawl, not a site walk).
3. ``page_analyzer``    — extracts a rich structural fingerprint
                          (outline tree, link density, image alt %,
                          schema types, FAQ presence, content size).
4. ``section_clusterer``— LLM-clusters each page into named topical
                          sections so we can compare *topics*, not just
                          heading strings.
5. ``gap_engine``       — multi-dimensional diff (missing sections,
                          word-count delta, link density delta, image
                          gap, schema gap, FAQ gap, heading-depth gap).
6. ``seo_overlay``      — deterministic best-practice checks (title
                          50-60ch, meta 140-160ch, single H1, etc.).
7. ``writer``           — provider-agnostic agent that produces the
                          full rewrite: title, meta, ordered outline,
                          long-form body (HTML), FAQ Q&A, internal-link
                          plan, JSON-LD schema. Prompt is gap-driven.
8. ``orchestrator``     — public entry point ``run_revamp``.

Provider switching
------------------
Reads ``settings.LLM["provider"]`` — currently ``groq`` (dev) or
``anthropic`` (added in ``apps.seo_ai.llm.provider``). Set
``LLM_PROVIDER=anthropic`` + ``ANTHROPIC_API_KEY=...`` in the env to
swap. No code changes required in this package.
"""
from __future__ import annotations

# Public surface — keep tight; everything else is implementation detail.
__all__ = [
    "run_revamp",
    "find_serp_competitors",
    "analyze_page",
    "compute_revamp_gap",
    "generate_revamp",
]


def __getattr__(name: str):  # lazy re-export, avoids cycles at import
    if name == "run_revamp":
        from .orchestrator import run_revamp

        return run_revamp
    if name == "find_serp_competitors":
        from .serp_discovery import find_serp_competitors

        return find_serp_competitors
    if name == "analyze_page":
        from .page_analyzer import analyze_page

        return analyze_page
    if name == "compute_revamp_gap":
        from .gap_engine import compute_revamp_gap

        return compute_revamp_gap
    if name == "generate_revamp":
        from .writer import generate_revamp

        return generate_revamp
    raise AttributeError(name)
