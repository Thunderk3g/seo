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
    """Wrap a handler so any exception is returned as a structured dict.

    Also strips unknown kwargs before calling the underlying function.
    The LLM occasionally hallucinates arguments not in the schema
    (e.g., calling ``get_crawler_summary(limit=0)`` when the schema
    declares zero params); silently dropping unknowns is friendlier to
    the chat surface than a 500 error with a TypeError traceback.
    """
    import inspect

    sig = inspect.signature(fn)
    accepts_var_kwargs = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    )
    known_param_names = {
        name for name, p in sig.parameters.items()
        if p.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        )
    }

    def wrapper(**kwargs: Any) -> dict[str, Any]:
        if not accepts_var_kwargs:
            unknown = set(kwargs) - known_param_names
            if unknown:
                logger.info(
                    "chat tool %s: dropping unknown kwargs %s",
                    fn.__name__, sorted(unknown),
                )
                kwargs = {k: v for k, v in kwargs.items() if k in known_param_names}
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


# ── Audit / detection agents invokable from chat ─────────────────────
# Each wrapper takes the same single-URL or single-domain shape so the
# LLM doesn't have to learn separate calling conventions per agent.
# The three existing detection agents (Technical/Architecture/
# Extractability) need a SEORun for their event logging; we create a
# transient row keyed triggered_by="chat" so logs land somewhere
# inspectable without polluting full-grade history.


def _ephemeral_run(domain: str):
    """Create a transient SEORun for chat-invoked agent calls.

    Same pattern used by ``get_competitor_gap`` above. Lets the existing
    detection agents log to ``SEORunMessage`` without us having to make
    the run argument optional everywhere in the agent class.
    """
    from ..models import SEORun
    return SEORun.objects.create(domain=domain, triggered_by="chat")


def _drafts_to_dicts(drafts: list, cap: int = 30) -> list[dict[str, Any]]:
    """Serialize FindingDraft list to LLM-friendly dicts (slim)."""
    out: list[dict[str, Any]] = []
    for d in drafts[:cap]:
        out.append({
            "category": getattr(d, "category", ""),
            "severity": getattr(d, "severity", "notice"),
            "title": getattr(d, "title", ""),
            "description": (getattr(d, "description", "") or "")[:500],
            "impact": getattr(d, "impact", "medium"),
            "evidence_refs": list(getattr(d, "evidence_refs", []) or [])[:5],
        })
    return out


