"""Tests for the post-crawl ``CrawlEvent`` retention cap.

The helper :func:`apps.crawl_sessions.services.event_retention.cap_events_for_session`
is invoked from terminal-state ``SessionManager`` transitions
(``complete_session`` / ``fail_session`` / ``cancel_session``). Tests
cover:

1. Trim deletes only the oldest excess rows.
2. No-op when row count is at or below the cap.
3. DB errors are swallowed (returns 0 instead of propagating).
4. The wiring from ``complete_session`` actually invokes the helper —
   no mocks here, end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz
from unittest.mock import patch

import pytest

from apps.crawl_sessions.models import CrawlEvent, CrawlSession
from apps.crawl_sessions.services.event_retention import (
    DEFAULT_CAP,
    cap_events_for_session,
)
from apps.crawl_sessions.services.session_manager import SessionManager
from apps.crawler.models import Website


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def website(db):
    return Website.objects.create(domain="example.test", name="Example")


@pytest.fixture
def session(db, website):
    return CrawlSession.objects.create(website=website)


def _bulk_create_events(session: CrawlSession, count: int) -> list[CrawlEvent]:
    """Create *count* events with strictly monotonic timestamps.

    ``CrawlEvent.timestamp`` has ``auto_now_add=True``, so we must
    override it explicitly via ``bulk_create`` (which bypasses
    ``auto_now`` semantics) AND via post-create UPDATE because some
    Django/PG combos still re-stamp on bulk_create. We do the UPDATE
    pass second to guarantee the desired ordering.
    """
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=dt_tz.utc)
    objs = [
        CrawlEvent(
            crawl_session=session,
            kind=CrawlEvent.KIND_CRAWL,
            url=f"https://example.test/page-{i}",
            message=f"event {i}",
        )
        for i in range(count)
    ]
    created = CrawlEvent.objects.bulk_create(objs)

    # Stamp deterministic timestamps so the trim has a stable ordering.
    for i, ev in enumerate(created):
        CrawlEvent.objects.filter(id=ev.id).update(
            timestamp=base + timedelta(seconds=i)
        )
    return created


# ─────────────────────────────────────────────────────────────
# Helper: retention behaviour
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_cap_deletes_oldest_when_over_cap(session):
    """Insert 5050 events; after capping at 5000 exactly 50 oldest must
    be deleted, and the remaining 5000 must be the newest by timestamp.
    """
    _bulk_create_events(session, 5050)
    assert CrawlEvent.objects.filter(crawl_session=session).count() == 5050

    deleted = cap_events_for_session(session, cap=5000)

    assert deleted == 50
    remaining = CrawlEvent.objects.filter(crawl_session=session)
    assert remaining.count() == 5000

    # The surviving rows must be the 5000 newest. Their messages were
    # numbered 0..5049 with timestamps in the same order, so the oldest
    # 50 (messages "event 0".."event 49") must be gone.
    surviving_msgs = set(remaining.values_list("message", flat=True))
    for i in range(50):
        assert f"event {i}" not in surviving_msgs
    for i in range(50, 5050):
        assert f"event {i}" in surviving_msgs


@pytest.mark.django_db
def test_cap_no_op_when_under_cap(session):
    """100 events with cap=5000 → nothing deleted, return value 0."""
    _bulk_create_events(session, 100)

    deleted = cap_events_for_session(session, cap=5000)

    assert deleted == 0
    assert CrawlEvent.objects.filter(crawl_session=session).count() == 100


@pytest.mark.django_db
def test_cap_no_op_when_exactly_at_cap(session):
    """Edge: row_count == cap should NOT trigger a delete pass."""
    _bulk_create_events(session, 50)

    deleted = cap_events_for_session(session, cap=50)

    assert deleted == 0
    assert CrawlEvent.objects.filter(crawl_session=session).count() == 50


@pytest.mark.django_db
def test_cap_swallows_errors(session):
    """If the underlying query raises, the helper must return 0 and not
    propagate. Critical because activity-feed cleanup must NEVER block
    session-completion bookkeeping.
    """
    # Patch ``CrawlEvent.objects.filter`` to always raise. The helper's
    # try/except wraps the whole body, so even the first call (count())
    # blowing up should be caught.
    def boom(*args, **kwargs):
        raise RuntimeError("simulated db failure")

    with patch.object(CrawlEvent.objects, "filter", side_effect=boom):
        result = cap_events_for_session(session)

    assert result == 0


# ─────────────────────────────────────────────────────────────
# Wiring: SessionManager.complete_session triggers the cap
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_complete_session_triggers_cap(session):
    """End-to-end wiring test: bulk-create 5050 events, call
    ``complete_session``, assert the table is trimmed down to <= 5000
    rows. Do NOT mock the helper — verify the real call path.

    Note: ``complete_session`` itself records a "completed" KIND_SESSION
    event, which slightly bumps the count. The cap is applied AFTER that
    event is recorded, so the final count must be exactly ``DEFAULT_CAP``.
    """
    SessionManager.start_session(session)  # required for duration_seconds path
    _bulk_create_events(session, 5050)

    SessionManager.complete_session(session)

    final_count = CrawlEvent.objects.filter(crawl_session=session).count()
    assert final_count == DEFAULT_CAP, (
        f"complete_session should trim to {DEFAULT_CAP} rows; got {final_count}"
    )


@pytest.mark.django_db
def test_fail_session_triggers_cap(session):
    """``fail_session`` is also a terminal state and must trim."""
    SessionManager.start_session(session)
    _bulk_create_events(session, 5050)

    SessionManager.fail_session(session, "boom")

    final_count = CrawlEvent.objects.filter(crawl_session=session).count()
    assert final_count == DEFAULT_CAP


@pytest.mark.django_db
def test_cancel_session_triggers_cap(session):
    """``cancel_session`` is also a terminal state and must trim."""
    SessionManager.start_session(session)
    _bulk_create_events(session, 5050)

    cancelled = SessionManager.cancel_session(session)
    assert cancelled is True

    final_count = CrawlEvent.objects.filter(crawl_session=session).count()
    assert final_count == DEFAULT_CAP
