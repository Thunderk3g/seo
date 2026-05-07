"""Analytics chart aggregation for the dashboard analytics page.

Computes the four chart datasets surfaced on the Analytics page:

1. Status code distribution (donut)
2. Depth distribution (bar)
3. Response time histogram (bar)
4. Content type distribution (donut)

All four datasets are computed in a single :meth:`AnalyticsService.get_chart_data`
call so the frontend can render the analytics page from a single endpoint.

Design notes
------------
- Pure read aggregation over ``Page`` rows for a given ``CrawlSession``.
- Targets <= 4 SQL queries (one aggregate per chart) for a v1 cap of
  ~50k URLs per session.
- All buckets are returned even when their count is zero so the frontend
  has stable shape and order.
"""

from urllib.parse import urlsplit

from django.db.models import Count, Q

from apps.crawl_sessions.models import CrawlSession, Page


# ── Status code chart palette (lifted from design tokens) ──────────────
# Frontend may override these; we pass them through for convenience.
_STATUS_COLORS = {
    "2xx": "#6ee7b7",      # mint / accent
    "3xx": "#60a5fa",      # notice blue
    "4xx": "#f87171",      # error red
    "5xx": "#dc2626",      # deeper red
    "unknown": "#94a3b8",  # slate
}

# Order in which status buckets are emitted. The frontend hides empty
# slices but the shape and order are stable.
_STATUS_ORDER = ("2xx", "3xx", "4xx", "5xx", "unknown")

# ── Response time histogram bin definitions ────────────────────────────
# Bucket semantics: left-inclusive, right-exclusive (``[lo, hi)``).
# A page with ``load_time_ms == 250`` falls into ``250-500ms``, NOT
# ``100-250ms``. The final bucket has no upper bound.
#
# Each entry is (label, lo_inclusive, hi_exclusive_or_None).
_RESPONSE_BUCKETS: list[tuple[str, float, float | None]] = [
    ("0-100ms",     0.0,    100.0),
    ("100-250ms",   100.0,  250.0),
    ("250-500ms",   250.0,  500.0),
    ("500-1000ms",  500.0,  1000.0),
    ("1000-2500ms", 1000.0, 2500.0),
    ("2500ms+",     2500.0, None),
]

# ── Content type extension mapping ─────────────────────────────────────
# Order of categories in the returned list:
_CONTENT_TYPE_ORDER = (
    "html",
    "image",
    "css",
    "js",
    "font",
    "document",
    "other",
)

