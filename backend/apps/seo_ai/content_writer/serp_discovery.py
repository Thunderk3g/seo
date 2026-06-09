"""SERP-based competitor discovery for a single Bajaj URL.

The premise: for a page-revamp, our competitors are the pages Google is
*actually ranking* for the intent our page targets — not the brand
roster sitting in the DB. The brand roster is for portfolio intel; this
module is for "outrank these five URLs".

Flow
----
1. Resolve our page (live crawl if needed) so we have title + body.
2. Ask the LLM to synthesize the most likely *search query* a user
   would type to land on a page like ours. The model gets the URL,
   the page title, the H1, a body excerpt, and the operator's optional
   free-text steer. Returns 1 primary + 2 secondary candidate queries.
3. Run the primary query through ``SerpAPIAdapter`` for Google (in /
   en by default — SERP_API settings already shape this).
4. Drop Bajaj domains, drop directory aggregators / news / Wikipedia,
   return the top N URLs ordered by SERP position.

The LLM step is the smart part — a page like
``/term-insurance-plans/`` could legitimately be queried as
"best term insurance plan in india", "term insurance buy online",
or "term life insurance" — and which one we synthesize determines the
SERP we benchmark against. We hand the model the page body excerpt so
the query reflects the page's actual angle, not a guess from the slug.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("seo.ai.content_writer.serp_discovery")


# Domains we never want to benchmark against — our own, Wikipedia,
# news aggregators, generic comparison sites, gov regulators. Bajaj
# canonical hosts come first; the rest are noise that ranks for
# insurance queries but isn't a "page we'd revamp against".
_BLOCKED_DOMAIN_SUBSTRINGS: tuple[str, ...] = (
    # ours (Bajaj Life Insurance)
    "bajajlifeinsurance.com",
    # related Bajaj entities — NOT us (parent group), excluded only as noise
    "bajajfinserv.in",
    "bajajfinserv.com",          # parent group
    # encyclopedic / news
    "wikipedia.org",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "linkedin.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "quora.com",
    "reddit.com",
    "medium.com",
    "indiatoday.in",
    "moneycontrol.com",
    "economictimes.indiatimes.com",
    "livemint.com",
    "business-standard.com",
    "ndtv.com",
    "thehindu.com",
    "hindustantimes.com",
    # regulators / gov
    ".gov.in",
    "irdai.gov.in",
    "rbi.org.in",
    # generic aggregators / comparison & advisory sites
    "policybazaar.com",
    "coverfox.com",
    "bankbazaar.com",
    "paisabazaar.com",
    "myinsuranceclub.com",
    "joinditto.in",
    "ditto.com",
    "acko.com",
    "policyx.com",
    "insurancedekho.com",
    "compareplans.com",
)


def _is_blocked(domain: str) -> bool:
    d = (domain or "").lower().lstrip(".")
    return any(b in d for b in _BLOCKED_DOMAIN_SUBSTRINGS)


# Bajaj canonical hosts — used to detect whether WE rank for a query
# (a distinct signal from "blocked", which lumps us in with aggregators).
_BAJAJ_HOSTS: tuple[str, ...] = (
    "bajajlifeinsurance.com",
    "bajajfinserv.in",
    "bajajfinserv.com",
)


def _is_bajaj(s: str) -> bool:
    d = (s or "").lower()
    return any(b in d for b in _BAJAJ_HOSTS)


def _bare_host(url_or_host: str) -> str:
    s = (url_or_host or "").strip().lower()
    if "://" in s:
        s = urlparse(s).hostname or s
    s = s.lstrip(".")
    return s[4:] if s.startswith("www.") else s


# Page-type classification — so a PRODUCT page is benchmarked against
# competitor PRODUCT pages (not blogs/comparison articles), a BLOG vs
# blogs, etc. Heuristic over URL + title; URL slug is the strongest
# signal for Indian insurer sites. Order matters: comparison/calculator
# are checked before blog/product because their URLs often also contain
# product/plan tokens (e.g. "term-insurance-vs-ulip").
_BLOG_MARKERS = (
    "/blog", "blogs/", "/article", "insurance-library", "knowledge-centre",
    "knowledge-center", "/learning", "/learn", "/guide", "/guides",
    "/resources", "/wealth/", "/news/", "/tips/", "/posts/", "-guide",
)
_PRODUCT_MARKERS = (
    "-plan", "-plans", "/plans", "/plan/", "/investment-plans",
    "/insurance-plans", "/ulip", "/term-insurance", "/savings",
    "/retirement", "/child-plan", "/pension", "/products/", "/buy-",
)


def classify_page_type(url: str, title: str = "", snippet: str = "") -> str:
    """Return one of: product | comparison | calculator | blog | other.

    Used to match like-for-like pages in the SERP benchmark so product
    pages compete against product pages (the ones that actually rank for
    transactional intent), not against knowledge-base articles.
    """
    u = (url or "").lower()
    t = (title or "").lower()
    if any(k in u for k in ("-vs-", "/vs/", "-vs.", "vs-", "/compare", "comparison")) \
            or " vs " in t or "vs." in t or " versus " in t:
        return "comparison"
    if "calculator" in u or "calculator" in t:
        return "calculator"
    if any(k in u for k in _BLOG_MARKERS):
        return "blog"
    if t.startswith((
        "what is", "what are", "how to", "how does", "how do", "why ",
        "when ", "should ", "top ", "benefits of", "types of",
    )) or "guide" in t or re.search(r"\b(in|for)\s*20\d\d\b", t):
        return "blog"
    if any(k in u for k in _PRODUCT_MARKERS):
        return "product"
    if t.startswith("buy ") or "plans" in t or t.endswith(" plan"):
        return "product"
    return "other"


def _dedupe_by_domain(cands: list) -> list:
    """Keep first occurrence per bare domain (preserves input priority)."""
    seen: set[str] = set()
    out: list = []
    for c in cands:
        d = _bare_host(getattr(c, "domain", "") or getattr(c, "url", ""))
        if not d or d in seen:
            continue
        seen.add(d)
        out.append(c)
    return out


@dataclass
class SerpCandidate:
    position: int
    url: str
    domain: str
    title: str
    snippet: str
    # Which synthesized query first surfaced this URL (multi-query runs).
    found_via_query: str = ""
    # product | comparison | calculator | blog | other — for like-for-like matching.
    page_type: str = ""
    # serp | web_search | custom — where this candidate came from.
    source: str = "serp"
    # True when this candidate's page_type matches OUR page type.
    type_match: bool = False


@dataclass
class SerpDiscoveryResult:
    our_url: str
    primary_query: str
    candidate_queries: list[str]
    people_also_ask: list[str]
    featured_snippet: dict[str, Any] | None
    ai_overview: dict[str, Any] | None
    competitors: list[SerpCandidate]
    # Diagnostics for the UI — operator can see what was filtered out.
    blocked: list[SerpCandidate] = field(default_factory=list)
    # All synthesized queries (≥10) the user could plausibly type.
    all_queries: list[str] = field(default_factory=list)
    # Extra unblocked insurer candidates beyond the primary set — the
    # orchestrator crawls these when a primary competitor blocks (403).
    substitution_pool: list[SerpCandidate] = field(default_factory=list)
    # Did Bajaj itself rank for any query? {found, best_position, query, url, source}
    bajaj_presence: dict[str, Any] = field(default_factory=dict)
    # Per-query record of which URLs each query surfaced (UI provenance).
    queries_run: list[str] = field(default_factory=list)
    serp_engine: str = "google"
    serp_error: str = ""
    llm_model: str = ""
    llm_cost_usd: float = 0.0
    web_search_used: bool = False
    # Page type of OUR url — competitors are matched to this type.
    our_page_type: str = ""
    notes: list[str] = field(default_factory=list)


# ── query synthesis ──────────────────────────────────────────────────


_QUERY_SYS_PROMPT = """You are an SEO query analyst. Given one page from
Bajaj Life Insurance and an optional operator steer, propose the FULL SET
of distinct Google searches a real Indian user would type to land on a
page like this — the queries we will benchmark competitors against.

