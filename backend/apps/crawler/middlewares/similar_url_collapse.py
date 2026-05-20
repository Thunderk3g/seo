"""Similar-URL collapse middleware — Phase 3e.

Imported from the Katana SEO/security crawler's `-fsu` flag pattern.

Problem: faceted-search and paginated catalogs blow up the URL
frontier into thousands of near-identical URLs that contribute zero
new SEO signal. Example from the Bajaj branch locator:

  https://branch.bajajlifeinsurance.com/storepages/...id=123059
  https://branch.bajajlifeinsurance.com/storepages/...id=123060
  https://branch.bajajlifeinsurance.com/storepages/...id=123061
  ... (10,000+ such URLs)

Each is HTTP 403 in our data, but Scrapy would still queue every one,
burn the crawl budget, and dilute the audit catalog's signal-to-noise.

This middleware sits IN the Scrapy spider middleware chain (NOT the
downloader chain) so it intercepts ``Request`` objects before the
dupefilter sees them. For each request:

  1. Canonicalize the URL by replacing high-cardinality path segments
     (pure numeric, UUID, hex hash) with a placeholder token.
  2. Track each canonical form in an in-memory set keyed by (host,
     canonical_path).
  3. Once we've seen ``MAX_PER_PATTERN`` URLs for a canonical form
     (default 50), subsequent requests with the same canonical are
     dropped silently and counted in stats.

Why 50: enough to sample a paginated catalog for SEO signals (titles,
schema coverage, content depth) without crawling every variant. Audit
detectors only need ~20-30 samples to fire reliably.

Configurable via:

  * ``SIMILAR_URL_COLLAPSE_ENABLED`` env / setting (default True)
  * ``SIMILAR_URL_MAX_PER_PATTERN`` env / setting (default 50)
"""
from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from urllib.parse import urlparse

from scrapy.exceptions import IgnoreRequest

log = logging.getLogger("apps.crawler.middlewares.similar_url_collapse")

MAX_PER_PATTERN = int(os.environ.get("CRAWLER_SIMILAR_URL_MAX_PER_PATTERN", "50"))

# Segment classifiers, ordered: pure numeric first (most common), then
# UUID (8-4-4-4-12 hex), then long hex / base32 hashes.
_PURE_NUMERIC = re.compile(r"^\d+$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_LONG_HEX = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
_BASE32_LIKE = re.compile(r"^[A-Z2-7]{12,}$")
# Base64url-encoded payloads (>=12 chars of [A-Za-z0-9_-]). Generated
# by our own per-URL routes; collapsing them is harmless.
_BASE64URL = re.compile(r"^[A-Za-z0-9_\-]{16,}$")


def _classify_segment(seg: str) -> str:
    """Return a placeholder token if segment looks generated, else the
    segment as-is."""
    if not seg:
        return seg
    if _PURE_NUMERIC.match(seg):
        return "{id}"
    if _UUID.match(seg):
        return "{uuid}"
    if _LONG_HEX.match(seg):
        return "{hex}"
    if _BASE32_LIKE.match(seg):
        return "{b32}"
    if _BASE64URL.match(seg):
        return "{b64}"
    return seg


def canonical_form(url: str) -> str:
    """Return the canonical pattern for a URL. Same input → same
    output, regardless of which numeric/UUID variant is passed.

    >>> canonical_form("https://example.com/product/12345")
    'example.com:/product/{id}'
    >>> canonical_form("https://example.com/product/67890")
    'example.com:/product/{id}'
    """
    try:
        p = urlparse(url)
    except (ValueError, AttributeError):
        return url or ""
    host = (p.netloc or "").lower()
    segments = (p.path or "").split("/")
    placeholders = [_classify_segment(s) for s in segments]
    return f"{host}:{'/'.join(placeholders)}"


class SimilarUrlCollapseMiddleware:
    """Spider middleware. Lives in SPIDER_MIDDLEWARES so it intercepts
    Request objects yielded by the spider before they reach the
    downloader / dupefilter."""

    def __init__(self, *, enabled: bool = True,
                 max_per_pattern: int = MAX_PER_PATTERN) -> None:
        self.enabled = enabled
        self.max_per_pattern = max_per_pattern
        # canonical_form -> count
        self._counts: defaultdict[str, int] = defaultdict(int)
        self._dropped = 0

    @classmethod
    def from_crawler(cls, crawler):
        enabled = crawler.settings.getbool(
            "SIMILAR_URL_COLLAPSE_ENABLED", True,
        )
        max_per_pattern = crawler.settings.getint(
            "SIMILAR_URL_MAX_PER_PATTERN", MAX_PER_PATTERN,
        )
        return cls(enabled=enabled, max_per_pattern=max_per_pattern)

    def process_spider_output(self, response, result, spider):
        """Scrapy contract: filter the items + requests the spider's
        parse callback yielded. Drop requests whose canonical form has
        already been seen too many times."""
        if not self.enabled:
            return result

        def _filter():
            for item_or_request in result:
                if not hasattr(item_or_request, "url"):
                    # Plain item — yield through.
                    yield item_or_request
                    continue
                request = item_or_request
                key = canonical_form(request.url)
                self._counts[key] += 1
                if self._counts[key] > self.max_per_pattern:
                    self._dropped += 1
                    if self._dropped % 100 == 1:
                        # Log every 100th drop so the operator sees
                        # the pattern without log spam.
                        log.info(
                            "similar_url_collapse: dropped %d total (latest pattern=%s, count=%d)",
                            self._dropped, key, self._counts[key],
                        )
                    continue
                yield request

        return _filter()

    def process_start_requests(self, start_requests, spider):
        """Same filter on the initial seed list — sitemap-harvested URLs
        often include paginated archives."""
        if not self.enabled:
            return start_requests
        for request in start_requests:
            key = canonical_form(request.url)
            self._counts[key] += 1
            if self._counts[key] > self.max_per_pattern:
                self._dropped += 1
                continue
            yield request
