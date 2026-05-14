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
_MAX_SUBSITEMAPS = 20
_MAX_DEPTH = 3


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

        # 1. robots.txt
        sitemap_candidates = self._candidates_from_robots(bare)
        if sitemap_candidates:
            summary.discovered_via = "robots.txt"
        else:
            sitemap_candidates = [
                f"https://{bare}/sitemap.xml",
                f"https://{bare}/sitemap_index.xml",
            ]
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

    # ── internals ────────────────────────────────────────────────────

    def _candidates_from_robots(self, host: str) -> list[str]:
        try:
            resp = self._session.get(
                f"https://{host}/robots.txt",
                timeout=self.timeout_sec,
                verify=self._verify,
            )
        except requests.RequestException as exc:
            logger.info("robots.txt fetch %s failed: %s", host, exc)
            return []
        if resp.status_code != 200:
            return []
        out: list[str] = []
        for line in resp.text.splitlines():
            if line.lower().startswith("sitemap:"):
                out.append(line.split(":", 1)[1].strip())
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
            count = sum(
                1 for child in root if _strip_ns(child.tag) == "url"
            )
            summary.total_url_count += count
            return True

        # Unknown root tag — try a defensive count of any <url>-like leaves.
        logger.info("sitemap unknown root tag %s on %s", tag, sitemap_url)
        return False

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
