"""Integration tests for CrawlSessionViewSet custom @action endpoints.

Exercises five action methods on CrawlSessionViewSet via the public DRF
URL space (router prefix ``/api/v1/sessions/``):

  - GET /api/v1/sessions/<id>/activity/      (regression: datetime/str merge)
  - GET /api/v1/sessions/<id>/pages/         (paginated, filtered, sorted)
  - GET /api/v1/sessions/<id>/issues/        (12-category summary)
  - GET /api/v1/sessions/<id>/issues/<id>/   (per-issue detail)
  - GET /api/v1/sessions/<id>/analytics/     (chart datasets)

Mirrors the pytest + ORM-fixture conventions of
``apps/crawl_sessions/tests/test_issue_service.py``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.crawl_sessions.models import CrawlEvent, CrawlSession, Page
from apps.crawl_sessions.services.session_manager import SessionManager
from apps.crawler.models import Website


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def website(db):
    return Website.objects.create(domain="example.test", name="Example")


@pytest.fixture
def session(db, website):
    return CrawlSession.objects.create(website=website)


def _url(session, action, *, suffix=""):
    """Build the canonical ``/api/v1/sessions/<id>/<action>/`` path."""
    return f"/api/v1/sessions/{session.id}/{action}/{suffix}"


def _make_page(session: CrawlSession, url: str, **kwargs) -> Page:
    """Create a Page with sensible defaults shared across tests."""
    defaults = {
        "http_status_code": 200,
        "title": "Default",
        "meta_description": (
            "A reasonably long meta description that satisfies the "
            "70-char minimum easily."
        ),
        "crawl_depth": 1,
        "load_time_ms": 250.0,
        "content_size_bytes": 5_000,
    }
    defaults.update(kwargs)
    return Page.objects.create(crawl_session=session, url=url, **defaults)


# ─────────────────────────────────────────────────────────────
# /activity/  — 6 tests including the datetime/str regression
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_activity_empty_session_returns_empty_list(client, session):
    resp = client.get(_url(session, "activity"))

    assert resp.status_code == 200, resp.content
    assert resp.data == []


@pytest.mark.django_db
def test_activity_with_only_lifecycle_event(client, session):
    SessionManager.start_session(session)

    resp = client.get(_url(session, "activity"))

    assert resp.status_code == 200, resp.content
    assert len(resp.data) == 1
    entry = resp.data[0]
    assert entry["kind"] == "session"
    assert isinstance(entry["timestamp"], str)


@pytest.mark.django_db
def test_activity_with_pages_only(client, session):
    _make_page(session, "https://example.test/a", http_status_code=200)
    _make_page(session, "https://example.test/b", http_status_code=301)

    resp = client.get(_url(session, "activity"))

    assert resp.status_code == 200, resp.content
    assert len(resp.data) == 2
    for entry in resp.data:
        assert entry["id"].startswith("page-")
        assert entry["kind"] in ("crawl", "redirect", "error")
        assert isinstance(entry["timestamp"], str)


@pytest.mark.django_db
def test_activity_with_both_events_and_pages(client, session):
    """Regression: ``sorted()`` must not raise TypeError when the merged
    list mixes serialized CrawlEvent rows (string timestamps) with
    synthesized Page entries. The synthesized side must also emit ISO
    strings, not native datetimes."""
    SessionManager.start_session(session)
    _make_page(session, "https://example.test/page", http_status_code=200)

    resp = client.get(_url(session, "activity"))

    # Must not 500 — the bug surfaces as TypeError inside sorted().
    assert resp.status_code == 200, resp.content
    assert len(resp.data) >= 2

    # Every timestamp must be a string after the fix.
    for entry in resp.data:
        assert isinstance(entry["timestamp"], str), entry

    # Merged result must be DESC by timestamp.
    timestamps = [entry["timestamp"] for entry in resp.data]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.django_db
def test_activity_with_since_filter(client, session):
    now = timezone.now()
    old = _make_page(session, "https://example.test/old", http_status_code=200)
    # auto_now_add ignored values on .create(); rewrite via .update().
    Page.objects.filter(pk=old.pk).update(crawl_timestamp=now - timedelta(minutes=10))

    SessionManager.start_session(session)  # writes a CrawlEvent at "now"

    since = (now - timedelta(minutes=5)).isoformat()
    resp = client.get(_url(session, "activity"), {"since": since})

    assert resp.status_code == 200, resp.content
    # Old page is filtered out; only the recent lifecycle event remains.
    assert len(resp.data) == 1
    assert resp.data[0]["kind"] == "session"


@pytest.mark.django_db
def test_activity_respects_limit_param(client, session):
    for i in range(5):
        _make_page(session, f"https://example.test/p{i}", http_status_code=200)

    resp = client.get(_url(session, "activity"), {"limit": 2})

    assert resp.status_code == 200, resp.content
    assert len(resp.data) <= 2


# ─────────────────────────────────────────────────────────────
# /pages/  — 6 tests covering pagination + filters + ordering
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_pages_returns_paginated_envelope(client, session):
    for i in range(3):
        _make_page(session, f"https://example.test/p{i}", http_status_code=200)

    resp = client.get(_url(session, "pages"))

    assert resp.status_code == 200, resp.content
    assert set(resp.data.keys()) == {"count", "next", "previous", "results"}
    assert resp.data["count"] == 3
    assert len(resp.data["results"]) == 3


@pytest.mark.django_db
def test_pages_status_class_filter(client, session):
    _make_page(session, "https://example.test/ok", http_status_code=200)
    _make_page(session, "https://example.test/redir", http_status_code=301)
    _make_page(session, "https://example.test/missing", http_status_code=404)

    resp = client.get(_url(session, "pages"), {"status_class": "4xx"})

    assert resp.status_code == 200, resp.content
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["http_status_code"] == 404


@pytest.mark.django_db
def test_pages_content_type_image_filter(client, session):
    _make_page(session, "https://x.com/a", http_status_code=200)
    _make_page(session, "https://x.com/foo.png", http_status_code=200)

    resp = client.get(_url(session, "pages"), {"content_type": "image"})

    assert resp.status_code == 200, resp.content
    assert resp.data["count"] == 1


@pytest.mark.django_db
def test_pages_search_q_filter(client, session):
    # Use neutral path slugs so "about" only appears in the title we search.
    _make_page(session, "https://example.test/p1", title="Home")
    _make_page(session, "https://example.test/p2", title="About")

    resp = client.get(_url(session, "pages"), {"q": "about"})

    assert resp.status_code == 200, resp.content
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["title"] == "About"


@pytest.mark.django_db
def test_pages_ordering_whitelist_accepted(client, session):
    _make_page(session, "https://example.test/a", http_status_code=200)

    resp = client.get(_url(session, "pages"), {"ordering": "-http_status_code"})

    assert resp.status_code == 200, resp.content


@pytest.mark.django_db
def test_pages_ordering_unknown_falls_back(client, session):
    _make_page(session, "https://example.test/a", http_status_code=200)

    resp = client.get(_url(session, "pages"), {"ordering": "DROP+TABLE"})

    # Must silently fall back to default ordering, never 500.
    assert resp.status_code == 200, resp.content


# ─────────────────────────────────────────────────────────────
# /issues/  — 12-category summary
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_issues_returns_twelve_categories(client, session):
    resp = client.get(_url(session, "issues"))

    assert resp.status_code == 200, resp.content
    assert len(resp.data) == 12
    for entry in resp.data:
        assert set(entry.keys()) == {"id", "name", "severity", "description", "count"}
        assert entry["count"] == 0


@pytest.mark.django_db
def test_issues_count_increments_for_4xx_page(client, session):
    _make_page(session, "https://example.test/missing", http_status_code=404)

    resp = client.get(_url(session, "issues"))

    assert resp.status_code == 200, resp.content
    by_id = {entry["id"]: entry for entry in resp.data}
    assert by_id["broken-4xx"]["count"] == 1


# ─────────────────────────────────────────────────────────────
# /issues/<issue_id>/  — per-issue detail
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_issue_detail_returns_affected_urls(client, session):
    _make_page(session, "https://example.test/oops", http_status_code=503)

    resp = client.get(_url(session, "issues", suffix="server-5xx/"))

    assert resp.status_code == 200, resp.content
    assert resp.data["id"] == "server-5xx"
    assert resp.data["count"] == 1
    affected = resp.data["affected_urls"]
    assert len(affected) == 1
    assert affected[0]["url"] == "https://example.test/oops"


@pytest.mark.django_db
def test_issue_detail_unknown_id_returns_404(client, session):
    resp = client.get(_url(session, "issues", suffix="not-a-real-issue/"))

    assert resp.status_code == 404, resp.content
    assert "detail" in resp.data


# ─────────────────────────────────────────────────────────────
# /analytics/  — chart datasets
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_analytics_empty_session(client, session):
    resp = client.get(_url(session, "analytics"))

    assert resp.status_code == 200, resp.content
    body = resp.data
    assert "status_distribution" in body
    assert "depth_distribution" in body
    assert "response_time_histogram" in body
    assert "content_type_distribution" in body
    assert body["total_pages"] == 0
    # Five fixed status buckets (2xx, 3xx, 4xx, 5xx, unknown).
    assert len(body["status_distribution"]) == 5
    # Six fixed response-time buckets.
    assert len(body["response_time_histogram"]) == 6


@pytest.mark.django_db
def test_analytics_counts_a_200_page(client, session):
    _make_page(
        session,
        "https://example.test/home",
        http_status_code=200,
        crawl_depth=1,
        load_time_ms=50.0,
    )

    resp = client.get(_url(session, "analytics"))

    assert resp.status_code == 200, resp.content
    body = resp.data
    assert body["total_pages"] == 1

    by_status = {entry["label"]: entry for entry in body["status_distribution"]}
    assert by_status["2xx"]["count"] == 1

    by_bucket = {entry["bucket"]: entry for entry in body["response_time_histogram"]}
    assert by_bucket["0-100ms"]["count"] == 1
