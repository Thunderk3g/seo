"""Unit tests for ``TreeService.build_tree``.

Exercises the folder-hierarchy logic: empty session, root pages,
nested folders, count aggregation, deterministic sort order,
``max_depth`` clamping, and URL-normalization edge cases (query
strings, trailing slashes, double slashes).
"""

from __future__ import annotations

import pytest

from apps.common import constants
from apps.crawl_sessions.models import CrawlSession, Page
from apps.crawl_sessions.services.tree_service import TreeService
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
    """Create a Page with a default 200 status code."""
    defaults = {"http_status_code": 200}
    defaults.update(kwargs)
    return Page.objects.create(crawl_session=session, url=url, **defaults)


def _child(node: dict, name: str) -> dict:
    """Return the immediate child with the given name (or fail loudly)."""
    for child in node["children"]:
        if child["name"] == name:
            return child
    raise AssertionError(
        f"Child {name!r} not found under {node['path']!r}; "
        f"have {[c['name'] for c in node['children']]}"
    )


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_empty_session_returns_root_only(session):
    """No pages → root has zero counts and no children."""
    tree = TreeService.build_tree(session)

    assert tree == {
        "name": "/",
        "path": "/",
        "url_count": 0,
        "direct_url_count": 0,
        "children": [],
        "max_depth_reached": 0,
    }


@pytest.mark.django_db
def test_single_root_page(session):
    """A single ``https://x.com/`` lands on the root, no children."""
    _make_page(session, "https://x.com/")

    tree = TreeService.build_tree(session)

    assert tree["name"] == "/"
    assert tree["path"] == "/"
    assert tree["url_count"] == 1
    assert tree["direct_url_count"] == 1
    assert tree["children"] == []


@pytest.mark.django_db
def test_two_top_level_folders(session):
    """Two pages in different top-level folders → root has two children."""
    _make_page(session, "https://x.com/blog/post-1")
    _make_page(session, "https://x.com/products/p-1")

    tree = TreeService.build_tree(session)

    assert tree["url_count"] == 2
    assert tree["direct_url_count"] == 0
    assert {c["name"] for c in tree["children"]} == {"blog", "products"}
    for child in tree["children"]:
        assert child["url_count"] == 1


@pytest.mark.django_db
def test_nested_folder_count_aggregation(session):
    """Counts roll up from leaves to ancestors via post-order traversal."""
    _make_page(session, "https://x.com/blog/")
    _make_page(session, "https://x.com/blog/2024/")
    _make_page(session, "https://x.com/blog/2024/post-1")

    tree = TreeService.build_tree(session)

    blog = _child(tree, "blog")
    assert blog["path"] == "/blog"
    assert blog["url_count"] == 3
    assert blog["direct_url_count"] == 1

    y2024 = _child(blog, "2024")
    assert y2024["path"] == "/blog/2024"
    assert y2024["url_count"] == 2
    assert y2024["direct_url_count"] == 1

    post = _child(y2024, "post-1")
    assert post["path"] == "/blog/2024/post-1"
    assert post["url_count"] == 1
    assert post["direct_url_count"] == 1
    assert post["children"] == []


@pytest.mark.django_db
def test_children_sorted_by_count_desc(session):
    """Top-level children appear in descending ``url_count`` order."""
    # /alpha → 1 page; /beta → 5 pages; /gamma → 3 pages.
    _make_page(session, "https://x.com/alpha/p-1")
    for i in range(5):
        _make_page(session, f"https://x.com/beta/p-{i}")
    for i in range(3):
        _make_page(session, f"https://x.com/gamma/p-{i}")

    tree = TreeService.build_tree(session)
    names = [c["name"] for c in tree["children"]]
    counts = [c["url_count"] for c in tree["children"]]

    assert names == ["beta", "gamma", "alpha"]
    assert counts == [5, 3, 1]


@pytest.mark.django_db
def test_children_with_equal_count_sorted_by_name(session):
    """Tie-break: equal counts sort by name ascending."""
    _make_page(session, "https://x.com/beta/p")
    _make_page(session, "https://x.com/alpha/p")

    tree = TreeService.build_tree(session)
    names = [c["name"] for c in tree["children"]]

    assert names == ["alpha", "beta"]


@pytest.mark.django_db
def test_max_depth_caps_tree(session):
    """Pages deeper than ``max_depth`` collapse into the deepest ancestor."""
    _make_page(session, "https://x.com/a/b/c/d/e/f")

    tree = TreeService.build_tree(session, max_depth=2)

    a = _child(tree, "a")
    b = _child(a, "b")

    # /b is the depth-2 ancestor of the deeply-nested page; everything
    # below it is folded into b.direct_url_count and no nodes are created.
    assert b["children"] == []
    assert b["direct_url_count"] == 1
    assert b["url_count"] == 1
    assert a["url_count"] == 1
    assert tree["url_count"] == 1


@pytest.mark.django_db
def test_query_string_is_stripped(session):
    """``?q=1`` and ``?q=2`` collapse to the same node."""
    _make_page(session, "https://x.com/page?q=1")
    _make_page(session, "https://x.com/page?q=2")

    tree = TreeService.build_tree(session)
    page = _child(tree, "page")

    assert page["direct_url_count"] == 2
    assert page["url_count"] == 2
    assert page["children"] == []


@pytest.mark.django_db
def test_trailing_slash_normalized(session):
    """``/foo`` and ``/foo/`` map to the same node."""
    _make_page(session, "https://x.com/foo")
    _make_page(session, "https://x.com/foo/")

    tree = TreeService.build_tree(session)
    foo = _child(tree, "foo")

    assert foo["direct_url_count"] == 2
    assert foo["url_count"] == 2
    # Only one top-level child must exist.
    assert len(tree["children"]) == 1


@pytest.mark.django_db
def test_empty_path_segments_skipped(session):
    """Empty segments from ``//`` are dropped from the hierarchy."""
    _make_page(session, "https://x.com//foo//bar")

    tree = TreeService.build_tree(session)
    foo = _child(tree, "foo")
    bar = _child(foo, "bar")

    assert bar["direct_url_count"] == 1
    # No empty-string child must appear at any level.
    for node in (tree, foo, bar):
        for child in node["children"]:
            assert child["name"] != ""


@pytest.mark.django_db
def test_max_depth_reached_field(session):
    """``max_depth_reached`` is the deepest level with at least one page."""
    _make_page(session, "https://x.com/")           # depth 0
    _make_page(session, "https://x.com/a/b")        # depth 2
    _make_page(session, "https://x.com/a/b/c/d")    # depth 4

    tree = TreeService.build_tree(session)

    assert tree["max_depth_reached"] == 4


@pytest.mark.django_db
def test_isolation_between_sessions(website, session):
    """Pages from another session must not leak into this session's tree."""
    other = CrawlSession.objects.create(
        website=website,
        status=constants.SESSION_STATUS_COMPLETED,
    )
    _make_page(other, "https://x.com/leak/page-1")
    _make_page(other, "https://x.com/leak/page-2")

    _make_page(session, "https://x.com/mine/page")

    tree = TreeService.build_tree(session)

    assert tree["url_count"] == 1
    names = {c["name"] for c in tree["children"]}
    assert names == {"mine"}
    assert "leak" not in names
