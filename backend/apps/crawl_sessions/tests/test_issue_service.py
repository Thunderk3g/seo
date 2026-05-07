"""Unit tests for ``IssueService``.

Covers each of the 12 issue categories plus the
``get_issue_detail`` happy path and unknown-id error path.
"""

from __future__ import annotations

import pytest

from apps.common import constants
from apps.crawl_sessions.models import CrawlSession, Link, Page
from apps.crawl_sessions.services.issue_service import IssueService
from apps.crawler.models import Website


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def website(db):
    return Website.objects.create(domain="example.com", name="Example")


@pytest.fixture
def session(db, website):
    return CrawlSession.objects.create(
        website=website,
        status=constants.SESSION_STATUS_COMPLETED,
    )


def _make_page(session: CrawlSession, url: str, **kwargs) -> Page:
    """Create a Page with sensible defaults for issue testing."""
    defaults = {
        "http_status_code": 200,
        "title": "Default Title",
        "meta_description": "A reasonably long meta description "
                            "that satisfies the 70-char minimum easily.",
        "crawl_depth": 1,
        "load_time_ms": 250.0,
        "content_size_bytes": 5_000,
    }
    defaults.update(kwargs)
    return Page.objects.create(crawl_session=session, url=url, **defaults)


def _counts(session: CrawlSession) -> dict[str, int]:
    return {entry["id"]: entry["count"] for entry in IssueService.derive_issues(session)}


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_empty_session_returns_all_twelve_categories_with_zero_count(session):
    """An empty session yields all 12 entries, each with count == 0."""
    result = IssueService.derive_issues(session)

    assert len(result) == 12
    assert all(entry["count"] == 0 for entry in result)

    expected_ids = [
        "broken-4xx", "server-5xx", "missing-title", "missing-meta",
        "duplicate-title", "long-title", "short-meta", "redirect-3xx",
        "slow-response", "orphan-pages", "deep-pages", "large-pages",
    ]
    assert [e["id"] for e in result] == expected_ids

    for entry in result:
        assert entry["severity"] in {"error", "warning", "notice"}
        assert entry["name"]
        assert entry["description"]


@pytest.mark.django_db
def test_single_404_page_counts_only_in_broken_4xx(session):
    _make_page(session, "https://example.com/missing", http_status_code=404)
    counts = _counts(session)

    assert counts["broken-4xx"] == 1
    assert counts["server-5xx"] == 0
    # The 404 page also has no inbound link — but it's not html-200/<400
    # only requirement is status<400, 404 is 4xx so NOT orphan-eligible.
    assert counts["orphan-pages"] == 0


@pytest.mark.django_db
def test_single_503_page_counts_only_in_server_5xx(session):
    _make_page(session, "https://example.com/down", http_status_code=503)
    counts = _counts(session)

    assert counts["server-5xx"] == 1
    assert counts["broken-4xx"] == 0


@pytest.mark.django_db
def test_two_pages_with_identical_title_count_as_duplicate(session):
    _make_page(session, "https://example.com/a", title="Same Title")
    _make_page(session, "https://example.com/b", title="Same Title")
    # A third unique page that should NOT count.
    _make_page(session, "https://example.com/c", title="Different Title")

    counts = _counts(session)
    assert counts["duplicate-title"] == 2


@pytest.mark.django_db
def test_title_length_eighty_counts_as_long_title(session):
    long_title = "x" * 80
    _make_page(session, "https://example.com/long", title=long_title)

    counts = _counts(session)
    assert counts["long-title"] == 1


@pytest.mark.django_db
def test_meta_length_fifty_counts_as_short_meta(session):
    short_meta = "x" * 50
    _make_page(
        session, "https://example.com/short-meta",
        meta_description=short_meta,
    )

    counts = _counts(session)
    assert counts["short-meta"] == 1


@pytest.mark.django_db
def test_load_time_above_one_second_counts_as_slow(session):
    _make_page(session, "https://example.com/slow", load_time_ms=1500.0)

    counts = _counts(session)
    assert counts["slow-response"] == 1


