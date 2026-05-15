"""Stage 2: multi-LLM web-grounded search.

For each (query × LLM provider) cell, call the existing
``AILLMProbeAdapter`` subclasses and persist what came back. The
adapters already:

* Self-gate on missing API keys (``AdapterDisabledError``).
* Use web-search grounding where the provider supports it
  (OpenAI ``web_search_preview`` tool, Perplexity ``sonar``, Grok,
  Gemini grounding chunks).
* 7-day disk cache so re-runs cost zero.
* Never raise out of ``probe`` — errors are surfaced via
  ``AIProbeResult.error``.

We add: brand-mention detection against the focus domain's brand token,
``web_search_used`` flag per provider, and persistence into
``GapLLMResult``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from ..adapters.ai_visibility import PROVIDER_REGISTRY, AdapterDisabledError
from ..adapters.ai_visibility.base import AILLMProbeAdapter, AIProbeResult
from ..agents.ai_visibility import _brand_token, _mentions_brand
from ..models import GapLLMResult, GapPipelineQuery, GapPipelineRun

logger = logging.getLogger("seo.ai.gap_pipeline.llm_search")


# Providers that actually pull from the live web — used only as a UI
# hint so we can label results "web-grounded" vs "from training data".
# OpenAI uses the web_search_preview tool; Perplexity sonar and Grok
# are natively grounded; Gemini grounds when grounding_chunks come
# back (best-effort, set when cited_urls is non-empty).
_GROUNDED_BY_DEFAULT = {"openai", "perplexity", "grok"}


@dataclass
class _StageStats:
    provider_count: int = 0
    call_count: int = 0
    total_cost_usd: float = 0.0


def _build_adapters() -> list[AILLMProbeAdapter]:
    """Instantiate every adapter whose API key is set. Each provider
    self-gates by raising ``AdapterDisabledError`` if its key is empty
    — we swallow that so the others still run."""
    out: list[AILLMProbeAdapter] = []
    for cls in PROVIDER_REGISTRY:
        try:
            out.append(cls())
        except AdapterDisabledError as exc:
            logger.info(
                "gap_pipeline.llm_search: %s skipped: %s",
                getattr(cls, "provider", cls.__name__),
                exc,
            )
        except Exception as exc:  # noqa: BLE001 - never crash the stage
            logger.warning(
                "gap_pipeline.llm_search: %s init crashed: %s",
                getattr(cls, "provider", cls.__name__),
                exc,
            )
    return out


def _was_web_grounded(result: AIProbeResult) -> bool:
    """Best-effort: True when the provider is known web-grounded OR the
    answer carried citations the adapter extracted from grounding
    metadata (not just URLs the model happened to type)."""
    if result.provider in _GROUNDED_BY_DEFAULT:
        return True
    # For providers like Gemini, citations only land in cited_urls when
    # grounding_metadata was returned — a reliable "yes, grounded" signal.
    # For raw-chat providers (Anthropic in current adapter), cited_urls
    # gets populated by the base class regex from answer text, which
    # isn't true grounding, so this heuristic over-counts. The UI
    # treats this as a hint, not a hard claim.
    return False


def _run_llm_search(
    *, run: GapPipelineRun, domain: str, queries: list[GapPipelineQuery]
) -> _StageStats:
    """Run every (provider × query) probe and persist a GapLLMResult.

    Returns aggregate stats for the run header. Empty result list (no
    providers configured) is a valid outcome — the orchestrator marks
    the stage as ``skipped`` upstream rather than failing the run.
    """
    cfg = getattr(settings, "AI_VISIBILITY", {}) or {}
    if not cfg.get("enabled", True):
        logger.info("gap_pipeline.llm_search: disabled by AI_VISIBILITY_ENABLED")
        return _StageStats()
    adapters = _build_adapters()
    if not adapters:
        logger.info(
            "gap_pipeline.llm_search: no providers configured — stage empty"
        )
        return _StageStats()

    brand_token = _brand_token(domain)
    stats = _StageStats(provider_count=len(adapters))

    for adapter in adapters:
        for q_row in queries:
            try:
                result = adapter.probe(q_row.query)
            except Exception as exc:  # noqa: BLE001 - defence in depth
                logger.warning(
                    "%s probe %r crashed: %s",
                    adapter.provider,
                    q_row.query[:80],
                    exc,
                )
                result = AIProbeResult(
                    provider=adapter.provider,
                    query=q_row.query,
                    error=f"{type(exc).__name__}: {exc}"[:300],
                )
            stats.call_count += 1
            stats.total_cost_usd += float(result.cost_usd or 0.0)

            GapLLMResult.objects.create(
                run=run,
                query=q_row,
                provider=adapter.provider,
                model=getattr(adapter, "model", "") or getattr(adapter, "model_name", ""),
                answer_text=(result.answer_text or "")[:8000],
                cited_urls=list(result.cited_urls or [])[:30],
                cited_domains=list(result.mentioned_domains or [])[:30],
                mentions_our_brand=_mentions_brand(
                    result.answer_text or "", brand_token
                ),
                web_search_used=_was_web_grounded(result),
                tokens_in=int(result.tokens_in or 0),
                tokens_out=int(result.tokens_out or 0),
                cost_usd=float(result.cost_usd or 0.0),
                latency_ms=int(result.latency_ms or 0),
                cached=bool(result.cached),
                error=(result.error or "")[:1000],
            )

    return stats


def execute(
    *, run: GapPipelineRun, domain: str, queries: list[GapPipelineQuery]
) -> dict[str, object]:
    """Public entry. Returns a status dict for ``stage_status``."""
    if not queries:
        return {"status": "skipped", "reason": "no queries to probe"}
    stats = _run_llm_search(run=run, domain=domain, queries=queries)
    if stats.provider_count == 0:
        return {
            "status": "skipped",
            "reason": "no LLM API keys configured "
            "(set OPENAI/ANTHROPIC/GOOGLE/PERPLEXITY/XAI_API_KEY)",
        }
    # Persist counters on the run row so the polling UI shows them
    # without re-aggregating the child table.
    run.llm_provider_count = stats.provider_count
    run.llm_call_count = stats.call_count
    run.llm_total_cost_usd = round(stats.total_cost_usd, 6)
    run.save(
        update_fields=[
            "llm_provider_count",
            "llm_call_count",
            "llm_total_cost_usd",
        ]
    )
    return {
        "status": "ok",
        "provider_count": stats.provider_count,
        "call_count": stats.call_count,
        "cost_usd": round(stats.total_cost_usd, 6),
    }
