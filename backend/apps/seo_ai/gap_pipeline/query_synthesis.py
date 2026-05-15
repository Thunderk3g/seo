"""Stage 1: LLM-driven query synthesis.

Pulls a keyword seed corpus from SEMrush — our own organic keywords
plus the top organic competitors' keywords — then asks Groq to convert
that corpus into 20–30 user-intent queries spanning six buckets
(informational / commercial / comparison / brand_specific / long_tail /
conversational). The queries drive stages 2 (LLM web-search) and 3
(SerpAPI).

Failure handling: if SEMrush is unavailable, we fall back to the
existing seed_queries module so the pipeline still has *something* to
probe. If the LLM call itself fails, we fall back to the SEMrush
keywords directly as "queries" (less natural but still useful).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from ..adapters.semrush import SemrushAdapter, SemrushError
from ..llm import get_provider
from ..models import GapPipelineQuery, GapPipelineRun
from ..queries.seed_queries import load_queries

logger = logging.getLogger("seo.ai.gap_pipeline.query_synthesis")


# Bucket vocab the LLM is instructed to use. Mirrors the seed-bucket
# names so downstream UI can colour-code intents consistently across
# the pipeline + seed runs.
_INTENTS = (
    "informational",
    "commercial",
    "comparison",
    "brand_specific",
    "long_tail",
    "conversational",
)

_SYSTEM_PROMPT = (
    "You are an SEO query strategist. Given a domain and a list of "
    "keywords the domain (and its competitors) rank for, synthesise a "
    "balanced set of natural user-intent queries we should probe AI "
    "search engines and Google with.\n\n"
    "Return STRICT JSON: {\"queries\": [{\"query\": \"...\", "
    "\"intent\": \"informational|commercial|comparison|brand_specific|"
    "long_tail|conversational\", \"rationale\": \"<8-15 word reason>\", "
    "\"source_keywords\": [\"...\"]}, ...]}.\n\n"
    "Rules:\n"
    "- Output {n} queries, balanced across all six intents.\n"
    "- Queries must read like real human searches (no marketing copy).\n"
    "- Include brand-vs-competitor comparisons where rivals are obvious.\n"
    "- Long-tail = 5+ words. Conversational = a full question like a "
    "user would ask ChatGPT.\n"
    "- source_keywords cites 1-3 keywords from the seed list that "
    "inspired this query (verbatim).\n"
    "- Do NOT wrap the JSON in markdown fences. Pure JSON only."
)


@dataclass
class _SeedCorpus:
    """Seed keywords drawn from SEMrush; either side may be empty if
    the API is rate-limited or the domain has no data in the configured
    SEMrush database (defaults to ``in``)."""

    our_keywords: list[str]
    competitor_keywords: list[dict[str, Any]]  # [{domain, keyword, position}, ...]
    competitor_domains: list[str]


def _semrush_seed_corpus(domain: str, *, top_n_competitors: int = 5) -> _SeedCorpus:
    """Pull seed keywords from SEMrush; tolerate failure.

    Pulls our top-50 organic keywords + the top-25 keywords of each of
    the top-5 organic competitors. SEMrush results are 7-day cached at
    the adapter layer (see ``SemrushAdapter._cache_*``) so repeat runs
    cost zero units.
    """
    try:
        adapter = SemrushAdapter()
    except SemrushError as exc:
        logger.info("query_synthesis: SEMrush adapter unavailable: %s", exc)
        return _SeedCorpus(our_keywords=[], competitor_keywords=[], competitor_domains=[])

    our_kw: list[str] = []
    try:
        rows = adapter.organic_keywords(domain, limit=50)
        our_kw = [r.keyword for r in rows if r.keyword]
    except SemrushError as exc:
        logger.info("query_synthesis: our organic_keywords failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 - don't crash the stage
        logger.warning(
            "query_synthesis: unexpected error pulling our keywords: %s", exc
        )

    comp_domains: list[str] = []
    comp_keywords: list[dict[str, Any]] = []
    try:
        comps = adapter.organic_competitors(domain, limit=top_n_competitors)
        for c in comps:
            if not c.domain:
                continue
            comp_domains.append(c.domain)
            try:
                kw_rows = adapter.organic_keywords(c.domain, limit=25)
            except SemrushError as exc:
                logger.info(
                    "query_synthesis: %s keywords failed: %s", c.domain, exc
                )
                continue
            for r in kw_rows[:25]:
                if not r.keyword:
                    continue
                comp_keywords.append(
                    {
                        "domain": c.domain,
                        "keyword": r.keyword,
                        "position": r.position,
                    }
                )
    except SemrushError as exc:
        logger.info("query_synthesis: organic_competitors failed: %s", exc)

    return _SeedCorpus(
        our_keywords=our_kw,
        competitor_keywords=comp_keywords,
        competitor_domains=comp_domains,
    )


def _build_user_prompt(*, domain: str, corpus: _SeedCorpus, n: int) -> str:
    """Pack the seed corpus into a compact prompt for Groq."""
    # Trim each list so the prompt stays well under the context window
    # even when SEMrush returns the maximum row count.
    our = corpus.our_keywords[:50]
    rival = corpus.competitor_keywords[:60]
    rival_lines = [
        f"- {row['keyword']} (rank #{row['position']} on {row['domain']})"
        for row in rival
    ]
    our_lines = [f"- {k}" for k in our]

    parts = [
        f"Target domain: {domain}",
        "",
        f"Generate {n} balanced queries.",
        "",
        "Our top organic keywords (SEMrush):",
        ("\n".join(our_lines) if our_lines else "(no keyword data available)"),
        "",
        "Competitor keywords we DON'T necessarily rank for (SEMrush):",
        (
            "\n".join(rival_lines)
            if rival_lines
            else "(no competitor keyword data available)"
        ),
        "",
        "Known competitor domains: "
        + (", ".join(corpus.competitor_domains[:8]) if corpus.competitor_domains else "(none)"),
    ]
    return "\n".join(parts)


_BUCKET_TO_INTENT = {
    "PRIMARY": "informational",
    "COMMERCIAL": "commercial",
    "INFORMATIONAL": "informational",
    "BRAND_COMPARISON": "brand_specific",
    "LONG_TAIL": "long_tail",
    "CONVERSATIONAL": "conversational",
}


def _fallback_from_seeds(*, n: int) -> list[dict[str, Any]]:
    """When the LLM is unreachable, fall back to the hand-curated seed
    queries so the pipeline still has something to probe."""
    pool = load_queries()[:n]
    return [
        {
            "query": q,
            "intent": "informational",
            "rationale": "fallback seed query",
            "source_keywords": [],
        }
        for q in pool
    ]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Tolerant JSON extraction — handles models that wrap responses in
    markdown code fences despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        # Strip leading ```json / ``` and trailing ```
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Sometimes the model leads with prose — find the first { and
        # the matching last } and try that slice.
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            try:
                return json.loads(text[first : last + 1])
            except json.JSONDecodeError:
                return None
    return None


def synthesize_queries(
    *, run: GapPipelineRun, domain: str, n: int = 24
) -> list[GapPipelineQuery]:
    """Run stage 1. Persists ``GapPipelineQuery`` rows + updates run
    counters. Returns the persisted queries in display order.
    """
    corpus = _semrush_seed_corpus(domain)
    n = max(8, min(int(n), 40))  # clamp so prompt size stays bounded

    queries_payload: list[dict[str, Any]] = []
    try:
        provider = get_provider()
        prompt = _build_user_prompt(domain=domain, corpus=corpus, n=n)
        system = _SYSTEM_PROMPT.format(n=n)
        resp = provider.complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=2400,
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(resp.content)
        if parsed and isinstance(parsed.get("queries"), list):
            queries_payload = parsed["queries"]
        else:
            logger.warning(
                "query_synthesis: LLM returned unparseable payload; "
                "falling back to seed queries"
            )
    except Exception as exc:  # noqa: BLE001 - stage must never crash run
        logger.warning("query_synthesis: LLM call failed: %s", exc)

    if not queries_payload:
        queries_payload = _fallback_from_seeds(n=n)

    # Normalise + persist.
    created: list[GapPipelineQuery] = []
    seen: set[str] = set()
    for i, item in enumerate(queries_payload[:n]):
        if not isinstance(item, dict):
            continue
        q = (item.get("query") or "").strip()
        if not q or len(q) > 500:
            continue
        # Cheap de-dup — LLMs occasionally repeat themselves.
        norm = q.lower()
        if norm in seen:
            continue
        seen.add(norm)
        intent = (item.get("intent") or "informational").lower()
        if intent not in _INTENTS:
            intent = "informational"
        rationale = (item.get("rationale") or "")[:500]
        source_kw = item.get("source_keywords") or []
        if not isinstance(source_kw, list):
            source_kw = []
        source_kw = [str(k)[:200] for k in source_kw][:5]
        created.append(
            GapPipelineQuery.objects.create(
                run=run,
                query=q,
                intent=intent,
                rationale=rationale,
                source_keywords=source_kw,
                order=len(created),
            )
        )

    # Roll counters back to the run row for the polling UI strip.
    run.query_count = len(created)
    run.seed_keyword_count = len(corpus.our_keywords) + len(corpus.competitor_keywords)
    run.save(update_fields=["query_count", "seed_keyword_count"])
    return created
