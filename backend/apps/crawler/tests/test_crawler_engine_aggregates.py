"""Live session-aggregate flush tests for ``CrawlerEngine``.

The engine's existing ``_flush_events_periodically`` task now also writes
the in-memory KPI counts (``total_urls_discovered``/``crawled``/``failed``/
``skipped``, ``max_depth_reached``, ``avg_response_time_ms``) back onto
the ``CrawlSession`` row every ``flush_interval_s`` seconds, so the
Dashboard's KPI strip and health gauge update DURING a running crawl
instead of only at end-of-crawl.

These tests verify:

1. After a run, the session row's aggregates reflect the live counts the
   engine accumulated (proves the flusher wired the aggregate update path
   up — the final flusher tick fires before ``persist_crawl_results``).
2. A transient ``CrawlSession.objects.filter().update`` failure is
   swallowed and the engine still completes the run and tail-flushes the
   activity events successfully.
3. When ``session_id`` is empty / falsy, the flusher does not start, so
   no aggregate UPDATE is ever issued.

The fixture pattern (``@pytest.mark.django_db(transaction=True)``,
``_build_engine``, fetcher stub, hand-seeded frontier) mirrors
``test_crawler_engine_activity.py`` — see that module's header for the
cross-thread visibility rationale.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock

import pytest

from apps.crawl_sessions.models import CrawlEvent, CrawlSession
from apps.crawler.models import Website
from apps.crawler.services.crawler_engine import CrawlerEngine
from apps.crawler.services.fetcher import FetchResult


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
SYNTHETIC_HTML = (
    "<!doctype html><html><head><title>T</title></head>"
    "<body><h1>H</h1><p>x</p></body></html>"
)


def _build_engine(session_id: str, *, flush_interval_s: float = 0.05) -> CrawlerEngine:
    """Build an engine wired for offline testing.

    Bypasses ``_fetch_robots`` / ``_seed_frontier`` so the test seeds the
    frontier directly and controls exactly which URLs the BFS loop sees.
    """
    engine = CrawlerEngine(
        domain="https://example.test",
        max_depth=3,
        max_urls=50,
        concurrency=2,
        request_delay=0.0,
        respect_robots=False,
        session_id=session_id,
        flush_interval_s=flush_interval_s,
    )

    async def _noop():
        return None

    engine._fetch_robots = _noop  # type: ignore[assignment]
    engine._seed_frontier = _noop  # type: ignore[assignment]
    return engine


def _stub_fetch_factory(urls: dict[str, FetchResult]):
    async def _fake_fetch(url: str) -> FetchResult:
        await asyncio.sleep(0)
        if url in urls:
            return urls[url]
        return FetchResult(
            url=url,
            status_code=0,
            error="not stubbed",
            latency_ms=1.0,
        )

    return _fake_fetch


def _ok_result(url: str, latency_ms: float = 42.0) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        status_code=200,
        html=SYNTHETIC_HTML,
        headers={"content-type": "text/html; charset=utf-8"},
        redirect_chain=[],
        latency_ms=latency_ms,
        content_size=len(SYNTHETIC_HTML),
        is_https=url.startswith("https://"),
        content_type="text/html; charset=utf-8",
    )


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def website(db):
    return Website.objects.create(domain="example.test", name="Example")


@pytest.fixture
def session(db, website):
    return CrawlSession.objects.create(website=website)


# ─────────────────────────────────────────────────────────────
# Test 1 — aggregates land on the session row by end-of-run
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_aggregates_flush_during_run(session):
    """The flusher's final tick (right before ``persist_crawl_results``)
    must have written live aggregate counts back onto the session row.

    The test fetches three synthetic 200 URLs, lets the engine run to
    completion, then asserts the session row's aggregate columns reflect
    the engine's in-memory counts. This proves the periodic flusher's
    aggregate-update branch is wired up — if it weren't, the columns
    would still be 0 because no ``persist_crawl_results`` call follows
    inside ``run()`` itself.
    """
    urls = [
        "https://example.test/a",
        "https://example.test/b",
        "https://example.test/c",
    ]

    engine = _build_engine(str(session.id), flush_interval_s=0.05)
    engine.fetcher.fetch = _stub_fetch_factory(  # type: ignore[assignment]
        {u: _ok_result(u, latency_ms=10.0) for u in urls}
    )

    for u in urls:
        engine.frontier.add(url=u, depth=0, source="seed")

    asyncio.run(engine.run())

    session.refresh_from_db()

    # Discovered: 3 seeds (no new links extracted from the fixture HTML's
    # <p>x</p> body, so frontier stays at the seeded count).
    assert session.total_urls_discovered == engine.frontier.total_discovered
    assert session.total_urls_discovered == 3

    # Crawled: 3 successful fetches.
    assert session.total_urls_crawled == engine.frontier.total_crawled
    assert session.total_urls_crawled == 3

    # No failures expected on this happy path.
    assert session.total_urls_failed == 0

    # No skip events from the synthetic fixture (no excluded paths set).
    assert session.total_urls_skipped == 0

    # Max depth = 0 (seeds only).
    assert session.max_depth_reached == 0

    # Avg response time matches the rounded mean of the latencies.
    assert session.avg_response_time_ms == pytest.approx(10.0, rel=0.01)


# ─────────────────────────────────────────────────────────────
# Test 2 — DB errors on the aggregate update must be swallowed
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_aggregates_swallow_db_errors(session):
    """If ``CrawlSession.objects.filter(...).update`` raises on one tick,
    the engine must:
      a) NOT propagate the error out of ``run()``.
      b) Continue running and tail-flush activity events successfully.

    We patch ``_flush_session_aggregates_sync`` to raise on the first
    call. The engine must complete cleanly and at least one CrawlEvent
    row must still land — proving the aggregate-flush failure didn't
    short-circuit the events flush in the same tick.
    """
    urls = [
        "https://example.test/x",
        "https://example.test/y",
    ]

    engine = _build_engine(str(session.id), flush_interval_s=0.05)

    # concurrency=1 + per-URL sleep > flush_interval_s ensures the BFS
    # loop straddles AT LEAST two flusher ticks: the first one raises,
    # the second proves the engine kept calling the aggregate flush.
    engine.concurrency = 1

    fixtures = {u: _ok_result(u) for u in urls}

    async def slow_fetch(url):
        await asyncio.sleep(0.20)  # ~4 * flush_interval_s, per URL
        return fixtures.get(
            url,
            FetchResult(url=url, status_code=0, error="not stubbed"),
        )

    engine.fetcher.fetch = slow_fetch  # type: ignore[assignment]

    for u in urls:
        engine.frontier.add(url=u, depth=0, source="seed")

    state = {"calls": 0}
    real_flush = engine._flush_session_aggregates_sync

    def flaky_flush():
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("simulated db error on aggregate update")
        return real_flush()

    engine._flush_session_aggregates_sync = flaky_flush  # type: ignore[assignment]

    # Must NOT raise.
    result = asyncio.run(engine.run())
    assert result is not None

    # The flusher kept ticking after the failed update (we needed at
    # least one more tick to write the final live snapshot).
    assert state["calls"] >= 2, (
        "Aggregate flush must keep being called after a failed update"
    )

    # Activity events still landed in the DB (events flush ran in the
    # same tick BEFORE the aggregate flush, so it wasn't blocked).
    surviving = CrawlEvent.objects.filter(crawl_session=session).count()
    assert surviving >= 1


# ─────────────────────────────────────────────────────────────
# Test 3 — no session_id => no aggregate update calls
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_no_session_id_means_no_flush():
    """When the engine is constructed with ``session_id=""`` (e.g. ad-hoc
    crawl with no persisted session), the periodic flusher task is never
    even started — see ``run()``'s ``if self.session_id:`` guard. So
    ``_flush_session_aggregates_sync`` must never be invoked, and no
    UPDATE on ``CrawlSession`` may be issued by the engine.
    """
    engine = _build_engine(session_id="", flush_interval_s=0.02)

    urls = [
        "https://example.test/p",
    ]
    engine.fetcher.fetch = _stub_fetch_factory(  # type: ignore[assignment]
        {u: _ok_result(u) for u in urls}
    )
    for u in urls:
        engine.frontier.add(url=u, depth=0, source="seed")

    spy = MagicMock(side_effect=engine._flush_session_aggregates_sync)
    engine._flush_session_aggregates_sync = spy  # type: ignore[assignment]

    with patch.object(CrawlSession.objects, "filter") as filter_spy:
        asyncio.run(engine.run())

    spy.assert_not_called()
    # The engine itself must not have touched CrawlSession.objects.filter
    # for an aggregate update either.
    assert filter_spy.call_count == 0
