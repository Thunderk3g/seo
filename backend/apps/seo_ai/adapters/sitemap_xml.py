"""Sitemap.xml discovery + URL counting for any domain.

Used by the competitor-gap feature to surface "they have 12 000
indexable URLs, we have 600" — the most basic measure of site
breadth.

Discovery order per the sitemaps.org spec:

  1. ``robots.txt`` ``Sitemap:`` directives (canonical, RFC-style).
  2. ``/sitemap.xml`` at the root (default WP / framework convention).
  3. ``/sitemap_index.xml`` (Yoast SEO and several other plugins).

A ``<sitemapindex>`` element nests sub-sitemaps; we follow up to 3
levels deep and cap at 20 sub-sitemaps so a hostile or oversized
index can't blow up memory or block the crawl behind it. Inside each
sub-sitemap we count ``<url>`` elements but do NOT store the URLs —
the scoring step only needs the total count.

Parsing: stdlib ``xml.etree.ElementTree`` (no new deps). It tolerates
the default sitemap-protocol namespace (``http://www.sitemaps.org/
schemas/sitemap/0.9``) which Python's ElementTree handles
out-of-the-box via the ``{namespace}tag`` qualifier.

Cache: file-backed JSON at ``{SEO_AI.data_dir}/_sitemap_cache/`` with
the same 7-day TTL as the competitor HTML cache. Cache key is the
bare hostname so subdomain shifts re-trigger discovery.

SSL / UA handling mirrors ``CompetitorCrawler``: we honour
``COMPETITOR_SSL_VERIFY`` and the same browser-like User-Agent so we
don't get 403'd by Cloudflare on the same hosts the competitor
crawler already reaches.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import requests
from django.conf import settings

from .competitor_crawler import _resolve_competitor_ssl_verify

logger = logging.getLogger("seo.ai.adapters.sitemap_xml")

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
# Bumped from 20 → 50 so big rivals (HDFC Life has ~30 sub-sitemaps,
# Tata AIA has 25+) get full coverage. Hard cap remains so a malicious
# sitemap-index loop can't blow up memory.
_MAX_SUBSITEMAPS = 50
_MAX_DEPTH = 3
# Hard ceiling on how many URLs discover_urls() will return per domain.
# Real rival sitemaps top out around 15k-20k. 30k gives headroom while
# capping worst-case memory at ~6 MB of strings per call.
_MAX_URLS_RETURNED = 30_000

# Default sitemap paths to try when robots.txt has no Sitemap: directive.
# Ordered by frequency in the wild — most common CMS / SEO-plugin
# conventions first.
_DEFAULT_SITEMAP_PATHS = (
    "/sitemap.xml",                 # default everywhere
    "/sitemap_index.xml",           # Yoast SEO
    "/wp-sitemap.xml",              # WordPress 5.5+ core (replaces Yoast on new installs)
    "/sitemap1.xml",                # Yoast paginated index entry
    "/sitemap.xml.gz",              # gzip-compressed sitemap (some CDNs)
    "/post-sitemap.xml",            # WordPress per-content-type
    "/page-sitemap.xml",            # WordPress per-content-type
    "/news-sitemap.xml",            # Google News
    "/sitemap-index.xml",           # alternate spelling
    "/sitemaps/sitemap.xml",        # subdir convention
    "/sitemap/sitemap.xml",         # subdir convention
)


def _host_variants(bare_host: str) -> list[str]:
    """Both ``www.`` and apex forms of a host, www first.

    Many insurers (Kotak, PNB MetLife) serve robots.txt / sitemap.xml ONLY
    on ``www.`` — the apex returns an HTML redirect page that fails XML
    parsing. Trying both forms (www first, the more common host for these
    CMSes) is the difference between 0 URLs and the full sitemap.
    """
    bare = re.sub(r"^www\d?\.", "", bare_host)
    return [f"www.{bare}", bare]


def _is_sitemap_loc(loc: str) -> bool:
    """True when a <loc> points at another sitemap file (``.xml`` /
    ``.xml.gz``) rather than a content page. HDFC Life ships a
    non-standard index — a ``<urlset>`` whose <loc>s are ``.xml``
    sub-sitemaps — so we must recurse into these, not treat them as pages.
    """
    p = loc.lower().split("?", 1)[0].split("#", 1)[0]
    return p.endswith(".xml") or p.endswith(".xml.gz")


def _default_sitemap_candidates(bare_host: str) -> list[str]:
    """Build the fallback sitemap-URL list for one host (no robots.txt hit).
    Tries every known CMS / SEO-plugin path on BOTH the ``www.`` and apex
    host before giving up — handles WP / Yoast / Drupal / handcrafted
    sitemap conventions, and hosts that only answer on one of www/apex.
    """
    return [
        f"https://{h}{p}"
        for h in _host_variants(bare_host)
        for p in _DEFAULT_SITEMAP_PATHS
    ]


@dataclass
class SitemapSummary:
    """Result of discovering one domain's sitemap(s)."""

    domain: str
    total_url_count: int = 0
    sitemap_urls: list[str] = field(default_factory=list)  # all sitemap files visited
    discovered_via: str = ""    # "robots.txt", "/sitemap.xml", "/sitemap_index.xml", or ""
    fetched_at: str = ""
    error: str = ""
    capped: bool = False        # True when we hit _MAX_SUBSITEMAPS


