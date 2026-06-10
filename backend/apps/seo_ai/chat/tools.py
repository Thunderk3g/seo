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
def get_trends(window: int = 90, engine: str = "") -> dict[str, Any]:
    """Time-series of daily Health Score + per-category counts from
    MetricSnapshot rows. Use when the user asks "are we improving?",
    "trend?", "health score history", "how did errors change over
    time?". Returns chronologically ascending snapshots (oldest -> newest).
    Empty list when MetricSnapshot table is empty — operator must run
    `python manage.py snapshot_metrics` (or wait for the Celery beat
    nightly task) at least once."""
    from apps.crawler.services.snapshot_runner import latest

    capped = max(1, min(int(window or 90), 365))
    rows = latest(engine=engine, limit=capped)
    return {
        "ok": True,
        "engine": engine or "any",
        "window": capped,
        "snapshot_count": len(rows),
        "snapshots": rows,
    }


@_safe
def compare_crawls(a: str = "", b: str = "") -> dict[str, Any]:
    """SEMrush-style Compare Crawls — diff any two CrawlSnapshot rows
    (legacy or scrapy). When a/b are blank, picks the two most-recent
    snapshots automatically. Use when the user asks "what changed
    since the last crawl?", "compare snapshots", "did <X> get fixed?".
    Returns Fixed / New / Changed per issue + per-URL page-set diffs
    + Health Score delta."""
    from apps.crawler.services.crawl_diff import diff, latest_two_snapshots

    if not (a and b):
        pair = latest_two_snapshots()
        if pair is None:
            return {
                "ok": False,
                "error": "need at least 2 CrawlSnapshot rows",
                "hint": "run python manage.py crawl twice",
            }
        a, b = pair
    return {"ok": True, **diff(a, b).as_dict()}


@_safe
def get_thematic_report(slug: str = "") -> dict[str, Any]:
    """One of 8 thematic deep-dive reports: robots, crawlability,
    https, international, performance, linking, markup, cwv.
    Bundles curated issues + relevant page-explorer slices into one
    focused payload. Use when the user asks about a specific concern
    ("how are our robots?", "markup hygiene?", "international SEO?",
    "performance theme?"). Without `slug`, returns the list of
    available themes."""
    from apps.crawler.services.themes import get as get_theme, list_themes

    if not slug:
        return {"ok": True, "themes": list_themes()}
    theme = get_theme(slug)
    if theme is None:
        return {"ok": False, "error": f"unknown theme slug: {slug}",
                "available": [t["slug"] for t in list_themes()]}
    return {"ok": True, **theme.as_dict()}


@_safe
def audit_llms_txt(domain: str = "bajajlifeinsurance.com") -> dict[str, Any]:
    """Audit /llms.txt at the given site root (the llmstxt.org spec — AI
    search's equivalent of robots.txt). Returns presence, byte size,
    section + link counts, structural validation (H1 + blockquote +
    sections) and companion llms-full.txt detection. Use when the
    user asks "do we have an llms.txt?", "is our llms.txt valid?",
    "GEO readiness?", or "how do AI search engines see us?"."""
    from apps.crawler.services.llms_txt import audit as audit_fn
    result = audit_fn(domain)
    return {"ok": True, **result.as_dict()}


@_safe
def generate_llms_txt(max_pages_per_section: int = 30) -> dict[str, Any]:
    """Generate a draft /llms.txt from the live AEM sitemap + crawler
    page-type data. Groups pages by intent (Insurance products,
    Calculators, Knowledge centre, etc.) and produces a Markdown body
    the operator pastes into AEM. Use when the user asks "write our
    llms.txt", "draft an llms.txt", or "generate llms.txt"."""
    from apps.crawler.services.llms_txt import generate
    draft = generate(max_pages_per_section=int(max_pages_per_section or 30))
    return {"ok": True, **draft.as_dict()}


# ── Live crawl tools — the assistant's own crawler ─────────────────────
# Any URL (ours or a competitor's), on demand, full structural mirror:
# zoned headings/links/images, body stats, schema, optional CWV. Results
# are deliberately compact — the router truncates tool output at 4 000
# chars, so we ship counts + capped samples, never raw lists.


def _live_page_digest(row) -> dict[str, Any]:
    """Compact structural digest of one ``CrawlerPageResult`` row
    produced by ``crawl_live`` — small enough that an 8-page comparison
    survives the router's 4k tool-result cap."""
    headings = list(row.headings_json or [])
    internal = list(row.internal_links_json or [])
    external = list(row.external_links_json or [])
    images = list(row.images_json or [])

    h_by_level: dict[int, list[str]] = {}
    for h in headings:
        h_by_level.setdefault(int(h.get("level") or 0), []).append(
            (h.get("text") or "")[:120]
        )

    def _zone_counts(entries: list[dict]) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in entries:
            z = (e.get("zone") or "content") or "content"
            out[z] = out.get(z, 0) + 1
        return out

    missing_alt = [i for i in images if not (i.get("alt") or "").strip()]
    return {
        "url": row.url,
        "status_code": row.status_code,
        "response_time_ms": row.response_time_ms,
        "title": (row.title or "")[:160],
        "title_length": len(row.title or ""),
        "meta_description_length": len(row.meta_description or ""),
        "canonical": (row.canonical or "")[:200],
        "meta_robots": row.meta_robots or "",
        "word_count": row.word_count,
        "headings": {
            "h1": h_by_level.get(1, [])[:3],
            "h1_count": len(h_by_level.get(1, [])),
            "h2_count": len(h_by_level.get(2, [])),
            "h3_count": len(h_by_level.get(3, [])),
            "h2_outline": h_by_level.get(2, [])[:12],
        },
        "links": {
            "internal": len(internal),
            "external": len(external),
            "internal_by_zone": _zone_counts(internal),
            # In-body links = anything outside the chrome landmarks.
            # _classify_zone emits main/other for body content (plus
            # header/nav/footer/aside for chrome).
            "content_link_samples": [
                {"anchor": (l.get("anchor") or "")[:60],
                 "href": (l.get("href") or "")[:140]}
                for l in internal
                if (l.get("zone") or "other") in ("content", "main", "other")
            ][:5],
        },
        "images": {
            "total": len(images),
            "missing_alt": len(missing_alt),
            "missing_alt_pct": (
                round(100.0 * len(missing_alt) / len(images), 1) if images else 0.0
            ),
            "missing_alt_samples": [
                (i.get("src") or "")[:140] for i in missing_alt
            ][:5],
        },
        "schema_types": list(row.jsonld_types or [])[:8],
        "videos": len(row.videos_json or []),
    }


