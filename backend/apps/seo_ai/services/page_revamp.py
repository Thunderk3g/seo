"""Per-page revamp service — orchestrates: find competitor counterparts,
refresh stale rows, gather signals, run the AI agent.

Flow (one operator click on the Content Writer page):

1. Operator passes their Bajaj URL (+ optional free-text prompt).
2. We live-crawl that URL — fresh content is always better than what
   the nightly Bajaj crawl might have. ``crawl_live`` writes a fresh
   ``CrawlerPageResult`` row.
3. We scan **every competitor brand** for a counterpart page — URL-slug
   overlap + title overlap. Best 1-2 matches per brand, ranked.
4. For each counterpart: if the row is fresh AND has body text, we use
   the DB row directly; otherwise we live-fetch to refresh.
5. We pull CWV (PSI) for our URL + each counterpart (parallel) and
   Semrush ranking keywords for our domain + each counterpart's domain
   (cached on disk per the existing Phase 7 pattern).
6. We hand the entire payload to ``revamp_writer.generate_revamp`` —
   a Groq agent that compares OUR page against N competitor pages and
   emits an improved-version proposal (title, meta, headings, body
   sections, FAQ, CTAs, HTML, tech recommendations).

This module is the ONLY caller-facing surface. The view is a 30-line
HTTP wrapper.
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("seo.ai.page_revamp")


# ── helpers ──────────────────────────────────────────────────────────


# Vertical-noise tokens that show up on nearly every insurance page URL;
# stripping them keeps the URL-overlap signal focused on the actual
# topic ("term", "ulip", "tax-saving", "retirement", …).
_URL_STOP_TOKENS: frozenset[str] = frozenset({
    "insurance", "insurance-plans", "insurance-plan",
    "policy", "policies", "plan", "plans",
    "life-insurance", "life-insurance-plans",
    "online", "india", "buy", "best", "top",
    "page", "pages",
    "html", "htm", "aspx", "php",
    "www", "com", "in", "co",
})


def _tokens(path: str) -> list[str]:
    """Extract slug tokens from a URL path.

    Example: '/term-insurance-plans/click-2-protect-super.html'
             → ['term', 'insurance', 'plans', 'click', 'protect', 'super']
    Drops stopword-y vertical noise. Returns lowercase, deduped.
    """
    if not path:
        return []
    # Strip query, fragment, leading/trailing slash, trailing extension.
    p = path.strip().lower()
    p = p.split("?", 1)[0].split("#", 1)[0].strip("/")
    # Replace separators with space, drop file extensions.
    p = re.sub(r"\.(html?|aspx?|php|jsp)$", "", p)
    p = re.sub(r"[/_\-.]+", " ", p)
    raw = [t for t in p.split() if t and not t.isdigit() and len(t) > 1]
    out: list[str] = []
    seen: set[str] = set()
    for t in raw:
        if t in _URL_STOP_TOKENS or t in seen:
            continue
        # Skip pure stopword endings like '2' or single letters.
        if len(t) < 2:
            continue
        out.append(t)
        seen.add(t)
    return out


def _title_tokens(title: str) -> set[str]:
    """Lowercase content-word tokens from a page title."""
    if not title:
        return set()
    raw = re.findall(r"[a-z]{3,}", title.lower())
    return {t for t in raw if t not in _URL_STOP_TOKENS}


def _overlap_score(
    our_url_tokens: list[str],
    our_title_tokens: set[str],
    cand_url: str,
    cand_title: str,
) -> float:
    """0..1 — how well a competitor URL matches our topic."""
    ct = _tokens(urlparse(cand_url).path)
    if not ct or not our_url_tokens:
        return 0.0
    # Jaccard on URL tokens, weighted heavier than title.
    a, b = set(our_url_tokens), set(ct)
    if not a or not b:
        return 0.0
    url_jac = len(a & b) / max(1, len(a | b))
    title_a = our_title_tokens
    title_b = _title_tokens(cand_title or "")
    title_jac = (
        len(title_a & title_b) / max(1, len(title_a | title_b))
        if title_a or title_b
        else 0.0
    )
    return 0.7 * url_jac + 0.3 * title_jac


# ── dataclasses ──────────────────────────────────────────────────────


@dataclass
class CounterpartMatch:
    brand: str
    url: str
    title: str
    snapshot_id: str
    confidence: float
    source: str  # "db" | "live"
    word_count: int = 0


@dataclass
class PageSignals:
    url: str
    title: str
    meta_description: str
    word_count: int
    h1: list[str]
    h2: list[str]
    headings: list[dict]
    internal_links: list[dict]
    external_links: list[dict]
    images: list[dict]
    videos: list[dict]
    jsonld_types: list[str]
    body_excerpt: str  # capped to ~4000 chars
    cwv_mobile: dict = field(default_factory=dict)
    cwv_desktop: dict = field(default_factory=dict)
    semrush_keywords: list[dict] = field(default_factory=list)


@dataclass
class RevampPayload:
    our: PageSignals
    counterparts: list[tuple[CounterpartMatch, PageSignals]]
    prompt: str
    competitors_scanned: int
    competitors_matched: int
    warnings: list[str] = field(default_factory=list)
    # Section clusters computed BEFORE the rewrite call so the agent
    # generates content explicitly closing identified gaps rather than
    # inferring them from raw evidence. ``our_sections`` is the LLM
    # cluster output for our page; ``their_sections`` is a list of
    # (brand, sections_list) pairs.
    our_sections: list[dict] = field(default_factory=list)
    their_sections: list[tuple[str, list[dict]]] = field(default_factory=list)
    # Structured diff fed to both the agent and the UI gap panel.
    gap: dict = field(default_factory=dict)


# ── counterpart discovery ─────────────────────────────────────────────


def find_competitor_counterparts(
    our_url: str,
    *,
    max_per_brand: int = 1,
    max_brands: int = 8,
    min_confidence: float = 0.15,
    brand_filter: str | None = None,
) -> tuple[list[CounterpartMatch], int]:
    """Scan every competitor brand for a counterpart page to ``our_url``.

    Returns ``(matches, brands_scanned)``. ``brand_filter`` (lowercased
    parent_domain) restricts the scan to one brand — used when the
    operator's prompt mentions e.g. "compare only with hdfclife.com".
    """
    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult

    our_parsed = urlparse(our_url)
    our_path_tokens = _tokens(our_parsed.path)
    if not our_path_tokens:
        return [], 0

    # Get our title from the freshest CrawlerPageResult — used as a
    # secondary signal alongside URL slug overlap.
    our_row = (
        CrawlerPageResult.objects.filter(url=our_url)
        .order_by("-snapshot__started_at")
        .first()
    )
    our_title_toks = _title_tokens(our_row.title if our_row else "")

    brands_qs = (
        CrawlSnapshot.objects
        .filter(kind=CrawlSnapshot.Kind.COMPETITOR, status="complete")
        .exclude(parent_domain="")
        .exclude(parent_domain="bajajlifeinsurance.com")
        .values_list("parent_domain", flat=True)
        .distinct()
    )
    brands = sorted({b for b in brands_qs if b})
    if brand_filter:
        brands = [b for b in brands if brand_filter in b]
    brands = brands[: max_brands * 2]  # leave headroom — some won't match

    # Pre-build URL token sets per brand to avoid N×M Python-side scans.
    # We score every candidate with one ORM hit per brand: filter by any
    # of our top-3 most-informative tokens appearing in the URL.
    top_signal_tokens = our_path_tokens[:3]
    matches: list[CounterpartMatch] = []
    for brand in brands:
        # Query: pages from that brand whose URL contains one of our
        # signal tokens. ``Q | Q | Q`` over icontains — small filter,
        # avoids loading every page row.
        from django.db.models import Q

        q = Q()
        for tok in top_signal_tokens:
            q |= Q(url__icontains=tok)
        cands = (
            CrawlerPageResult.objects
            .filter(
                snapshot__kind=CrawlSnapshot.Kind.COMPETITOR,
                snapshot__parent_domain=brand,
                status_code="200",
            )
            .filter(q)
            .only("url", "title", "snapshot_id", "word_count")
        )[:200]  # cap — even a sprawling site won't exceed this after the OR filter
        scored: list[CounterpartMatch] = []
        for c in cands:
            score = _overlap_score(our_path_tokens, our_title_toks, c.url, c.title or "")
            if score < min_confidence:
                continue
            scored.append(CounterpartMatch(
                brand=brand,
                url=c.url,
                title=c.title or "",
                snapshot_id=str(c.snapshot_id),
                confidence=round(score, 3),
                source="db",
                word_count=int(c.word_count or 0),
            ))
        scored.sort(key=lambda m: -m.confidence)
        matches.extend(scored[:max_per_brand])

    matches.sort(key=lambda m: -m.confidence)
    matches = matches[:max_brands]
    return matches, len(brands)


# ── URL-guess fallback for brands without a DB match ────────────────


def _url_guesses_for_brand(our_url: str, brand: str) -> list[str]:
    """Produce candidate URLs for ``brand`` based on our path slug.

    Tight: only the 2 most-likely variants per brand so a brand whose
    DNS/TLS is slow can't blow the orchestrator's latency budget.
    Caller short-circuits on the first 200 hit anyway.
    """
    if not our_url or not brand:
        return []
    parsed = urlparse(our_url)
    path = parsed.path.strip("/")
    if not path:
        return [f"https://www.{brand}/"]
    base = re.sub(r"\.(html?|aspx?|php|jsp)$", "", path, flags=re.I)
    candidates: list[str] = [
        f"https://www.{brand}/{base}",
        f"https://www.{brand}/{base}/",
    ]
    # Singular variant if path ends in -plans (term-insurance-plans →
    # term-insurance). Many competitors use the singular slug.
    if base.endswith("-plans"):
        candidates.append(f"https://www.{brand}/{base[:-len('-plans')] + '-plan'}")
    # De-dup while preserving order.
    seen: set[str] = set()
    return [c for c in candidates if not (c in seen or seen.add(c))][:3]


def _try_url_guess_for_brand(
    our_url: str, brand: str, *, our_path_tokens: list[str],
    our_title_toks: set[str], min_confidence: float = 0.15,
) -> CounterpartMatch | None:
    """Live-fetch URL guesses for ``brand`` until one returns 200 with
    a real title, then return it as a ``CounterpartMatch`` (source='live').

    Logs every attempt so the operator can see what URLs were tried.
    """
    from apps.crawler.views import crawl_live, CrawlLiveError

    for url in _url_guesses_for_brand(our_url, brand):
        try:
            _snap, row = crawl_live(url)
        except CrawlLiveError as exc:
            logger.info("url-guess miss %s: %s", url, exc)
            continue
        # crawl_live writes under kind='adhoc' — but the URL conceptually
        # belongs to the competitor brand. Tag the match accordingly so
        # downstream surfaces don't show "adhoc" as the source.
        if not row or not row.title:
            continue
        score = _overlap_score(
            our_path_tokens, our_title_toks, row.url, row.title or "",
        )
        if score < min_confidence:
            continue
        return CounterpartMatch(
            brand=brand,
            url=row.url,
            title=row.title or "",
            snapshot_id=str(row.snapshot_id),
            confidence=round(score, 3),
            source="live-guess",
            word_count=int(row.word_count or 0),
        )
    return None


def find_or_guess_counterparts(
    our_url: str,
    *,
    max_brands: int = 5,
    brand_filter: str | None = None,
    enable_url_guess: bool = True,
) -> tuple[list[CounterpartMatch], int, list[str]]:
    """Like ``find_competitor_counterparts`` but for brands without a
    DB match, tries common URL conventions live.

    Returns ``(matches, brands_scanned, attempted_guess_brands)``.
    """
    from apps.crawler.models import CrawlSnapshot

    matches, brands_scanned = find_competitor_counterparts(
        our_url,
        max_per_brand=1,
        max_brands=max_brands,
        brand_filter=brand_filter,
    )
    if not enable_url_guess:
        return matches, brands_scanned, []

    matched_brands = {m.brand for m in matches}
    all_brands = list(
        CrawlSnapshot.objects
        .filter(kind=CrawlSnapshot.Kind.COMPETITOR, status="complete")
        .exclude(parent_domain="")
        .exclude(parent_domain="bajajlifeinsurance.com")
        .values_list("parent_domain", flat=True)
        .distinct()
    )
    if brand_filter:
        all_brands = [b for b in all_brands if brand_filter in b]

    parsed = urlparse(our_url)
    path_tokens = _tokens(parsed.path)
    # Get our title for scoring guess matches.
    from apps.crawler.models import CrawlerPageResult
    our_row = (
        CrawlerPageResult.objects.filter(url=our_url)
        .order_by("-snapshot__started_at")
        .first()
    )
    title_toks = _title_tokens(our_row.title if our_row else "")

    brands_to_guess = [
        b for b in sorted(set(all_brands))
        if b not in matched_brands
    ]
    # Cap how many brands we try to keep latency bounded — caller wants
    # max_brands total, we already have len(matches) from DB.
    remaining = max(0, max_brands - len(matches))
    brands_to_guess = brands_to_guess[: remaining * 2]  # try 2x in case some miss
    attempted = list(brands_to_guess)

    if brands_to_guess:
        with ThreadPoolExecutor(max_workers=min(4, len(brands_to_guess))) as ex:
            future_map = {
                ex.submit(
                    _try_url_guess_for_brand,
                    our_url, brand,
                    our_path_tokens=path_tokens,
                    our_title_toks=title_toks,
                ): brand
                for brand in brands_to_guess
            }
            for fut in future_map:
                brand = future_map[fut]
                try:
                    guess = fut.result(timeout=30)
                except Exception as exc:  # noqa: BLE001
                    logger.info("url-guess for %s crashed: %s", brand, exc)
                    continue
                if guess is not None:
                    matches.append(guess)
                    logger.info(
                        "url-guess hit for %s: %s (conf=%.2f)",
                        brand, guess.url, guess.confidence,
                    )

    matches.sort(key=lambda m: -m.confidence)
    return matches[:max_brands], brands_scanned, attempted


# ── signal gathering ─────────────────────────────────────────────────


def _to_page_signals(row, *, body_cap: int = 4000) -> PageSignals:
    """Project a ``CrawlerPageResult`` ORM row into the ``PageSignals``
    shape the agent ingests.

    Pulls only the fields the agent reads — keeps the eventual evidence
    dict compact (the writer's prompt is large already once you stack 5
    competitor pages on top of ours).
    """
    headings = list(row.headings_json or [])
    h1 = [h.get("text", "") for h in headings if isinstance(h, dict) and int(h.get("level") or 0) == 1]
    h2 = [h.get("text", "") for h in headings if isinstance(h, dict) and int(h.get("level") or 0) == 2]
    return PageSignals(
        url=row.url,
        title=row.title or "",
        meta_description=row.meta_description or "",
        word_count=int(row.word_count or 0),
        h1=[t for t in h1 if t],
        h2=[t for t in h2 if t],
        headings=headings,
        internal_links=list(row.internal_links_json or []),
        external_links=list(row.external_links_json or []),
        images=list(row.images_json or []),
        videos=list(row.videos_json or []),
        jsonld_types=list(row.jsonld_types or []),
        body_excerpt=(row.body_text or "")[:body_cap],
        cwv_mobile={
            "lcp_ms": row.mobile_lcp_ms,
            "cls": row.mobile_cls,
            "inp_ms": row.mobile_inp_ms,
            "pagespeed_score": row.mobile_pagespeed_score,
        },
        cwv_desktop={
            "lcp_ms": row.desktop_lcp_ms,
            "cls": row.desktop_cls,
            "inp_ms": row.desktop_inp_ms,
            "pagespeed_score": row.desktop_pagespeed_score,
        },
    )


def _fresh_or_live(match: CounterpartMatch, *, freshness_days: int = 14):
    """Return a ``CrawlerPageResult`` row for ``match.url``.

    Uses the DB row when it has body text AND the snapshot is fresher
    than ``freshness_days``; otherwise live-fetches. Mutates
    ``match.source`` to record which path was taken.
    """
    from datetime import datetime, timedelta, timezone

    from apps.crawler.models import CrawlerPageResult
    from apps.crawler.views import crawl_live, CrawlLiveError

    row = (
        CrawlerPageResult.objects
        .filter(url=match.url)
        .select_related("snapshot")
        .order_by("-snapshot__started_at")
        .first()
    )
    if row and row.body_text:
        started = row.snapshot.started_at if row.snapshot else None
        if started is not None:
            try:
                age = datetime.now(timezone.utc) - started
            except TypeError:  # naive datetime guard
                age = timedelta(days=0)
            if age < timedelta(days=freshness_days):
                match.source = "db"
                return row
        else:
            match.source = "db"
            return row

    try:
        _snap, fresh_row = crawl_live(match.url)
        match.source = "live"
        return fresh_row
    except CrawlLiveError as exc:
        logger.warning(
            "page_revamp: live refresh failed for %s — %s", match.url, exc,
        )
        return row  # may be None — caller filters that


def _enrich_with_cwv(signals: PageSignals) -> None:
    """Best-effort PSI fetch for one PageSignals; mutates in place. PSI
    quota or network failures degrade silently to empty dicts."""
    try:
        from apps.seo_ai.adapters.cwv_psi import (
            AdapterDisabledError, PSIAdapter,
        )
        psi = PSIAdapter()
    except Exception:  # noqa: BLE001 — adapter disabled, no SA key, etc.
        return

    def _shape(rec) -> dict:
        if rec is None or rec.error:
            return {}
        return {
            "lcp_ms": rec.lab_lcp_ms,
            "cls": rec.lab_cls,
            "inp_ms": rec.field_inp_ms,
            "pagespeed_score": (
                int(rec.performance_score * 100)
                if rec.performance_score is not None
                else None
            ),
            "lab_fcp_ms": rec.lab_fcp_ms,
            "ttfb_ms": rec.lab_ttfb_ms,
        }

    try:
        with ThreadPoolExecutor(max_workers=2) as ex:
            m_future = ex.submit(psi.fetch, signals.url, strategy="mobile")
            d_future = ex.submit(psi.fetch, signals.url, strategy="desktop")
            m_rec = m_future.result(timeout=60)
            d_rec = d_future.result(timeout=60)
        signals.cwv_mobile = _shape(m_rec)
        signals.cwv_desktop = _shape(d_rec)
    except Exception as exc:  # noqa: BLE001
        logger.info("psi enrich failed for %s: %s", signals.url, exc)


def _semrush_top_for_url(parent_domain: str, target_url: str, *, top: int = 10) -> list[dict]:
    """Top Semrush ranking keywords whose ``url`` column matches the
    competitor's specific page (not just the domain). Cached on disk via
    the existing adapter behaviour.
    """
    try:
        from apps.seo_ai.adapters.semrush import SemrushAdapter
    except Exception:  # noqa: BLE001
        return []
    try:
        adapter = SemrushAdapter()
    except Exception as exc:  # noqa: BLE001
        logger.info("semrush adapter init failed: %s", exc)
        return []
    try:
        kws = adapter.organic_keywords(parent_domain, limit=500)
    except Exception as exc:  # noqa: BLE001
        logger.info("semrush organic_keywords failed for %s: %s", parent_domain, exc)
        return []

    target_path = urlparse(target_url).path.strip("/").lower()
    if not target_path:
        return []
    filtered = []
    for k in kws:
        kw_path = urlparse(k.url or "").path.strip("/").lower()
        # Match if the kw's ranking URL ends with our target path
        # (handles www / non-www / trailing-slash variants).
        if kw_path and (kw_path == target_path or kw_path.endswith(target_path)):
            filtered.append({
                "keyword": k.keyword,
                "position": k.position,
                "search_volume": k.search_volume,
                "traffic_pct": k.traffic_pct,
            })
    filtered.sort(key=lambda x: -x["search_volume"])
    return filtered[:top]


# ── prompt-instruction parsing ───────────────────────────────────────


_BRAND_HINTS = (
    "hdfc", "iciciprulife", "icicipru", "icici",
    "tata aia", "tataaia",
    "max life", "maxlife", "maxlifeinsurance",
    "bandhan", "bandhanlife",
    "kotak",
    "aviva",
    "canara", "canarahsbc",
    "indiafirst", "indiafirstlife",
    "allianz",
)


def _extract_brand_filter(prompt: str) -> str | None:
    """Look for a competitor brand mention in the operator's prompt.

    Returns a substring to filter ``parent_domain`` against, or None.
    Crude pattern match — operators usually say "compare with hdfc"
    rather than "compare with hdfclife.com", so we map prose hints to
    parent-domain substrings.
    """
    if not prompt:
        return None
    p = prompt.lower()
    for hint in _BRAND_HINTS:
        if hint in p:
            # Map to parent_domain substring.
            mapping = {
                "hdfc": "hdfclife",
                "iciciprulife": "iciciprulife",
                "icicipru": "iciciprulife",
                "icici": "iciciprulife",
                "tata aia": "tataaia",
                "tataaia": "tataaia",
                "max life": "maxlife",
                "maxlife": "maxlife",
                "maxlifeinsurance": "maxlifeinsurance",
                "bandhan": "bandhanlife",
                "bandhanlife": "bandhanlife",
                "kotak": "kotaklife",
                "aviva": "avivaindia",
                "canara": "canarahsbclife",
                "canarahsbc": "canarahsbclife",
                "indiafirst": "indiafirstlife",
                "indiafirstlife": "indiafirstlife",
                "allianz": "allianz",
            }
            return mapping.get(hint)
    return None


# ── public entry point ──────────────────────────────────────────────


def build_revamp_payload(
    *,
    our_url: str,
    prompt: str = "",
    max_competitors: int = 5,
    enable_psi: bool = True,
    enable_semrush: bool = True,
) -> RevampPayload:
    """Assemble everything the agent needs: our live-crawled page +
    matched competitor pages (refreshed if stale) + CWV + Semrush.

    All network calls (live crawl, PSI fetches, Semrush) are run in a
    bounded parallel pool so the wall time is roughly the slowest single
    operation, not the sum.
    """
    from apps.crawler.views import crawl_live, CrawlLiveError

    warnings: list[str] = []
    t0 = time.monotonic()

    # 1) Live-crawl ours (always fresh).
    try:
        _snap, our_row = crawl_live(our_url)
    except CrawlLiveError as exc:
        raise RuntimeError(f"live crawl of our URL failed: {exc}") from exc

    our_signals = _to_page_signals(our_row)

    # 2) Find counterparts in DB + URL-guess fallback for missing brands.
    brand_filter = _extract_brand_filter(prompt)
    matches, brands_scanned, guessed_brands = find_or_guess_counterparts(
        our_url,
        max_brands=max_competitors,
        brand_filter=brand_filter,
        enable_url_guess=True,
    )
    if brand_filter and not matches:
        warnings.append(
            "prompt mentioned a brand but no counterpart pages found "
            "(neither in DB nor via URL-guess); falling back to "
            "scanning all competitors"
        )
        matches, brands_scanned, guessed_brands = find_or_guess_counterparts(
            our_url, max_brands=max_competitors,
        )
    if guessed_brands:
        for m in matches:
            if m.source == "live-guess":
                warnings.append(
                    f"{m.brand}: no DB match — live-fetched via URL guess "
                    f"({m.url})"
                )

    # 3) Resolve each match to a fresh-or-cached row. Live-guess matches
    # already came back via crawl_live so we already have a fresh row.
    counterparts: list[tuple[CounterpartMatch, PageSignals]] = []
    if matches:
        from apps.crawler.models import CrawlerPageResult

        def _resolve(match):
            if match.source == "live-guess":
                # We already crawled it; pull the row out of the DB.
                return (
                    CrawlerPageResult.objects
                    .filter(snapshot_id=match.snapshot_id, url=match.url)
                    .first()
                )
            return _fresh_or_live(match)

        with ThreadPoolExecutor(max_workers=min(4, len(matches))) as ex:
            future_map = {ex.submit(_resolve, m): m for m in matches}
            for f in future_map:
                m = future_map[f]
                row = f.result(timeout=120)
                if row is None or not row.body_text:
                    warnings.append(
                        f"could not refresh {m.url}; skipping it"
                    )
                    continue
                counterparts.append((m, _to_page_signals(row)))

    # 4) PSI for all signals in parallel (mutates signals in place).
    if enable_psi:
        targets = [our_signals] + [s for _m, s in counterparts]
        with ThreadPoolExecutor(max_workers=min(6, len(targets))) as ex:
            list(ex.map(_enrich_with_cwv, targets))

    # 5) Semrush for ours + each counterpart.
    if enable_semrush:
        from apps.crawler.util.host import apex
        try:
            our_signals.semrush_keywords = _semrush_top_for_url(
                apex(our_signals.url), our_signals.url, top=10,
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("semrush for ours failed: %s", exc)
        for m, s in counterparts:
            try:
                s.semrush_keywords = _semrush_top_for_url(
                    m.brand, m.url, top=10,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("semrush for %s failed: %s", m.url, exc)

    # 6) Cluster ours + each counterpart via LLM (parallel). This is the
    # explicit "cluster-first-then-rewrite" step the operator asked for:
    # the rewrite agent receives the gap as primary structured input.
    from .page_topic_sections import (
        build_page_topic_sections, _to_dict as _section_to_dict,
    )

    def _cluster_page(row):
        if row is None:
            return {"sections": []}
        try:
            res = build_page_topic_sections(page=row)
            return _section_to_dict(res)
        except Exception as exc:  # noqa: BLE001
            logger.info("section cluster failed for %s: %s", row.url, exc)
            return {"sections": [], "error": str(exc)}

    # Resolve our CrawlerPageResult row to feed the clusterer.
    our_section_payload: dict = _cluster_page(our_row)
    their_section_payloads: list[tuple[str, dict]] = []
    if counterparts:
        # We need the actual CrawlerPageResult rows the counterpart
        # signals came from. Re-look-up by (snapshot, url) to keep this
        # cheap; ORM cache catches the hot path.
        from apps.crawler.models import CrawlerPageResult

        def _cluster_counterpart(match):
            row = (
                CrawlerPageResult.objects
                .filter(snapshot_id=match.snapshot_id, url=match.url)
                .first()
            )
            return (match.brand, _cluster_page(row))

        with ThreadPoolExecutor(max_workers=min(4, len(counterparts))) as ex:
            for brand, sec_payload in ex.map(
                _cluster_counterpart, (m for m, _s in counterparts),
            ):
                their_section_payloads.append((brand, sec_payload))

    # 7) Structured gap computation — same shape we send to the agent
    # and render in the UI's Gap Analysis panel.
    from .page_revamp_gap import compute_gap, to_dict as _gap_to_dict

    our_sections_list = our_section_payload.get("sections") or []
    their_sections_list = [
        (brand, payload.get("sections") or [])
        for brand, payload in their_section_payloads
    ]
    # PageSignals → dict for the gap-compute helper.
    def _signals_dict(s):
        return {
            "url": s.url,
            "title": s.title,
            "word_count": s.word_count,
            "headings": s.headings,
            "internal_links": s.internal_links,
            "images": s.images,
            "h1": s.h1,
            "h2": s.h2,
        }
    their_signals_for_gap = [
        (m.brand, _signals_dict(s)) for m, s in counterparts
    ]
    gap_obj = compute_gap(
        our_sections=our_sections_list,
        our_signals=_signals_dict(our_signals),
        their_sections_by_brand=their_sections_list,
        their_signals_by_brand=their_signals_for_gap,
    )

    elapsed = time.monotonic() - t0
    logger.info(
        "revamp payload assembled in %.1fs: counterparts=%d brands_scanned=%d guessed=%d",
        elapsed, len(counterparts), brands_scanned, len(guessed_brands),
    )

    return RevampPayload(
        our=our_signals,
        counterparts=counterparts,
        prompt=prompt,
        competitors_scanned=brands_scanned,
        competitors_matched=len(counterparts),
        warnings=warnings,
        our_sections=our_sections_list,
        their_sections=their_sections_list,
        gap=_gap_to_dict(gap_obj),
    )
