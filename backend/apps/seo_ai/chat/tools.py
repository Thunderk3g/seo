"""Tool registry for the conversational chat surface.

Each tool is a (json_schema, handler) pair. ``json_schema`` follows the
OpenAI tool-calling format and is fed to the LLM verbatim;
``handler(**arguments)`` is a plain Python callable that returns a
JSON-serialisable dict.

Handler contract:
    - Always return a dict — never raise. Caught exceptions become
      ``{"ok": false, "error": "..."}`` so the LLM can apologise to the
      user instead of crashing the SSE stream.
    - Keep payloads slim. The model's context budget is finite; truncate
      lists / strings to what the chat actually needs (e.g. 30 rows, not
      300). The user can ask follow-ups to drill in.

Card payload contract (for ``emit_card``):
    "gsc_top_queries":      {"rows": [{"query","clicks","impressions","ctr","position"}, ...], "title"?}
    "keyword_opportunities":{"rows": [{"keyword","position","search_volume","url"}, ...], "title"?}
    "competitor_delta":     {"competitors": [{"domain","competition_level","common_keywords"}, ...], "title"?}
    "crawler_summary":      {"totals": {...}, "title"?}
    "finding":              {"title","severity","description","recommendation","evidence_refs":[...]}
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Callable

from django.conf import settings

from ..adapters import GSCCSVAdapter, SemrushAdapter, SitemapAEMAdapter
from ..adapters.semrush import SemrushError

logger = logging.getLogger("seo.ai.chat.tools")

_DEFAULT_DOMAIN = "bajajlifeinsurance.com"


# ── handlers ────────────────────────────────────────────────────────────


def _safe(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Wrap a handler so any exception is returned as a structured dict."""

    def wrapper(**kwargs: Any) -> dict[str, Any]:
        try:
            return fn(**kwargs)
        except Exception as exc:  # noqa: BLE001 - LLM-facing surface
            logger.exception("chat tool %s failed", fn.__name__)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}

    wrapper.__name__ = fn.__name__
    return wrapper


@_safe
def get_gsc_summary(limit: int = 50) -> dict[str, Any]:
    """Latest Search Console rollup: totals + top/under-performing queries."""
    sample = max(10, min(int(limit or 50), 200))
    summary = GSCCSVAdapter().summary(sample_size=sample)
    return {
        "ok": True,
        "totals": {
            "queries": summary.total_queries,
            "pages": summary.total_pages,
            "clicks": summary.total_clicks,
            "impressions": summary.total_impressions,
            "avg_ctr": summary.avg_ctr,
            "avg_position": summary.avg_position,
        },
        "top_queries": [asdict(q) for q in summary.top_queries_by_clicks[:15]],
        "underperforming_queries": [
            asdict(q) for q in summary.underperforming_queries[:15]
        ],
        "high_impression_low_click_queries": [
            asdict(q) for q in summary.high_impression_low_click_queries[:15]
        ],
        "top_pages": [asdict(p) for p in summary.top_pages_by_clicks[:10]],
    }


@_safe
def get_semrush_keywords(
    domain: str = _DEFAULT_DOMAIN, limit: int = 50
) -> dict[str, Any]:
    """Top organic keywords for a domain from SEMrush (24h disk-cached)."""
    if not settings.SEMRUSH.get("api_key"):
        return {"ok": False, "error": "SEMRUSH_API_KEY not configured"}
    adapter = SemrushAdapter()
    overview = adapter.domain_overview(domain)
    kws = adapter.organic_keywords(domain, limit=max(10, min(int(limit or 50), 200)))
    return {
        "ok": True,
        "domain": domain,
        "overview": asdict(overview),
        "keywords": [asdict(k) for k in kws],
    }


