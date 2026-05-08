"""Unit tests for ``OverviewService.get_overview``.

Exercises the Dashboard snapshot payload: top-level shape, KPI fidelity
to the CrawlSession aggregate columns, the health-score formula edges,
the p95 response-time edge cases, and the distinct-pages-with-issues
union behaviour.

Mirrors the pytest + ORM-fixture conventions of
``test_issue_service.py`` and ``test_tree_service.py``.
"""

from __future__ import annotations

import pytest

from apps.common import constants
from apps.crawl_sessions.models import CrawlSession, Link, Page
from apps.crawl_sessions.services.overview_service import OverviewService
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
    """Create a Page with sensible "no-issue" defaults.

    Defaults: 200 OK, valid (URL-derived) title + meta, depth 1, fast load,
    small body. Title defaults to a string derived from the URL so multiple
    pages don't collectively trip the ``duplicate-title`` issue. Override
    any field via kwargs to introduce specific issues.
    """
    defaults = {
        "http_status_code": 200,
        "title": f"Title for {url}",
        "meta_description": (
            "A reasonably long meta description that satisfies the "
            "70-char minimum easily for the test fixture defaults."
        ),
        "canonical_url": url,
        "crawl_depth": 1,
        "load_time_ms": 100.0,
        "content_size_bytes": 5_000,
        # Health sub-score thresholds: word_count < 100 is "thin content".
        # Default well above the threshold so per-test fixtures remain
        # clean unless a test explicitly exercises the predicate.
        "word_count": 500,
    }
    defaults.update(kwargs)
    return Page.objects.create(crawl_session=session, url=url, **defaults)


def _give_inlinks(session: CrawlSession, urls: list[str]) -> None:
    """Create internal inlinks for *urls* so they are not "orphan-pages".

    Each url gets a single inbound link from a synthetic source. Without
    this helper every test page would be flagged as an orphan, since the
    "orphan-pages" issue category fires when a reachable HTML page has
    zero non-self internal inlinks.
    """
    for u in urls:
        Link.objects.create(
            crawl_session=session,
            source_url="https://example.com/__hub__",
            target_url=u,
            link_type="internal",
        )


# ─────────────────────────────────────────────────────────────
# Top-level shape
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_overview_returns_all_keys(session):
    """Smoke test — all top-level keys present, KPIs/health/system_metrics
    are dict-shaped, and inner keys match the spec."""
    session.total_urls_discovered = 3
    session.total_urls_crawled = 2
    session.total_urls_failed = 1
    session.save()

    _make_page(session, "https://example.com/a", http_status_code=200)
    _make_page(session, "https://example.com/b", http_status_code=404)

    payload = OverviewService.get_overview(session)

    assert set(payload.keys()) >= {
        "session_id", "session_status",
        "started_at", "finished_at", "duration_seconds",
        "kpis", "health", "system_metrics",
    }
    assert payload["session_id"] == str(session.id)
    assert payload["session_status"] == constants.SESSION_STATUS_COMPLETED

    assert set(payload["kpis"].keys()) == {
        "total_urls", "crawled", "pending", "failed", "excluded",
    }
    assert set(payload["health"].keys()) == {
        "score", "band", "reasons", "sub_scores",
    }
    assert set(payload["health"]["sub_scores"].keys()) == {
        "technical", "content", "performance",
    }
    assert set(payload["system_metrics"].keys()) == {
        "avg_response_time_ms", "p95_response_time_ms",
        "median_depth", "max_depth_reached", "pages_with_issues",
    }


# ─────────────────────────────────────────────────────────────
# KPI fidelity
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_kpis_are_consistent_with_session_aggregates(session):
    """Aggregate columns are the source of truth for KPIs.

    pending = total_urls - crawled - failed - excluded, clamped at 0.
    """
    session.total_urls_discovered = 10
    session.total_urls_crawled = 6
    session.total_urls_failed = 2
    session.total_excluded = 1
    session.save()

    payload = OverviewService.get_overview(session)
    kpis = payload["kpis"]

    assert kpis["total_urls"] == 10
    assert kpis["crawled"] == 6
    assert kpis["failed"] == 2
    assert kpis["excluded"] == 1
    assert kpis["pending"] == 1  # 10 - 6 - 2 - 1


@pytest.mark.django_db
def test_kpis_pending_clamped_at_zero(session):
    """If aggregates drift mid-crawl, ``pending`` must not go negative."""
    session.total_urls_discovered = 1
    session.total_urls_crawled = 5
    session.save()

    payload = OverviewService.get_overview(session)
    assert payload["kpis"]["pending"] == 0


