"""Stage 3: SerpAPI multi-engine web search.

For each query × each enabled engine, calls the existing
``SerpAPIAdapter`` (Google + Bing + DuckDuckGo are wired; ``SERP_API
_ENGINES`` env controls which run). Captures organic top 10, featured
snippet, AI Overview, related searches, and our domain's position
when we appear in the top 10.

The adapter caches results for 7 days, so re-runs against the same
query+engine cost nothing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from ..adapters.ai_visibility.base import AdapterDisabledError
from ..adapters.serp_api import SerpAPIAdapter
from ..models import GapPipelineQuery, GapPipelineRun, GapSerpResult

logger = logging.getLogger("seo.ai.gap_pipeline.serp_search")


def _bare(domain: str) -> str:
    bare = re.sub(r"^www\d?\.", "", (domain or "").lower())
    return bare.split("/")[0]


def _is_us(host: str, focus: str) -> bool:
    if not host or not focus:
        return False
    return host == focus or host.endswith("." + focus) or focus.endswith("." + host)


@dataclass
class _StageStats:
    engine_count: int = 0
    call_count: int = 0


def _our_position(organic_rows, focus: str) -> Optional[int]:
    """Return our top-10 position (1-indexed) or None if absent."""
    for row in organic_rows[:10]:
        if _is_us(row.domain, focus):
            return int(row.position)
    return None


def execute(
    *, run: GapPipelineRun, domain: str, queries: list[GapPipelineQuery]
) -> dict[str, object]:
    """Run SerpAPI for every (query × engine). Persist GapSerpResult."""
    if not queries:
        return {"status": "skipped", "reason": "no queries to probe"}

    cfg = getattr(settings, "SERP_API", {}) or {}
    if not cfg.get("enabled", True):
        return {"status": "skipped", "reason": "SERP_API_ENABLED=false"}

    try:
        adapter = SerpAPIAdapter()
    except AdapterDisabledError as exc:
        return {"status": "skipped", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - never crash the stage
        logger.warning("serp adapter init crashed: %s", exc)
        return {
            "status": "skipped",
            "reason": f"init error: {type(exc).__name__}",
        }

    engines = tuple(cfg.get("engines") or ("google",))
    focus = _bare(domain)
    stats = _StageStats(engine_count=len(engines))

    for engine in engines:
        for q_row in queries:
            result = adapter.search(q_row.query, engine=engine)
            stats.call_count += 1
            # Skip persistence when the engine errored AND the row would
            # carry zero useful data — keeps the table clean.
            organic_payload = [
                {
                    "position": r.position,
                    "title": r.title,
                    "url": r.url,
                    "domain": r.domain,
                    "snippet": r.snippet,
                }
                for r in result.organic[:10]
            ]
            GapSerpResult.objects.create(
                run=run,
                query=q_row,
                engine=engine,
                organic=organic_payload,
                featured_snippet=result.featured_snippet or None,
                ai_overview=result.ai_overview or None,
                people_also_ask=list(result.people_also_ask or [])[:10],
                related_searches=list(result.related_searches or [])[:10],
                our_position=_our_position(result.organic, focus),
                cached=bool(result.cached),
                latency_ms=int(result.latency_ms or 0),
                error=(result.error or "")[:1000],
            )

    run.serp_engine_count = stats.engine_count
    run.serp_call_count = stats.call_count
    run.save(update_fields=["serp_engine_count", "serp_call_count"])

    return {
        "status": "ok",
        "engine_count": stats.engine_count,
        "call_count": stats.call_count,
        "engines": list(engines),
    }