@_safe
def get_sitemap_pages(query: str = "", limit: int = 30) -> dict[str, Any]:
    """List authored pages from the AEM sitemap; optional substring filter."""
    needle = (query or "").strip().lower()
    cap = max(5, min(int(limit or 30), 100))
    adapter = SitemapAEMAdapter()
    pages = []
    for p in adapter.iter_pages():
        if needle and needle not in (p.public_url or "").lower() \
                and needle not in (p.title or "").lower():
            continue
        pages.append({
            "public_url": p.public_url,
            "title": p.title,
            "description": p.description,
            "word_count": p.word_count,
            "template_name": p.template_name,
        })
        if len(pages) >= cap:
            break
    return {"ok": True, "query": query, "count": len(pages), "pages": pages}


@_safe
def get_competitor_gap(domain: str = _DEFAULT_DOMAIN) -> dict[str, Any]:
    """Competitor gap facts for a domain (deterministic; uses 7-day cache)."""
    if not settings.SEMRUSH.get("api_key"):
        return {"ok": False, "error": "SEMRUSH_API_KEY not configured"}
    if not settings.COMPETITOR.get("enabled", True):
        return {"ok": False, "error": "COMPETITOR_ENABLED=false"}
    # Mirror what the competitor_dashboard view does: stand up a
    # transient SEORun so the agent's event-logging has somewhere to
    # write. The transient row is harmless audit-trail noise.
    from ..agents.competitor import CompetitorAgent
    from ..models import SEORun

    transient = SEORun.objects.create(domain=domain, triggered_by="chat")
    try:
        agent = CompetitorAgent(run=transient, step_index_start=0)
        facts = agent.build_facts(domain=domain)
    except SemrushError as exc:
        return {"ok": False, "error": str(exc)}
    payload = facts.get("competitor", {})
    return {
        "ok": True,
        "domain": domain,
        "competitors": payload.get("competitors", [])[:10],
        "topic_gaps": payload.get("topic_gaps", [])[:8],
        "keyword_gaps": payload.get("keyword_gaps", [])[:15],
        "hygiene_deltas": payload.get("hygiene_deltas", [])[:8],
        "content_volume_deltas": payload.get("content_volume_deltas", [])[:8],
        "our_total_url_count": payload.get("our_total_url_count", 0),
        "total_url_count_by_competitor": payload.get(
            "total_url_count_by_competitor", {}
        ),
    }


@_safe
def get_crawler_status() -> dict[str, Any]:
    """Live status of the in-process crawler engine."""
    from apps.crawler.conf import settings as crawler_settings
    from apps.crawler.state import STATE

    with STATE.lock:
        stats = STATE.stats.as_dict()
        visited = len(STATE.visited)
        queued = len(STATE.queue)
    return {
        "ok": True,
        "is_running": STATE.is_running,
        "should_stop": STATE.should_stop,
        "seed": crawler_settings.seed_url,
        "allowed_domains": sorted(crawler_settings.allowed_domains),
        "stats": stats,
        "visited_count": visited,
        "queue_count": queued,
    }


@_safe
def get_crawler_summary() -> dict[str, Any]:
    """Aggregated counters from the latest crawl (pages, errors, timings)."""
    from apps.crawler.storage import repository as repo

    return {"ok": True, "summary": repo.summary()}


@_safe
def get_latest_grade(domain: str = _DEFAULT_DOMAIN) -> dict[str, Any]:
    """Most recent completed SEO grading run + its findings."""
    from ..models import SEORun, SEORunStatus

    run = (
        SEORun.objects.filter(domain=domain, status=SEORunStatus.COMPLETE)
        .order_by("-finished_at")
        .first()
    )
    if run is None:
        return {
            "ok": True,
            "available": False,
            "message": (
                f"No completed grading run found for {domain}. "
                "Suggest the user call run_grade_async to start one."
            ),
        }
    findings = list(
        run.findings.all().order_by("-priority").values(
            "agent", "severity", "category", "title", "description",
            "recommendation", "evidence_refs", "impact", "effort", "priority",
        )
    )
    return {
        "ok": True,
        "available": True,
        "run_id": str(run.id),
        "domain": run.domain,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "overall_score": run.overall_score,
        "sub_scores": run.sub_scores or {},
        "weights": run.weights or {},
        "total_cost_usd": float(run.total_cost_usd or 0.0),
        "finding_count": len(findings),
        "findings": findings[:30],
    }