def _cwv_for_url(url: str) -> dict[str, Any]:
    """Single-URL Core Web Vitals via PSI — BOTH mobile and desktop
    (operator rule: single-page crawls report mobile + PC; bulk
    competitor crawls never run CWV). Disk-cached 7 days at the
    adapter, so repeat questions cost zero quota."""
    from ..adapters.cwv_psi import AdapterDisabledError, PSIAdapter
    try:
        psi = PSIAdapter()
    except AdapterDisabledError as exc:
        return {"available": False, "reason": str(exc)}

    out: dict[str, Any] = {"available": False}
    for strategy in ("mobile", "desktop"):
        try:
            rec = psi.fetch(url, strategy=strategy)
        except Exception as exc:  # noqa: BLE001
            out[strategy] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
            continue
        if rec is None or rec.error:
            out[strategy] = {"error": (rec.error if rec else "no record")[:200]}
            continue
        out["available"] = True
        out[strategy] = {
            "performance_score": rec.performance_score,
            "lab": {"lcp_ms": rec.lab_lcp_ms, "cls": rec.lab_cls,
                    "fcp_ms": rec.lab_fcp_ms, "ttfb_ms": rec.lab_ttfb_ms},
            "field": ({
                "lcp_ms": rec.field_lcp_ms, "lcp_category": rec.field_lcp_category,
                "inp_ms": rec.field_inp_ms, "inp_category": rec.field_inp_category,
                "cls": rec.field_cls, "cls_category": rec.field_cls_category,
            } if rec.has_field_data else None),
            "cached": rec.cached,
        }
    return out


@_safe
def crawl_page(url: str, include_cwv: bool = False) -> dict[str, Any]:
    """LIVE-CRAWL one URL right now (ours or any competitor's) and return
    its full page structure: h1/h2/h3 outline + counts, every-link
    inventory split by zone (header/nav/content/footer), image alt-text
    coverage with offending samples, word count, title/meta/canonical/
    robots, schema types. Set include_cwv=true to also run PageSpeed
    (mobile lab + CrUX field LCP/INP/CLS) for that page. Use when the
    user pastes a URL and asks "crawl this", "check this page", "what's
    the structure of …", or "LCP of this page"."""
    from apps.crawler.views import CrawlLiveError, crawl_live
    try:
        _snap, row = crawl_live(url)
    except CrawlLiveError as exc:
        return {"ok": False, "error": str(exc)[:300],
                "status_code": exc.status_code}
    out: dict[str, Any] = {"ok": True, "page": _live_page_digest(row)}
    if include_cwv:
        out["cwv"] = _cwv_for_url(row.final_url or row.url)
    return out


