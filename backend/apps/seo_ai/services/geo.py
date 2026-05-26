"""GEO (Generative Engine Optimization) — full coverage service.

What "GEO" means here:
  The signals AI engines (ChatGPT, Claude, Gemini, Perplexity, Bing
  Copilot) use to decide who to cite when a user asks "best 1 crore
  term insurance in India". Different from classic SEO (Google
  ranking) because the surface of competition is *citations inside
  AI-generated answers*, not blue-link rankings.

Six signal families covered here:

  1. Citation density — definitions / lists / tables / Q&A in the
     first 1500 chars of each page. AI engines prefer pages whose
     opening paragraphs are dense with citable atoms.

  2. E-E-A-T markup — Person schema, sameAs links, author entities,
     publisher org markup. Google's quality docs + the GEO research
     literature converge: AI engines weigh entity-verified authors.

  3. Reddit / Quora brand mentions — AI engines train + retrieve
     heavily from these. Site-restricted SerpAPI queries surface
     where Bajaj is talked about (or isn't).

  4. YouTube presence — channel + recent uploads. Video transcripts
     are first-class GEO content; ChatGPT cites them often.

  5. Wikidata entity — if Bajaj has a clean Q-id, AI engines anchor
     to it. Missing or sparse entity = invisible to entity-grounded
     models.

  6. Unified GEO score — single 0-100 rollup the operator sees on
     the dashboard, with per-factor breakdown.

All factors are gated where they need API keys; nothing crashes when
a key is missing — the score just shows partial-coverage.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("seo.ai.services.geo")


# ── 1. Citation density per page ──────────────────────────────────────


# Pre-compiled regexes for citation atoms in the first 1500 chars.
# Definitions: short sentence containing "is a/an X" or "refers to" or
# "means" or "defined as". Hand-tuned for finance/insurance copy.
_DEF_RE = re.compile(
    r"\b(is|are)\s+(?:a|an|the)\b|"
    r"\brefers?\s+to\b|"
    r"\bmeans\b|"
    r"\bdefined\s+as\b",
    re.I,
)
_LIST_BULLET_RE = re.compile(r"(?:^|\n)\s*(?:[-•*]|\d+[.)])\s+", re.M)
_QA_RE = re.compile(r"\?\s+", re.M)


@dataclass
class CitationDensity:
    url: str
    chars_analysed: int
    definitions: int
    list_bullets: int
    tables: int
    qa_pairs: int
    score: int  # 0-100


def citation_density(
    *,
    title: str,
    body_text: str,
    headings_json: list[dict] | None = None,
    image_count_in_first_1500: int = 0,
    char_window: int = 1500,
) -> CitationDensity:
    """Compute the per-page citation-density score.

    Scoring:
      * 10 pts per definition (cap 30)
      * 2 pts per list bullet  (cap 20)
      * 15 pts per table tag detected (cap 30)
      * 5 pts per Q&A pair (cap 20)
    Capped at 100.

    Tables are detected via `<table>` substring count (we run on
    body_text which is the visible-text strip — so we approximate by
    counting headings that look like "How does..." / "Why..." / "What...".
    The Bajaj parser already strips raw HTML, so we estimate from the
    heading structure as a proxy.
    """
    window = (body_text or "")[:char_window]
    chars_analysed = len(window)

    definitions = len(_DEF_RE.findall(window))
    list_bullets = len(_LIST_BULLET_RE.findall(window))
    qa_pairs = len(_QA_RE.findall(window))

    # Table proxy — headings starting with How/What/Why suggest
    # structured-content pages. We use the heading-question count as
    # a lightweight stand-in for explicit `<table>` tags.
    table_proxy = 0
    for h in (headings_json or []):
        t = ((h or {}).get("text") or "").strip().lower()
        if t.startswith(("how ", "what ", "why ", "when ")):
            table_proxy += 1

    score = (
        min(30, definitions * 10)
        + min(20, list_bullets * 2)
        + min(30, table_proxy * 15)
        + min(20, qa_pairs * 5)
    )
    return CitationDensity(
        url="",  # filled by caller
        chars_analysed=chars_analysed,
        definitions=definitions,
        list_bullets=list_bullets,
        tables=table_proxy,
        qa_pairs=qa_pairs,
        score=min(100, score),
    )


# ── 2. E-E-A-T markup audit ───────────────────────────────────────────


@dataclass
class EEATAudit:
    has_person_schema: bool = False
    has_organisation_schema: bool = False
    has_sameas: bool = False
    sameas_targets: list[str] = field(default_factory=list)
    has_author_url: bool = False
    has_publisher: bool = False
    score: int = 0  # 0-100


_AUTHORITATIVE_HOSTS = {
    "wikipedia.org", "wikidata.org", "linkedin.com", "twitter.com",
    "x.com", "facebook.com", "youtube.com", "instagram.com",
    "crunchbase.com", "irdai.gov.in", "sebi.gov.in", "rbi.org.in",
}


def audit_eeat(jsonld_blocks: list[dict]) -> EEATAudit:
    """Walk a page's JSON-LD blocks for E-E-A-T signals.

    Scoring:
      * Person schema present:        +30
      * Publisher organisation:       +20
      * sameAs links present:         +20
      * sameAs to authoritative host: +15 per hit (cap 30)
    Capped at 100.
    """
    out = EEATAudit()
    sameas_set: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            tval = node.get("@type")
            types: list[str] = []
            if isinstance(tval, str):
                types = [tval]
            elif isinstance(tval, list):
                types = [t for t in tval if isinstance(t, str)]
            for t in types:
                tl = t.lower()
                if "person" in tl:
                    out.has_person_schema = True
                if "organization" in tl:
                    out.has_organisation_schema = True
                    if "publisher" in (node.get("name") or "").lower() or node.get("publisher"):
                        out.has_publisher = True
            # sameAs: spec is array of URLs but some sites use string.
            sa = node.get("sameAs")
            if isinstance(sa, str) and sa.startswith("http"):
                sameas_set.add(sa)
            elif isinstance(sa, list):
                for u in sa:
                    if isinstance(u, str) and u.startswith("http"):
                        sameas_set.add(u)
            # author.url
            author = node.get("author")
            if isinstance(author, dict) and isinstance(author.get("url"), str):
                out.has_author_url = True
            for v in node.values():
                if isinstance(v, (dict, list)):
                    _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    for block in jsonld_blocks or []:
        _walk(block)

    out.sameas_targets = sorted(sameas_set)
    out.has_sameas = bool(out.sameas_targets)

    # Score.
    authoritative_hits = sum(
        1 for u in out.sameas_targets
        if any(h in u.lower() for h in _AUTHORITATIVE_HOSTS)
    )
    score = (
        (30 if out.has_person_schema else 0)
        + (20 if out.has_publisher else 0)
        + (20 if out.has_sameas else 0)
        + min(30, authoritative_hits * 15)
    )
    out.score = min(100, score)
    return out


# ── 3. Reddit / Quora brand mentions ──────────────────────────────────


@dataclass
class SocialMentions:
    brand: str
    reddit_count: int = 0
    quora_count: int = 0
    reddit_top: list[dict] = field(default_factory=list)
    quora_top: list[dict] = field(default_factory=list)
    error: str = ""


def fetch_social_mentions(brand: str, *, per_site: int = 10) -> SocialMentions:
    """Run two site-restricted Google searches via SerpAPI and return
    the top Reddit + Quora mentions of the brand.

    These two surfaces are heavily weighted by ChatGPT (RLHF training
    data) and Perplexity (live retrieval). A brand with no Reddit /
    Quora presence is invisible to those engines for long-tail queries.

    Gated on SERP_API_KEY. Returns ``error`` on the dataclass when
    the key is missing so the dashboard can surface that.
    """
    out = SocialMentions(brand=brand)
    try:
        from ..adapters.serp_api import SerpAPIAdapter
        adapter = SerpAPIAdapter()
    except Exception as exc:  # noqa: BLE001
        out.error = f"SerpAPI disabled: {exc}"
        return out

    for site, label in [("reddit.com", "reddit"), ("quora.com", "quora")]:
        try:
            sr = adapter.search(
                query=f"site:{site} {brand}",
                engine="google",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("social mentions %s failed: %s", site, exc)
            continue
        if sr.error:
            log.info("social mentions %s: %s", site, sr.error)
            continue
        entries = [
            {
                "title": (row.title or "")[:200],
                # OrganicRow's URL field is ``url``, not ``link`` — using
                # ``link`` here was an AttributeError that 500-ed the
                # entire /api/v1/seo/geo/score/?deep=true endpoint.
                "link": row.url or "",
                "snippet": (row.snippet or "")[:300],
            }
            for row in (sr.organic or [])[:per_site]
        ]
        if label == "reddit":
            out.reddit_count = len(entries)
            out.reddit_top = entries
        else:
            out.quora_count = len(entries)
            out.quora_top = entries
    return out


# ── 4. YouTube presence (via SerpAPI YouTube engine) ─────────────────


@dataclass
class YouTubePresence:
    brand: str
    channel_url: str = ""
    video_count: int = 0
    videos: list[dict] = field(default_factory=list)
    error: str = ""


def fetch_youtube_presence(brand: str, *, num: int = 10) -> YouTubePresence:
    """Find YouTube video presence for the brand.

    Uses ``site:youtube.com {brand}`` via the existing Google SerpAPI
    adapter — no separate YouTube Data API key needed. SerpAPI
    organic rows contain youtube.com URLs which we treat as video
    hits. The video count is the GEO signal we care about.
    """
    out = YouTubePresence(brand=brand)
    try:
        from ..adapters.serp_api import SerpAPIAdapter
        adapter = SerpAPIAdapter()
    except Exception as exc:  # noqa: BLE001
        out.error = f"SerpAPI disabled: {exc}"
        return out

    try:
        sr = adapter.search(
            query=f"site:youtube.com {brand}",
            engine="google",
        )
    except Exception as exc:  # noqa: BLE001
        out.error = f"YouTube search failed: {exc}"
        return out
    if sr.error:
        out.error = sr.error
        return out

    videos = [
        {
            "title": (r.title or "")[:200],
            # OrganicRow exposes the URL as ``.url``, not ``.link`` —
            # second occurrence of the same AttributeError as
            # fetch_social_mentions above.
            "link": r.url or "",
            "snippet": (r.snippet or "")[:300],
        }
        for r in (sr.organic or [])[:num]
        if "/watch?" in (r.url or "") or "youtube.com/" in (r.url or "")
    ]
    out.video_count = len(videos)
    out.videos = videos
    # Channel URL — first /channel/ or /@handle/ URL in results.
    for r in (sr.organic or []):
        link = r.url or ""
        if "/channel/" in link or "/@" in link:
            out.channel_url = link
            break
    return out


# ── 5. Wikidata entity check (free, no key) ──────────────────────────


@dataclass
class WikidataEntity:
    brand: str
    qid: str = ""
    label: str = ""
    description: str = ""
    sitelinks_count: int = 0
    has_logo: bool = False
    error: str = ""


def fetch_wikidata_entity(brand: str) -> WikidataEntity:
    """Query the public Wikidata SPARQL endpoint for the brand entity.

    Wikidata Q-id presence + sitelinks count + logo presence are
    proxies for "AI engines know who this brand is". Free, no key.
    """
    import httpx

    out = WikidataEntity(brand=brand)
    sparql = (
        "SELECT ?item ?itemLabel ?itemDescription ?logo "
        "(COUNT(DISTINCT ?sitelink) AS ?sitelinkCount) WHERE { "
        f'  ?item rdfs:label "{brand}"@en . '
        "  OPTIONAL { ?item wdt:P154 ?logo . } "
        "  OPTIONAL { ?sitelink schema:about ?item . } "
        '  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } '
        "} GROUP BY ?item ?itemLabel ?itemDescription ?logo LIMIT 1"
    )
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(
                "https://query.wikidata.org/sparql",
                params={"query": sparql, "format": "json"},
                headers={"User-Agent": "BajajSEOPlatform/1.0 (https://www.bajajlifeinsurance.com)"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        out.error = f"Wikidata SPARQL failed: {exc}"
        return out

    bindings = (data.get("results") or {}).get("bindings") or []
    if not bindings:
        out.error = "no Wikidata entity found for this brand label"
        return out

    row = bindings[0]
    item_url = (row.get("item") or {}).get("value") or ""
    out.qid = item_url.rsplit("/", 1)[-1] if item_url else ""
    out.label = (row.get("itemLabel") or {}).get("value") or ""
    out.description = (row.get("itemDescription") or {}).get("value") or ""
    try:
        out.sitelinks_count = int(
            (row.get("sitelinkCount") or {}).get("value") or 0,
        )
    except ValueError:
        out.sitelinks_count = 0
    out.has_logo = bool((row.get("logo") or {}).get("value"))
    return out


# ── 6. Unified GEO score ──────────────────────────────────────────────


@dataclass
class GeoScore:
    brand: str
    overall_score: int = 0      # 0-100
    factors: dict[str, Any] = field(default_factory=dict)
    suggestions: list[str] = field(default_factory=list)


def compute_geo_score(
    *,
    brand: str = "Bajaj Allianz Life Insurance",
    snapshot_id: str | None = None,
    deep: bool = True,
) -> GeoScore:
    """Aggregate every GEO signal we have into one operator-facing score.

    ``deep=False`` skips the external API calls (Reddit/Quora/YouTube/
    Wikidata) — useful for a fast read where you only want the
    page-level signals.

    Returns a :class:`GeoScore` whose ``factors`` carries one entry
    per family and whose ``suggestions`` lists the top actions.
    """
    out = GeoScore(brand=brand)

    # ── Page-level rollup (citation density + E-E-A-T) ─────────
    page_signals = _aggregate_page_signals(snapshot_id=snapshot_id)
    out.factors["page_signals"] = page_signals

    # ── AI bot hit rollup ──────────────────────────────────────
    out.factors["ai_bot_hits"] = _ai_bot_hits_summary()

    # ── llms.txt presence ──────────────────────────────────────
    out.factors["llms_txt"] = _llms_txt_status()

    # ── Brand mentions feed (already in BrandMention table) ───
    out.factors["brand_mentions"] = _brand_mentions_summary()

    if deep:
        out.factors["social_mentions"] = fetch_social_mentions(brand).__dict__
        out.factors["youtube"] = fetch_youtube_presence(brand).__dict__
        out.factors["wikidata"] = fetch_wikidata_entity(brand).__dict__

    # ── Composite score (weighted average) ─────────────────────
    score, suggestions = _compose_score(out.factors)
    out.overall_score = score
    out.suggestions = suggestions
    return out


def _aggregate_page_signals(*, snapshot_id: str | None) -> dict[str, Any]:
    """Per-page citation density + E-E-A-T averaged across the snapshot."""
    from django.db.models import Count

    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult

    if snapshot_id:
        snap = CrawlSnapshot.objects.filter(id=snapshot_id).first()
    else:
        snap = (
            CrawlSnapshot.objects.annotate(n=Count("pages"))
            .filter(kind="bajaj", n__gte=5)
            .order_by("-started_at")
            .first()
        )
    if snap is None:
        return {"available": False, "reason": "no snapshot"}

    rows = list(
        CrawlerPageResult.objects.filter(snapshot=snap, status_code="200")
        .values("url", "title", "body_text", "headings_json", "jsonld_blocks")[:500]
    )
    if not rows:
        return {"available": False, "reason": "no 200-OK rows"}

    citation_scores: list[int] = []
    eeat_scores: list[int] = []
    pages_with_person_schema = 0
    pages_with_sameas = 0

    for r in rows:
        cd = citation_density(
            title=r["title"] or "",
            body_text=r["body_text"] or "",
            headings_json=r["headings_json"] or [],
        )
        citation_scores.append(cd.score)
        ee = audit_eeat(r["jsonld_blocks"] or [])
        eeat_scores.append(ee.score)
        if ee.has_person_schema:
            pages_with_person_schema += 1
        if ee.has_sameas:
            pages_with_sameas += 1

    avg = lambda xs: int(sum(xs) / len(xs)) if xs else 0
    return {
        "available": True,
        "snapshot_id": str(snap.id),
        "pages_analysed": len(rows),
        "avg_citation_density": avg(citation_scores),
        "avg_eeat_score": avg(eeat_scores),
        "pages_with_person_schema_pct": round(
            100.0 * pages_with_person_schema / max(1, len(rows)), 1,
        ),
        "pages_with_sameas_pct": round(
            100.0 * pages_with_sameas / max(1, len(rows)), 1,
        ),
    }


def _ai_bot_hits_summary() -> dict[str, Any]:
    """30-day rollup of AIBotLog hits by bot family."""
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    try:
        from apps.crawler.models import AIBotLog
    except Exception:  # noqa: BLE001
        return {"available": False, "reason": "AIBotLog import failed"}

    cutoff = dj_tz.now() - timedelta(days=30)
    qs = AIBotLog.objects.filter(seen_at__gte=cutoff)
    total = qs.count()
    by_bot: dict[str, int] = {}
    for row in qs.values("bot"):
        k = row["bot"] or "unknown"
        by_bot[k] = by_bot.get(k, 0) + 1
    return {
        "available": True,
        "total_30d": total,
        "by_bot": by_bot,
        "distinct_bots": len(by_bot),
    }


def _llms_txt_status() -> dict[str, Any]:
    """Presence + size of /llms.txt on bajajlifeinsurance.com."""
    try:
        import httpx
        with httpx.Client(timeout=10.0, follow_redirects=True, verify=False) as c:
            r = c.get("https://www.bajajlifeinsurance.com/llms.txt")
            return {
                "present": r.status_code == 200,
                "status_code": r.status_code,
                "bytes": len(r.content) if r.status_code == 200 else 0,
                "url_count_approx": (r.text.count("\n") if r.status_code == 200 else 0),
            }
    except Exception as exc:  # noqa: BLE001
        return {"present": False, "error": str(exc)}


def _brand_mentions_summary() -> dict[str, Any]:
    """30-day BrandMention table rollup with per-tier breakdown.

    Defensively wraps the whole thing — field-name drift, missing
    table, etc. shouldn't fail the unified GEO score.
    """
    from collections import Counter
    from datetime import timedelta

    try:
        from django.utils import timezone as dj_tz

        from ..models import BrandMention

        cutoff = dj_tz.now() - timedelta(days=30)
        qs = BrandMention.objects.filter(last_seen_at__gte=cutoff)
        tiers = Counter(qs.values_list("source_tier", flat=True))
        return {
            "available": True,
            "count_30d": qs.count(),
            "tier_breakdown": dict(tiers),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)[:200]}


def _compose_score(factors: dict[str, Any]) -> tuple[int, list[str]]:
    """Weighted aggregate + suggestion list."""
    suggestions: list[str] = []

    # Page signals — 30% weight.
    ps = factors.get("page_signals", {})
    page_score = 0
    if ps.get("available"):
        cit = ps.get("avg_citation_density", 0)
        eea = ps.get("avg_eeat_score", 0)
        page_score = int(0.5 * cit + 0.5 * eea)
        if cit < 40:
            suggestions.append(
                "Low citation density on pages — add more definitions, "
                "lists, tables and Q&A blocks to the first 1500 chars.",
            )
        if ps.get("pages_with_person_schema_pct", 0) < 10:
            suggestions.append(
                "<10% of pages have Person schema — adding author markup "
                "raises E-E-A-T weight in AI rankings.",
            )

    # AI bot hits — 20% weight.
    ab = factors.get("ai_bot_hits", {})
    bot_score = 0
    if ab.get("available"):
        n = ab.get("total_30d", 0)
        bot_score = min(100, n // 5)
        if n < 50:
            suggestions.append(
                f"Only {n} AI-bot hits in last 30 days. Check robots.txt "
                "doesn't block GPTBot/ClaudeBot/PerplexityBot.",
            )

    # llms.txt — 10% weight.
    lt = factors.get("llms_txt", {})
    llms_score = 100 if lt.get("present") else 0
    if not lt.get("present"):
        suggestions.append(
            "No /llms.txt — generate one via /api/v1/crawler/geo/llms-txt/draft.",
        )

    # Wikidata — 10% weight (only if deep).
    wd = factors.get("wikidata", {})
    wd_score = 0
    if wd:
        if wd.get("qid"):
            wd_score = min(100, 50 + (wd.get("sitelinks_count", 0) * 2))
        else:
            wd_score = 0
            suggestions.append(
                "No Wikidata entity found — request one at "
                "https://www.wikidata.org/wiki/Special:NewItem so AI "
                "engines can anchor citations.",
            )

    # YouTube — 10% weight (only if deep).
    yt = factors.get("youtube", {})
    yt_score = 0
    if yt:
        v = yt.get("video_count", 0)
        yt_score = min(100, v * 10)
        if v < 3:
            suggestions.append(
                "Limited YouTube presence — publish topical videos "
                "(transcripts feed ChatGPT/Perplexity).",
            )

    # Social (Reddit/Quora) — 10% weight (only if deep).
    sm = factors.get("social_mentions", {})
    sm_score = 0
    if sm:
        n = (sm.get("reddit_count") or 0) + (sm.get("quora_count") or 0)
        sm_score = min(100, n * 5)

    # Brand mentions feed — 10% weight.
    bm = factors.get("brand_mentions", {})
    bm_score = 0
    if bm.get("available"):
        bm_score = min(100, (bm.get("count_30d", 0) // 3))

    # Weighted overall.
    overall = int(
        0.30 * page_score
        + 0.20 * bot_score
        + 0.10 * llms_score
        + 0.10 * wd_score
        + 0.10 * yt_score
        + 0.10 * sm_score
        + 0.10 * bm_score
    )
    return overall, suggestions