class SitemapXMLAdapter:
    """Fetch + count URLs in any public sitemap.xml.

    Designed to be idempotent and silent on failure — the consumer
    (competitor agent) treats a missing sitemap as a `0` count
    rather than a hard error.
    """

    def __init__(
        self,
        *,
        timeout_sec: int | None = None,
        user_agent: str | None = None,
        cache_ttl_seconds: int | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        cfg = settings.COMPETITOR
        self.timeout_sec = timeout_sec or cfg["timeout_sec"]
        self.user_agent = user_agent or cfg["user_agent"]
        self.cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else cfg["cache_ttl_seconds"]
        )
        self.cache_dir = (
            cache_dir
            if cache_dir
            else settings.SEO_AI["data_dir"] / "_sitemap_cache"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._verify = _resolve_competitor_ssl_verify(cfg.get("ssl_verify", ""))

        self._session = requests.Session()
        self._session.headers.update(
            {"User-Agent": self.user_agent, "Accept": "application/xml, text/xml, */*"}
        )
        # Optional proxy (default ""): lets sitemap discovery reach
        # Akamai/Cloudflare-blocked rivals through the same residential /
        # scraper-API endpoint the competitor crawler uses. No-op empty.
        _proxy = (cfg.get("proxy_url") or "").strip()
        if _proxy:
            self._session.proxies.update({"http": _proxy, "https": _proxy})

    # ── public API ───────────────────────────────────────────────────

    def discover(self, domain: str) -> SitemapSummary:
        """Return a count of indexable URLs declared by ``domain``'s
        sitemap(s). Network failures, malformed XML, and missing
        sitemaps all return a ``SitemapSummary`` with ``total_url_count=0``
        rather than raising."""
        bare = _normalise_domain(domain)
        cached = self._cache_read(bare)
        if cached is not None:
            return cached

        summary = SitemapSummary(
            domain=bare,
            fetched_at=_now_iso(),
        )

        # Discovery chain — robots.txt directive first (canonical), then
        # well-known framework paths. Order matters: try the most likely
        # locations first so we don't burn round-trips on dead URLs.
        sitemap_candidates = self._candidates_from_robots(bare)
        if sitemap_candidates:
            summary.discovered_via = "robots.txt"
        else:
            sitemap_candidates = _default_sitemap_candidates(bare)
            summary.discovered_via = "default-paths"

        seen: set[str] = set()
        for first in sitemap_candidates:
            if first in seen:
                continue
            ok = self._walk(first, summary, seen=seen, depth=0)
            if ok and summary.total_url_count > 0:
                break

        self._cache_write(bare, summary)
        return summary

    def discover_urls(
        self, domain: str, *, limit: int | None = None
    ) -> list[str]:
        """Return the full URL list declared by ``domain``'s sitemap(s).

        Walks every sub-sitemap up to ``_MAX_SUBSITEMAPS`` (50) and
        collects every ``<loc>`` URL. Returns up to ``limit`` URLs
        (default: ``_MAX_URLS_RETURNED`` = 30k). Order: sub-sitemaps
        processed left-to-right as they appear in the index, URLs
        within each sub-sitemap in document order.

        On failure (network error, malformed XML, no sitemap at all)
        returns an empty list — never raises. Calling code can fall
        back to homepage-only crawling if needed.

        NOT cached on its own — re-reads from the disk-cached summary
        of sub-sitemap URLs but always re-fetches the actual <loc>
        values. If you need cached URLs across runs, persist them in
        the caller's data store.
        """
        bare = _normalise_domain(domain)
        max_urls = limit or _MAX_URLS_RETURNED

        # Reuse the same discovery flow to populate the sub-sitemap
        # list, then read URLs out of each one. We don't piggyback on
        # discover()'s SitemapSummary because that one only counts.
        sitemap_candidates = self._candidates_from_robots(bare)
        if not sitemap_candidates:
            sitemap_candidates = _default_sitemap_candidates(bare)

        urls: list[str] = []
        seen_sitemaps: set[str] = set()
        # First, build the full list of leaf sitemaps (the ones with
        # <url> entries, not <sitemap> entries). This handles nested
        # sitemap-index documents.
        leaf_sitemaps: list[str] = []
        self._collect_leaf_sitemaps(
            sitemap_candidates, leaf_sitemaps, seen_sitemaps, depth=0
        )

        # Now pull <loc> from each leaf sitemap until we hit the cap.
        for sm_url in leaf_sitemaps:
            if len(urls) >= max_urls:
                break
            for loc in self._iter_locs(sm_url):
                if not loc:
                    continue
                urls.append(loc.strip())
                if len(urls) >= max_urls:
                    break

        return urls

    # ── internals ────────────────────────────────────────────────────

    def _candidates_from_robots(self, host: str) -> list[str]:
        """Collect ``Sitemap:`` directives from robots.txt, trying BOTH the
        ``www.`` and apex host. Some insurers only declare the sitemap on
        one of the two — we union both and de-dupe."""
        out: list[str] = []
        seen: set[str] = set()
        for h in _host_variants(host):
            try:
                resp = self._session.get(
                    f"https://{h}/robots.txt",
                    timeout=self.timeout_sec,
                    verify=self._verify,
                )
            except requests.RequestException as exc:
                logger.info("robots.txt fetch %s failed: %s", h, exc)
                continue
            if resp.status_code != 200:
                continue
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    u = line.split(":", 1)[1].strip()
                    if u and u not in seen:
                        seen.add(u)
                        out.append(u)
        return out

    def _walk(
        self,
        sitemap_url: str,
        summary: SitemapSummary,
        *,
        seen: set[str],
        depth: int,
    ) -> bool:
        """Fetch one sitemap and either count its <url> entries or
        recurse into its <sitemap> entries. Returns True on a valid
        XML response (200 + parseable), False otherwise.
        """
        if sitemap_url in seen:
            return False
        seen.add(sitemap_url)
        summary.sitemap_urls.append(sitemap_url)
        if len(summary.sitemap_urls) >= _MAX_SUBSITEMAPS:
            summary.capped = True
            return False
        if depth > _MAX_DEPTH:
            return False

        body = self._fetch_xml(sitemap_url)
        if body is None:
            return False
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            logger.info("sitemap xml parse fail %s: %s", sitemap_url, exc)
            return False

        tag = _strip_ns(root.tag)
        if tag == "sitemapindex":
            for child in root:
                if _strip_ns(child.tag) != "sitemap":
                    continue
                loc = child.findtext(f"{_SITEMAP_NS}loc") or child.findtext("loc")
                if loc:
                    self._walk(loc.strip(), summary, seen=seen, depth=depth + 1)
            return True

        if tag == "urlset":
            locs = []
            for child in root:
                if _strip_ns(child.tag) != "url":
                    continue
                loc = child.findtext(f"{_SITEMAP_NS}loc") or child.findtext("loc")
                locs.append((loc or "").strip())
            xml_locs = [l for l in locs if l and _is_sitemap_loc(l)]
            # Non-standard index (HDFC Life): a <urlset> of .xml sub-sitemaps.
            if xml_locs and len(xml_locs) >= max(1, len(locs) // 2):
                for x in xml_locs:
                    self._walk(x, summary, seen=seen, depth=depth + 1)
                return True
            summary.total_url_count += sum(
                1 for l in locs if l and not _is_sitemap_loc(l)
            )
            return True

        # Unknown root tag — try a defensive count of any <url>-like leaves.
        logger.info("sitemap unknown root tag %s on %s", tag, sitemap_url)
        return False

    def _collect_leaf_sitemaps(
        self,
        candidates: list[str],
        out: list[str],
        seen: set[str],
        *,
        depth: int,
    ) -> None:
        """Walk sitemap-index docs recursively, accumulating leaf
        (urlset-bearing) sitemap URLs into ``out``. Bounds via the same
        _MAX_SUBSITEMAPS / _MAX_DEPTH guards as _walk."""
        if depth > _MAX_DEPTH:
            return
        for sm_url in candidates:
            if len(out) >= _MAX_SUBSITEMAPS:
                return
            if sm_url in seen:
                continue
            seen.add(sm_url)
            body = self._fetch_xml(sm_url)
            if body is None:
                continue
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                continue
            tag = _strip_ns(root.tag)
            if tag == "sitemapindex":
                nested = []
                for child in root:
                    if _strip_ns(child.tag) != "sitemap":
                        continue
                    loc = child.findtext(f"{_SITEMAP_NS}loc") or child.findtext("loc")
                    if loc:
                        nested.append(loc.strip())
                self._collect_leaf_sitemaps(nested, out, seen, depth=depth + 1)
            elif tag == "urlset":
                # Standard leaf: a <urlset> of content pages. BUT some
                # sites (HDFC Life) ship a non-standard index — a <urlset>
                # whose <loc>s point at .xml sub-sitemaps. Detect that and
                # recurse instead of recording 6 ".xml" URLs as pages.
                locs = []
                for child in root:
                    if _strip_ns(child.tag) != "url":
                        continue
                    loc = child.findtext(f"{_SITEMAP_NS}loc") or child.findtext("loc")
                    if loc:
                        locs.append(loc.strip())
                xml_locs = [l for l in locs if _is_sitemap_loc(l)]
                if xml_locs and len(xml_locs) >= max(1, len(locs) // 2):
                    self._collect_leaf_sitemaps(
                        xml_locs, out, seen, depth=depth + 1
                    )
                else:
                    out.append(sm_url)

    def _iter_locs(self, sitemap_url: str):
        """Yield <loc> URLs from a single leaf sitemap. Returns nothing
        on fetch / parse failure."""
        body = self._fetch_xml(sitemap_url)
        if body is None:
            return
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return
        if _strip_ns(root.tag) != "urlset":
            return
        for url_el in root.iter(f"{_SITEMAP_NS}url"):
            loc = url_el.findtext(f"{_SITEMAP_NS}loc")
            if loc and not _is_sitemap_loc(loc.strip()):
                yield loc
        # Defensive: some sitemaps lack the namespace declaration.
        for url_el in root.iter("url"):
            loc = url_el.findtext("loc")
            if loc and not _is_sitemap_loc(loc.strip()):
                yield loc

    def _fetch_xml(self, url: str) -> bytes | None:
        try:
            resp = self._session.get(
                url,
                timeout=self.timeout_sec,
                verify=self._verify,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            logger.info("sitemap fetch %s failed: %s", url, exc)
            return None
        if resp.status_code != 200:
            return None
        content = resp.content
        # Transparent gzip — some hosts serve sitemap.xml.gz even from
        # the .xml endpoint (Yoast does this on certain configs).
        if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
            try:
                content = gzip.decompress(content)
            except OSError:
                logger.info("sitemap gzip decompress failed for %s", url)
                return None
        return content

    # ── disk cache ──────────────────────────────────────────────────

    def _cache_path(self, bare_host: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", bare_host)
        return self.cache_dir / f"sitemap__{safe}.json"

    def _cache_read(self, bare_host: str) -> SitemapSummary | None:
        path = self._cache_path(bare_host)
        if not path.exists():
            return None
        try:
            if (time.time() - path.stat().st_mtime) > self.cache_ttl_seconds:
                return None
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return SitemapSummary(**data)
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def _cache_write(self, bare_host: str, summary: SitemapSummary) -> None:
        path = self._cache_path(bare_host)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(summary.__dict__, f, default=str)
        except OSError as exc:
            logger.warning("sitemap cache write failed for %s: %s", bare_host, exc)


# ── helpers ──────────────────────────────────────────────────────────────


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _normalise_domain(domain: str) -> str:
    """Strip scheme, path, port, and a single ``www.`` prefix."""
    bare = domain.strip().lower()
    if "://" in bare:
        bare = bare.split("://", 1)[1]
    bare = bare.split("/", 1)[0].split(":", 1)[0]
    return re.sub(r"^www\d?\.", "", bare)


def _now_iso() -> str:
    from datetime import datetime, timezone as tz

    return datetime.now(tz.utc).isoformat()