Your output is consumed by a Google SERP fetch — the more your queries
cover the real intent spread, the better the competitor benchmark.

Constraints:
* Each query MUST be in Indian English, ≤ 8 words, lowercase, no quotes.
* Queries MUST reflect the page's ACTUAL angle (term, ULIP, retirement,
  child, savings, tax, calculator, claim, ...) — read title + H1 + excerpt.
* Cover the intent SPREAD with at least 10 distinct queries across these
  angles: head term ("ulip plans"), "best ___ in india", buy/online
  intent ("buy ___ online"), benefit angle ("___ tax benefit"),
  calculator/tool ("___ premium calculator"), comparison ("___ vs ___"
  generic, no brand), question forms ("what is ___", "is ___ a good
  investment"), and a returns/maturity angle where relevant.
* Do NOT include the word "bajaj" — we want the SERP without us in it.
* Avoid brand qualifiers ("hdfc", "icici", ...) UNLESS the operator's
  steer explicitly asks to compare with that brand.

Output JSON ONLY:
{
  "primary_query": "the single highest-intent match",
  "all_queries": ["q1", "q2", ... at least 10, primary included first],
  "reasoning": "1 sentence on the page's core intent."
}
""".strip()


def synthesize_queries(
    *,
    our_url: str,
    title: str,
    h1: str,
    body_excerpt: str,
    operator_prompt: str = "",
    provider=None,
    model: str | None = None,
) -> tuple[dict[str, Any], float, str]:
    """Use the LLM to propose 1 primary + ≥9 variant search queries.

    Returns ``(queries_obj, cost_usd, model_used)`` where ``queries_obj``
    carries ``primary_query`` and ``all_queries`` (≥10, deduped). On any
    LLM failure falls back to slug-derived variants so the pipeline runs.
    """
    from ..llm import get_provider

    provider = provider or get_provider()
    payload = {
        "url": our_url,
        "title": title or "",
        "h1": h1 or "",
        "body_excerpt": (body_excerpt or "")[:2000],
        "operator_prompt": operator_prompt or "",
    }
    user_content = (
        "Propose the full query set for this page. JSON only.\n\n"
        "<page>\n```json\n"
        + json.dumps(payload, indent=2, default=str)
        + "\n```\n</page>"
    )
    messages = [
        {"role": "system", "content": _QUERY_SYS_PROMPT},
        {"role": "user", "content": user_content},
    ]
    try:
        resp = provider.complete(
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.3,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("query synthesis LLM failed: %s", exc)
        return _fallback_query_from_slug(our_url, title), 0.0, ""

    raw = (resp.content or "").strip()
    if raw.startswith("```"):
        nl = raw.find("\n")
        if nl != -1:
            raw = raw[nl + 1:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("query synth returned non-JSON: %r", (resp.content or "")[:200])
        return _fallback_query_from_slug(our_url, title), resp.cost_usd, resp.model

    primary = _normalize_query(obj.get("primary_query") or "")
    raw_all = obj.get("all_queries") or obj.get("secondary_queries") or []
    all_q: list[str] = []
    seen: set[str] = set()
    for q in ([primary] + [_normalize_query(x) for x in raw_all if x]):
        if q and q not in seen:
            seen.add(q)
            all_q.append(q)
    if not primary and all_q:
        primary = all_q[0]
    if not primary:
        return _fallback_query_from_slug(our_url, title), resp.cost_usd, resp.model
    # Top up to ≥10 with slug-derived variants if the model was stingy.
    if len(all_q) < 10:
        for q in (_fallback_query_from_slug(our_url, title).get("all_queries") or []):
            if q and q not in seen:
                seen.add(q)
                all_q.append(q)
            if len(all_q) >= 10:
                break
    return (
        {
            "primary_query": primary,
            "all_queries": all_q,
            "reasoning": str(obj.get("reasoning") or "")[:500],
        },
        resp.cost_usd,
        resp.model,
    )


_QUERY_NOISE_RE = re.compile(r"[^a-z0-9\s]+")
_QUERY_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "with"}


def _normalize_query(q: str) -> str:
    q = (q or "").lower().strip()
    q = _QUERY_NOISE_RE.sub(" ", q)
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        return ""
    # Drop "bajaj" if the model slipped it in.
    toks = [t for t in q.split() if t != "bajaj"]
    return " ".join(toks)[:120]


def _fallback_query_from_slug(url: str, title: str) -> dict[str, Any]:
    """Cheap deterministic query set when the LLM step fails — derives a
    bag-of-words head query from the URL slug + title head, then expands
    it across the standard intent angles so we still run a multi-query
    SERP fan-out."""
    parsed = urlparse(url)
    slug_toks = re.split(r"[/_\-.]+", parsed.path.strip("/").lower())
    slug_toks = [t for t in slug_toks if t and not t.isdigit() and len(t) > 2]
    slug_toks = [t for t in slug_toks if t not in {"html", "htm", "aspx", "php"}]
    title_toks = re.findall(r"[a-z]{3,}", (title or "").lower())
    seen: set[str] = set()
    out: list[str] = []
    for t in slug_toks + title_toks:
        if t in seen or t == "bajaj" or t in _QUERY_STOP:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= 5:
            break
    head = " ".join(out) or "life insurance"
    variants = [
        head,
        f"best {head} in india",
        f"buy {head} online",
        f"{head} tax benefit",
        f"{head} premium calculator",
        f"{head} returns",
        f"what is {head}",
        f"is {head} a good investment",
        f"{head} for nri",
        f"compare {head}",
    ]
    all_q: list[str] = []
    qseen: set[str] = set()
    for v in variants:
        nq = _normalize_query(v)
        if nq and nq not in qseen:
            qseen.add(nq)
            all_q.append(nq)
    return {
        "primary_query": head,
        "all_queries": all_q,
        "reasoning": "fallback: LLM unavailable, derived from URL slug",
    }


# ── public entry point ──────────────────────────────────────────────


def find_serp_competitors(
    *,
    our_url: str,
    operator_prompt: str = "",
    top_n: int = 10,
    provider=None,
    budget=None,
    custom_urls: list[str] | None = None,
) -> SerpDiscoveryResult:
    """Discover SERP competitors for ``our_url``'s search intent.

    Synthesizes ≥10 queries, runs the top-K through SerpAPI, aggregates +
    dedupes competitors by domain across queries (keeping each domain's
    best position), records whether **Bajaj itself ranks**, builds a
    substitution pool for the crawl-fallback, and (when enabled) uses
    Claude web search to corroborate discovery + Bajaj presence.

    SerpAPI is billed on its own key, so ``budget`` is decremented only
    for the LLM query synthesis and the optional Claude web search.
    """
    from django.conf import settings

    from apps.crawler.models import CrawlerPageResult
    from apps.crawler.views import CrawlLiveError, crawl_live

    cw = getattr(settings, "CONTENT_WRITER", None) or {}
    # Only push a Claude model id when the provider is actually Anthropic —
    # a Groq/stub fallback must use its own configured model (model=None).
    _is_anthropic = getattr(provider, "name", "") == "anthropic"
    cheap_model = cw.get("cheap_model") if _is_anthropic else None
    run_top_k = max(1, int(cw.get("serp_run_top_k", 4)))
    use_web_search = bool(cw.get("use_web_search", False))
    web_search_max_uses = int(cw.get("web_search_max_uses", 4))
    min_comp = int(cw.get("min_competitors", 4))

    notes: list[str] = []

    # 1) Load ours — prefer freshest CrawlerPageResult, live-fetch if missing.
    row = (
        CrawlerPageResult.objects.filter(url=our_url)
        .order_by("-snapshot__started_at")
        .first()
    )
    if row is None or not (row.title or row.body_text):
        try:
            _snap, row = crawl_live(our_url)
            notes.append("live-fetched our URL (no prior crawl row)")
        except CrawlLiveError as exc:
            notes.append(f"could not live-fetch our URL: {exc}")

    title = (getattr(row, "title", "") or "") if row else ""
    body = (getattr(row, "body_text", "") or "") if row else ""
    h1_list = [
        h.get("text", "")
        for h in (getattr(row, "headings_json", None) or [])
        if isinstance(h, dict) and int(h.get("level") or 0) == 1
    ]
    h1 = h1_list[0] if h1_list else ""

    # Classify OUR page so competitors are matched like-for-like
    # (product↔product, blog↔blog) rather than a product page being
    # benchmarked against a knowledge-base article.
    our_page_type = classify_page_type(our_url, title or h1)
    notes.append(f"our page type: {our_page_type}")

    # 2) Synthesize ≥10 search queries (cheap model).
    queries_obj, llm_cost, llm_model = synthesize_queries(
        our_url=our_url,
        title=title,
        h1=h1,
        body_excerpt=body,
        operator_prompt=operator_prompt,
        provider=provider,
        model=cheap_model,
    )
    if budget is not None and llm_cost:
        budget.add_usd(llm_cost)
    primary_q = queries_obj["primary_query"]
    all_queries: list[str] = queries_obj.get("all_queries") or [primary_q]
    notes.append(f"synthesized {len(all_queries)} queries; primary={primary_q!r}")

    # 3) Run top-K queries through SerpAPI and aggregate.
    queries_run = all_queries[:run_top_k]
    best_by_domain: dict[str, SerpCandidate] = {}
    blocked: list[SerpCandidate] = []
    blocked_seen: set[str] = set()
    paa: list[str] = []
    featured: dict[str, Any] | None = None
    ai_overview: dict[str, Any] | None = None
    serp_error = ""
    bajaj_presence: dict[str, Any] = {"found": False, "best_position": None, "query": "", "url": "", "source": ""}

    try:
        from ..adapters.ai_visibility.base import AdapterDisabledError
        from ..adapters.serp_api import SerpAPIAdapter

        try:
            adapter = SerpAPIAdapter()
        except AdapterDisabledError as exc:
            serp_error = f"adapter disabled: {exc}"
            adapter = None

        if adapter is not None:
            for qi, q in enumerate(queries_run):
                serp = adapter.search(q, engine="google", device="desktop")
                if serp.error:
                    serp_error = serp_error or serp.error
                    continue
                # Capture SERP features from the primary query.
                if qi == 0:
                    paa = list(serp.people_also_ask or [])
                    featured = serp.featured_snippet
                    ai_overview = serp.ai_overview
                for row_ in serp.organic[:30]:
                    # Bajaj presence — record our best rank across queries.
                    if _is_bajaj(row_.domain) or _is_bajaj(row_.url):
                        if (not bajaj_presence["found"]) or (
                            bajaj_presence["best_position"] is None
                            or row_.position < bajaj_presence["best_position"]
                        ):
                            bajaj_presence = {
                                "found": True,
                                "best_position": row_.position,
                                "query": q,
                                "url": row_.url,
                                "source": "serp",
                            }
                        continue
                    if _is_blocked(row_.domain) or _is_blocked(row_.url):
                        if row_.url not in blocked_seen:
                            blocked_seen.add(row_.url)
                            blocked.append(SerpCandidate(
                                position=row_.position, url=row_.url,
                                domain=row_.domain, title=row_.title,
                                snippet=row_.snippet, found_via_query=q,
                            ))
                        continue
                    dom = _bare_host(row_.domain or row_.url)
                    existing = best_by_domain.get(dom)
                    if existing is None or row_.position < existing.position:
                        best_by_domain[dom] = SerpCandidate(
                            position=row_.position, url=row_.url,
                            domain=row_.domain, title=row_.title,
                            snippet=row_.snippet, found_via_query=q,
                        )
    except Exception as exc:  # noqa: BLE001 - never crash the pipeline
        logger.exception("serp discovery failed")
        serp_error = serp_error or f"{type(exc).__name__}: {exc}"

    ranked = sorted(best_by_domain.values(), key=lambda c: c.position)

    # 4) Optional Claude web search — enrich discovery + corroborate Bajaj.
    web_search_used = False
    if (
        use_web_search
        and provider is not None
        and hasattr(provider, "complete_with_web_search")
        and (budget is None or not budget.would_exceed(0.06))
    ):
        try:
            qlist = ", ".join(f'"{q}"' for q in queries_run)
            ws_messages = [
                {"role": "system", "content": (
                    "You are an SEO research assistant for the Indian "
                    "life-insurance market. Use web search to find which "
                    "insurance company pages currently rank on Google."
                )},
                {"role": "user", "content": (
                    "Search Google for these queries and list the actual "
                    f"ranking result URLs you find: {qlist}. Focus on Indian "
                    "life-insurance companies (HDFC Life, ICICI Pru, SBI "
                    "Life, Max Life, Tata AIA, Kotak Life, etc.). Also state "
                    "explicitly whether bajajlifeinsurance.com appears in the "
                    "results and at roughly what position."
                )},
            ]
            ws_resp = provider.complete_with_web_search(
                messages=ws_messages,
                model=cheap_model,
                max_uses=web_search_max_uses,
                temperature=0.2,
            )
            if budget is not None:
                budget.add(ws_resp)
            web_search_used = True
            existing_domains = {c.domain and _bare_host(c.domain) for c in ranked}
            synth_pos = 100
            for r in (ws_resp.web_search_results or []):
                u = r.get("url") or ""
                if not u:
                    continue
                if _is_bajaj(u):
                    if not bajaj_presence["found"]:
                        bajaj_presence = {
                            "found": True, "best_position": None,
                            "query": "web_search", "url": u, "source": "web_search",
                        }
                    continue
                dom = _bare_host(u)
                if not dom or _is_blocked(dom) or dom in existing_domains:
                    continue
                existing_domains.add(dom)
                synth_pos += 1
                ranked.append(SerpCandidate(
                    position=synth_pos, url=u, domain=dom,
                    title=r.get("title") or dom, snippet="",
                    found_via_query="claude web search",
                ))
            notes.append(
                f"claude web search: +{len(ws_resp.web_search_results or [])} results, "
                f"{ws_resp.web_search_count} searches"
            )
        except Exception as exc:  # noqa: BLE001
            notes.append(f"web search enrichment failed: {exc}")

    # ── Page-type matching + custom URLs ────────────────────────────
    # Classify every SERP/web-search candidate and tag whether it matches
    # OUR page type. Operator-supplied custom URLs are ALWAYS included and
    # crawled (the operator knows best which rival page to compare against).
    for c in ranked:
        c.page_type = classify_page_type(c.url, c.title, c.snippet)
        c.type_match = (c.page_type == our_page_type)

    custom_cands: list[SerpCandidate] = []
    for cu in (custom_urls or []):
        cu = (cu or "").strip()
        if not cu:
            continue
        if "://" not in cu:
            cu = "https://" + cu
        dom = _bare_host(cu)
        if not dom or _is_bajaj(cu):
            continue
        ptype = classify_page_type(cu)
        custom_cands.append(SerpCandidate(
            position=0, url=cu, domain=dom, title="", snippet="",
            found_via_query="custom", page_type=ptype, source="custom",
            type_match=(ptype == our_page_type),
        ))
    if custom_cands:
        notes.append(f"{len(custom_cands)} custom competitor URL(s) added")

    # Priority: custom first, then SAME-type SERP results (by position),
    # then other-type only to backfill if same-type is short. This makes a
    # product page compete against product pages and only falls back to
    # blogs/comparisons when there aren't enough same-type rivals.
    same_type = [c for c in ranked if c.type_match]
    other_type = [c for c in ranked if not c.type_match]
    ordered = _dedupe_by_domain(custom_cands + same_type + other_type)

    competitors = ordered[:top_n]
    substitution_pool = ordered[top_n:top_n + 8]

    same_in_set = sum(1 for c in competitors if c.type_match or c.source == "custom")
    notes.append(
        f"competitor match: {same_in_set}/{len(competitors)} are {our_page_type}-type "
        f"(custom={len(custom_cands)}, same_serp={len(same_type)}, other={len(other_type)})"
    )
    if len(competitors) < min_comp:
        notes.append(
            f"only {len(competitors)} unblocked competitor(s) found "
            f"(target {min_comp}) — benchmark will run with what we have"
        )
    if not bajaj_presence["found"]:
        notes.append("Bajaj did not rank in the top results for these queries")

    return SerpDiscoveryResult(
        our_url=our_url,
        primary_query=primary_q,
        candidate_queries=[q for q in all_queries if q != primary_q],
        people_also_ask=paa,
        featured_snippet=featured,
        ai_overview=ai_overview,
        competitors=competitors,
        blocked=blocked,
        all_queries=all_queries,
        substitution_pool=substitution_pool,
        bajaj_presence=bajaj_presence,
        queries_run=queries_run,
        serp_engine="google",
        serp_error=serp_error,
        llm_model=llm_model,
        llm_cost_usd=llm_cost,
        web_search_used=web_search_used,
        our_page_type=our_page_type,
        notes=notes,
    )


def to_dict(r: SerpDiscoveryResult) -> dict[str, Any]:
    """Serializable dict — used by the orchestrator and the API view."""
    return {
        "our_url": r.our_url,
        "primary_query": r.primary_query,
        "candidate_queries": list(r.candidate_queries),
        "all_queries": list(r.all_queries),
        "queries_run": list(r.queries_run),
        "people_also_ask": list(r.people_also_ask),
        "featured_snippet": r.featured_snippet,
        "ai_overview": r.ai_overview,
        "competitors": [c.__dict__ for c in r.competitors],
        "substitution_pool": [c.__dict__ for c in r.substitution_pool],
        "blocked": [c.__dict__ for c in r.blocked],
        "bajaj_presence": dict(r.bajaj_presence or {}),
        "serp_engine": r.serp_engine,
        "serp_error": r.serp_error,
        "llm_model": r.llm_model,
        "llm_cost_usd": r.llm_cost_usd,
        "web_search_used": r.web_search_used,
        "our_page_type": r.our_page_type,
        "notes": list(r.notes),
    }
