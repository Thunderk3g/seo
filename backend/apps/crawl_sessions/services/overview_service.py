"""Dashboard overview service for the Lattice SEO crawler.

Powers the Dashboard's KPI strip, SEO Health gauge, and System Metrics
card via a single one-shot endpoint. Mirrors the static-method shape of
the surrounding services (``SnapshotService``, ``IssueService``,
``AnalyticsService``).

This module deliberately re-uses existing CrawlSession aggregate columns
where they exist (``total_urls_discovered``, ``total_urls_crawled``,
``total_urls_failed``, ``avg_response_time_ms``, ``max_depth_reached``).
Only the extras the design calls for — p95 response time, median depth,
distinct pages-with-issues, and the synthesized health score — are
computed here.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable
from urllib.parse import urlsplit

from django.db.models import F

from apps.crawl_sessions.models import CrawlSession, Link, Page


# ─────────────────────────────────────────────────────────────
# HTML detection — duplicated locally rather than importing from
# IssueService, to keep this service self-contained for unit testing
# and avoid circular-import surprises.
# ─────────────────────────────────────────────────────────────
_NON_HTML_EXTS: tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".pdf", ".xml", ".txt", ".json",
    ".woff", ".woff2", ".ttf", ".otf",
    ".mp4", ".webm", ".mp3", ".zip", ".gz",
)


def _is_html_page(page: Page) -> bool:
    path = urlsplit(page.url or "").path.lower()
    return not path.endswith(_NON_HTML_EXTS)


# Bytes threshold for "large-pages" (200 KB) — must stay in sync with
# IssueService._LARGE_PAGE_BYTES.
_LARGE_PAGE_BYTES = 200 * 1024


# ─────────────────────────────────────────────────────────────
# Per-page predicates — the ones that operate on a single Page row
# without needing a global view (mirror of IssueService's set).
# ─────────────────────────────────────────────────────────────
def _has_any_single_page_issue(page: Page) -> bool:
    """Return ``True`` when this page is hit by any single-page issue.

    Mirrors the issue predicates in ``IssueService`` for the 10 categories
    that don't require a global view (``duplicate-title`` and
    ``orphan-pages`` are handled separately in ``_pages_with_issues``).
    """
    s = page.http_status_code
    is_html = _is_html_page(page)

    # broken-4xx / server-5xx / redirect-3xx
    if s is not None and s >= 300:
        return True
    # missing-title / missing-meta — html 200 with empty field
    if is_html and s == 200 and (not page.title or not page.meta_description):
        return True
    # long-title
    if page.title and len(page.title) > 60:
        return True
    # short-meta (positive but under 70 chars)
    meta = page.meta_description
    if meta and 0 < len(meta) < 70:
        return True
    # slow-response
    if page.load_time_ms is not None and page.load_time_ms > 1000:
        return True
    # deep-pages
    if page.crawl_depth is not None and page.crawl_depth >= 5:
        return True
    # large-pages
    if is_html and (page.content_size_bytes or 0) > _LARGE_PAGE_BYTES:
        return True
    return False


def _build_duplicate_title_ids(pages: Iterable[Page]) -> set:
    """ids of html-200 pages whose title is shared by another page."""
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


def _is_reachable_html(page: Page) -> bool:
    s = page.http_status_code
    return _is_html_page(page) and s is not None and s < 400


def _scan_pages(session: CrawlSession) -> dict:
    """Single pass over ``Page`` rows yielding every aggregate the
    Dashboard snapshot needs.

    Returns a dict with:

      * ``pages_with_issues``: distinct URLs hit by ANY of the 12 issue
        categories (parity with the previous ``_pages_with_issues``).
      * ``health_counters``: per-predicate counts feeding the spec-defined
        Technical / Content / Performance sub-scores. See
        ``_compute_health`` for the predicate definitions.
      * ``load_times``: ``list[float]`` of non-null ``load_time_ms`` values
        for the p95 calculation.
      * ``depths``: ``list[int]`` of ``crawl_depth`` values for the median.

    Folding everything into one pass avoids 4 separate queries (issues +
    p95 load times + median depths + sub-score predicates) over the same
    Page table.
    """
    pages = list(Page.objects.filter(crawl_session=session))
    dup_ids = _build_duplicate_title_ids(pages)
    inbound = _build_inbound_target_set(session)

    hit_ids: set = set()
    load_times: list[float] = []
    depths: list[int] = []

    failed_count = 0
    redirect_count = 0
    missing_canonical_count = 0
    missing_title_count = 0
    missing_meta_count = 0
    low_word_count = 0
    slow_count = 0
    very_slow_count = 0

    for p in pages:
        # ── pages_with_issues union ────────────────────────────
        if _has_any_single_page_issue(p):
            hit_ids.add(p.id)
        elif p.id in dup_ids:
            hit_ids.add(p.id)
        elif _is_reachable_html(p) and p.url not in inbound:
            hit_ids.add(p.id)

        # ── load times / depths for system_metrics ─────────────
        if p.load_time_ms is not None:
            load_times.append(p.load_time_ms)
        if p.crawl_depth is not None:
            depths.append(p.crawl_depth)

        # ── health sub-score predicates ────────────────────────
        s = p.http_status_code
        is_html = _is_html_page(p)
        is_html_200 = is_html and s == 200

        # Technical
        if s is not None and s >= 500:
            failed_count += 1
        if s is not None and 300 <= s < 400:
            redirect_count += 1
        if is_html_200 and not (p.canonical_url or ""):
            missing_canonical_count += 1

        # Content (only on reachable HTML 200 — same gate as
        # _has_any_single_page_issue's title/meta predicate)
        if is_html_200:
            if not (p.title or ""):
                missing_title_count += 1
            if not (p.meta_description or ""):
                missing_meta_count += 1
            if (p.word_count or 0) < 100:
                low_word_count += 1

        # Performance — note very_slow ⊂ slow by design (spec).
        lt = p.load_time_ms
        if lt is not None and lt > 1000:
            slow_count += 1
        if lt is not None and lt > 2500:
            very_slow_count += 1

    return {
        "pages_with_issues": len(hit_ids),
        "load_times": load_times,
        "depths": depths,
        "health_counters": {
            "failed_count": failed_count,
            "redirect_count": redirect_count,
            "missing_canonical_count": missing_canonical_count,
            "missing_title_count": missing_title_count,
            "missing_meta_count": missing_meta_count,
            "low_word_count": low_word_count,
            "slow_count": slow_count,
            "very_slow_count": very_slow_count,
        },
    }


def _percentile_nearest_rank(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile (NIST method).

    Returns ``None`` when ``values`` is empty. For a sorted list of n items
    and percentile p in (0, 100], the nearest-rank index is::

        rank = ceil(p / 100 * n)  → returns sorted[rank - 1]

    For the spec's ``[10, 20, 30, ..., 100]`` case (n=10, p=95):
    rank = ceil(0.95 * 10) = 10 → sorted[9] = 100. (Documented in tests.)
    """
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    cleaned.sort()
    rank = max(1, math.ceil((pct / 100.0) * len(cleaned)))
    return cleaned[min(rank, len(cleaned)) - 1]


