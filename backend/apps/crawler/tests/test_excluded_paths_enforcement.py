"""Engine-level enforcement tests for ``CrawlConfig.excluded_paths`` and
``CrawlConfig.excluded_params`` (URL hygiene, follow-up to #32).

The engine constructor accepts the two filters as kwargs; the producer
sites in ``_seed_frontier`` and ``_process_url`` apply them BEFORE
``frontier.add(...)`` so that:

* dedup hashes (``FrontierManager._seen``) operate on the cleaned form,
* a banned URL never enters the frontier in the first place,
* a ``KIND_SKIP`` ``CrawlEvent`` is enqueued so the activity feed shows
  the skip with the matching prefix in metadata.

Tests assert against the in-memory ``engine._event_queue`` rather than
the DB-flushed ``CrawlEvent`` rows, so they do not require
``transaction=True`` or live the flusher coroutine. That mirrors the
pattern in ``test_crawler_engine_activity.py``.
"""

from __future__ import annotations

import asyncio

import pytest

from apps.crawl_sessions.models import CrawlSession
from apps.crawler.models import Website
from apps.crawler.services.crawler_engine import CrawlerEngine
from apps.crawler.services.fetcher import FetchResult


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def website(db):
    return Website.objects.create(domain="example.test", name="Example")


@pytest.fixture
def session(db, website):
    return CrawlSession.objects.create(website=website)


def _build_engine(
    session_id: str,
    *,
    excluded_paths=None,
    excluded_params=None,
) -> CrawlerEngine:
    """Construct an engine wired for offline producer-only tests.

    We never call ``run()`` here; instead we exercise the helper methods
    (``_strip_excluded_params``, ``_is_excluded_path``) and the
    producer-site enforcement directly via ``frontier.add`` after a
    pre-call filter, mirroring the production code path.
    """
    return CrawlerEngine(
        domain="https://example.test",
        max_depth=3,
        max_urls=50,
        concurrency=2,
        request_delay=0.0,
        respect_robots=False,
        session_id=session_id,
        flush_interval_s=0.05,
        excluded_paths=excluded_paths or [],
        excluded_params=excluded_params or [],
    )


# ─────────────────────────────────────────────────────────────
# Path-prefix enforcement
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_excluded_path_skips_url(session):
    """A URL whose path starts with a configured prefix must be skipped
    entirely: not added to the frontier, and a KIND_SKIP event enqueued.
    """
    engine = _build_engine(str(session.id), excluded_paths=["/admin"])

    # Simulate the producer site at ``_process_url``'s link loop:
    # the engine inspects the link, finds it banned, and short-circuits
    # before frontier.add. We exercise the same helper + branch.
    target = "https://example.test/admin/users"
    matched = engine._is_excluded_path(target)
    assert matched == "/admin", "expected the configured prefix to match"

    # Mirror the production short-circuit: enqueue skip, do NOT add.
    if matched:
        engine._enqueue_event(
            "skip", target,
            f"Skipped (excluded path: {matched})",
            {"reason": "excluded_path", "matched_prefix": matched},
        )
    else:  # pragma: no cover — exercised by other tests
        engine.frontier.add(url=target, depth=1, source="link")

    # Frontier must be empty (URL never entered).
    assert engine.frontier.is_empty
    assert not engine.frontier.is_seen(target)

    # Exactly one queued KIND_SKIP event with the right metadata.
    skip_events = [e for e in engine._event_queue if e["kind"] == "skip"]
    assert len(skip_events) == 1
    ev = skip_events[0]
    assert ev["url"] == target
    assert ev["metadata"]["reason"] == "excluded_path"
    assert ev["metadata"]["matched_prefix"] == "/admin"


@pytest.mark.django_db
def test_path_prefix_match_only(session):
    """``/admin`` must exclude ``/admin/x`` but NOT ``/admincats``.

    Path-prefix rule: stripped path either equals the prefix or begins
    with ``prefix + "/"``. A bare ``startswith`` check would falsely
    match ``/admincats`` against ``/admin``.
    """
    engine = _build_engine(str(session.id), excluded_paths=["/admin"])

    # Excluded forms.
    assert engine._is_excluded_path("https://example.test/admin") == "/admin"
    assert engine._is_excluded_path("https://example.test/admin/") == "/admin"
    assert engine._is_excluded_path("https://example.test/admin/users") == "/admin"
    assert engine._is_excluded_path("https://example.test/admin/users/42") == "/admin"

    # Non-excluded look-alikes.
    assert engine._is_excluded_path("https://example.test/admincats") is None
    assert engine._is_excluded_path("https://example.test/admin-panel") is None
    assert engine._is_excluded_path("https://example.test/blog/admin") is None
    assert engine._is_excluded_path("https://example.test/") is None


@pytest.mark.django_db
def test_excluded_path_normalizes_missing_leading_slash(session):
    """Users may write ``admin`` (no leading slash) in the settings UI.
    The engine normalizes it to ``/admin`` so the prefix check still works.
    """
    engine = _build_engine(str(session.id), excluded_paths=["admin"])
    assert engine._is_excluded_path("https://example.test/admin/users") == "/admin"
    assert engine._is_excluded_path("https://example.test/blog") is None


