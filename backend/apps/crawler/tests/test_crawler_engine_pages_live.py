"""Live ``Page`` row persistence tests for ``CrawlerEngine``.

The engine's existing ``_flush_events_periodically`` task now ALSO
bulk-creates ``Page`` rows for any dicts appended to
``self.result.pages`` since the last tick, so the frontend Pages/URLs
page populates DURING a running crawl instead of staying empty until
``persist_crawl_results`` runs at end-of-crawl.

These tests verify:

1. ``Page`` rows land in the database during ``run()`` BEFORE
   ``persist_crawl_results`` would have written them. (We never call
   ``persist_crawl_results`` in this test — any rows present came from
   the live flush path.)
2. ``persist_crawl_results`` is idempotent with respect to rows
   already inserted by the live flush — no duplicate-key
   ``IntegrityError`` and total ``Page`` count stays correct (no
   double-counting).
3. A transient ``Page.objects.bulk_create`` failure is swallowed,
   the cursor advances past the broken batch (no infinite retry of
   the same rows), and the next batch lands.
4. With ``session_id`` falsy/empty, the periodic flusher is never
   started, so the live page flush is never invoked.

The fixture pattern (``@pytest.mark.django_db(transaction=True)``,
``_build_engine``, fetcher stub, hand-seeded frontier) mirrors
``test_crawler_engine_activity.py`` — see that module's header for
the cross-thread visibility rationale (the flusher runs in a thread
pool with its own DB connection, so the test thread needs
``transaction=True`` to see what the worker thread committed).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from apps.crawl_sessions.models import Page, CrawlSession
from apps.crawl_sessions.services.session_manager import SessionManager
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

    Identical shape to ``test_crawler_engine_activity._build_engine`` —
    bypasses robots & seeding so the test controls exactly which URLs
    go through the BFS loop.
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
    """Async fetcher stub: looks the URL up, else returns a 0-status error."""

    async def _fake_fetch(url: str) -> FetchResult:
        # Yield control so the periodic flusher can run between fetches.
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


def _ok_result(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        status_code=200,
        html=SYNTHETIC_HTML,
        headers={"content-type": "text/html; charset=utf-8"},
        redirect_chain=[],
        latency_ms=42.0,
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
# Test 1 — pages flush DURING run, not only via persist_crawl_results
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_pages_flush_during_run(session):
    """Live flusher must write ``Page`` rows during the BFS crawl.

    We never call ``SessionManager.persist_crawl_results`` in this test,
    so any ``Page`` rows present after ``run()`` returns must have been
    inserted by the engine's periodic flusher (or its final-flush
    sibling). This proves the live persist path is wired up — the
    Pages/URLs view will see rows mid-crawl rather than only at
    end-of-crawl.
    """
    urls = [
        "https://example.test/a",
        "https://example.test/b",
        "https://example.test/c",
    ]

    engine = _build_engine(str(session.id), flush_interval_s=0.05)
    engine.fetcher.fetch = _stub_fetch_factory(  # type: ignore[assignment]
        {u: _ok_result(u) for u in urls}
    )
    for u in urls:
        engine.frontier.add(url=u, depth=0, source="seed")

    asyncio.run(engine.run())

    # All three URLs must be present as Page rows. We do NOT call
    # persist_crawl_results — so this can only be the live flush.
    persisted_urls = set(
        Page.objects.filter(crawl_session=session).values_list("url", flat=True)
    )
    assert persisted_urls == set(urls), (
        f"Expected live-flushed pages for {urls}, got {persisted_urls}"
    )

    # Cursor must have caught up to the producer.
    assert engine._page_persist_cursor == len(engine.result.pages)


# ─────────────────────────────────────────────────────────────
# Test 2 — persist_crawl_results is idempotent against the live flush
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_persist_crawl_results_idempotent_with_live_flush(session):
    """End-of-crawl ``persist_crawl_results`` must not duplicate live rows.

    After ``engine.run()`` returns (with the live flush having already
    inserted Page rows), the canonical end-of-crawl writer is invoked
    explicitly. The unique constraint on (crawl_session, url) plus
    ``ignore_conflicts=True`` in ``persist_crawl_results`` must make the
    second write a true no-op: no IntegrityError, and the final Page
    count equals the number of distinct URLs crawled (no doubles).
    """
    urls = [
        "https://example.test/p1",
        "https://example.test/p2",
    ]

    engine = _build_engine(str(session.id), flush_interval_s=0.05)
    engine.fetcher.fetch = _stub_fetch_factory(  # type: ignore[assignment]
        {u: _ok_result(u) for u in urls}
    )
    for u in urls:
        engine.frontier.add(url=u, depth=0, source="seed")

    result = asyncio.run(engine.run())

    # Live flush already wrote these.
    pre_count = Page.objects.filter(crawl_session=session).count()
    assert pre_count == len(urls), (
        f"Live flush should have written {len(urls)} pages, got {pre_count}"
    )

    # Refresh the session row from DB before handing it back — the
    # aggregate flusher updated it via .filter().update() which doesn't
    # touch the in-memory instance.
    session.refresh_from_db()

    # Canonical end-of-crawl writer. Must NOT raise on the duplicate
    # rows — relies on the (crawl_session, url) unique constraint plus
    # ignore_conflicts=True.
    SessionManager.persist_crawl_results(session, result)

    # Total count unchanged: no duplicates inserted.
    post_count = Page.objects.filter(crawl_session=session).count()
    assert post_count == pre_count, (
        f"persist_crawl_results duplicated rows: {pre_count} -> {post_count}"
    )


# ─────────────────────────────────────────────────────────────
# Test 3 — bulk_create errors are swallowed and cursor advances
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_pages_flush_swallows_db_errors(session):
    """A transient ``Page.objects.bulk_create`` failure must be swallowed.

    The cursor must advance past the broken batch so we don't retry
    the same rows on every subsequent tick (which would either keep
    failing or, worse, succeed and double-count). The NEXT batch
    must then land normally.

    Concurrency=1 + slow fetch ensures the two URLs land in DIFFERENT
    flusher ticks (so we get >= 2 distinct page-flush calls — the
    first to fail, the second to succeed).
    """
    urls = [
        "https://example.test/x",
        "https://example.test/y",
    ]

    engine = _build_engine(str(session.id), flush_interval_s=0.05)
    engine.concurrency = 1

    fixtures = {u: _ok_result(u) for u in urls}

    async def slow_fetch(url):
        await asyncio.sleep(0.20)  # ~4 * flush_interval_s, per URL
        return fixtures.get(
            url, FetchResult(url=url, status_code=0, error="not stubbed"),
        )

    engine.fetcher.fetch = slow_fetch  # type: ignore[assignment]
    for u in urls:
        engine.frontier.add(url=u, depth=0, source="seed")

    real_bulk_create = Page.objects.bulk_create
    state = {"calls": 0}

    def flaky_bulk_create(objs, *args, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("simulated db error")
        return real_bulk_create(objs, *args, **kwargs)

    with patch.object(Page.objects, "bulk_create", side_effect=flaky_bulk_create):
        # Crawl must complete cleanly despite the failed batch.
        asyncio.run(engine.run())

    # The flusher must have called bulk_create at least twice (first
    # failing, second succeeding). If only one call happened, the test
    # didn't exercise the recovery path.
    assert state["calls"] >= 2, (
        f"Page flusher must keep running after a failed batch; "
        f"only saw {state['calls']} calls"
    )

    # Cursor must have advanced past EVERY page dict the producer added,
    # not just the survivors. Otherwise we'd keep retrying the dead rows.
    assert engine._page_persist_cursor == len(engine.result.pages)

    # At least one page must have landed (the post-failure batch).
    surviving = Page.objects.filter(crawl_session=session).count()
    assert surviving >= 1, "Recovery batch must write at least one Page row"


# ─────────────────────────────────────────────────────────────
# Test 4 — no session_id → no live page flush
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_no_session_id_skips_page_flush():
    """With ``session_id=""``, the periodic flusher task is never spawned.

    Asserted explicitly so that a future refactor that starts the
    flusher unconditionally (e.g. for some other piece of bookkeeping)
    can't silently start writing Page rows for the no-session case
    without an FK to attach them to.
    """
    engine = CrawlerEngine(
        domain="https://example.test",
        max_depth=1,
        max_urls=5,
        concurrency=1,
        request_delay=0.0,
        respect_robots=False,
        session_id="",  # ← falsy: gates the flusher start in run()
        flush_interval_s=0.02,
    )

    async def _noop():
        return None

    engine._fetch_robots = _noop  # type: ignore[assignment]
    engine._seed_frontier = _noop  # type: ignore[assignment]

    # Stub fetcher so the BFS loop does some work.
    url = "https://example.test/solo"
    engine.fetcher.fetch = _stub_fetch_factory({url: _ok_result(url)})  # type: ignore[assignment]
    engine.frontier.add(url=url, depth=0, source="seed")

    with patch.object(
        Page.objects, "bulk_create", wraps=Page.objects.bulk_create,
    ) as bulk_spy:
        asyncio.run(engine.run())

    # Flusher never started → live page flush never invoked.
    assert bulk_spy.call_count == 0, (
        f"Page.objects.bulk_create must not be called when session_id is "
        f"empty; saw {bulk_spy.call_count} calls"
    )
