"""Tests for ``AnalyticsService.get_chart_data``.

Covers the four chart datasets the analytics page renders:
status, depth, response time histogram, and content type.

Boundary rule for the response time histogram: each bucket is
left-inclusive, right-exclusive (``[lo, hi)``). For example,
``100-250ms`` matches ``100 <= ms < 250`` so a value of exactly
``250`` lands in ``250-500ms`` — see ``test_response_time_boundary_*``.
"""

import pytest

from apps.crawl_sessions.models import CrawlSession, Page
from apps.crawl_sessions.services.analytics_service import (
    AnalyticsService,
    _classify_content_type,
)
from apps.crawler.models import Website


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def website(db):
    return Website.objects.create(domain="example.com", name="example")


@pytest.fixture
def session(website):
    return CrawlSession.objects.create(website=website)


def _make_page(
    session,
    url,
    *,
    status_code=200,
    depth=0,
    load_time_ms=None,
):
    """Create a Page row with sensible defaults. URLs must be unique
    per session because of the ``unique_session_url`` constraint."""
    return Page.objects.create(
        crawl_session=session,
        url=url,
        http_status_code=status_code,
        crawl_depth=depth,
        load_time_ms=load_time_ms,
    )


# ── 1. Empty session ───────────────────────────────────────────────────

@pytest.mark.django_db
def test_empty_session_returns_all_buckets_with_zero_counts(session):
    """Empty session: stable shape; all buckets present at count 0."""
    data = AnalyticsService.get_chart_data(session)

    assert data["total_pages"] == 0

    # Status: all 5 classes present, every count is 0.
    labels = [row["label"] for row in data["status_distribution"]]
    assert labels == ["2xx", "3xx", "4xx", "5xx", "unknown"]
    assert all(row["count"] == 0 for row in data["status_distribution"])
    assert all("color" in row for row in data["status_distribution"])

    # Depth: empty when no pages at all (no max_depth to bound the range).
    assert data["depth_distribution"] == []

    # Response time histogram: all 6 buckets present at 0.
    buckets = [row["bucket"] for row in data["response_time_histogram"]]
    assert buckets == [
        "0-100ms", "100-250ms", "250-500ms",
        "500-1000ms", "1000-2500ms", "2500ms+",
    ]
    assert all(row["count"] == 0 for row in data["response_time_histogram"])

    # Content type: all 7 categories present at 0, fixed order.
    ct_labels = [row["label"] for row in data["content_type_distribution"]]
    assert ct_labels == [
        "html", "image", "css", "js", "font", "document", "other",
    ]
    assert all(row["count"] == 0 for row in data["content_type_distribution"])


# ── 2-3. Status code distribution ──────────────────────────────────────

@pytest.mark.django_db
def test_status_distribution_single_200_page(session):
    """One 200 page → 2xx=1, others 0."""
    _make_page(session, "https://x.com/a", status_code=200)
    data = AnalyticsService.get_chart_data(session)

    by_label = {row["label"]: row["count"] for row in data["status_distribution"]}
    assert by_label == {"2xx": 1, "3xx": 0, "4xx": 0, "5xx": 0, "unknown": 0}


@pytest.mark.django_db
def test_status_distribution_mix_including_null(session):
    """Mix of 200/301/404/503/None → counts in all 5 classes."""
    _make_page(session, "https://x.com/a", status_code=200)
    _make_page(session, "https://x.com/b", status_code=301)
    _make_page(session, "https://x.com/c", status_code=404)
    _make_page(session, "https://x.com/d", status_code=503)
    _make_page(session, "https://x.com/e", status_code=None)

    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["status_distribution"]}

    assert by_label == {
        "2xx": 1, "3xx": 1, "4xx": 1, "5xx": 1, "unknown": 1,
    }


@pytest.mark.django_db
def test_status_distribution_zero_status_counts_as_unknown(session):
    """Sentinel ``0`` (no response received) is classified as unknown."""
    _make_page(session, "https://x.com/a", status_code=0)
    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["status_distribution"]}
    assert by_label["unknown"] == 1
    assert by_label["2xx"] == 0


# ── 4. Depth distribution ──────────────────────────────────────────────

@pytest.mark.django_db
def test_depth_distribution_fills_zero_buckets_between(session):
    """Pages at depths 0,1,1,2,5 → continuous range 0..5 with zeros at 3,4."""
    for url, depth in [
        ("https://x.com/a", 0),
        ("https://x.com/b", 1),
        ("https://x.com/c", 1),
        ("https://x.com/d", 2),
        ("https://x.com/e", 5),
    ]:
        _make_page(session, url, depth=depth)

    data = AnalyticsService.get_chart_data(session)
    assert data["depth_distribution"] == [
        {"depth": 0, "count": 1},
        {"depth": 1, "count": 2},
        {"depth": 2, "count": 1},
        {"depth": 3, "count": 0},
        {"depth": 4, "count": 0},
        {"depth": 5, "count": 1},
    ]


# ── 5-8. Response time histogram ───────────────────────────────────────

@pytest.mark.django_db
def test_response_time_50ms_lands_in_first_bucket(session):
    """load_time_ms = 50 → 0-100ms bucket = 1."""
    _make_page(session, "https://x.com/a", load_time_ms=50)
    data = AnalyticsService.get_chart_data(session)
    by_bucket = {row["bucket"]: row["count"] for row in data["response_time_histogram"]}
    assert by_bucket["0-100ms"] == 1
    assert sum(by_bucket.values()) == 1


