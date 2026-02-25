"""URL/Content Normalization Service.

Handles URL normalization and filtering as defined in
Section 12 (URL Normalization & Filtering) of the Web Crawler Engine spec:

- Remove fragments (#)
- Standardize slashes
- Convert relative to absolute URLs
- Skip non-HTTP links (mailto:, tel:, etc.)
- Deduplicate via content hashing
"""

import re
from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
    parse_qs,
    urlencode,
    quote,
    unquote,
)
from typing import Optional

from apps.common.constants import IGNORED_SCHEMES, RESOURCE_EXTENSIONS, MEDIA_EXTENSIONS
from apps.common.helpers import compute_url_hash


class URLNormalizer:
    """Normalize, validate, and classify URLs for frontier insertion."""

    # Query parameters that are typically tracking/session junk
    JUNK_PARAMS = frozenset([
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "gclsrc", "dclid",
        "mc_cid", "mc_eid",
        "ref", "source",
        "_ga", "_gl",
        "sessionid", "sid", "jsessionid",
    ])

    def __init__(self, base_url: str):
        """Initialize with the base URL of the website being crawled.

        Args:
            base_url: The root domain URL (e.g. https://example.com)
        """
        self.base_url = base_url
        parsed = urlparse(base_url)
        self.base_scheme = parsed.scheme
        self.base_netloc = parsed.netloc
        self.base_domain = self._strip_www(parsed.hostname or "")

    @staticmethod
    def _strip_www(hostname: str) -> str:
        if hostname.startswith("www."):
            return hostname[4:]
        return hostname.lower()

    def normalize(self, url: str, source_url: Optional[str] = None) -> Optional[str]:
        """Normalize a URL for consistent storage and deduplication.

        Returns None if the URL should be filtered out entirely.

        Normalization steps:
        1. Resolve relative → absolute using source_url or base_url
        2. Lowercase scheme and hostname
        3. Remove fragments (#)
        4. Standardize trailing slashes
        5. Remove junk tracking parameters
        6. Remove default ports (80/443)
        7. URL-decode then re-encode path
        """
        if not url or not url.strip():
            return None

        url = url.strip()

        # ── Filter out non-HTTP schemes ────────────────────────
        for scheme in IGNORED_SCHEMES:
            if url.lower().startswith(scheme):
                return None

        # ── Resolve relative URLs ──────────────────────────────
        resolve_base = source_url or self.base_url
        try:
            url = urljoin(resolve_base, url)
        except Exception:
            return None

        # ── Parse ──────────────────────────────────────────────
        try:
            parsed = urlparse(url)
        except Exception:
            return None

        # Only allow http/https
        if parsed.scheme not in ("http", "https"):
            return None

        # ── Lowercase scheme + hostname ────────────────────────
        scheme = parsed.scheme.lower()
        hostname = (parsed.hostname or "").lower()

        # ── Remove default ports ───────────────────────────────
        port = parsed.port
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        netloc = hostname
        if port:
            netloc = f"{hostname}:{port}"

        # ── Normalize path ─────────────────────────────────────
        path = parsed.path
        # Decode then re-encode for consistency
        path = unquote(path)
        path = quote(path, safe="/:@!$&'()*+,;=-._~")
        # Remove trailing slash except for root
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        # Ensure path starts with /
        if not path.startswith("/"):
            path = "/" + path
        # Collapse multiple slashes
        path = re.sub(r"/+", "/", path)

        # ── Remove fragment ────────────────────────────────────
        fragment = ""

        # ── Normalize query params ─────────────────────────────
        query = parsed.query
        if query:
            params = parse_qs(query, keep_blank_values=True)
            # Remove junk tracking parameters
            filtered = {
                k: v for k, v in params.items()
                if k.lower() not in self.JUNK_PARAMS
            }
            # Sort params for deterministic URLs
            query = urlencode(filtered, doseq=True)

        # ── Reconstruct ───────────────────────────────────────
        normalized = urlunparse((scheme, netloc, path, "", query, fragment))
        return normalized

    def is_same_domain(self, url: str) -> bool:
        """Check if a URL belongs to the same domain."""
        try:
            parsed = urlparse(url)
            hostname = self._strip_www(parsed.hostname or "")
            return hostname == self.base_domain or hostname.endswith(f".{self.base_domain}")
        except Exception:
            return False

    def is_internal(self, url: str, include_subdomains: bool = False) -> bool:
        """Determine if a URL is internal to the monitored website."""
        try:
            parsed = urlparse(url)
            hostname = self._strip_www(parsed.hostname or "")
            if hostname == self.base_domain:
                return True
            if include_subdomains and hostname.endswith(f".{self.base_domain}"):
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def classify_url_type(url: str) -> str:
        """Classify a URL as internal, external, media, or resource.

        Based on Section 11 (Link Extraction Engine) of the spec.
        """
        parsed = urlparse(url)
        path_lower = parsed.path.lower()

        for ext in RESOURCE_EXTENSIONS:
            if path_lower.endswith(ext):
                return "resource"

        for ext in MEDIA_EXTENSIONS:
            if path_lower.endswith(ext):
                return "media"

        # Internal/External classification is domain-based,
        # handled by the caller using is_internal()
        return "page"

    @staticmethod
    def get_url_hash(url: str) -> str:
        """Get the deduplication hash for a normalized URL."""
        return compute_url_hash(url)

    @staticmethod
    def has_excessive_params(url: str, threshold: int = 5) -> bool:
        """Detect query-heavy junk URLs (infinite filter/pagination traps)."""
        try:
            parsed = urlparse(url)
            if not parsed.query:
                return False
            params = parse_qs(parsed.query)
            return len(params) > threshold
        except Exception:
            return False