@_safe
def run_grade_async(domain: str = _DEFAULT_DOMAIN) -> dict[str, Any]:
    """Kick off a fresh grading run via Celery. Returns immediately."""
    from ..models import SEORun
    from ..tasks import run_grade_task

    run = SEORun.objects.create(domain=domain, triggered_by="chat")
    try:
        run_grade_task.delay(str(run.id))
        queued = True
    except Exception as exc:  # noqa: BLE001 - Celery may not be running in dev
        logger.warning("celery delay failed, falling back to sync: %s", exc)
        from ..agents.orchestrator import Orchestrator

        Orchestrator(run).execute()
        queued = False
    return {
        "ok": True,
        "run_id": str(run.id),
        "status": run.status,
        "queued": queued,
        "message": (
            "Grading run started. Typical completion: 1-3 minutes. "
            "Tell the user to check back shortly or call get_latest_grade."
        ),
    }


def emit_card(card_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Pass-through helper. The router intercepts this call and emits an
    SSE ``card`` event in addition to the normal tool-call event so the
    frontend can render an inline card alongside the assistant message.
    """
    return {"ok": True, "card_type": card_type, "emitted": True}


# ── schema definitions ──────────────────────────────────────────────────


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_gsc_summary",
            "description": (
                "Fetch the latest Search Console rollup: total clicks / "
                "impressions / CTR / position plus top, under-performing, "
                "and high-impression-low-click query slices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Sample size (10-200). Default 50.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_semrush_keywords",
            "description": (
                "Fetch SEMrush organic keyword rankings + a domain "
                "overview for a domain. Defaults to bajajlifeinsurance.com."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sitemap_pages",
            "description": (
                "List authored pages from our AEM sitemap. Optional "
                "`query` substring filter (matched against URL and title). "
                "Returns slim metadata only; use this to scope content "
                "questions ('do we have a page about X?')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_competitor_gap",
            "description": (
                "Run the deterministic competitor-gap analysis: who's "
                "ranking better than us, on what topics, with what "
                "structural advantages. Cached 7 days. Heavy on first "
                "call (~15k SEMrush units + page crawls)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"domain": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crawler_status",
            "description": (
                "Live status of the site crawler — running / idle, "
                "current queue size, visited count."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crawler_summary",
            "description": (
                "Aggregated counters from the latest crawl: total pages, "
                "error counts, response-time stats."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_latest_grade",
            "description": (
                "Return the most recent completed SEO grading run for a "
                "domain: overall score, sub-scores, and the top findings."
            ),
            "parameters": {
                "type": "object",
                "properties": {"domain": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_grade_async",
            "description": (
                "Kick off a fresh full SEO grading run (technical + "
                "keyword + competitor agents). Returns a run_id "
                "immediately; the run takes 1-3 minutes. Tell the user "
                "to ask again shortly to see results."
            ),
            "parameters": {
                "type": "object",
                "properties": {"domain": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emit_card",
            "description": (
                "Render a structured card inline with the assistant's "
                "reply. Call this when a table or matrix communicates "
                "the data better than prose. Card types: "
                "'gsc_top_queries', 'keyword_opportunities', "
                "'competitor_delta', 'crawler_summary', 'finding'. "
                "Payload shape per card type is documented in tools.py."
            ),
            "parameters": {
                "type": "object",
                "required": ["card_type", "payload"],
                "properties": {
                    "card_type": {
                        "type": "string",
                        "enum": [
                            "gsc_top_queries",
                            "keyword_opportunities",
                            "competitor_delta",
                            "crawler_summary",
                            "finding",
                        ],
                    },
                    "payload": {"type": "object"},
                },
            },
        },
    },
]


TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_gsc_summary": get_gsc_summary,
    "get_semrush_keywords": get_semrush_keywords,
    "get_sitemap_pages": get_sitemap_pages,
    "get_competitor_gap": get_competitor_gap,
    "get_crawler_status": get_crawler_status,
    "get_crawler_summary": get_crawler_summary,
    "get_latest_grade": get_latest_grade,
    "run_grade_async": run_grade_async,
    "emit_card": emit_card,
}