# ─────────────────────────────────────────────────────────────
# Health score (spec §5.4.1)
#
# Top score = round( min(100, index_eligible / max(crawled, 1) * 100) )
# Three sub-scores, each 0..100, are computed server-side.
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_health_score_perfect(session):
    """All-200, all index-eligible, no issues → score 100, band 'good'.

    Note: under the spec formula the top score now depends on
    ``total_index_eligible`` rather than crawl coverage, so this fixture
    sets it explicitly. With 2 crawled / 2 index_eligible the ratio is
    1.0 → 100.
    """
    session.total_urls_discovered = 2
    session.total_urls_crawled = 2
    session.total_urls_failed = 0
    session.total_index_eligible = 2
    session.save()

    urls = ["https://example.com/a", "https://example.com/b"]
    for u in urls:
        _make_page(session, u)
    # Ensure no page is flagged as an "orphan-pages" issue.
    _give_inlinks(session, urls)

    payload = OverviewService.get_overview(session)

    assert payload["health"]["score"] == 100
    assert payload["health"]["band"] == "good"
    assert payload["system_metrics"]["pages_with_issues"] == 0


@pytest.mark.django_db
def test_health_score_with_failures_and_issues(session):
    """No index-eligible pages → top score 0, band 'poor'.

    With 4 discovered / 2 crawled / 0 index_eligible the top-score
    ratio is 0/2 = 0. Sub-scores: one 500-failure page and one
    missing-title page → both Technical and Content < 100.
    """
    session.total_urls_discovered = 4
    session.total_urls_crawled = 2
    session.total_urls_failed = 2
    session.total_index_eligible = 0
    session.save()

    # Add the crawled pages, each with at least one issue.
    _make_page(session, "https://example.com/a", title="")  # missing-title
    _make_page(session, "https://example.com/b", http_status_code=500)

    payload = OverviewService.get_overview(session)

    assert payload["health"]["score"] == 0
    assert payload["health"]["band"] == "poor"
    # Sub-scores reflect the predicates the two pages trigger.
    sub = payload["health"]["sub_scores"]
    assert sub["technical"] < 100   # 500 status → -60/2 = -30 → 70
    assert sub["content"] < 100     # missing title → -50/2 = -25 → 75


@pytest.mark.django_db
def test_health_score_warn_band(session):
    """``index_eligible / crawled`` between 50 and 80 lands in 'warn'.

    With 10 crawled / 6 index_eligible the ratio is 0.6 → top score 60.
    """
    session.total_urls_discovered = 10
    session.total_urls_crawled = 10
    session.total_urls_failed = 0
    session.total_index_eligible = 6
    session.save()

    urls = [f"https://example.com/p{i}" for i in range(10)]
    for u in urls:
        _make_page(session, u)
    _give_inlinks(session, urls)  # avoid orphan-page penalty

    payload = OverviewService.get_overview(session)
    assert payload["health"]["score"] == 60
    assert payload["health"]["band"] == "warn"


@pytest.mark.django_db
def test_health_overall_uses_index_eligible(session):
    """Top score = round(index_eligible / crawled * 100). 8/10 → 80."""
    session.total_urls_discovered = 10
    session.total_urls_crawled = 10
    session.total_urls_failed = 0
    session.total_index_eligible = 8
    session.save()

    urls = [f"https://example.com/p{i}" for i in range(10)]
    for u in urls:
        _make_page(session, u)
    _give_inlinks(session, urls)

    payload = OverviewService.get_overview(session)
    assert payload["health"]["score"] == 80
    assert payload["health"]["band"] == "good"


@pytest.mark.django_db
def test_health_perfect_returns_100_per_subscore(session):
    """Clean fixture pages → all three sub-scores == 100."""
    session.total_urls_discovered = 3
    session.total_urls_crawled = 3
    session.total_index_eligible = 3
    session.save()

    urls = [f"https://example.com/p{i}" for i in range(3)]
    for u in urls:
        _make_page(session, u)
    _give_inlinks(session, urls)

    payload = OverviewService.get_overview(session)
    sub = payload["health"]["sub_scores"]
    assert sub["technical"] == 100
    assert sub["content"] == 100
    assert sub["performance"] == 100
    # Backwards-compat shape: reasons exposes the deltas, all 0 here.
    deltas = {r["label"]: r["delta"] for r in payload["health"]["reasons"]}
    assert deltas == {"Technical": 0, "Content": 0, "Performance": 0}