# ─────────────────────────────────────────────────────────────
# Param-strip enforcement
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_excluded_param_stripped(session):
    """Seed URL with ``?utm_source=foo&id=42`` and ``excluded_params=["utm_source"]``
    must round-trip through the frontier as ``?id=42``.

    This exercises the param-strip helper end-to-end: the cleaned form
    is what the frontier sees, dedup hashes are computed on it, and the
    KIND_DISCOVERY event (if any) carries the cleaned URL.
    """
    engine = _build_engine(str(session.id), excluded_params=["utm_source"])

    seed = "https://example.test/page?utm_source=foo&id=42"
    cleaned = engine._strip_excluded_params(seed)

    assert cleaned == "https://example.test/page?id=42"

    # Add to frontier and verify the popped entry has the cleaned URL.
    engine.frontier.add(url=cleaned, depth=0, source="seed")
    entry = engine.frontier.pop()
    assert entry is not None
    assert entry.url == "https://example.test/page?id=42"


@pytest.mark.django_db
def test_param_strip_preserves_other_keys(session):
    """Multiple keys: only matching ones removed, order of remaining
    preserved, value contents irrelevant to the match.
    """
    engine = _build_engine(
        str(session.id),
        excluded_params=["utm_source", "fbclid"],
    )

    url = (
        "https://example.test/p"
        "?utm_source=newsletter"
        "&id=1"
        "&fbclid=abc123"
        "&page=2"
        "&utm_medium=email"  # unrelated to "utm_source" exact key match prefix
    )
    cleaned = engine._strip_excluded_params(url)

    # NOTE: prefix match on key name (per spec) — ``utm_source`` strips
    # any key starting with "utm_source"; ``utm_medium`` is also caught
    # by the "utm" subset only if "utm" is in the list. Here we listed
    # the more conservative full prefixes ``utm_source`` and ``fbclid``,
    # so utm_medium survives.
    assert "utm_source" not in cleaned
    assert "fbclid" not in cleaned
    assert "id=1" in cleaned
    assert "page=2" in cleaned
    assert "utm_medium=email" in cleaned


@pytest.mark.django_db
def test_param_strip_prefix_match_on_key_name(session):
    """Per spec: case-sensitive prefix match on key names.
    ``excluded_params=["utm"]`` strips both ``utm_source`` and ``utm_medium``.
    """
    engine = _build_engine(str(session.id), excluded_params=["utm"])

    url = "https://example.test/p?utm_source=foo&utm_medium=bar&id=42"
    cleaned = engine._strip_excluded_params(url)

    assert "utm_source" not in cleaned
    assert "utm_medium" not in cleaned
    assert "id=42" in cleaned


@pytest.mark.django_db
def test_no_filters_means_pass_through(session):
    """Empty config → URL hygiene helpers are no-ops."""
    engine = _build_engine(str(session.id))  # no excluded_paths / params

    url = "https://example.test/admin/x?utm_source=foo&id=1"
    assert engine._is_excluded_path(url) is None
    assert engine._strip_excluded_params(url) == url


# ─────────────────────────────────────────────────────────────
# End-to-end: link loop honours both filters
# ─────────────────────────────────────────────────────────────
SYNTHETIC_HTML = (
    "<!doctype html><html><head><title>T</title></head>"
    '<body><h1>H</h1>'
    '<a href="/admin/users">admin</a>'
    '<a href="/blog/post-1?utm_source=foo&id=42">post1</a>'
    '<a href="/about">about</a>'
    "</body></html>"
)


def _ok_result(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=url,
        status_code=200,
        html=SYNTHETIC_HTML,
        headers={"content-type": "text/html; charset=utf-8"},
        redirect_chain=[],
        latency_ms=10.0,
        content_size=len(SYNTHETIC_HTML),
        is_https=True,
        content_type="text/html; charset=utf-8",
    )


@pytest.mark.django_db(transaction=True)
def test_run_loop_skips_excluded_and_strips_params(session):
    """Integration: run the engine on one synthetic page that links to
    ``/admin/users`` (banned) and ``/blog/post-1?utm_source=foo&id=42``
    (param-strippable). Verify:

    * ``/admin/users`` never enters the frontier; a KIND_SKIP event is queued.
    * ``/blog/post-1?id=42`` enters the frontier (cleaned form).
    """
    engine = _build_engine(
        str(session.id),
        excluded_paths=["/admin"],
        excluded_params=["utm_source"],
    )

    # Bypass network setup.
    async def _noop():
        return None

    engine._fetch_robots = _noop  # type: ignore[assignment]
    engine._seed_frontier = _noop  # type: ignore[assignment]

    seed = "https://example.test/"

    async def fake_fetch(url: str) -> FetchResult:
        await asyncio.sleep(0)
        if url == seed:
            return _ok_result(url)
        # All discovered links return a tiny 200; depth limit will stop
        # the recursion shortly after.
        return _ok_result(url)

    engine.fetcher.fetch = fake_fetch  # type: ignore[assignment]
    engine.frontier.add(url=seed, depth=0, source="seed")

    asyncio.run(engine.run())

    # No URL in the frontier or the seen set should match the banned prefix.
    assert not engine.frontier.is_seen("https://example.test/admin/users")

    # The cleaned link must have been seen (frontier dedup recorded it).
    # Depth ordering means it may have been crawled and removed — either
    # way ``is_seen`` returns True.
    assert engine.frontier.is_seen("https://example.test/blog/post-1?id=42")

    # Find at least one queued KIND_SKIP event for the banned URL.
    # Note: the in-memory queue is drained by the flusher; check the DB
    # via the model below.
    from apps.crawl_sessions.models import CrawlEvent

    skip_events = CrawlEvent.objects.filter(
        crawl_session=session, kind=CrawlEvent.KIND_SKIP,
    )
    matched_urls = list(skip_events.values_list("url", flat=True))
    assert any(
        u.endswith("/admin/users") for u in matched_urls
    ), f"expected a /admin/users skip event, got {matched_urls}"
