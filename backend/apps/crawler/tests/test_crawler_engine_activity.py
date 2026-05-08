"""Live activity feed tests for ``CrawlerEngine`` (Phase 2.5 follow-up #19).

The engine now keeps an in-memory ``_event_queue`` and runs a sibling
``_flush_events_periodically`` coroutine that drains it into ``CrawlEvent``
rows via ``bulk_create`` while the BFS crawl loop is still running.

These tests verify:

1. Per-URL ``CrawlEvent`` rows land in the database during ``run()`` (not
   only at end-of-crawl synthesised by ``views.py:activity``).
2. A transient ``bulk_create`` failure is swallowed and the next batch lands.
3. When nothing happens that produces an event (e.g. a robots-blocked-only
   frontier with ``session_id`` falsy), ``bulk_create`` is never called with
   an empty list — i.e. no spurious empty flushes.

Implementation notes for future maintainers
-------------------------------------------

The flusher dispatches its sync work through
``sync_to_async(thread_sensitive=False)``, which routes to a thread pool
with its own DB connection. Default ``@pytest.mark.django_db`` wraps the
test in a transaction on the test thread, so worker-thread writes are
invisible from the test thread (and vice versa) until the transaction
commits. We therefore use ``@pytest.mark.django_db(transaction=True)``
on the live-flush tests that need cross-thread visibility.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

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

    - Bypass ``_fetch_robots`` (no network).
    - Bypass ``_seed_frontier``; the test seeds the frontier directly so
      we control which URLs the BFS loop will process.
    - Keep ``respect_robots=False`` so ``robots.is_allowed`` doesn't gate.
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

    # No-op robots / seeding to keep the test purely in-memory.
    async def _noop():
        return None

    engine._fetch_robots = _noop  # type: ignore[assignment]
    engine._seed_frontier = _noop  # type: ignore[assignment]
    return engine


def _stub_fetch_factory(urls: dict[str, FetchResult]):
    """Return an async stub that mimics ``Fetcher.fetch``.

    Looks the URL up in a fixture map; if not present, returns a 404-like
    error result so the engine takes the error branch deterministically.
    """

    async def _fake_fetch(url: str) -> FetchResult:
        # Yield control so the flusher can run between fetches in the
        # event loop.
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
# Test 1 — events flush DURING run, not only after
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_events_flush_during_run(session):
    """Engine must emit CrawlEvent rows for each fetched URL, written via
    the periodic flusher (not synthesised end-of-crawl from Pages).

    We observe this indirectly but reliably: after ``run()`` returns,
    raw ``CrawlEvent`` rows exist in the database for each fetched URL.
    Synthesised activity rows live in memory inside the activity view,
    not the DB; so any CrawlEvent row in the DB came from the flusher.
    """
    urls = [
        "https://example.test/a",
        "https://example.test/b",
        "https://example.test/c",
    ]

    engine = _build_engine(str(session.id), flush_interval_s=0.05)

    # Stub the fetcher with synthetic 200 responses.
    engine.fetcher.fetch = _stub_fetch_factory(  # type: ignore[assignment]
        {u: _ok_result(u) for u in urls}
    )

    # Hand-seed the frontier directly so the engine processes exactly
    # these three URLs and stops.
    for u in urls:
        engine.frontier.add(url=u, depth=0, source="seed")

    asyncio.run(engine.run())

    # One CrawlEvent per fetched URL with kind="crawl" must exist.
    crawl_events = CrawlEvent.objects.filter(
        crawl_session=session, kind=CrawlEvent.KIND_CRAWL,
    )
    crawl_urls = set(crawl_events.values_list("url", flat=True))
    assert crawl_urls == set(urls), (
        f"Expected crawl events for {urls}, got {crawl_urls}"
    )

    # Each CrawlEvent row carries metadata pushed by the producer site.
    for ev in crawl_events:
        assert ev.metadata.get("status_code") == 200
        assert "latency_ms" in ev.metadata


# ─────────────────────────────────────────────────────────────
# Test 2 — flush failures must not break the crawl
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_flush_failure_does_not_break_crawl(session):
    """If ``CrawlEvent.objects.bulk_create`` raises once, the engine must
    swallow the error, drop that batch, and continue. The next successful
    flush then writes the remaining events.
    """
    urls = [
        "https://example.test/x",
        "https://example.test/y",
    ]

    engine = _build_engine(str(session.id), flush_interval_s=0.05)

    # Concurrency=1 + per-URL sleep > flush_interval_s ensures the two
    # crawl events land in DIFFERENT flusher ticks. Otherwise the whole
    # batch can finish inside one tick and the "second batch lands"
    # assertion has nothing to assert (the only batch was the failed one).
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

    real_bulk_create = CrawlEvent.objects.bulk_create
    state = {"calls": 0}

    def flaky_bulk_create(objs, *args, **kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("simulated db error")
        return real_bulk_create(objs, *args, **kwargs)

    with patch.object(CrawlEvent.objects, "bulk_create", side_effect=flaky_bulk_create):
        # Crawl must not raise.
        result = asyncio.run(engine.run())

    assert result is not None  # run() returned cleanly.
    assert state["calls"] >= 2, (
        "Flusher must keep running after a failed bulk_create"
    )

    # At least one crawl event must have landed (the second-or-later batch
    # succeeded). We don't assert all of them — the first batch was lost
    # by design, since the activity feed is best-effort.
    surviving = CrawlEvent.objects.filter(
        crawl_session=session, kind=CrawlEvent.KIND_CRAWL,
    ).count()
    assert surviving >= 1


# ─────────────────────────────────────────────────────────────
# Test 3 — empty queue must not trigger empty bulk_creates
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db(transaction=True)
def test_no_events_when_queue_empty(session):
    """When nothing produces events (no seeded URLs at all), the flusher
    must not call ``bulk_create`` with an empty list. Otherwise we'd
    waste DB round-trips on every tick of an idle crawl.
    """
    engine = _build_engine(str(session.id), flush_interval_s=0.02)

    # Empty frontier: BFS loop exits on the first iteration.
    # No fetcher stub needed.

    with patch.object(
        CrawlEvent.objects, "bulk_create", wraps=CrawlEvent.objects.bulk_create,
    ) as bulk_spy:
        asyncio.run(engine.run())

    # The flusher MAY tick zero or more times; whatever it does, every
    # call must have a non-empty list.
    for call in bulk_spy.call_args_list:
        objs = call.args[0] if call.args else call.kwargs.get("objs", [])
        assert objs, "bulk_create called with empty list"