@_safe
def crawl_pages(urls: list[str] | None = None) -> dict[str, Any]:
    """LIVE-CRAWL up to 8 URLs in parallel and return each page's
    compact structure digest (headings, zoned links, image alt coverage,
    word count, schema). Use when the user asks to "compare these
    pages", "crawl these 5 URLs", or hands over a list of competitor
    pages to inspect. For a single URL prefer crawl_page."""
    from concurrent.futures import ThreadPoolExecutor

    from apps.crawler.views import CrawlLiveError, crawl_live

    wanted = [u.strip() for u in (urls or []) if u and u.strip()][:8]
    if not wanted:
        return {"ok": False, "error": "pass urls=[...] — at least one URL"}

    def _one(u: str) -> dict[str, Any]:
        try:
            _s, row = crawl_live(u)
            return _live_page_digest(row)
        except CrawlLiveError as exc:
            return {"url": u, "error": str(exc)[:200]}
        except Exception as exc:  # noqa: BLE001
            return {"url": u, "error": f"{type(exc).__name__}: {exc}"[:200]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        digests = list(pool.map(_one, wanted))
    crawled = [d for d in digests if not d.get("error")]
    return {"ok": True, "requested": len(wanted),
            "crawled": len(crawled), "pages": digests}


def _heading_tokens(text: str) -> set[str]:
    """Normalised token set for heading-topic overlap. Drops stopwords
    so "What is Term Insurance?" ≈ "Term Insurance Meaning"."""
    import re as _re
    stop = {"the", "a", "an", "of", "in", "on", "for", "to", "and", "or",
            "is", "are", "what", "how", "why", "your", "you", "with",
            "our", "we", "do", "does", "vs"}
    toks = {t for t in _re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(t) > 2 and t not in stop}
    return toks


@_safe
def compare_page_structures(
    our_url: str, competitor_urls: list[str] | None = None,
) -> dict[str, Any]:
    """CONTENT-GAP comparison: live-crawl OUR page plus up to 5
    competitor pages, then report side-by-side structure (word count,
    h2/h3 counts, image alt %, internal links, schema) AND the heading
    topics competitors cover that our page does not (the gap list). Use
    when the user asks "compare our term page with HDFC's", "what do
    competitor pages cover that we don't", or any our-page-vs-rivals
    content question."""
    from concurrent.futures import ThreadPoolExecutor

    from apps.crawler.views import CrawlLiveError, crawl_live

    rivals = [u.strip() for u in (competitor_urls or []) if u and u.strip()][:5]
    if not (our_url or "").strip():
        return {"ok": False, "error": "our_url required"}
    if not rivals:
        return {"ok": False, "error": "pass competitor_urls=[...] — at least one"}

    def _one(u: str):
        try:
            _s, row = crawl_live(u)
            return row, None
        except (CrawlLiveError, Exception) as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"[:200]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_one, [our_url.strip(), *rivals]))

    ours_row, ours_err = results[0]
    if ours_row is None:
        return {"ok": False, "error": f"our page failed: {ours_err}"}
    ours = _live_page_digest(ours_row)

    our_tokens: set[str] = set()
    for h in (ours_row.headings_json or []):
        our_tokens |= _heading_tokens(h.get("text") or "")

    rival_digests: list[dict[str, Any]] = []
    gap_counter: dict[str, int] = {}
    for (row, err), url in zip(results[1:], rivals):
        if row is None:
            rival_digests.append({"url": url, "error": err})
            continue
        rival_digests.append(_live_page_digest(row))
        page_gaps: set[str] = set()  # dedupe repeated headings per page
        for h in (row.headings_json or []):
            text = (h.get("text") or "").strip()
            toks = _heading_tokens(text)
            # Skip stat/number headings ("652", "~5 crore") — need at
            # least two meaningful word tokens to be a topic.
            word_toks = [t for t in toks if not t.isdigit()]
            if len(word_toks) < 2:
                continue
            # A heading is "uncovered" when under half its meaningful
            # tokens appear anywhere in our heading vocabulary.
            if len(toks & our_tokens) < max(1, len(toks) // 2):
                page_gaps.add(text[:90])
        for key in page_gaps:
            gap_counter[key] = gap_counter.get(key, 0) + 1

    gaps = sorted(gap_counter.items(), key=lambda kv: -kv[1])[:15]
    return {
        "ok": True,
        "ours": ours,
        "competitors": rival_digests,
        "topics_competitors_cover_we_dont": [
            {"heading": k, "competitor_pages": v} for k, v in gaps
        ],
        "note": ("Gap list = competitor h1-h6 headings whose topic tokens "
                 "don't appear in our page's headings. Verify against body "
                 "copy before acting — content can exist without a heading."),
    }


@_safe
def get_page_links(url: str, kind: str = "internal", fresh: bool = True) -> dict[str, Any]:
    """List the actual links on a page (live-crawls by default so the
    list is current). kind='internal' (default), 'external', or 'all'.
    Returns each link's anchor text, URL and zone (header/nav/content/
    footer). Use when the user asks 'give me the internal links of this
    page', 'what does this page link to', 'external links on X'."""
    from ..services.technical_audit import audit_url
    a = audit_url(url, include_cwv=False, fresh=bool(fresh))
    if not a.get("ok"):
        # audit_url already DB-falls-back; surface its error.
        from apps.crawler.views import CrawlLiveError, crawl_live
        try:
            _s, row = crawl_live(url)
        except CrawlLiveError as exc:
            return {"ok": False, "error": str(exc)[:200]}
        internal = list(row.internal_links_json or [])
        external = list(row.external_links_json or [])
    else:
        # Re-derive from the same source the audit used.
        from ..services.technical_audit import _row_from_db
        row = _row_from_db(a["url"])
        internal = list(row.internal_links_json or []) if row else []
        external = list(row.external_links_json or []) if row else []

    def _fmt(links: list[dict], cap: int = 60) -> list[dict]:
        return [{"anchor": (l.get("anchor") or "")[:80],
                 "href": (l.get("href") or "")[:200],
                 "zone": l.get("zone") or "content"} for l in links[:cap]]

    out: dict[str, Any] = {"ok": True, "url": a.get("url", url),
                           "source": a.get("source", "live_crawl"),
                           "internal_count": len(internal),
                           "external_count": len(external)}
    k = (kind or "internal").lower()
    if k in ("internal", "all"):
        out["internal_links"] = _fmt(internal)
    if k in ("external", "all"):
        out["external_links"] = _fmt(external)
    if len(internal) > 60 or len(external) > 60:
        out["note"] = ("Showing up to 60 per type. For the full list, run a "
                       "technical audit export (XLSX) of this URL.")
    return out


@_safe
def technical_audit_site() -> dict[str, Any]:
    """Whole-WEBSITE technical audit over the latest own-site crawl —
    aggregate issues across all pages: duplicate titles/meta, indexability
    breakdown, redirect chains, broken/oversized images, thin content,
    missing titles/descriptions, pages without schema, hreflang errors —
    each with a count, the drawback, a recommendation, and sample
    affected URLs. Use when the user asks 'audit the whole site', 'site-
    wide technical issues', 'duplicate titles across the site', 'how many
    pages are noindex'."""
    from ..services.technical_audit import audit_site
    a = audit_site()
    if not a.get("ok"):
        return a
    # Trim sample lists so the whole rollup survives the 4k tool cap.
    for f in a.get("findings", []):
        f["samples"] = (f.get("samples") or [])[:5]
    return a


@_safe
def technical_audit_url(url: str, check_broken_links: bool = False,
                        fresh: bool = False) -> dict[str, Any]:
    """FULL technical SEO audit of ONE URL (ours, a competitor's, or any
    URL). DB-first: if the URL was already crawled it audits the stored
    data; if not, it LIVE-CRAWLS the page right now. Runs a live Core Web
    Vitals test (PageSpeed mobile + desktop, lab + CrUX field), and
    checks against standard on-page SEO guidelines: title/meta length,
    single-H1, heading structure, per-image alt text (lists the images
    missing alt), internal/external links, canonical, noindex, thin
    content, schema, HTTPS, response time. Returns a 0-100 score plus a
    prioritised findings list where every finding has the drawback AND a
    concrete recommendation. Set check_broken_links=true to also probe
    the page's links for 4xx/5xx (slower). Use when the user pastes a URL
    and asks 'technical audit', 'check this page', 'is this page SEO-
    healthy', 'LCP of this page', 'which images miss alt', or 'broken
    links on this page'. Set fresh=true to force a live re-crawl (ignore
    stored data) so the audit reflects the page as it is right now."""
    from ..services.technical_audit import audit_url
    return audit_url(url, check_broken_links=bool(check_broken_links),
                     fresh=bool(fresh))


@_safe
def compare_technical_audit(our_url: str,
                            competitor_urls: list[str] | None = None) -> dict[str, Any]:
    """Compare the TECHNICAL audit of OUR page against up to 5 competitor
    pages, side by side — score, title/meta, H1/H2/H3 counts, internal/
    external links, image alt coverage, schema, and mobile LCP for each.
    DB-first; any URL not already crawled is live-crawled on the spot.
    Use for product-to-product / page-to-page technical comparison:
    'compare our term page with HDFC's technically', 'how does our ULIP
    page stack up against ICICI on SEO'."""
    from ..services.technical_audit import compare_urls
    return compare_urls(our_url, competitor_urls or [])


@_safe
def get_ai_bot_hits(limit: int = 50) -> dict[str, Any]:
    """Recent verified AI-bot hits on Bajaj pages (GPTBot, ClaudeBot,
    PerplexityBot, Google-Extended, Bytespider, etc.). Returns
    per-bot aggregate totals (total / verified / spoofed) plus the
    most recent ``limit`` hits. Use when the user asks "is GPTBot
    crawling us?", "how often does ClaudeBot hit our site?", "AI
    crawler activity?"."""
    from apps.crawler.adapters.bot_log_parser import recent_hits, hits_by_bot
    cap = max(1, min(int(limit or 50), 500))
    return {
        "ok": True,
        "totals": hits_by_bot(),
        "recent": recent_hits(cap),
    }


@_safe
def get_backlinks(limit: int = 50, target_domain: str = "") -> dict[str, Any]:
    """Common Crawl-derived inbound links pointing at Bajaj URLs.
    Returns the most recent ``limit`` backlinks and a per-target
    summary. Use when the user asks "who links to us?", "our
    backlinks?", "inbound link profile?"."""
    from apps.crawler.adapters.commoncrawl_backlinks import recent_backlinks, summary
    cap = max(1, min(int(limit or 50), 500))
    rows = recent_backlinks(cap)
    if target_domain:
        rows = [r for r in rows if r.get("target_domain") == target_domain]
    return {"ok": True, "summary": summary(), "backlinks": rows}


@_safe
def ping_indexnow(urls: str = "") -> dict[str, Any]:
    """Submit a batch of Bajaj URLs to IndexNow (Bing + Yandex +
    partners). Pass a comma-separated string of URLs. URLs that don't
    match the Bajaj allow-list are rejected. Dry-run mode if
    INDEXNOW_KEY env var is unset. Use when the user asks to push a
    fresh URL for AI/search re-indexing."""
    from apps.crawler.adapters.indexnow import ping_urls
    url_list = [u.strip() for u in (urls or "").split(",") if u.strip()]
    return ping_urls(url_list)


@_safe
def get_pagerank_top(n: int = 20) -> dict[str, Any]:
    """Top URLs by internal PageRank ("Link Score") — Ahrefs Page Rating
    equivalent. Computed from crawl_discovered.csv link graph using
    networkx. Use when the user asks "what are our most-linked pages?",
    "which URLs concentrate link equity?", or "are our hero pages
    well-linked internally?". Returns URLs with pagerank_score 0-100
    (log-rescaled) + in_degree / out_degree."""
    from apps.crawler.services.pagerank import all_entries, top_n, summary

    cap = max(1, min(int(n or 20), 200))
    return {
        "ok": True,
        "summary": summary(),
        "top": top_n(cap),
    }


@_safe
def get_orphan_pages(max_in_degree: int = 0) -> dict[str, Any]:
    """URLs with no internal inbound links (or below a threshold).
    High-leverage SEO fix: orphan pages can't accumulate link equity
    and are slow to be discovered by Google. Use when the user asks
    "what pages have no internal links?", "orphans?", "buried pages?".
    """
    from apps.crawler.services.pagerank import orphans

    return {
        "ok": True,
        "max_in_degree": max_in_degree,
        "orphans": orphans(max_in_degree=int(max_in_degree or 0)),
    }


@_safe
def get_near_duplicates(n: int = 20, threshold: float = 0.9) -> dict[str, Any]:
    """Near-duplicate URL clusters via MinHash + LSH (Screaming Frog
    uses the same algorithm). Returns clusters where multiple URLs
    share a near-identical title + URL pattern. Use when the user
    asks "duplicate content?", "title duplicates?", "cannibalised
    pages?", or wants to find template bugs producing dup pages."""
    from apps.crawler.services.near_dup import top_clusters, summary

    cap = max(1, min(int(n or 20), 100))
    return {
        "ok": True,
        "summary": summary(threshold=threshold),
        "clusters": top_clusters(cap, threshold=threshold),
    }


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


# ── Adobe Analytics ────────────────────────────────────────────────────


@_safe
def get_adobe_summary(lookback_days: int = 7) -> dict[str, Any]:
    """Adobe Analytics rollup — visitors, visits, page views, channels,
    top countries, devices, top pages, year-over-year compare. File-cached
    per section; never re-pulls if a recent fetch exists.

    The Adobe pull is heavy (~20 reports). The dashboard endpoint reads
    cached payloads when available — this tool just hits that endpoint.
    """
    from ..adapters.adobe_analytics import (
        AdapterDisabledError, AdobeAnalyticsAdapter,
    )

    try:
        adapter = AdobeAnalyticsAdapter()
    except AdapterDisabledError as exc:
        return {"ok": False, "error": str(exc), "available": False}

    dash = adapter.dashboard(lookback_days=int(lookback_days or 7), limit=15)
    # Trim aggressively — chat router caps at 4 KB.
    return {
        "ok": True,
        "rsid": dash.rsid,
        "lookback_days": dash.lookback_days,
        "totals": dash.totals,
        "visitors_summary": dash.visitors_summary,
        "top_pages": [asdict(p) for p in dash.top_pages[:8]],
        "channels": [asdict(c) for c in dash.channels[:8]],
        "top_countries": [asdict(c) for c in dash.countries[:8]],
        "devices": [asdict(d) for d in dash.devices[:5]],
        "daily_trend_tail": [asdict(d) for d in dash.daily_trend[-7:]],
        "data_freshness_summary": {
            k: v for k, v in dash.data_freshness.items()
            if v != "live"
        },
    }


@_safe
def get_adobe_top_pages(lookback_days: int = 7, limit: int = 15) -> dict[str, Any]:
    """Adobe Analytics top pages by page-views over the last N days."""
    from ..adapters.adobe_analytics import (
        AdapterDisabledError, AdobeAnalyticsAdapter,
    )

    try:
        adapter = AdobeAnalyticsAdapter()
    except AdapterDisabledError as exc:
        return {"ok": False, "error": str(exc)}

    rows, summary = adapter.top_pages(
        lookback_days=int(lookback_days or 7),
        limit=max(5, min(int(limit or 15), 50)),
    )
    return {
        "ok": True,
        "lookback_days": int(lookback_days or 7),
        "totals": summary,
        "pages": [asdict(r) for r in rows],
    }


# ── Meta Ads (Apify) ──────────────────────────────────────────────────


@_safe
def get_meta_ads_summary(
    competitor: str = "", include_ours: bool = False, count: int = 25,
) -> dict[str, Any]:
    """Facebook + Instagram ad-library data for one competitor (default
    domain) or for Bajaj itself. ``competitor`` accepts a domain or a
    brand name. Pass ``include_ours=true`` only when comparing — the
    backend will prepend Bajaj's own ads to the list. Cached 24h on disk.
    """
    from ..adapters.apify_meta_ads import (
        AdapterDisabledError, dashboard_payload,
    )

    target = competitor.strip() or "Bajaj Life Insurance"
    try:
        body = dashboard_payload(
            competitors=[target] if target else None,
            count=max(5, min(int(count or 25), 50)),
            include_ours=bool(include_ours),
        )
    except AdapterDisabledError as exc:
        return {"ok": False, "error": str(exc)}
    except TypeError:
        # Older dashboard_payload signature; fall back.
        body = dashboard_payload(
            competitors=[target] if target else None,
            count=max(5, min(int(count or 25), 50)),
        )
    comps = (body or {}).get("competitors") or []
    # Only emit the headline numbers per competitor — full ads list bursts
    # the 4 KB tool cap.
    slim = []
    for c in comps:
        slim.append({
            "competitor": c.get("competitor"),
            "total_ads": c.get("total_ads"),
            "active_ads": c.get("active_ads"),
            "new_ads_last_7d": c.get("new_ads_last_7d"),
            "page_name": c.get("page_name"),
            "top_ctas": (c.get("top_ctas") or [])[:3],
            "top_themes": (c.get("common_themes") or [])[:3],
            "top_landing_domains": (c.get("top_landing_domains") or [])[:3],
            "error": c.get("error") or "",
        })
    return {
        "ok": True,
        "country": (body or {}).get("country"),
        "refreshed_at": (body or {}).get("refreshed_at"),
        "competitors": slim,
    }


# ── Brand mentions ──────────────────────────────────────────────────────


@_safe
def get_brand_mentions(limit: int = 25) -> dict[str, Any]:
    """Third-party brand mentions: RSS feeds + SerpAPI daily catch-all.
    Returns recent mentions tagged by brand variant (new / old / parent /
    ambiguous). Use this to track how the rebrand is sticking.
    """
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    from ..models import BrandMention

    since = dj_tz.now() - timedelta(days=30)
    rows = list(
        BrandMention.objects
        .filter(published_at__gte=since)
        .order_by("-published_at")[:max(5, min(int(limit or 25), 100))]
    )
    by_variant: dict[str, int] = {}
    for r in rows:
        by_variant[r.brand_variant] = by_variant.get(r.brand_variant, 0) + 1
    return {
        "ok": True,
        "window_days": 30,
        "count": len(rows),
        "by_variant": by_variant,
        "recent": [
            {
                "title": (r.title or "")[:180],
                "source": r.source or "",
                "url": r.url or "",
                "brand_variant": r.brand_variant,
                "sentiment": getattr(r, "sentiment_label", "") or "",
                "published_at": (
                    r.published_at.isoformat() if r.published_at else ""
                ),
            }
            for r in rows[:15]
        ],
    }


# ── GEO score ─────────────────────────────────────────────────────────


@_safe
def get_geo_score(deep: bool = False) -> dict[str, Any]:
    """Unified Generative Engine Optimization score for the brand —
    citation density, E-E-A-T markup, AI-bot hit count, llms.txt
    presence, Reddit / Quora mentions, YouTube presence, Wikidata
    entity, brand-mention feed. ``deep=true`` includes the external
    SerpAPI + Wikidata calls (slower)."""
    from dataclasses import asdict

    from ..services.geo import compute_geo_score

    result = compute_geo_score(deep=bool(deep))
    body = asdict(result)
    # Suggestions list can be long; cap to top 6.
    if isinstance(body.get("suggestions"), list):
        body["suggestions"] = body["suggestions"][:6]
    return {"ok": True, **body}


# ── Competitor crawls (Phase G storage) ────────────────────────────────


@_safe
def list_competitors_crawled() -> dict[str, Any]:
    """List every competitor domain we've crawled via the daily Scrapy
    walker. Returns target_domain, status (running / complete),
    pages_in_db, change_events. Use this BEFORE
    ``get_competitor_detail`` so the model knows what's available."""
    from collections import defaultdict

    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult
    from django.db.models import Count

    from ..models import CompetitorChangeEvent

    qs = (
        CrawlSnapshot.objects
        .filter(kind=CrawlSnapshot.Kind.COMPETITOR)
        .exclude(status=CrawlSnapshot.Status.FAILED)
        .order_by("-started_at")
    )
    latest_by_domain: dict[str, Any] = {}
    for snap in qs:
        td = (snap.target_domain or "").strip().lower()
        if not td or td in latest_by_domain:
            continue
        latest_by_domain[td] = snap

    if not latest_by_domain:
        return {"ok": True, "competitors": [], "count": 0}

    snapshot_ids = [s.id for s in latest_by_domain.values()]
    page_counts = dict(
        CrawlerPageResult.objects
        .filter(snapshot_id__in=snapshot_ids)
        .values_list("snapshot_id")
        .annotate(n=Count("id"))
    )
    change_counts: dict[str, int] = defaultdict(int)
    for row in (
        CompetitorChangeEvent.objects
        .filter(competitor_domain__in=list(latest_by_domain.keys()))
        .values_list("competitor_domain")
        .annotate(n=Count("id"))
    ):
        change_counts[row[0]] = row[1]

    rows = []
    for td, snap in sorted(latest_by_domain.items()):
        rows.append({
            "domain": td,
            "status": snap.status,
            "started_at": (
                snap.started_at.isoformat() if snap.started_at else None
            ),
            "pages_in_db": page_counts.get(snap.id, 0),
            "change_events": change_counts.get(td, 0),
        })
    return {"ok": True, "competitors": rows, "count": len(rows)}


@_safe
def get_competitor_detail(domain: str) -> dict[str, Any]:
    """Per-competitor data: latest crawl profile + sample pages + KPI
    aggregates (avg word count, schema coverage, page-type mix, CWV
    medians). Domain is the apex (e.g. ``hdfclife.com``). Reads the
    Phase G Scrapy-walker storage."""
    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult

    if not domain:
        return {"ok": False, "error": "domain required"}
    domain = domain.strip().lower().lstrip("www.")

    snap = (
        CrawlSnapshot.objects
        .filter(
            kind=CrawlSnapshot.Kind.COMPETITOR,
            status=CrawlSnapshot.Status.COMPLETE,
            target_domain__iexact=domain,
        )
        .order_by("-started_at")
        .first()
    )
    if snap is None:
        return {"ok": False, "error": f"no snapshot for {domain}"}

    pages = list(
        CrawlerPageResult.objects.filter(snapshot=snap)
        .only("url", "title", "word_count", "jsonld_count", "page_type",
              "headings_json", "internal_links_json")
        [:50]
    )
    page_types: dict[str, int] = {}
    schema_pages = 0
    word_counts: list[int] = []
    for p in pages:
        pt = (p.page_type or "").strip() or "unknown"
        page_types[pt] = page_types.get(pt, 0) + 1
        if (p.jsonld_count or 0) > 0:
            schema_pages += 1
        word_counts.append(int(p.word_count or 0))

    avg_wc = (sum(word_counts) / len(word_counts)) if word_counts else 0
    return {
        "ok": True,
        "domain": domain,
        "snapshot_id": str(snap.id),
        "started_at": (snap.started_at.isoformat() if snap.started_at else None),
        "pages_crawled": snap.pages_ok,
        "pages_in_sample": len(pages),
        "avg_word_count": round(avg_wc),
        "schema_pct": (
            round(100 * schema_pages / len(pages)) if pages else 0
        ),
        "page_type_mix": page_types,
        "sample_titles": [
            (p.title or "")[:140] for p in pages[:10] if p.title
        ],
    }


# ── Data-sources introspection (the meta-tool) ────────────────────────


@_safe
def list_data_sources() -> dict[str, Any]:
    """ALWAYS available. Lists every data source the platform can query
    + which chat tool to use for each. Call this FIRST whenever the user
    asks about a data source you're not sure is available
    ('do we have Adobe data?', 'what about Meta ads?', 'is GSC pulled?')
    instead of replying that we don't have it. Returns a static
    inventory of capabilities — fast, no DB hit.
    """
    return {
        "ok": True,
        "sources": [
            {"name": "Search Console (GSC)", "tool": "get_gsc_summary",
             "data": "clicks / impressions / CTR / position by query, page, country, device"},
            {"name": "SEMrush", "tool": "get_semrush_keywords",
             "data": "organic keyword rankings + domain overview"},
            {"name": "Adobe Analytics", "tool": "get_adobe_summary",
             "data": "visitors, page views, sessions, channels, geo, devices, top pages, daily trend, YoY"},
            {"name": "Adobe Analytics — top pages", "tool": "get_adobe_top_pages",
             "data": "page-view ranking for a chosen lookback window"},
            {"name": "Meta Ad Library (Apify)", "tool": "get_meta_ads_summary",
             "data": "active Facebook + Instagram ads per competitor or for our own brand"},
            {"name": "Brand mentions", "tool": "get_brand_mentions",
             "data": "RSS + SerpAPI third-party mentions of the brand"},
            {"name": "GEO score", "tool": "get_geo_score",
             "data": "Generative Engine Optimisation rollup (citations, E-E-A-T, AI bots, llms.txt, Reddit/Quora, YouTube)"},
            {"name": "AEM sitemap", "tool": "get_sitemap_pages",
             "data": "authored pages list with title / URL / template"},
            {"name": "In-house crawl summary", "tool": "get_crawler_summary",
             "data": "total pages, error counts, response-time stats"},
            {"name": "In-house crawler status", "tool": "get_crawler_status",
             "data": "live running / idle / queue size"},
            {"name": "Competitor gap (SEMrush-driven)", "tool": "get_competitor_gap",
             "data": "competitor roster + topic / hygiene / volume gaps"},
            {"name": "Competitor crawls list", "tool": "list_competitors_crawled",
             "data": "every competitor we've Scrapy-walked + live crawl status"},
            {"name": "Per-competitor detail", "tool": "get_competitor_detail",
             "data": "sample pages, page-type mix, schema coverage, avg word count"},
            {"name": "Health score", "tool": "get_health_score",
             "data": "single SEO health rollup across crawler + GSC + audits"},
            {"name": "Latest grading run", "tool": "get_latest_grade",
             "data": "most recent multi-agent run: overall score, sub-scores, top findings"},
            {"name": "Backlinks", "tool": "get_backlinks",
             "data": "external links pointing at our site (Ahrefs-style when key configured)"},
            {"name": "AI bot hits", "tool": "get_ai_bot_hits",
             "data": "GPTBot / ClaudeBot / PerplexityBot crawl activity from server logs"},
            {"name": "llms.txt audit", "tool": "audit_llms_txt",
             "data": "presence + validity of /llms.txt for AI engine consumption"},
            {"name": "Trends", "tool": "get_trends",
             "data": "Health Score over time + engine breakdown"},
            {"name": "Compare crawls", "tool": "compare_crawls",
             "data": "diff two crawler snapshots"},
            {"name": "Issues", "tool": "get_issues_summary",
             "data": "per-issue-type counts from the audit engine"},
            {"name": "Page explorer", "tool": "query_page_explorer",
             "data": "sortable / filterable URL inventory from the latest crawl"},
            {"name": "PageRank top", "tool": "get_pagerank_top",
             "data": "highest-PageRank pages from our internal link graph"},
            {"name": "Orphan pages", "tool": "get_orphan_pages",
             "data": "pages with low / zero inbound internal links"},
            {"name": "Near-duplicates", "tool": "get_near_duplicates",
             "data": "page pairs above a similarity threshold (canonicalisation candidates)"},
            {"name": "Thematic report", "tool": "get_thematic_report",
             "data": "themed slice across the crawl (e.g. ULIP-only, retirement-only)"},
        ],
        "audit_agents": [
            {"name": "Content audit", "tool": "run_content_audit",
             "purpose": "LLM-graded comparison of our URL vs competitors"},
            {"name": "Technical audit", "tool": "run_technical_audit",
             "purpose": "site-wide tech checks (robots, sitemap, HTTPS, AI bots)"},
            {"name": "Architecture audit", "tool": "run_architecture_audit",
             "purpose": "internal link graph + orphan detection"},
            {"name": "Extractability audit", "tool": "run_extractability_audit",
             "purpose": "AI-citation worthiness scoring"},
        ],
        "disambiguation_hints": [
            {"term": "clicks",
             "guidance": "ALWAYS clarify or pull both. GSC clicks = organic search clicks (get_gsc_summary). Adobe clicks ≠ same thing — Adobe doesn't have 'clicks', it has page_views / visits / entries (get_adobe_summary)."},
            {"term": "visits / sessions",
             "guidance": "Adobe Analytics (get_adobe_summary). NOT in GSC."},
            {"term": "page views",
             "guidance": "Adobe Analytics (get_adobe_summary / get_adobe_top_pages)."},
            {"term": "ranking / position",
             "guidance": "GSC (get_gsc_summary) for queries we already rank for; SEMrush (get_semrush_keywords) for broader keyword set."},
            {"term": "impressions",
             "guidance": "GSC (get_gsc_summary). NOT in Adobe."},
            {"term": "bounces / bounce rate",
             "guidance": "Adobe Analytics entry-pages (get_adobe_summary)."},
            {"term": "conversions / leads / forms",
             "guidance": "Adobe Analytics — wire ADOBE_LEAD_HASH_EVAR; see get_adobe_summary lead_events block."},
            {"term": "ads / creatives",
             "guidance": "Meta Ad Library (get_meta_ads_summary). Set competitor='' for our own ads."},
            {"term": "competitor",
             "guidance": "First list_competitors_crawled to see what we have, then get_competitor_detail(domain=...)."},
        ],
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
            "name": "get_pagerank_top",
            "description": (
                "Top URLs by internal PageRank ('Link Score', Ahrefs "
                "Page Rating equivalent) computed from the crawl link "
                "graph. Use when the user asks which pages concentrate "
                "the most internal link equity, or which hero pages "
                "are well-linked. Returns pagerank_score 0-100 + "
                "in/out degree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Top-N to return (1-200, default 20)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_orphan_pages",
            "description": (
                "URLs with no internal inbound links (or below "
                "max_in_degree). Orphans can't accumulate link equity "
                "and are slow to be discovered by Google. Use when the "
                "user asks 'orphan pages', 'pages with no inbound "
                "links', 'buried content'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_in_degree": {
                        "type": "integer",
                        "description": (
                            "Cap on inbound link count to qualify as "
                            "orphan. 0 = strict (zero inbound), 1-3 "
                            "for 'effectively orphan'."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_near_duplicates",
            "description": (
                "Near-duplicate URL clusters via MinHash + LSH "
                "(Screaming Frog uses the same algorithm). Surfaces "
                "URLs whose title + URL pattern is similar enough that "
                "Google will treat them as duplicates. Use when the "
                "user asks 'duplicate content', 'cannibalised pages', "
                "or to find template bugs producing dup pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer", "description": "Top-N clusters (1-100, default 20)."},
                    "threshold": {
                        "type": "number",
                        "description": (
                            "Jaccard similarity threshold 0.0-1.0. "
                            "Default 0.9 matches SF default. Lower "
                            "for fuzzier matching."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trends",
            "description": (
                "Time-series of daily Health Score + per-category "
                "counts from MetricSnapshot rows. Use when the user "
                "asks 'are we improving?', 'trend?', 'health score "
                "history', 'how did errors change over time?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "window": {"type": "integer", "description": "Days to return (1-365, default 90)."},
                    "engine": {"type": "string", "description": "Optional 'legacy' or 'scrapy' filter."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_crawls",
            "description": (
                "SEMrush-style Compare Crawls — diff any two "
                "CrawlSnapshot rows. Without args, picks the two "
                "most-recent automatically. Use when the user asks "
                "'what changed since last crawl?', 'compare snapshots', "
                "'did X get fixed?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "description": "Older snapshot UUID (optional)."},
                    "b": {"type": "string", "description": "Newer snapshot UUID (optional)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_thematic_report",
            "description": (
                "One of 8 thematic deep-dive reports: robots, "
                "crawlability, https, international, performance, "
                "linking, markup, cwv. Bundles curated issues for one "
                "focused concern. Without slug, returns the list of "
                "available themes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Theme slug. Empty returns the available list.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "audit_llms_txt",
            "description": (
                "Audit /llms.txt for a given domain (llmstxt.org spec). "
                "Returns presence, byte size, section + link counts, "
                "structural validation, and companion llms-full.txt "
                "detection. Use when the user asks about GEO / AI-search "
                "readiness."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to audit. Defaults to bajajlifeinsurance.com.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_llms_txt",
            "description": (
                "Draft a Bajaj-branded llms.txt from the live AEM sitemap "
                "+ crawler page-type data. Groups pages by intent. Returns "
                "a Markdown body the operator pastes into AEM."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_pages_per_section": {
                        "type": "integer",
                        "description": "Cap pages per section (default 30).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ai_bot_hits",
            "description": (
                "Recent verified AI-bot hits (GPTBot, ClaudeBot, "
                "PerplexityBot, etc.) with per-bot totals + the most "
                "recent hits. Spoofed UAs are flagged verified=false."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many recent rows (default 50, max 500).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_backlinks",
            "description": (
                "Common Crawl-derived backlinks to Bajaj URLs. Returns "
                "per-target summary + the most recent rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many rows (default 50, max 500).",
                    },
                    "target_domain": {
                        "type": "string",
                        "description": "Filter by target domain (e.g. www.bajajlifeinsurance.com).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ping_indexnow",
            "description": (
                "Submit URLs to IndexNow (Bing + Yandex + partners). "
                "Pass comma-separated URLs. Allow-list filters out "
                "anything outside Bajaj domains. Dry-run if "
                "INDEXNOW_KEY is unset."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "string",
                        "description": "Comma-separated list of fully-qualified Bajaj URLs.",
                    },
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
    # ── Adobe Analytics ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_adobe_summary",
            "description": (
                "Adobe Analytics rollup for bajajlifeinsurance.com — "
                "visitors, visits, page-views, marketing channels, top "
                "countries, devices, top pages, daily trend, year-over-"
                "year compare. File-cached per section so this is fast "
                "after the first pull of the day. USE THIS when the user "
                "asks about Adobe, Analytics, traffic, visits, sessions, "
                "page-views, bounce rate, or behavioural metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_days": {
                        "type": "integer",
                        "description": "7, 14, or 30. Default 7.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_adobe_top_pages",
            "description": (
                "Top pages by page-views from Adobe Analytics. Use when "
                "the user asks 'what pages get the most traffic / views' "
                "(NOT 'which pages rank' — that's GSC)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_days": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    # ── Meta Ad Library ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_meta_ads_summary",
            "description": (
                "Facebook + Instagram ad library data. Pass a domain "
                "('hdfclife.com') or brand name ('HDFC Life') as "
                "`competitor`. Pass `competitor=''` and `include_ours=true` "
                "for our own ads. Returns headline counts + top CTAs / "
                "creative themes / landing domains per competitor."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "competitor": {"type": "string"},
                    "include_ours": {"type": "boolean"},
                    "count": {"type": "integer"},
                },
            },
        },
    },
    # ── Brand mentions ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_brand_mentions",
            "description": (
                "Recent third-party brand mentions (last 30 days) — RSS "
                "feeds + SerpAPI daily catch-all. Tagged by brand variant "
                "(new 'Bajaj Life Insurance', old 'Bajaj Allianz Life', "
                "parent 'Bajaj Allianz'). Use this to answer 'how is the "
                "rebrand sticking', 'who's writing about us', mentions / "
                "PR questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    # ── GEO score ───────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_geo_score",
            "description": (
                "Unified Generative Engine Optimization score — "
                "citation density, E-E-A-T markup, AI-bot hit count, "
                "llms.txt presence, Reddit / Quora mentions, YouTube, "
                "Wikidata entity, brand mentions. Use this for 'how AI-"
                "ready are we', 'GEO score', 'are we citable by "
                "ChatGPT / Perplexity' questions. Pass deep=true for "
                "the slow Wikidata + SerpAPI external calls."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "deep": {"type": "boolean"},
                },
            },
        },
    },
    # ── Competitor crawls ───────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "list_competitors_crawled",
            "description": (
                "List every competitor domain the daily Scrapy walker "
                "has visited, with live page counts. Use this BEFORE "
                "`get_competitor_detail` to confirm what we've got — "
                "especially when the user asks vague 'who do we have data "
                "on' / 'list competitors' questions."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_competitor_detail",
            "description": (
                "Per-competitor crawl detail — sample pages, page-type "
                "mix, avg word count, schema coverage. Pass the apex "
                "domain (e.g. 'hdfclife.com', 'kotaklife.com'). Reads "
                "the Phase G Scrapy-walker storage (NOT SEMrush — that's "
                "get_competitor_gap)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                },
                "required": ["domain"],
            },
        },
    },
    # ── Data-sources introspection (always available) ──────────────
    {
        "type": "function",
        "function": {
            "name": "list_data_sources",
            "description": (
                "Inventory of EVERY data source the platform exposes — "
                "Adobe, GSC, SEMrush, Meta Ads, brand mentions, GEO, "
                "competitor crawls, content clusters, etc. — with the "
                "exact tool name for each. Call this FIRST whenever the "
                "user asks about a data source and you're unsure whether "
                "it's available. Static inventory, fast, no DB hit. Also "
                "carries disambiguation hints for ambiguous terms like "
                "'clicks' (GSC) vs 'visits' (Adobe)."
            ),
            "parameters": {"type": "object", "properties": {}},
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
    "get_pagerank_top": get_pagerank_top,
    "get_orphan_pages": get_orphan_pages,
    "get_near_duplicates": get_near_duplicates,
    "get_trends": get_trends,
    "compare_crawls": compare_crawls,
    "get_thematic_report": get_thematic_report,
    "audit_llms_txt": audit_llms_txt,
    "generate_llms_txt": generate_llms_txt,
    "ping_indexnow": ping_indexnow,
    "get_ai_bot_hits": get_ai_bot_hits,
    "get_backlinks": get_backlinks,
    "emit_card": emit_card,
    # ── new: Adobe / Meta Ads / brand mentions / GEO / competitor /
    # content clusters / data-sources introspection ──
    "get_adobe_summary": get_adobe_summary,
    "get_adobe_top_pages": get_adobe_top_pages,
    "get_meta_ads_summary": get_meta_ads_summary,
    "get_brand_mentions": get_brand_mentions,
    "get_geo_score": get_geo_score,
    "list_competitors_crawled": list_competitors_crawled,
    "get_competitor_detail": get_competitor_detail,
    "list_data_sources": list_data_sources,
    # ── live crawl tools — the assistant's own crawler ──
    "crawl_page": crawl_page,
    "crawl_pages": crawl_pages,
    "compare_page_structures": compare_page_structures,
    "technical_audit_url": technical_audit_url,
    "compare_technical_audit": compare_technical_audit,
    "technical_audit_site": technical_audit_site,
    "get_page_links": get_page_links,
}


# ── Chat-surface compact schemas ────────────────────────────────────────
# The full TOOL_SCHEMAS list serializes to ~18 KB / ~4.5 k tokens which
# burns most of the 8 k-TPM bucket BEFORE any user input. The chat
# router uses this CHAT_TOOL_SCHEMAS subset — same handler names, much
# terser descriptions, plus we drop a handful of niche tools
# (compare_crawls, get_thematic_report, ping_indexnow, query_page_explorer,
# get_pagerank_top, get_orphan_pages, get_near_duplicates,
# generate_llms_txt). Those handlers are still registered in
# TOOL_HANDLERS for non-chat callers; they're just not advertised to
# the LLM in the per-turn schema payload.

def _f(name: str, desc: str, params: dict | None = None,
       required: list[str] | None = None) -> dict[str, Any]:
    """Build a compact OpenAI tool-call schema entry."""
    fn: dict[str, Any] = {
        "name": name,
        "description": desc,
        "parameters": {
            "type": "object",
            "properties": params or {},
        },
    }
    if required:
        fn["parameters"]["required"] = required
    return {"type": "function", "function": fn}


_STR = {"type": "string"}
_INT = {"type": "integer"}
_BOOL = {"type": "boolean"}

CHAT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    # ── ALWAYS call first when unsure what data exists ─────────────
    _f("list_data_sources",
       "Inventory of all data sources + which tool to use for each. Call FIRST if unsure whether a source exists."),
    # ── Adobe ─────────────────────────────────────────────────────
    _f("get_adobe_summary",
       "Adobe Analytics rollup: visitors, visits, page-views, channels, devices, geo, top pages, daily trend.",
       {"lookback_days": _INT}),
    _f("get_adobe_top_pages",
       "Top pages by page-views from Adobe Analytics.",
       {"lookback_days": _INT, "limit": _INT}),
    # ── GSC ───────────────────────────────────────────────────────
    _f("get_gsc_summary",
       "Search Console: clicks, impressions, CTR, position. Top + underperforming queries.",
       {"limit": _INT}),
    # ── SEMrush ───────────────────────────────────────────────────
    _f("get_semrush_keywords",
       "SEMrush organic keywords + domain overview.",
       {"domain": _STR, "limit": _INT}),
    # ── Meta Ads ──────────────────────────────────────────────────
    _f("get_meta_ads_summary",
       "Meta Ad Library data. Pass competitor='' + include_ours=true for our own ads.",
       {"competitor": _STR, "include_ours": _BOOL, "count": _INT}),
    # ── Brand mentions / GEO ──────────────────────────────────────
    _f("get_brand_mentions",
       "Third-party brand mentions (RSS + SerpAPI), last 30 days, tagged by variant.",
       {"limit": _INT}),
    _f("get_geo_score",
       "GEO score: citations, E-E-A-T, AI bots, llms.txt, Reddit/Quora, YouTube, Wikidata. deep=true for slow external calls.",
       {"deep": _BOOL}),
    # ── Live crawl — the assistant's own crawler ──────────────────
    _f("crawl_page",
       "LIVE-crawl one URL NOW (ours or competitor): h1/h2/h3 outline, links by zone (header/nav/content/footer), image alt coverage, schema. include_cwv=true adds PageSpeed LCP/INP/CLS.",
       {"url": _STR, "include_cwv": _BOOL}, required=["url"]),
    _f("crawl_pages",
       "LIVE-crawl up to 8 URLs in parallel, compact structure digest each. For user-supplied URL lists.",
       {"urls": {"type": "array", "items": _STR}}, required=["urls"]),
    _f("compare_page_structures",
       "Content-gap compare: live-crawl our page + up to 5 rival pages; side-by-side structure + heading topics rivals cover that we don't.",
       {"our_url": _STR, "competitor_urls": {"type": "array", "items": _STR}},
       required=["our_url", "competitor_urls"]),
    _f("technical_audit_url",
       "FULL technical SEO audit of ONE URL (DB-first, live-crawls if missing): live CWV (mobile+desktop), title/meta/H1/alt/canonical/schema/HTTPS/redirects/hreflang/indexability checks, 0-100 score + findings with recommendations. check_broken_links=true probes links for 4xx/5xx; fresh=true forces a live re-crawl.",
       {"url": _STR, "check_broken_links": _BOOL, "fresh": _BOOL}, required=["url"]),
    _f("technical_audit_site",
       "Whole-WEBSITE technical audit over the latest own crawl: duplicate titles/meta, indexability, redirect chains, broken/oversized images, thin content, missing metadata, no-schema, hreflang — counts + recommendations + sample URLs."),
    _f("get_page_links",
       "List the actual links on a page (live-crawls by default so it's current). kind=internal|external|all. Returns anchor + URL + zone.",
       {"url": _STR, "kind": _STR, "fresh": _BOOL}, required=["url"]),
    _f("compare_technical_audit",
       "Compare OUR page's technical audit vs up to 5 competitor pages side-by-side (score, tags, links, alt, LCP). DB-first, live-crawls misses.",
       {"our_url": _STR, "competitor_urls": {"type": "array", "items": _STR}},
       required=["our_url"]),
    # ── Competitors ───────────────────────────────────────────────
    _f("list_competitors_crawled",
       "Every competitor domain the Scrapy walker has visited, with live page counts + status."),
    _f("get_competitor_detail",
       "Per-competitor crawl detail: sample pages, page-type mix, schema coverage, avg word count.",
       {"domain": _STR}, required=["domain"]),
    _f("get_competitor_gap",
       "SEMrush-driven competitor gap (topics / keywords / hygiene). Cached 7 days.",
       {"domain": _STR}),
    # ── Content / sitemap ─────────────────────────────────────────
    _f("get_sitemap_pages",
       "AEM authored-page list. query= filter.",
       {"query": _STR, "limit": _INT}),
    # ── Crawler ───────────────────────────────────────────────────
    _f("get_crawler_status",
       "Live crawler status (running / idle, queue size)."),
    _f("get_crawler_summary",
       "Crawler totals: pages, errors, response times."),
    _f("get_health_score",
       "Single SEO health number rollup."),
    _f("get_latest_grade",
       "Most recent multi-agent grading run: overall score + top findings.",
       {"domain": _STR}),
    _f("run_grade_async",
       "Kick off a fresh grade run. Use only when explicitly asked or cache > 14d.",
       {"domain": _STR}),
    # ── Audits ────────────────────────────────────────────────────
    _f("run_content_audit",
       "LLM-graded per-URL comparison against competitors.",
       {"our_url": _STR, "competitors": {"type": "array", "items": _STR}}),
    _f("run_technical_audit",
       "Site-wide tech checks: robots.txt for AI bots, sitemap, HTTPS, schema.",
       {"domain": _STR}),
    _f("run_extractability_audit",
       "AI-citation readiness per page (lead para, FAQ, schema, freshness, query-style headings).",
       {"domain": _STR}),
    _f("run_architecture_audit",
       "Internal link graph + orphan / hub detection.",
       {"domain": _STR}),
    # ── AI bots / backlinks / llms.txt / issues ───────────────────
    _f("get_ai_bot_hits",
       "GPTBot / ClaudeBot / PerplexityBot crawl activity from server logs.",
       {"limit": _INT}),
    _f("get_backlinks",
       "External links pointing at our site.",
       {"limit": _INT, "target_domain": _STR}),
    _f("audit_llms_txt",
       "Audit /llms.txt for a domain.",
       {"domain": _STR}),
    _f("get_issues_summary",
       "Per-issue-type counts from the audit engine."),
    _f("get_trends",
       "Health Score over time + engine breakdown.",
       {"window": _INT, "engine": _STR}),
    # ── UI rendering ──────────────────────────────────────────────
    _f("emit_card",
       "Render a structured card in the chat UI. card_type ∈ gsc_top_queries, keyword_opportunities, competitor_delta, crawler_summary, finding.",
       {"card_type": _STR, "payload": {"type": "object"}},
       required=["card_type", "payload"]),
]