@_safe
def run_content_audit(
    our_url: str,
    their_url: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """LLM-grade our AEM page vs the topically-closest competitor page.

    Pairs the URL via the page_pairing matcher (or uses ``their_url`` if
    explicitly provided), then asks Groq to grade both pages on the v1
    rubric (E-E-A-T, intent match, freshness, structural extractability,
    schema coverage, internal links, word-count fit). Returns winner,
    scores, and 3-5 prioritized recommendations.

    Persists ``GapAuditFinding`` so the verdict is auditable later.
    No LLM billing required — runs on Groq's free tier.
    """
    from ..agents.content_audit_agent import ContentAuditAgent

    verdict = ContentAuditAgent(triggered_by="chat").audit(
        our_url=our_url,
        their_url=their_url or None,
        run_id=run_id or None,
    )
    return verdict.as_dict()


@_safe
def run_technical_audit(domain: str = _DEFAULT_DOMAIN) -> dict[str, Any]:
    """Detection-only technical SEO audit — AI bot access (robots.txt),
    sitemap, response times, HTTPS, canonical, viewport, structured-data
    coverage. Returns prioritized findings without recommendations.
    """
    from ..agents.technical_audit import TechnicalAuditAgent

    run = _ephemeral_run(domain)
    agent = TechnicalAuditAgent(run=run, step_index_start=0)
    findings = agent.detect(domain=domain)
    return {
        "ok": True,
        "domain": domain,
        "agent": "technical_audit",
        "run_id": str(run.id),
        "finding_count": len(findings),
        "findings": _drafts_to_dicts(findings),
    }


@_safe
def run_architecture_audit(domain: str = _DEFAULT_DOMAIN) -> dict[str, Any]:
    """Detection-only site-architecture audit — URL hierarchy depth,
    page-type distribution (product / category / blog / landing /
    comparison / calculator), orphan clusters, internal-linking shape.
    """
    from ..agents.architecture_audit import ArchitectureAuditAgent

    run = _ephemeral_run(domain)
    agent = ArchitectureAuditAgent(run=run, step_index_start=0)
    findings = agent.detect(domain=domain)
    return {
        "ok": True,
        "domain": domain,
        "agent": "architecture_audit",
        "run_id": str(run.id),
        "finding_count": len(findings),
        "findings": _drafts_to_dicts(findings),
    }


# ── Audit engine — Health Score + Issues catalogue (Phase 1) ─────────
# These wrap the new typed audit catalogue at apps/crawler/audits/.
# Read-only: they re-run the detectors over the current crawl_results.csv.
# Use when the user asks for overall health, the issue inbox, or details
# on a specific issue type.


@_safe
def get_health_score() -> dict[str, Any]:
    """Compute the current site Health Score (0-100) using the Ahrefs
    formula ``(URLs without errors / total URLs) × 100`` over the latest
    crawl results. Returns score, tier (Excellent/Good/Fair/Weak),
    severity counts, top 5 errors. Call this when the user asks
    "how are we doing?" or wants a single-number overview."""
    from apps.crawler.services.health_score import compute

    return {"ok": True, **compute().as_dict()}


@_safe
def query_page_explorer(
    sort: str = "url",
    status: str = "",
    subdomain: str = "",
    page_type: str = "",
    indexed: str = "",
    has_psi: str = "",
    q: str = "",
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Sortable / filterable URL inventory (Ahrefs Page Explorer style).

    Use this when the user asks to surface a slice of URLs:
      * "show me our slow pages over 3 seconds"
      * "what are our 404s on the branch subdomain"
      * "find pages with low word count under 300"
      * "list URLs with no schema"
    Filters mirror the query params on /api/v1/crawler/pages — see
    services/page_explorer.py for the contract. Returns up to 25 rows
    per call (cap is 200; raising further bloats the LLM context)."""
    from apps.crawler.services.page_explorer import query as run_query

    capped = max(1, min(int(limit or 25), 200))
    params = {
        "status": status,
        "subdomain": subdomain,
        "page_type": page_type,
        "indexed": indexed,
        "has_psi": has_psi,
        "q": q,
    }
    return {"ok": True, **run_query(params=params, sort=sort, limit=capped, offset=offset)}


@_safe
def get_issues_summary(
    severity: str = "",
    category: str = "",
) -> dict[str, Any]:
    """List every issue type detected in the latest crawl, sorted errors
    first then by URL count. Optional filters:
      * severity — comma-separated subset of error,warning,notice
      * category — comma-separated subset of the 8 categories
        (crawlability, indexability, content, titles, performance, cwv,
        urls, compliance)
    Returns slim summaries with counts; drill into a specific issue via
    affected URLs through the issue-detail endpoint."""
    from apps.crawler.audits import run_all

    sev_filter = {s for s in severity.split(",") if s}
    cat_filter = {c for c in category.split(",") if c}

    audit = run_all()
    occs = [o for o in audit.occurrences if o.count > 0]
    if sev_filter:
        occs = [o for o in occs if o.issue.severity in sev_filter]
    if cat_filter:
        occs = [o for o in occs if o.issue.category in cat_filter]
    order = {"error": 0, "warning": 1, "notice": 2}
    occs.sort(key=lambda o: (order[o.issue.severity], -o.count))

    return {
        "ok": True,
        "total_urls": audit.total_urls,
        "ok_urls": audit.ok_urls,
        "severity_counts": audit.severity_counts(),
        "issue_type_counts": audit.issue_type_counts(),
        "issues": [o.as_summary() for o in occs[:60]],
    }


@_safe
def run_extractability_audit(domain: str = _DEFAULT_DOMAIN) -> dict[str, Any]:
    """Detection-only content-extractability scoring — for each top AEM
    page: lead-paragraph definition, answer blocks, statistics, FAQ
    blocks, schema markup, author attribution, freshness, query-style
    headings. Surfaces the patterns AI search engines reward.
    """
    from ..agents.content_extractability import ContentExtractabilityAgent

    run = _ephemeral_run(domain)
    agent = ContentExtractabilityAgent(run=run, step_index_start=0)
    findings = agent.detect(domain=domain)
    return {
        "ok": True,
        "domain": domain,
        "agent": "content_extractability",
        "run_id": str(run.id),
        "finding_count": len(findings),
        "findings": _drafts_to_dicts(findings),
    }


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
            "name": "run_content_audit",
            "description": (
                "Run an LLM-graded content audit comparing one of OUR "
                "AEM pages to the topically-closest competitor page. "
                "Returns winner (us/them/tie), 0-100 scores for both "
                "sides, our strengths, our gaps, and 3-5 prioritized "
                "fix recommendations. Persists the verdict for history. "
                "Use this when the user asks to audit a specific page, "
                "compare against a competitor, or get fix suggestions. "
                "Requires a prior gap-pipeline run for competitor data."
            ),
            "parameters": {
                "type": "object",
                "required": ["our_url"],
                "properties": {
                    "our_url": {
                        "type": "string",
                        "description": (
                            "Full public URL of our AEM page, "
                            "e.g. https://www.bajajlifeinsurance.com/"
                            "term-insurance-plans.html"
                        ),
                    },
                    "their_url": {
                        "type": "string",
                        "description": (
                            "Optional. Specific competitor URL to "
                            "compare against. Default: auto-match "
                            "via URL slug + title similarity."
                        ),
                    },
                    "run_id": {
                        "type": "string",
                        "description": (
                            "Optional. Pin to a specific "
                            "gap-pipeline run UUID. Default: latest."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_technical_audit",
            "description": (
                "Detection-only technical SEO audit: AI bot access in "
                "robots.txt (GPTBot/ClaudeBot/PerplexityBot/Google-"
                "Extended/Bingbot), sitemap presence + indexable URL "
                "count, median response time, HTTPS/canonical/viewport/"
                "structured-data coverage. No fix recommendations "
                "(detection only). Use when the user asks for technical "
                "issues / health-check / AI bot accessibility."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": (
                            "Domain to audit. Defaults to "
                            "bajajlifeinsurance.com when omitted."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_architecture_audit",
            "description": (
                "Detection-only site-architecture audit: URL hierarchy "
                "depth, page-type distribution (product / category / "
                "blog / landing / comparison / calculator), orphan "
                "clusters, internal-linking shape. Use when the user "
                "asks about site structure, page organization, or "
                "navigation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to audit. Default: bajajlifeinsurance.com.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_extractability_audit",
            "description": (
                "Detection-only content-extractability audit on our top "
                "AEM pages: lead-paragraph definition, self-contained "
                "answer blocks, statistics with sources, FAQ blocks, "
                "schema markup, author attribution, freshness signals, "
                "query-style headings. Surfaces the structural patterns "
                "AI search engines (ChatGPT/Claude/Perplexity/Gemini) "
                "reward when picking what to cite."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to audit. Default: bajajlifeinsurance.com.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_health_score",
            "description": (
                "Compute the site Health Score (0-100) using the Ahrefs "
                "formula: URLs without any error-severity issue divided "
                "by total URLs, times 100. Returns score, tier "
                "(Excellent/Good/Fair/Weak), severity counts, and the top "
                "5 most-affecting error-severity issues. Call this when "
                "the user asks 'how are we doing?', 'overall status', or "
                "wants a single-number health overview."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_issues_summary",
            "description": (
                "List every issue type detected in the latest crawl, "
                "sorted errors first then by URL count. Each issue "
                "carries slug, title, severity, category, why-it-matters "
                "copy, how-to-fix copy, and count of affected URLs. Use "
                "this for the issues inbox view or when the user asks "
                "'what's broken?', 'show me errors', 'top issues'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "description": (
                            "Optional comma-separated subset of "
                            "error,warning,notice. Default: all."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "description": (
                            "Optional comma-separated subset of the 8 "
                            "categories: crawlability, indexability, "
                            "content, titles, performance, cwv, urls, "
                            "compliance."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_page_explorer",
            "description": (
                "Ahrefs-style sortable/filterable URL inventory over the "
                "latest crawl. Use when the user asks to find a slice of "
                "URLs by status code, subdomain, page type, indexed "
                "status, response time, or substring match. Returns up "
                "to 25 rows per call. Sort with column name (prefix `-` "
                "for descending, e.g. `-response_time_ms`)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sort": {
                        "type": "string",
                        "description": (
                            "Column to sort by. Prefix - for descending. "
                            "Valid: url, status_code, title, word_count, "
                            "response_time_ms, subdomain, page_type, "
                            "indexed_status, pagespeed_score, lcp_ms, "
                            "cls, inp_ms."
                        ),
                    },
                    "status": {
                        "type": "string",
                        "description": (
                            "Comma-separated HTTP status codes to keep "
                            "(e.g. '200', '404,500')."
                        ),
                    },
                    "subdomain": {
                        "type": "string",
                        "description": "e.g. 'www', 'branch', or 'www,branch'.",
                    },
                    "page_type": {"type": "string"},
                    "indexed": {
                        "type": "string",
                        "description": (
                            "Comma-separated subset of indexed,"
                            "not_indexed,excluded,unknown."
                        ),
                    },
                    "has_psi": {
                        "type": "string",
                        "description": (
                            "'1' to only return URLs with PSI data; "
                            "'0' for only URLs missing PSI."
                        ),
                    },
                    "q": {
                        "type": "string",
                        "description": (
                            "Case-insensitive substring filter over URL + title."
                        ),
                    },
                    "limit": {"type": "integer", "description": "1-200, default 25."},
                    "offset": {"type": "integer"},
                },
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
    "run_content_audit": run_content_audit,
    "run_technical_audit": run_technical_audit,
    "run_architecture_audit": run_architecture_audit,
    "run_extractability_audit": run_extractability_audit,
    "get_health_score": get_health_score,
    "get_issues_summary": get_issues_summary,
    "query_page_explorer": query_page_explorer,
    "emit_card": emit_card,
}
