"""Site-tree (folder hierarchy) service for the visualizations page.

Builds a recursive folder tree from the URL paths of every ``Page`` row
in a ``CrawlSession``. Each node tracks two counts:

- ``direct_url_count`` — pages whose path is exactly this node.
- ``url_count``        — inclusive count: this node plus all descendants.

Children at every level are sorted by ``url_count`` descending, then by
``name`` ascending for stable, deterministic output.

Design notes
------------
- Single SQL query: ``Page.objects.filter(...).only('url')``. The whole
  tree is then built in Python — trivial for the v1 cap of ~50k URLs.
- The model carries ``directory_segment`` (top-level only). Deeper folder
  hierarchy is derived from the URL path itself via ``urllib.parse``.
- ``max_depth`` caps the tree. Pages deeper than the cap are folded into
  the deepest allowed ancestor's ``direct_url_count`` so totals always
  reconcile to the page count.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from apps.crawl_sessions.models import CrawlSession, Page


def _path_segments(url: str) -> list[str]:
    """Return the list of non-empty path segments for *url*.

    - Strips query string and fragment via ``urlsplit``.
    - Drops empty segments (caused by trailing slashes or ``//``).
    - Returns ``[]`` for the site root (``/``).
    """
    if not url:
        return []
    try:
        path = urlsplit(url).path or ""
    except ValueError:
        path = url.split("?", 1)[0].split("#", 1)[0]

    return [seg for seg in path.split("/") if seg]


def _new_node(name: str, path: str) -> dict:
    """Allocate a fresh tree node with zero counts and no children."""
    return {
        "name": name,
        "path": path,
        "url_count": 0,
        "direct_url_count": 0,
        # ``children`` is kept as a dict during build (segment → node) for
        # O(1) lookup; converted to a sorted list during finalization.
        "_children": {},
    }


def _finalize(node: dict) -> dict:
    """Recursively post-process a node.

    - Computes inclusive ``url_count`` (post-order: direct + children).
    - Converts the ``_children`` dict into a sorted ``children`` list
      (count desc, then name asc).
    """
    children = [_finalize(child) for child in node["_children"].values()]
    children.sort(key=lambda c: (-c["url_count"], c["name"]))

    total = node["direct_url_count"] + sum(c["url_count"] for c in children)

    return {
        "name": node["name"],
        "path": node["path"],
        "url_count": total,
        "direct_url_count": node["direct_url_count"],
        "children": children,
    }


def _max_depth(node: dict, current: int = 0) -> int:
    """Deepest level (root = 0) that has at least one page beneath it.

    A node "has a page" iff its ``direct_url_count > 0``. A node with
    only zero-count descendants does not increase depth (in practice
    this never happens because intermediate nodes are only created when
    a page exists at or below them, but we still check defensively).
    """
    deepest = current if node["direct_url_count"] > 0 else -1
    for child in node["children"]:
        child_deepest = _max_depth(child, current + 1)
        if child_deepest > deepest:
            deepest = child_deepest
    return deepest if deepest >= 0 else current


class TreeService:
    """Build a folder-hierarchy tree for a crawl session.

    Static methods only — mirrors ``IssueService`` and ``AnalyticsService``.
    """

    @staticmethod
    def build_tree(session: CrawlSession, max_depth: int = 4) -> dict:
        """Return a recursive folder tree with per-folder URL counts.

        Each ``Page``'s URL path is split by ``/``, and each segment
        becomes a node. Counts at each node are inclusive — i.e. the
        count at ``/blog`` includes ``/blog/post-1`` and ``/blog/2024/post-2``.

        Args:
            session:   the crawl session to summarise.
            max_depth: hard cap on tree depth (root = 0). Pages deeper
                       than this are folded into the deepest allowed
                       ancestor's ``direct_url_count``.

        Returns:
            ``{
                "name": "/",                # root
                "path": "/",
                "url_count": int,           # total pages under this node
                "direct_url_count": int,    # pages exactly at this path
                "children": [<recursive>],  # count desc, name asc
                "max_depth_reached": int,   # deepest level with a page
            }``
        """
        root = _new_node(name="/", path="/")

        urls = (
            Page.objects
            .filter(crawl_session=session)
            .values_list("url", flat=True)
        )

        for url in urls:
            segments = _path_segments(url)

            # Site root (``/`` or empty path) → bump root's direct count.
            if not segments:
                root["direct_url_count"] += 1
                continue

            # Walk segments, creating intermediate nodes as needed,
            # but stop at ``max_depth`` levels below the root and fold
            # the page into the deepest allowed ancestor.
            node = root
            current_path_parts: list[str] = []
            for level, seg in enumerate(segments, start=1):
                current_path_parts.append(seg)

                if level > max_depth:
                    # Page lives below the cap — collapse into ``node``,
                    # which is the depth-``max_depth`` ancestor.
                    break

                child = node["_children"].get(seg)
                if child is None:
                    child = _new_node(
                        name=seg,
                        path="/" + "/".join(current_path_parts),
                    )
                    node["_children"][seg] = child
                node = child

            node["direct_url_count"] += 1

        finalized = _finalize(root)
        finalized["max_depth_reached"] = _max_depth(finalized)
        return finalized
