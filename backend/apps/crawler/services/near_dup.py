"""Near-duplicate detection via MinHash + LSH — Phase 4b.

Screaming Frog uses MinHash for the same purpose. Detects pages whose
TITLE + URL combined is similar enough to another page that Google
will likely treat them as duplicates and drop all but one from SERP.

90% Jaccard similarity threshold = SF default. Lower (e.g. 0.8)
catches more but introduces more false positives.

The cluster algorithm:

  1. Tokenize (title + URL path) to lowercase words.
  2. Compute MinHash signature (128 perms).
  3. Insert into MinHashLSH (threshold=0.9).
  4. For each URL, query LSH for matches.
  5. Build undirected clusters via union-find.

Output: list of clusters, each with cluster_id + member URLs +
representative title. The Page Explorer surfaces clusters > 1 as
"near-duplicate group" badges; the Excel report adds a per-cluster
sheet for triage.

Cache: keyed by crawl_results.csv mtime. ~3-5s to compute on 10k
URLs (the LSH index is what dominates); subsequent requests <50ms.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from typing import Any

from ..conf import settings


_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class DuplicateCluster:
    cluster_id: int
    member_urls: list[str]
    representative_title: str
    cluster_size: int


_CACHE: dict[float, list[DuplicateCluster]] = {}


def _tokens(title: str, url: str) -> set[str]:
    """Lowercase token set across title + URL path tokens."""
    blob = " ".join([title or "", url or ""]).lower()
    return set(_TOKEN.findall(blob))


def _load_url_titles() -> list[tuple[str, str]]:
    """Read every OK URL + title from crawl_results.csv."""
    path = settings.data_path / "crawl_results.csv"
    if not path.exists():
        return []
    out: list[tuple[str, str]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("status_code") or "").strip() != "200":
                continue
            url = (row.get("url") or "").strip()
            title = (row.get("title") or "").strip()
            if url and title:  # need both for similarity to make sense
                out.append((url, title))
    return out


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            return x
        # Iterative path-compression.
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _compute(rows: list[tuple[str, str]], *, threshold: float = 0.9) -> list[DuplicateCluster]:
    """Run MinHash + LSH; cluster via union-find."""
    if not rows:
        return []
    try:
        from datasketch import MinHash, MinHashLSH
    except ImportError:
        # datasketch missing — fall back to exact-title duplicate
        # grouping so the UI still renders something.
        return _exact_title_fallback(rows)

    lsh = MinHashLSH(threshold=threshold, num_perm=128)
    signatures: dict[str, MinHash] = {}

    for url, title in rows:
        tokens = _tokens(title, url)
        if not tokens:
            continue
        mh = MinHash(num_perm=128)
        for t in tokens:
            mh.update(t.encode("utf-8"))
        signatures[url] = mh
        lsh.insert(url, mh)

    uf = _UnionFind()
    for url, mh in signatures.items():
        for match in lsh.query(mh):
            if match != url:
                uf.union(url, match)

    # Group by cluster root.
    clusters: dict[str, list[str]] = {}
    titles_lookup = dict(rows)
    for url in signatures:
        root = uf.find(url)
        clusters.setdefault(root, []).append(url)

    out: list[DuplicateCluster] = []
    next_id = 1
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        # Use the shortest URL's title as representative — usually the
        # canonical-feeling one in a paginated set.
        members.sort(key=lambda u: len(u))
        rep_title = titles_lookup.get(members[0], "")
        out.append(DuplicateCluster(
            cluster_id=next_id,
            member_urls=members,
            representative_title=rep_title,
            cluster_size=len(members),
        ))
        next_id += 1
    out.sort(key=lambda c: -c.cluster_size)
    return out


def _exact_title_fallback(rows: list[tuple[str, str]]) -> list[DuplicateCluster]:
    """datasketch-missing fallback. Groups by exact lowercased title."""
    from collections import defaultdict
    groups: dict[str, list[str]] = defaultdict(list)
    for url, title in rows:
        key = (title or "").strip().lower()
        if key:
            groups[key].append(url)
    out: list[DuplicateCluster] = []
    next_id = 1
    for title, urls in groups.items():
        if len(urls) < 2:
            continue
        urls.sort(key=lambda u: len(u))
        out.append(DuplicateCluster(
            cluster_id=next_id,
            member_urls=urls,
            representative_title=title,
            cluster_size=len(urls),
        ))
        next_id += 1
    out.sort(key=lambda c: -c.cluster_size)
    return out


def all_clusters(*, threshold: float = 0.9) -> list[DuplicateCluster]:
    """Compute (or fetch cached) near-duplicate clusters."""
    path = settings.data_path / "crawl_results.csv"
    mtime = path.stat().st_mtime if path.exists() else 0
    cache_key = mtime + threshold * 0.000001
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    out = _compute(_load_url_titles(), threshold=threshold)
    _CACHE.clear()
    _CACHE[cache_key] = out
    return out


def top_clusters(n: int = 20, *, threshold: float = 0.9) -> list[dict[str, Any]]:
    """Top-N clusters by member count (JSON-safe)."""
    cap = max(1, min(int(n), 200))
    return [
        {
            "cluster_id": c.cluster_id,
            "cluster_size": c.cluster_size,
            "representative_title": c.representative_title,
            "member_urls": c.member_urls[:50],
            "more_members": max(0, c.cluster_size - 50),
        }
        for c in all_clusters(threshold=threshold)[:cap]
    ]


def summary(*, threshold: float = 0.9) -> dict[str, Any]:
    """Dashboard tile aggregates."""
    clusters = all_clusters(threshold=threshold)
    return {
        "cluster_count": len(clusters),
        "total_dupes": sum(c.cluster_size for c in clusters),
        "largest_cluster_size": clusters[0].cluster_size if clusters else 0,
        "largest_cluster_title": clusters[0].representative_title if clusters else "",
        "threshold": threshold,
    }
