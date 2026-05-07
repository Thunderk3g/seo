"""Issue derivation service for the Lattice SEO crawler dashboard.

Derives the 12-category issue list defined by the design spec
(.design-ref/project/data.js lines 204-260) from the persisted
``Page`` and ``Link`` rows of a ``CrawlSession``.

The taxonomy and severities mirror the design verbatim. This module
is intentionally self-contained (no view, serializer, or URL imports)
so it can be unit-tested in isolation and re-used by future export /
notification jobs.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable
from urllib.parse import urlsplit

from django.db.models import F

from apps.crawl_sessions.models import CrawlSession, Link, Page


# ─────────────────────────────────────────────────────────────
# HTML detection
# ─────────────────────────────────────────────────────────────
# URL path extensions that are NOT considered HTML for issue
# matching. Anything else (no extension, .html, .htm, etc.) is
# treated as HTML — matching the design's `contentType === 'html'`
# semantic intent on a backend that does not store content type.
_NON_HTML_EXTS: tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".pdf", ".xml", ".txt", ".json",
    ".woff", ".woff2", ".ttf", ".otf",
    ".mp4", ".webm", ".mp3", ".zip", ".gz",
)


def _is_html_page(page: Page) -> bool:
    """Return ``True`` when *page* should be treated as HTML.

    Strips any query string (via ``urlsplit().path``) and checks the
    lower-cased path against the non-HTML extension list. URLs without
    an extension (e.g. ``/about``, ``/``) are treated as HTML.
    """
    path = urlsplit(page.url or "").path.lower()
    return not path.endswith(_NON_HTML_EXTS)


# ─────────────────────────────────────────────────────────────
# Taxonomy — 12 categories, in canonical order.
# Descriptions are copied verbatim from data.js (lines 207-241).
# ─────────────────────────────────────────────────────────────
_TAXONOMY: list[dict] = [
    {
        "id": "broken-4xx",
        "name": "Broken links (4xx)",
        "severity": "error",
        "description": (
            "URLs returning a 4xx response. These hurt crawl efficiency "
            "and user trust."
        ),
    },
    {
        "id": "server-5xx",
        "name": "Server errors (5xx)",
        "severity": "error",
        "description": (
            "URLs returning a 5xx response — investigate before they cascade."
        ),
    },
    {
        "id": "missing-title",
        "name": "Missing title",
        "severity": "error",
        "description": (
            "Pages without a <title> tag. Critical for ranking and SERP "
            "appearance."
        ),
    },
    {
        "id": "missing-meta",
        "name": "Missing meta description",
        "severity": "warning",
        "description": (
            "Pages without a meta description. Search engines may "
            "auto-generate a snippet."
        ),
    },
    {
        "id": "duplicate-title",
        "name": "Duplicate titles",
        "severity": "warning",
        "description": "More than one page sharing the same <title>.",
    },
    {
        "id": "long-title",
        "name": "Title too long",
        "severity": "notice",
        "description": (
            "Titles over 60 characters may be truncated in search results."
        ),
    },
    {
        "id": "short-meta",
        "name": "Meta description too short",
        "severity": "notice",
        "description": (
            "Meta descriptions under 70 characters may be flagged as thin."
        ),
    },
    {
        "id": "redirect-3xx",
        "name": "Redirects (3xx)",
        "severity": "notice",
        "description": (
            "URLs redirecting elsewhere. Long chains hurt crawl budget."
        ),
    },
    {
        "id": "slow-response",
        "name": "Slow response (>1s)",
        "severity": "warning",
        "description": "URLs taking longer than a second to respond.",
    },
    {
        "id": "orphan-pages",
        "name": "Orphan pages",
        "severity": "warning",
        "description": "Reachable pages with zero internal inlinks.",
    },
    {
        "id": "deep-pages",
        "name": "Pages at depth ≥ 5",
        "severity": "notice",
        "description": "Pages buried more than 5 clicks from the homepage.",
    },
    {
        "id": "large-pages",
        "name": "Pages over 200 KB",
        "severity": "notice",
        "description": "HTML payloads larger than 200 KB. Consider trimming.",
    },
]

_TAXONOMY_BY_ID: dict[str, dict] = {entry["id"]: entry for entry in _TAXONOMY}

# Field set fetched from Page for issue derivation. Centralised so
# both ``derive_issues`` and ``get_issue_detail`` stay in sync.
_PAGE_FIELDS: tuple[str, ...] = (
    "id",
    "url",
    "http_status_code",
    "title",
    "meta_description",
    "crawl_depth",
    "load_time_ms",
    "content_size_bytes",
)

# Bytes threshold for "large-pages" (200 KB).
_LARGE_PAGE_BYTES = 200 * 1024


# ─────────────────────────────────────────────────────────────
# Per-page predicates (single-page; safe against NULL status).
# ─────────────────────────────────────────────────────────────
def _is_broken_4xx(page: Page) -> bool:
    s = page.http_status_code
    return s is not None and 400 <= s < 500


def _is_server_5xx(page: Page) -> bool:
    s = page.http_status_code
    return s is not None and s >= 500


def _is_redirect_3xx(page: Page) -> bool:
    s = page.http_status_code
    return s is not None and 300 <= s < 400


def _is_missing_title(page: Page) -> bool:
    return (
        _is_html_page(page)
        and page.http_status_code == 200
        and not page.title
    )


def _is_missing_meta(page: Page) -> bool:
    return (
        _is_html_page(page)
        and page.http_status_code == 200
        and not page.meta_description
    )


def _is_long_title(page: Page) -> bool:
    return bool(page.title) and len(page.title) > 60


def _is_short_meta(page: Page) -> bool:
    meta = page.meta_description
    return bool(meta) and 0 < len(meta) < 70


def _is_slow_response(page: Page) -> bool:
    return page.load_time_ms is not None and page.load_time_ms > 1000


def _is_deep_page(page: Page) -> bool:
    return page.crawl_depth is not None and page.crawl_depth >= 5


def _is_large_page(page: Page) -> bool:
    return _is_html_page(page) and page.content_size_bytes > _LARGE_PAGE_BYTES


def _is_reachable_html(page: Page) -> bool:
    """Used as the base predicate for orphan-pages detection."""
    s = page.http_status_code
    return _is_html_page(page) and s is not None and s < 400


# ─────────────────────────────────────────────────────────────
# Bulk helpers (for state requiring all pages in the session).
# ─────────────────────────────────────────────────────────────
def _build_duplicate_title_ids(pages: Iterable[Page]) -> set:
    """Return ids of html-200 pages whose title is shared by another page."""
    title_map: dict[str, list] = defaultdict(list)
    for p in pages:
        if (
            _is_html_page(p)
            and p.http_status_code == 200
            and p.title
        ):
            title_map[p.title].append(p.id)
    dup_ids: set = set()
    for ids in title_map.values():
        if len(ids) >= 2:
            dup_ids.update(ids)
    return dup_ids


def _build_inbound_target_set(session: CrawlSession) -> set:
    """Set of target URLs that have at least one non-self internal inlink."""
    qs = (
        Link.objects.filter(crawl_session=session, link_type="internal")
        .exclude(source_url=F("target_url"))
        .values_list("target_url", flat=True)
    )
    return set(qs)


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
class IssueService:
    """Derive the 12-category issue summary for a crawl session.

    All methods are static — no instance state. Intentionally mirrors
    the shape of ``SnapshotService`` for consistency.
    """

    @staticmethod
    def derive_issues(session: CrawlSession) -> list[dict]:
        """Return a list of all 12 issue summaries for *session*.

        Each item has the shape::

            {
                "id": str,            # e.g. "broken-4xx"
                "name": str,
                "severity": "error" | "warning" | "notice",
                "description": str,
                "count": int,         # number of affected URLs
            }

        All 12 entries are always returned (even with ``count == 0``)
        in the canonical order defined by ``_TAXONOMY``.
        """
        pages = list(
            Page.objects.filter(crawl_session=session).only(*_PAGE_FIELDS)
        )
        dup_title_ids = _build_duplicate_title_ids(pages)
        inbound_targets = _build_inbound_target_set(session)

        counts: dict[str, int] = {entry["id"]: 0 for entry in _TAXONOMY}

        for p in pages:
            if _is_broken_4xx(p):
                counts["broken-4xx"] += 1
            if _is_server_5xx(p):
                counts["server-5xx"] += 1
            if _is_redirect_3xx(p):
                counts["redirect-3xx"] += 1
            if _is_missing_title(p):
                counts["missing-title"] += 1
            if _is_missing_meta(p):
                counts["missing-meta"] += 1
            if _is_long_title(p):
                counts["long-title"] += 1
            if _is_short_meta(p):
                counts["short-meta"] += 1
            if _is_slow_response(p):
                counts["slow-response"] += 1
            if _is_deep_page(p):
                counts["deep-pages"] += 1
            if _is_large_page(p):
                counts["large-pages"] += 1
            if p.id in dup_title_ids:
                counts["duplicate-title"] += 1
            if _is_reachable_html(p) and p.url not in inbound_targets:
                counts["orphan-pages"] += 1

        return [
            {**entry, "count": counts[entry["id"]]}
            for entry in _TAXONOMY
        ]

    @staticmethod
    def get_issue_detail(
        session: CrawlSession,
        issue_id: str,
        limit: int = 200,
    ) -> dict:
        """Return detailed info for a single issue, including affected URLs.

        Raises:
            ValueError: when ``issue_id`` is not one of the 12 known IDs.

        Returns a dict with the same metadata as ``derive_issues`` plus an
        ``affected_urls`` list capped at ``limit`` entries.
        """
        if issue_id not in _TAXONOMY_BY_ID:
            raise ValueError(f"Unknown issue id: {issue_id!r}")

        meta = _TAXONOMY_BY_ID[issue_id]
        pages = list(
            Page.objects.filter(crawl_session=session).only(*_PAGE_FIELDS)
        )

        # Build any state required by predicates that need a global view.
        if issue_id == "duplicate-title":
            dup_ids = _build_duplicate_title_ids(pages)
            matched = [p for p in pages if p.id in dup_ids]
        elif issue_id == "orphan-pages":
            inbound = _build_inbound_target_set(session)
            matched = [
                p for p in pages
                if _is_reachable_html(p) and p.url not in inbound
            ]
        else:
            predicate = _SINGLE_PAGE_PREDICATES[issue_id]
            matched = [p for p in pages if predicate(p)]

        affected = [
            {
                "url": p.url,
                "http_status_code": p.http_status_code,
                "title": p.title,
                "crawl_depth": p.crawl_depth,
                "load_time_ms": p.load_time_ms,
            }
            for p in matched[:limit]
        ]

        return {
            **meta,
            "count": len(matched),
            "affected_urls": affected,
        }


# Single-page predicate registry (state-free issue ids only).
_SINGLE_PAGE_PREDICATES = {
    "broken-4xx": _is_broken_4xx,
    "server-5xx": _is_server_5xx,
    "redirect-3xx": _is_redirect_3xx,
    "missing-title": _is_missing_title,
    "missing-meta": _is_missing_meta,
    "long-title": _is_long_title,
    "short-meta": _is_short_meta,
    "slow-response": _is_slow_response,
    "deep-pages": _is_deep_page,
    "large-pages": _is_large_page,
}
