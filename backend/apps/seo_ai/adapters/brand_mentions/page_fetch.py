"""Second-pass page fetcher — turns SERP/RSS mentions into deep records.

After the first-pass adapters (RSS / SerpAPI) write a row with title +
snippet + tier classification, this second pass actually fetches the
source URL and extracts the things that matter for SEO + AI-search
context:

  * **body_excerpt** — the actual paragraph from the page containing
    the brand mention (up to 2000 chars, centred on the match). The
    SERP snippet is Google's 200-char description; this is the real
    text.
  * **is_linked + anchor_texts** — whether the brand is wrapped in
    an `<a href>` to bajajlifeinsurance.com, and the anchor text(s).
    Linked mentions pass PageRank; unlinked mentions are "implied
    links" (Google patent US 8260915) — both count, separately
    weighted.
  * **schema.org structured data** — Article / NewsArticle / Review
    JSON-LD. Yields author + publisher entity (different from domain),
    publication date (more accurate than RSS), and rating if a
    review.
  * **co_mentioned_brands** — every competitor brand name appearing
    on the same page. Tells us whether Bajaj is the standalone
    subject or being compared against rivals.
  * **language** — `<html lang>` attribute. Drives multi-lingual
    coverage tracking.

Failure modes (all degrade gracefully):
  * Page returns non-200 / non-HTML → keep the SERP snippet as
    `body_excerpt`, mark `page_fetched_at` so we don't re-try.
  * Cisco WSA blocks the host → log + skip.
  * Paywall / JS-rendered SPA → we extract whatever HTML is in the
    pre-render. JS-only sites get noticeably less.
  * Bad regex / parse error → log once per page, keep going.

Rate limiting: per-host token-bucket (1s between requests to same
host) so a daily run hitting 50 mentions across 10 hosts finishes
in ~10 seconds rather than slamming any single publisher.
"""
from __future__ import annotations

import json
import logging
import re
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone as tz
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings

from .classify import all_brand_tokens, domain_of, extract_snippet

log = logging.getLogger("apps.seo_ai.adapters.brand_mentions.page_fetch")


# ── output shape ──────────────────────────────────────────────────────


@dataclass
class FetchedEnrichment:
    """Per-page enrichment delta. Caller merges these into the
    existing BrandMention row. Any field left at default is treated
    as "no signal" — the existing value (from SERP/RSS) wins."""

    body_excerpt: str = ""
    is_linked: bool = False
    anchor_texts: list[str] = field(default_factory=list)
    structured_data: dict = field(default_factory=dict)
    author: str = ""
    publisher: str = ""
    co_mentioned_brands: list[str] = field(default_factory=list)
    language: str = ""
    rating_value: float | None = None
    rating_max: float | None = None
    published_at: datetime | None = None
    error: str = ""


# ── competitor catalogue for co-mention detection ────────────────────
#
# Indian life-insurance peer set. The regex matches at word boundary so
# "HDFC Life" doesn't accidentally hit "HDFC Bank". Order longest-first
# — Python `re.finditer` doesn't sort by length, so we manually order
# more-specific variants first.

_COMPETITOR_PATTERNS = [
    ("HDFC Life",       re.compile(r"\bHDFC\s+Life(?:\s+Insurance)?\b", re.I)),
    ("ICICI Prudential", re.compile(r"\bICICI\s+Prudential(?:\s+Life)?\b", re.I)),
    ("SBI Life",        re.compile(r"\bSBI\s+Life(?:\s+Insurance)?\b", re.I)),
    ("LIC",             re.compile(r"\bLIC(?:\s+India|\s+of\s+India)?\b", re.I)),
    ("Tata AIA",        re.compile(r"\bTata\s+AIA(?:\s+Life)?\b", re.I)),
    ("Axis Max Life",   re.compile(r"\bAxis\s+Max\s+Life(?:\s+Insurance)?\b", re.I)),
    ("Max Life",        re.compile(r"\bMax\s+Life(?:\s+Insurance)?\b", re.I)),
    ("Kotak Life",      re.compile(r"\bKotak(?:\s+Mahindra)?\s+Life(?:\s+Insurance)?\b", re.I)),
    ("Aditya Birla",    re.compile(r"\bAditya\s+Birla\s+(?:Sun\s+)?Life(?:\s+Insurance)?\b", re.I)),
    ("PNB MetLife",     re.compile(r"\bPNB\s+MetLife\b", re.I)),
    ("Reliance Nippon", re.compile(r"\bReliance\s+Nippon\s+Life\b", re.I)),
    ("Aviva",           re.compile(r"\bAviva(?:\s+Life)?(?:\s+Insurance)?\b", re.I)),
    ("PolicyBazaar",    re.compile(r"\bPolicy\s*Bazaar\b", re.I)),
    ("Coverfox",        re.compile(r"\bCoverfox\b", re.I)),
    ("Ditto",           re.compile(r"\b(?:Ditto|JoinDitto)\b", re.I)),
    ("PolicyX",         re.compile(r"\bPolicyX\b", re.I)),
    ("Acko",            re.compile(r"\bAcko\b", re.I)),
]