@pytest.mark.django_db
def test_content_size_over_two_hundred_kb_counts_as_large(session):
    # 250_000 bytes > 200 * 1024 (204_800)
    _make_page(
        session, "https://example.com/big",
        content_size_bytes=250_000,
    )

    counts = _counts(session)
    assert counts["large-pages"] == 1


@pytest.mark.django_db
def test_crawl_depth_six_counts_as_deep(session):
    _make_page(session, "https://example.com/deep", crawl_depth=6)

    counts = _counts(session)
    assert counts["deep-pages"] == 1


@pytest.mark.django_db
def test_html_page_with_no_inbound_internal_link_is_orphan(session):
    _make_page(session, "https://example.com/orphan")

    counts = _counts(session)
    assert counts["orphan-pages"] == 1


@pytest.mark.django_db
def test_html_page_with_inbound_internal_link_is_not_orphan(session):
    target_url = "https://example.com/linked"
    _make_page(session, "https://example.com/source")
    _make_page(session, target_url)
    Link.objects.create(
        crawl_session=session,
        source_url="https://example.com/source",
        target_url=target_url,
        link_type=constants.LINK_TYPE_INTERNAL,
    )

    counts = _counts(session)
    # /source has no inlink so it IS an orphan, but /linked is not.
    # Both pages are reachable html — only /source counts as orphan.
    assert counts["orphan-pages"] == 1


@pytest.mark.django_db
def test_self_link_does_not_save_page_from_orphan_status(session):
    """Self-links must be ignored — a page linking to itself is still orphan."""
    url = "https://example.com/self"
    _make_page(session, url)
    Link.objects.create(
        crawl_session=session,
        source_url=url,
        target_url=url,
        link_type=constants.LINK_TYPE_INTERNAL,
    )

    counts = _counts(session)
    assert counts["orphan-pages"] == 1


@pytest.mark.django_db
def test_image_url_with_no_title_does_not_count_as_missing_title(session):
    """Non-HTML URLs are excluded from missing-title."""
    _make_page(
        session,
        "https://example.com/photo.jpg",
        title="",
        meta_description="",
    )

    counts = _counts(session)
    assert counts["missing-title"] == 0
    assert counts["missing-meta"] == 0
    # Also: no orphan because it's not html.
    assert counts["orphan-pages"] == 0


@pytest.mark.django_db
def test_html_page_status_200_with_empty_title_is_missing_title(session):
    _make_page(
        session,
        "https://example.com/no-title",
        title="",
    )

    counts = _counts(session)
    assert counts["missing-title"] == 1


@pytest.mark.django_db
def test_redirect_3xx_counted(session):
    _make_page(
        session,
        "https://example.com/redir",
        http_status_code=301,
    )

    counts = _counts(session)
    assert counts["redirect-3xx"] == 1


@pytest.mark.django_db
def test_get_issue_detail_returns_affected_urls_for_broken_4xx(session):
    _make_page(session, "https://example.com/a", http_status_code=404)
    _make_page(session, "https://example.com/b", http_status_code=410)
    _make_page(session, "https://example.com/ok")  # 200, must NOT appear

    detail = IssueService.get_issue_detail(session, "broken-4xx")

    assert detail["id"] == "broken-4xx"
    assert detail["severity"] == "error"
    assert detail["count"] == 2
    affected_urls = {row["url"] for row in detail["affected_urls"]}
    assert affected_urls == {
        "https://example.com/a",
        "https://example.com/b",
    }
    # Each row carries the documented shape.
    sample = detail["affected_urls"][0]
    assert set(sample.keys()) == {
        "url", "http_status_code", "title", "crawl_depth", "load_time_ms",
    }


@pytest.mark.django_db
def test_get_issue_detail_unknown_id_raises_value_error(session):
    with pytest.raises(ValueError):
        IssueService.get_issue_detail(session, "nonexistent")


@pytest.mark.django_db
def test_get_issue_detail_respects_limit(session):
    for i in range(5):
        _make_page(
            session,
            f"https://example.com/err-{i}",
            http_status_code=500,
        )

    detail = IssueService.get_issue_detail(session, "server-5xx", limit=3)

    assert detail["count"] == 5
    assert len(detail["affected_urls"]) == 3
