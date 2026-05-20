"""Orphan page detection — Ahrefs-style "URLs nobody links to internally".

A URL is an orphan when ANY external source proves the page exists, but
NOTHING in our internal link graph points to it. The classic signal of
buried high-value content that earns traffic but has zero crawl-budget
support.

External sources we treat as authoritative for "page exists":

  1. **AEM sitemap** — every authored page (``SitemapAEMAdapter``).
  2. **GSC web__page.csv** — every page that's ever appeared in a Google
     SERP for our brand.
  3. **Crawled pages themselves** — every URL the crawler successfully
     hit AT THE SEED level (depth 0) or via a sitemap entry.

Internal link graph: ``crawl_discovered.csv`` carries every
``(discovered_from, url)`` edge. URLs that show up nowhere on the right-
hand side of any edge are orphans.

Result:

  ``find_orphans()`` returns a typed list of ``OrphanPage`` rows:

    url, source ("aem" | "gsc" | "crawl_self"), title,
    page_type (if known from crawl row), word_count, has_gsc_clicks,
    has_gsc_impressions.

The frontend renders this as the Page Explorer "Orphan" filter
preset and the Excel "Orphan Pages" sheet in Phase 5.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..conf import settings


@dataclass
class OrphanPage:
    url: str
    source: str                # "aem" | "gsc" | "crawl_self"
    title: str = ""
    page_type: str = ""
    word_count: int = 0
    has_gsc_clicks: bool = False
    has_gsc_impressions: bool = False


def _normalize(url: str) -> str:
    """Lowercase host + strip trailing slash so AEM vs GSC vs crawler
    URLs match up even when one source uses a trailing slash and
    another doesn't."""
    if not url:
        return ""
    return url.strip().rstrip("/").lower()


def _load_inlink_set() -> set[str]:
    """Every URL that appears as ``url`` (destination) in
    crawl_discovered.csv — i.e., every URL with at least one internal
    inbound link. Anything NOT in this set + present in any external
    source is an orphan."""
    path = settings.data_path / "crawl_discovered.csv"
    out: set[str] = set()
    if not path.exists():
        return out
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            u = _normalize(row.get("url") or "")
            if u:
                out.add(u)
    return out


def _load_crawled_rows() -> dict[str, dict]:
    """Map every crawled URL to its result-row dict (so the orphan
    output can carry title / page_type / word_count without a join)."""
    path = settings.data_path / "crawl_results.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            u = _normalize(row.get("url") or "")
            if u:
                out[u] = row
    return out


def _load_aem_urls() -> set[str]:
    """All public AEM URLs. Cheap (already used by the chat tools)."""
    try:
        from apps.seo_ai.adapters import SitemapAEMAdapter
    except ImportError:
        return set()
    try:
        return {
            _normalize(p.public_url) for p in SitemapAEMAdapter().iter_pages()
            if p.public_url
        }
    except Exception:  # noqa: BLE001
        return set()


def _load_gsc_pages() -> tuple[set[str], set[str]]:
    """GSC web__page.csv URLs. Returns two sets: one for URLs with any
    clicks (high-signal orphans), one for URLs with any impressions
    only (still orphan-worthy but lower priority)."""
    gsc_dir = settings.data_path / "gsc" / "www.bajajlifeinsurance.com"
    page_csv = gsc_dir / "web__page.csv"
    with_clicks: set[str] = set()
    with_impressions: set[str] = set()
    if not page_csv.exists():
        return with_clicks, with_impressions
    with open(page_csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            u = _normalize(row.get("page") or "")
            if not u:
                continue
            try:
                clicks = int(row.get("clicks") or 0)
            except (TypeError, ValueError):
                clicks = 0
            try:
                imps = int(row.get("impressions") or 0)
            except (TypeError, ValueError):
                imps = 0
            if clicks > 0:
                with_clicks.add(u)
            elif imps > 0:
                with_impressions.add(u)
    return with_clicks, with_impressions


def _crawled_seeds() -> set[str]:
    """URLs the crawler saw from a sitemap entry. These are not orphans
    in the crawl graph sense (the sitemap is an external anchor), but
    we still flag them if no internal link points there since they
    behave like orphans for crawl-budget purposes."""
    rows = _load_crawled_rows()
    return {u for u, r in rows.items() if (r.get("from_sitemap") or "") == "1"}


def find_orphans(*, include_aem: bool = True,
                 include_gsc: bool = True,
                 include_crawl_self: bool = True) -> list[OrphanPage]:
    """Compute the orphan set.

    Toggle the three signals to refine the result — operators often
    want "show me orphans with GSC clicks" (the highest-leverage subset)
    or "show me AEM-authored orphans" (production team's responsibility).
    """
    inlinks = _load_inlink_set()
    crawled = _load_crawled_rows()
    aem_urls = _load_aem_urls() if include_aem else set()
    gsc_clicks, gsc_impressions = (
        _load_gsc_pages() if include_gsc else (set(), set())
    )
    crawl_seeds = _crawled_seeds() if include_crawl_self else set()

    candidate_sources: dict[str, str] = {}
    for u in aem_urls:
        candidate_sources.setdefault(u, "aem")
    for u in gsc_clicks:
        candidate_sources.setdefault(u, "gsc")
    for u in gsc_impressions:
        candidate_sources.setdefault(u, "gsc")
    for u in crawl_seeds:
        candidate_sources.setdefault(u, "crawl_self")

    orphans: list[OrphanPage] = []
    for url, src in candidate_sources.items():
        if url in inlinks:
            continue
        row = crawled.get(url) or {}
        try:
            wc = int(row.get("word_count") or 0)
        except (TypeError, ValueError):
            wc = 0
        orphans.append(
            OrphanPage(
                url=url,
                source=src,
                title=(row.get("title") or "").strip(),
                page_type=(row.get("page_type") or "").strip(),
                word_count=wc,
                has_gsc_clicks=url in gsc_clicks,
                has_gsc_impressions=url in gsc_impressions or url in gsc_clicks,
            )
        )

    # Sort: GSC-click orphans first (highest value), then impression-only,
    # then AEM, then crawl_self. Within tier, by word_count desc.
    priority = {"gsc_clicks": 0, "gsc_impressions": 1, "aem": 2, "crawl_self": 3}

    def _key(o: OrphanPage):
        if o.has_gsc_clicks:
            tier = priority["gsc_clicks"]
        elif o.has_gsc_impressions:
            tier = priority["gsc_impressions"]
        elif o.source == "aem":
            tier = priority["aem"]
        else:
            tier = priority["crawl_self"]
        return (tier, -o.word_count)

    orphans.sort(key=_key)
    return orphans


def summary() -> dict:
    """Aggregate counts for the dashboard tile."""
    orphans = find_orphans()
    return {
        "total": len(orphans),
        "with_gsc_clicks": sum(1 for o in orphans if o.has_gsc_clicks),
        "with_gsc_impressions": sum(
            1 for o in orphans if o.has_gsc_impressions and not o.has_gsc_clicks
        ),
        "aem_only": sum(1 for o in orphans if o.source == "aem" and not o.has_gsc_clicks and not o.has_gsc_impressions),
        "crawl_self_only": sum(1 for o in orphans if o.source == "crawl_self"),
    }