@pytest.mark.django_db
def test_response_time_boundary_250_lands_in_250_500_bucket(session):
    """Boundary: 100-250ms is [100, 250); a value of 250 is in 250-500ms."""
    _make_page(session, "https://x.com/a", load_time_ms=250)
    data = AnalyticsService.get_chart_data(session)
    by_bucket = {row["bucket"]: row["count"] for row in data["response_time_histogram"]}
    assert by_bucket["100-250ms"] == 0
    assert by_bucket["250-500ms"] == 1


@pytest.mark.django_db
def test_response_time_boundary_100_lands_in_100_250_bucket(session):
    """Boundary: 0-100ms is [0, 100); a value of 100 is in 100-250ms."""
    _make_page(session, "https://x.com/a", load_time_ms=100)
    data = AnalyticsService.get_chart_data(session)
    by_bucket = {row["bucket"]: row["count"] for row in data["response_time_histogram"]}
    assert by_bucket["0-100ms"] == 0
    assert by_bucket["100-250ms"] == 1


@pytest.mark.django_db
def test_response_time_null_is_not_counted(session):
    """NULL load_time_ms is not counted in any bucket."""
    _make_page(session, "https://x.com/a", load_time_ms=None)
    data = AnalyticsService.get_chart_data(session)
    by_bucket = {row["bucket"]: row["count"] for row in data["response_time_histogram"]}
    assert sum(by_bucket.values()) == 0


@pytest.mark.django_db
def test_response_time_5000ms_lands_in_top_bucket(session):
    """load_time_ms = 5000 → 2500ms+ bucket."""
    _make_page(session, "https://x.com/a", load_time_ms=5000)
    data = AnalyticsService.get_chart_data(session)
    by_bucket = {row["bucket"]: row["count"] for row in data["response_time_histogram"]}
    assert by_bucket["2500ms+"] == 1


# ── 9-14. Content type distribution ────────────────────────────────────

@pytest.mark.django_db
def test_content_type_trailing_slash_is_html(session):
    _make_page(session, "https://x.com/")
    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["content_type_distribution"]}
    assert by_label["html"] == 1
    assert by_label["other"] == 0


@pytest.mark.django_db
def test_content_type_image(session):
    _make_page(session, "https://x.com/foo.jpg")
    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["content_type_distribution"]}
    assert by_label["image"] == 1


@pytest.mark.django_db
def test_content_type_css_with_query_string(session):
    """Query string is stripped before extension check."""
    _make_page(session, "https://x.com/style.css?v=1")
    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["content_type_distribution"]}
    assert by_label["css"] == 1


@pytest.mark.django_db
def test_content_type_uppercase_extension_is_case_insensitive(session):
    """Extensions are matched case-insensitively."""
    _make_page(session, "https://x.com/foo.PDF")
    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["content_type_distribution"]}
    assert by_label["document"] == 1


@pytest.mark.django_db
def test_content_type_no_extension_is_html(session):
    """Paths with no extension are HTML."""
    _make_page(session, "https://x.com/page")
    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["content_type_distribution"]}
    assert by_label["html"] == 1


@pytest.mark.django_db
def test_content_type_unknown_extension_is_other(session):
    """``.json`` is not in any specific bucket → other."""
    _make_page(session, "https://x.com/data.json")
    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["content_type_distribution"]}
    assert by_label["other"] == 1
    assert by_label["html"] == 0


# ── 15. Total pages ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_total_pages_matches_filtered_count(session):
    """``total_pages`` equals Page.objects.filter(crawl_session=session).count()."""
    for i in range(7):
        _make_page(session, f"https://x.com/p{i}")

    data = AnalyticsService.get_chart_data(session)

    assert data["total_pages"] == Page.objects.filter(crawl_session=session).count()
    assert data["total_pages"] == 7


# ── Cross-session isolation ────────────────────────────────────────────

@pytest.mark.django_db
def test_other_sessions_pages_are_excluded(website, session):
    """Pages from a different session must not leak into this session's data."""
    other_session = CrawlSession.objects.create(website=website)
    _make_page(other_session, "https://x.com/other-1", status_code=500)
    _make_page(other_session, "https://x.com/other-2", status_code=500)

    _make_page(session, "https://x.com/mine", status_code=200)

    data = AnalyticsService.get_chart_data(session)
    by_label = {row["label"]: row["count"] for row in data["status_distribution"]}
    assert by_label["2xx"] == 1
    assert by_label["5xx"] == 0
    assert data["total_pages"] == 1


# ── Helper: classifier unit tests (no DB) ──────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://x.com/", "html"),
    ("https://x.com", "html"),
    ("https://x.com/index.html", "html"),
    ("https://x.com/page.htm", "html"),
    ("https://x.com/page.php", "html"),
    ("https://x.com/page.aspx", "html"),
    ("https://x.com/foo.jpg", "image"),
    ("https://x.com/foo.JPEG", "image"),
    ("https://x.com/icon.svg", "image"),
    ("https://x.com/style.css", "css"),
    ("https://x.com/style.css?v=1", "css"),
    ("https://x.com/app.js", "js"),
    ("https://x.com/app.js?bust=1#frag", "js"),
    ("https://x.com/font.woff2", "font"),
    ("https://x.com/doc.PDF", "document"),
    ("https://x.com/data.json", "other"),
    ("https://x.com/archive.zip", "other"),
    ("https://x.com/page", "html"),
])
def test_classify_content_type(url, expected):
    assert _classify_content_type(url) == expected