_HTML_EXTS = {".html", ".htm", ".php", ".aspx", ".jsp"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico"}
_FONT_EXTS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
_DOCUMENT_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"}


def _classify_content_type(url: str) -> str:
    """Classify a URL into one of the seven content-type buckets.

    Rules:
    - Strip the query string and fragment before extension lookup.
    - Case-insensitive extension matching.
    - URL paths ending in ``/`` and paths with no extension are HTML.
    - Anything that doesn't match a known bucket falls through to
      ``other`` (e.g. ``.json``, ``.xml``, ``.zip``).
    """
    if not url:
        return "html"

    # Strip query/fragment so ``style.css?v=1`` still classifies as css.
    try:
        path = urlsplit(url).path or ""
    except ValueError:
        path = url.split("?", 1)[0].split("#", 1)[0]

    if not path or path.endswith("/"):
        return "html"

    # Last path segment determines the extension.
    segment = path.rsplit("/", 1)[-1]
    if "." not in segment:
        return "html"

    ext = "." + segment.rsplit(".", 1)[-1].lower()

    if ext in _HTML_EXTS:
        return "html"
    if ext in _IMAGE_EXTS:
        return "image"
    if ext == ".css":
        return "css"
    if ext == ".js":
        return "js"
    if ext in _FONT_EXTS:
        return "font"
    if ext in _DOCUMENT_EXTS:
        return "document"
    return "other"


class AnalyticsService:
    """Aggregate chart datasets for the analytics dashboard page.

    All methods are read-only and operate on a single ``CrawlSession``.
    """

    @staticmethod
    def get_chart_data(session: CrawlSession) -> dict:
        """Return all four chart datasets for the analytics page.

        Returns a dict with the following keys:

        - ``status_distribution``: list of ``{label, count, color}``
          for each of the five status classes (``2xx``, ``3xx``,
          ``4xx``, ``5xx``, ``unknown``). Always all five entries.
        - ``depth_distribution``: list of ``{depth, count}`` from
          depth ``0`` through ``max_depth_in_session`` inclusive,
          with zero-count buckets filled in.
        - ``response_time_histogram``: list of ``{bucket, count}``
          across the six fixed bins, in fixed order.
        - ``content_type_distribution``: list of ``{label, count}``
          for the seven content categories, in fixed order.
        - ``total_pages``: total page count for the session.

        Roughly four SQL queries: one aggregate per chart.
        """
        pages = Page.objects.filter(crawl_session=session)

        return {
            "status_distribution": AnalyticsService._status_distribution(pages),
            "depth_distribution": AnalyticsService._depth_distribution(pages),
            "response_time_histogram": AnalyticsService._response_time_histogram(pages),
            "content_type_distribution": AnalyticsService._content_type_distribution(pages),
            "total_pages": pages.count(),
        }

    # ── Chart 1: Status code distribution ──────────────────────────────
    @staticmethod
    def _status_distribution(pages) -> list[dict]:
        """Group pages into 2xx / 3xx / 4xx / 5xx / unknown.

        ``unknown`` covers NULL status codes and the sentinel ``0``
        (used by some fetchers to indicate "no response received").
        Single SQL query via conditional aggregation.
        """
        agg = pages.aggregate(
            c2xx=Count("id", filter=Q(http_status_code__gte=200,
                                      http_status_code__lt=300)),
            c3xx=Count("id", filter=Q(http_status_code__gte=300,
                                      http_status_code__lt=400)),
            c4xx=Count("id", filter=Q(http_status_code__gte=400,
                                      http_status_code__lt=500)),
            c5xx=Count("id", filter=Q(http_status_code__gte=500,
                                      http_status_code__lt=600)),
            cunknown=Count("id", filter=Q(http_status_code__isnull=True)
                                        | Q(http_status_code=0)),
        )
        counts = {
            "2xx": agg["c2xx"] or 0,
            "3xx": agg["c3xx"] or 0,
            "4xx": agg["c4xx"] or 0,
            "5xx": agg["c5xx"] or 0,
            "unknown": agg["cunknown"] or 0,
        }
        return [
            {
                "label": label,
                "count": counts[label],
                "color": _STATUS_COLORS[label],
            }
            for label in _STATUS_ORDER
        ]

    # ── Chart 2: Depth distribution ────────────────────────────────────
    @staticmethod
    def _depth_distribution(pages) -> list[dict]:
        """Distribution of pages by ``crawl_depth``.

        Returns every depth from ``0`` to ``max_depth`` (inclusive)
        so the resulting bar chart has continuous bars (zero-count
        depths are filled in).
        """
        rows = (
            pages
            .values("crawl_depth")
            .annotate(count=Count("id"))
            .order_by("crawl_depth")
        )
        observed = {row["crawl_depth"]: row["count"] for row in rows}

        if not observed:
            return []

        max_depth = max(observed.keys())
        return [
            {"depth": depth, "count": observed.get(depth, 0)}
            for depth in range(0, max_depth + 1)
        ]

    # ── Chart 3: Response time histogram ───────────────────────────────
    @staticmethod
    def _response_time_histogram(pages) -> list[dict]:
        """Bucket ``load_time_ms`` into the six fixed bins.

        Bucket semantics are left-inclusive, right-exclusive
        (``[lo, hi)``). A value of exactly ``250`` lands in
        ``250-500ms``, not ``100-250ms``. NULL values are skipped.
        Single SQL query via conditional aggregation.
        """
        annotations: dict[str, Count] = {}
        for idx, (_, lo, hi) in enumerate(_RESPONSE_BUCKETS):
            if hi is None:
                q = Q(load_time_ms__gte=lo)
            else:
                q = Q(load_time_ms__gte=lo, load_time_ms__lt=hi)
            annotations[f"b{idx}"] = Count("id", filter=q)

        agg = pages.aggregate(**annotations)
        return [
            {
                "bucket": label,
                "count": agg[f"b{idx}"] or 0,
            }
            for idx, (label, _, _) in enumerate(_RESPONSE_BUCKETS)
        ]

    # ── Chart 4: Content type distribution ─────────────────────────────
    @staticmethod
    def _content_type_distribution(pages) -> list[dict]:
        """Bucket pages by URL extension into the seven categories.

        We pull only the ``url`` column and classify in Python — URL
        strings are short and the v1 cap is 50k pages, so a single
        pass is acceptable and keeps the regex/extension logic out
        of the database.
        """
        counts: dict[str, int] = {label: 0 for label in _CONTENT_TYPE_ORDER}
        for url in pages.values_list("url", flat=True).iterator():
            counts[_classify_content_type(url or "")] += 1

        return [
            {"label": label, "count": counts[label]}
            for label in _CONTENT_TYPE_ORDER
        ]