def _median(values: list[int]) -> int:
    """Integer median for crawl_depth. Returns 0 when no values."""
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return 0
    cleaned.sort()
    n = len(cleaned)
    mid = n // 2
    if n % 2 == 1:
        return int(cleaned[mid])
    # Even-length: average the two middle values, integer-round (floor-half).
    return int((cleaned[mid - 1] + cleaned[mid]) // 2)


def _clamp_round(x: float) -> int:
    """Clamp ``x`` to ``[0, 100]`` and round to int."""
    return int(round(max(0.0, min(100.0, x))))


def _compute_health(
    crawled: int,
    index_eligible: int,
    failed_count: int,
    redirect_count: int,
    missing_canonical_count: int,
    missing_title_count: int,
    missing_meta_count: int,
    low_word_count: int,
    slow_count: int,
    very_slow_count: int,
) -> dict:
    """Compute the spec §5.4.1 SEO health gauge: top score + 3 sub-scores.

    All sub-scores live on ``[0, 100]``, are computed server-side, and are
    independent of the top score. The top score is the indexable-coverage
    ratio defined by spec::

        score = round( min(100, (index_eligible / max(crawled, 1)) * 100) )

    Sub-score predicates (each predicate is a per-page boolean evaluated
    once in a single iteration over ``Page`` rows):

      * **Technical** — penalises broken servers, redirect chains, and
        absent canonicals::

            tech = 100 - (failed/crawled)*60
                       - (redirects/crawled)*20
                       - (missing_canonical/crawled)*20

        where ``failed`` = ``http_status_code >= 500``,
        ``redirects`` = ``300 <= http_status_code < 400``,
        ``missing_canonical`` = empty ``canonical_url`` on a 200 HTML page.

      * **Content** — penalises absent titles / meta-descriptions and
        thin pages::

            content = 100 - (missing_title/crawled)*50
                          - (missing_meta/crawled)*30
                          - (low_word_count/crawled)*20

        where ``missing_title`` = empty ``title`` on a 200 HTML page,
        ``missing_meta`` = empty ``meta_description`` on a 200 HTML page,
        ``low_word_count`` = ``word_count < 100`` on a 200 HTML page.

      * **Performance** — penalises slow responses with an additive
        very-slow tier (very_slow is a subset of slow, both fire on the
        same page)::

            perf = 100 - (slow/crawled)*60
                       - (very_slow/crawled)*40

        where ``slow`` = ``load_time_ms > 1000`` and
        ``very_slow`` = ``load_time_ms > 2500``.

    Each sub-score is clamped to ``[0, 100]`` and rounded.

    Bands derived from the **top** score:
      * ``good``  ≥ 80
      * ``warn``  ≥ 50
      * ``poor``  otherwise

    The returned ``reasons`` list is preserved for backwards-compat with
    the existing UI: each entry is the delta of a sub-score from 100
    (always ``≤ 0``) and renders neutral when all sub-scores are perfect.
    """
    denom = max(crawled, 1)
    overall = _clamp_round(min(100.0, (index_eligible / denom) * 100.0))

    tech = _clamp_round(
        100.0
        - (failed_count / denom) * 60.0
        - (redirect_count / denom) * 20.0
        - (missing_canonical_count / denom) * 20.0
    )
    content = _clamp_round(
        100.0
        - (missing_title_count / denom) * 50.0
        - (missing_meta_count / denom) * 30.0
        - (low_word_count / denom) * 20.0
    )
    perf = _clamp_round(
        100.0
        - (slow_count / denom) * 60.0
        - (very_slow_count / denom) * 40.0
    )

    if overall >= 80:
        band = "good"
    elif overall >= 50:
        band = "warn"
    else:
        band = "poor"

    reasons = [
        {"label": "Technical", "delta": tech - 100},
        {"label": "Content", "delta": content - 100},
        {"label": "Performance", "delta": perf - 100},
    ]
    return {
        "score": overall,
        "band": band,
        "sub_scores": {
            "technical": tech,
            "content": content,
            "performance": perf,
        },
        "reasons": reasons,
    }


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
class OverviewService:
    """One-shot Dashboard snapshot for a single crawl session."""

    @staticmethod
    def get_overview(session: CrawlSession) -> dict:
        """Build the Dashboard snapshot for *session*.

        Returns a dict with ``session_id``, ``session_status``, ``kpis``,
        ``health``, and ``system_metrics``. See module docstring for the
        full shape and the health-score formula.
        """
        # Aggregate columns are the source of truth for the KPI strip.
        total_urls = session.total_urls_discovered or 0
        crawled = session.total_urls_crawled or 0
        failed = session.total_urls_failed or 0
        excluded = session.total_excluded or 0
        index_eligible = session.total_index_eligible or 0
        # Pending = discovered but neither crawled nor failed nor excluded.
        # Clamp to >= 0 because aggregates can drift slightly during a
        # running crawl.
        pending = max(0, total_urls - crawled - failed - excluded)

        # Single-pass scan over Page rows: pages_with_issues + p95 load
        # times + median depth + spec §5.4.1 health sub-score counters.
        scan = _scan_pages(session)
        p95 = _percentile_nearest_rank(scan["load_times"], 95.0)
        median_depth = _median(scan["depths"])
        pages_with_issues_count = scan["pages_with_issues"]

        health = _compute_health(
            crawled=crawled,
            index_eligible=index_eligible,
            **scan["health_counters"],
        )

        return {
            "session_id": str(session.id),
            "session_status": session.status,
            "started_at": (
                session.started_at.isoformat() if session.started_at else None
            ),
            "finished_at": (
                session.finished_at.isoformat() if session.finished_at else None
            ),
            "duration_seconds": session.duration_seconds,
            "kpis": {
                "total_urls": total_urls,
                "crawled": crawled,
                "pending": pending,
                "failed": failed,
                "excluded": excluded,
            },
            "health": health,
            "system_metrics": {
                "avg_response_time_ms": float(session.avg_response_time_ms or 0.0),
                "p95_response_time_ms": p95,
                "median_depth": median_depth,
                "max_depth_reached": session.max_depth_reached or 0,
                "pages_with_issues": pages_with_issues_count,
            },
        }