def detect_co_mentioned_brands(text: str) -> list[str]:
    """Find every competitor brand name in the supplied text. Returns
    a deduplicated, ordered list — useful for downstream filters
    (\"mentions ranked alongside HDFC\" etc.)."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for label, pat in _COMPETITOR_PATTERNS:
        if pat.search(text) and label not in seen:
            found.append(label)
            seen.add(label)
    return found


# ── per-host rate limiter ─────────────────────────────────────────────


_LAST_FETCH_PER_HOST: dict[str, float] = {}
_RATE_LOCK = threading.Lock()


def _throttle(host: str, min_gap: float = 1.0) -> None:
    """Block until at least ``min_gap`` seconds have passed since the
    last fetch to this host. Cheap and effective — keeps us polite
    to any single publisher even on a multi-mention run."""
    if not host:
        return
    with _RATE_LOCK:
        last = _LAST_FETCH_PER_HOST.get(host, 0.0)
        now = time.monotonic()
        wait = max(0.0, min_gap - (now - last))
        _LAST_FETCH_PER_HOST[host] = now + wait
    if wait > 0:
        time.sleep(wait)


# ── HTTP fetch + parse ───────────────────────────────────────────────


_OWN_DOMAIN_PATTERN = re.compile(
    r"bajaj(life|allianz|finserv)?\.(com|in|co\.in)", re.I,
)


def _resolve_ssl_verify(raw: str) -> bool | str:
    value = (raw or "").strip()
    if not value or value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    import os
    if os.path.exists(value):
        return value
    return True


_BRAND_PATTERN_CACHE: re.Pattern[str] | None = None


def _brand_pattern() -> re.Pattern[str]:
    global _BRAND_PATTERN_CACHE
    if _BRAND_PATTERN_CACHE is None:
        toks = all_brand_tokens() or ["Bajaj Life Insurance"]
        _BRAND_PATTERN_CACHE = re.compile(
            "|".join(re.escape(t) for t in toks), re.IGNORECASE,
        )
    return _BRAND_PATTERN_CACHE


def fetch_page_enrichment(source_url: str, *, timeout: int = 20) -> FetchedEnrichment:
    """Single-URL deep fetch + enrichment. Returns a FetchedEnrichment
    that the orchestrator merges onto the existing BrandMention row.

    Heavy: ~1-3s per call (HTTP + BeautifulSoup parse). Caller decides
    when to run (we recommend opt-in, only for tier-1 / forum / review
    sources where the depth pays off)."""
    out = FetchedEnrichment()
    if not source_url:
        out.error = "no_url"
        return out

    cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
    verify = _resolve_ssl_verify(cfg.get("ssl_verify", "false"))
    if verify is False:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:  # noqa: BLE001
            pass

    host = domain_of(source_url)
    _throttle(host, min_gap=1.0)

    headers = {
        # Mimic a real desktop browser. News sites often serve a stub
        # to obvious bots; we look like a human reader.
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8,hi;q=0.7",
    }
    try:
        resp = requests.get(
            source_url, headers=headers, timeout=timeout, verify=verify,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        log.info("page_fetch %s: network error (%s)", host, exc)
        out.error = f"network: {type(exc).__name__}"
        return out

    if resp.status_code != 200:
        log.info("page_fetch %s: HTTP %d", host, resp.status_code)
        out.error = f"http_{resp.status_code}"
        return out

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "html" not in ctype:
        out.error = f"not_html: {ctype[:64]}"
        return out

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.warning("page_fetch: BeautifulSoup missing — install bs4")
        out.error = "no_bs4"
        return out

    body_text = resp.text or ""
    if not body_text:
        out.error = "empty_body"
        return out

    try:
        soup = BeautifulSoup(body_text, "html.parser")
    except Exception as exc:  # noqa: BLE001
        log.info("page_fetch %s: parse failed (%s)", host, exc)
        out.error = f"parse: {type(exc).__name__}"
        return out

    # Drop script/style/nav/footer noise before extracting text.
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    # ── language ────────────────────────────────────────────────
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        out.language = str(html_tag["lang"])[:8].split("-")[0]

    # ── body_excerpt — paragraph containing brand mention ──────
    visible_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    out.body_excerpt = extract_snippet(
        visible_text,
        around_match="Bajaj",
        length=2000,
    )

    # ── is_linked + anchor_texts ────────────────────────────────
    anchors_to_us: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href:
            continue
        # Resolve relative URLs to absolute for the domain check.
        try:
            abs_href = urljoin(source_url, href)
            host_of_link = (urlparse(abs_href).hostname or "").lower()
        except (ValueError, TypeError):
            continue
        if not host_of_link:
            continue
        if _OWN_DOMAIN_PATTERN.search(host_of_link):
            anchor_text = a.get_text(" ", strip=True)[:200]
            if anchor_text:
                anchors_to_us.append(anchor_text)
    # Dedupe preserving order.
    seen: set[str] = set()
    out.anchor_texts = [
        a for a in anchors_to_us if not (a in seen or seen.add(a))
    ][:12]
    out.is_linked = bool(out.anchor_texts)

    # ── schema.org JSON-LD ──────────────────────────────────────
    schema_data: dict = {}
    article_schemas: list[dict] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        # Could be a single dict OR an array OR a graph.
        nodes: list = []
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                nodes = data["@graph"]
            else:
                nodes = [data]
        elif isinstance(data, list):
            nodes = data
        for node in nodes:
            if not isinstance(node, dict):
                continue
            t = node.get("@type")
            t_norm = (
                t.lower() if isinstance(t, str)
                else " ".join(s.lower() for s in t if isinstance(s, str)) if isinstance(t, list)
                else ""
            )
            if any(
                key in t_norm
                for key in ("article", "newsarticle", "blogposting", "review")
            ):
                article_schemas.append(node)

    if article_schemas:
        # Pick the first match — most pages emit one canonical article
        # schema. Multiple matches usually mean the page has both a
        # parent Article and a child Review.
        primary = article_schemas[0]
        schema_data = primary
        # Author can be a string OR an object OR a list.
        author = primary.get("author")
        if isinstance(author, dict):
            out.author = str(author.get("name") or "")[:255]
        elif isinstance(author, list) and author:
            if isinstance(author[0], dict):
                out.author = str(author[0].get("name") or "")[:255]
            else:
                out.author = str(author[0])[:255]
        elif isinstance(author, str):
            out.author = author[:255]
        # Publisher similar.
        publisher = primary.get("publisher")
        if isinstance(publisher, dict):
            out.publisher = str(publisher.get("name") or "")[:255]
        elif isinstance(publisher, str):
            out.publisher = publisher[:255]
        # Publication date.
        date_raw = (
            primary.get("datePublished")
            or primary.get("dateCreated")
            or primary.get("dateModified")
            or ""
        )
        if date_raw:
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(str(date_raw)[:25], fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=tz.utc)
                    out.published_at = dt
                    break
                except ValueError:
                    continue
        # Review rating.
        rating = primary.get("reviewRating") or primary.get("aggregateRating")
        if isinstance(rating, dict):
            try:
                out.rating_value = float(rating.get("ratingValue") or 0) or None
            except (TypeError, ValueError):
                pass
            try:
                out.rating_max = float(rating.get("bestRating") or 5) or None
            except (TypeError, ValueError):
                pass

    out.structured_data = schema_data

    # ── meta-tag fallback for author/publisher when no JSON-LD ─
    if not out.author:
        meta_author = soup.find("meta", attrs={"name": re.compile(r"^author$", re.I)})
        if meta_author and meta_author.get("content"):
            out.author = str(meta_author["content"])[:255]
    if not out.publisher:
        meta_pub = (
            soup.find("meta", attrs={"property": re.compile(r"og:site_name", re.I)})
            or soup.find("meta", attrs={"name": re.compile(r"^publisher$", re.I)})
        )
        if meta_pub and meta_pub.get("content"):
            out.publisher = str(meta_pub["content"])[:255]

    # ── co-mentioned competitor brands ─────────────────────────
    out.co_mentioned_brands = detect_co_mentioned_brands(visible_text)

    return out


def enrich_mention(mention) -> tuple[bool, FetchedEnrichment]:
    """Enrich a single BrandMention model instance in-place.

    Returns (changed, enrichment). When ``changed=True`` the caller
    should `mention.save()` to persist. The caller is responsible for
    skipping rows that already have ``page_fetched_at`` set unless
    a refresh is wanted.
    """
    enrichment = fetch_page_enrichment(mention.source_url)
    if enrichment.error and not enrichment.body_excerpt:
        # Total failure — still stamp page_fetched_at so we don't
        # re-try on every run.
        mention.page_fetched_at = datetime.now(tz.utc)
        return True, enrichment

    if enrichment.body_excerpt:
        mention.body_excerpt = enrichment.body_excerpt
    if enrichment.is_linked:
        mention.is_linked = True
        mention.anchor_texts = enrichment.anchor_texts
    if enrichment.structured_data:
        mention.structured_data = enrichment.structured_data
    if enrichment.author:
        mention.author = enrichment.author
    if enrichment.publisher:
        mention.publisher = enrichment.publisher
    if enrichment.co_mentioned_brands:
        mention.co_mentioned_brands = enrichment.co_mentioned_brands
    if enrichment.language:
        mention.language = enrichment.language
    if enrichment.rating_value is not None:
        mention.rating_value = enrichment.rating_value
        mention.rating_max = enrichment.rating_max
    if enrichment.published_at and not mention.published_at:
        mention.published_at = enrichment.published_at
    mention.page_fetched_at = datetime.now(tz.utc)
    return True, enrichment