@pytest.mark.django_db
def test_technical_subscore_penalizes_failures(session):
    """5 of 10 pages with status >= 500 → technical < 100, others ~100.

    Per the formula: tech = 100 - (5/10)*60 = 70. Content/Performance
    untouched: 5xx pages aren't HTML-200 so they don't trip the
    title/meta predicates, and their default load_time_ms is fast.
    """
    session.total_urls_discovered = 10
    session.total_urls_crawled = 10
    session.total_index_eligible = 10
    session.save()

    urls = [f"https://example.com/p{i}" for i in range(10)]
    for i, u in enumerate(urls):
        _make_page(session, u, http_status_code=500 if i < 5 else 200)
    _give_inlinks(session, urls)

    payload = OverviewService.get_overview(session)
    sub = payload["health"]["sub_scores"]
    assert sub["technical"] == 70
    assert sub["content"] == 100
    assert sub["performance"] == 100


@pytest.mark.django_db
def test_content_subscore_penalizes_missing_title(session):
    """4 of 10 pages with title == '' → content < 100.

    Per the formula: content = 100 - (4/10)*50 = 80.
    """
    session.total_urls_discovered = 10
    session.total_urls_crawled = 10
    session.total_index_eligible = 10
    session.save()

    urls = [f"https://example.com/p{i}" for i in range(10)]
    for i, u in enumerate(urls):
        _make_page(session, u, title="" if i < 4 else f"Title {i}")
    _give_inlinks(session, urls)

    payload = OverviewService.get_overview(session)
    sub = payload["health"]["sub_scores"]
    assert sub["content"] == 80
    assert sub["technical"] == 100
    assert sub["performance"] == 100


@pytest.mark.django_db
def test_performance_subscore_penalizes_slow_pages(session):
    """Pages with load_time_ms > 1000 → performance < 100.

    3 pages at 1500ms (slow only) and 2 pages at 3000ms (slow AND
    very_slow) out of 10:
      perf = 100 - (5/10)*60 - (2/10)*40 = 100 - 30 - 8 = 62.
    """
    session.total_urls_discovered = 10
    session.total_urls_crawled = 10
    session.total_index_eligible = 10
    session.save()

    urls = [f"https://example.com/p{i}" for i in range(10)]
    for i, u in enumerate(urls):
        if i < 3:
            _make_page(session, u, load_time_ms=1500.0)  # slow
        elif i < 5:
            _make_page(session, u, load_time_ms=3000.0)  # slow + very_slow
        else:
            _make_page(session, u)  # default fast
    _give_inlinks(session, urls)

    payload = OverviewService.get_overview(session)
    sub = payload["health"]["sub_scores"]
    assert sub["performance"] == 62
    assert sub["technical"] == 100
    assert sub["content"] == 100


# ─────────────────────────────────────────────────────────────
# p95 response time — uses nearest-rank percentile.
# For [10, 20, ..., 100] (n=10, p=95):
#   rank = ceil(0.95 * 10) = 10 → sorted[9] = 100.
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_p95_with_known_distribution(session):
    """p95 of [10, 20, ..., 100] is 100 under nearest-rank (NIST)."""
    for i, lt in enumerate(range(10, 110, 10)):
        _make_page(session, f"https://example.com/p{i}", load_time_ms=float(lt))

    payload = OverviewService.get_overview(session)
    assert payload["system_metrics"]["p95_response_time_ms"] == 100.0


@pytest.mark.django_db
def test_p95_returns_none_when_no_pages(session):
    """Empty session → p95 is None (no data, no fabricated value)."""
    payload = OverviewService.get_overview(session)
    assert payload["system_metrics"]["p95_response_time_ms"] is None


# ─────────────────────────────────────────────────────────────
# Distinct pages-with-issues union
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_pages_with_issues_unions_categories(session):
    """A page hit by N categories still counts as one — distinct URLs."""
    # Page A — long title (>60) AND slow response → 2 categories, count once.
    _make_page(
        session,
        "https://example.com/a",
        title="x" * 80,           # long-title
        load_time_ms=1500.0,      # slow-response
    )
    # Page B — single category (4xx).
    _make_page(
        session,
        "https://example.com/b",
        http_status_code=404,
    )
    # Page C — clean, must not be counted.
    _make_page(session, "https://example.com/c")
    # Without inlinks every reachable HTML page is an "orphan-pages"
    # match. Give every page (including A & B) an inlink so the test
    # isolates the long-title / slow / 4xx categories.
    _give_inlinks(
        session,
        [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ],
    )

    payload = OverviewService.get_overview(session)
    assert payload["system_metrics"]["pages_with_issues"] == 2
