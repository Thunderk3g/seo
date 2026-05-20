"""Internal PageRank — Ahrefs "Page Rating" / Screaming Frog "Link Score".

Phase 4b service. Reads the link graph from crawl_discovered.csv
(every ``(discovered_from, url)`` edge) and runs networkx's pagerank
iteration. Results expose the canonical "URLs that carry the most
internal link equity" view that every serious SEO tool ships.

Output shape per URL:

  * pagerank — float in [0, 1] summing to 1.0 across the whole graph
  * pagerank_score — int 0-100 LOG-rescaled like Ahrefs' Page Rating
    (Ahrefs uses log because raw PageRank is heavily skewed toward
    homepage; log distributes the score across a useful range)
  * in_degree, out_degree — raw link counts for context

Cache: results are memoised per crawl_discovered.csv mtime. The graph
construction + PageRank iteration cost ~1-3s on 10k nodes; this means
the first request after a crawl pays the compute cost and subsequent
requests are <10ms.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from typing import Any

from ..conf import settings


@dataclass
class PageRankEntry:
    url: str
    pagerank: float
    pagerank_score: int
    in_degree: int
    out_degree: int


# Cache: {mtime_ns: [PageRankEntry, ...]}
_CACHE: dict[float, list[PageRankEntry]] = {}


def _load_edges() -> list[tuple[str, str]]:
    """Read every (discovered_from, url) edge from crawl_discovered.csv.

    Self-loops are filtered. Both endpoints must be non-empty for the
    edge to count toward link equity.
    """
    path = settings.data_path / "crawl_discovered.csv"
    out: list[tuple[str, str]] = []
    if not path.exists():
        return out
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = (row.get("discovered_from") or "").strip()
            dst = (row.get("url") or "").strip()
            if not src or not dst or src == dst:
                continue
            out.append((src, dst))
    return out


def _compute(edges: list[tuple[str, str]]) -> list[PageRankEntry]:
    """Build the directed graph + run PageRank iteration."""
    try:
        import networkx as nx
    except ImportError:
        # networkx not installed — degrade to a degree-based fallback
        # so callers still get a result even when the dep is missing.
        # The fallback isn't a real PageRank, just in/out degree counts
        # rescaled to 0-100.
        return _degree_fallback(edges)

    g = nx.DiGraph()
    for src, dst in edges:
        g.add_edge(src, dst)
    if g.number_of_nodes() == 0:
        return []

    try:
        pr = nx.pagerank(
            g, alpha=0.85, max_iter=100, tol=1.0e-6,
        )
    except nx.PowerIterationFailedConvergence:
        # Sparse graphs sometimes fail to converge; widen the
        # tolerance and try once more.
        pr = nx.pagerank(g, alpha=0.85, max_iter=200, tol=1.0e-4)

    in_degs = dict(g.in_degree())
    out_degs = dict(g.out_degree())

    # Log-rescale to 0-100 like Ahrefs Page Rating. Use the max value
    # so the strongest URL gets 100 and weak nodes spread across the
    # log scale instead of all bunching near 0.
    if pr:
        max_pr = max(pr.values()) or 1.0
        min_pr = min(pr.values()) or max_pr / 1000.0
        log_min = math.log(max(min_pr, 1e-12))
        log_max = math.log(max(max_pr, 1e-12))
        log_range = max(log_max - log_min, 1e-12)
    else:
        log_min = 0
        log_range = 1

    out: list[PageRankEntry] = []
    for url, score in pr.items():
        log_score = math.log(max(score, 1e-12))
        normalized = int(round((log_score - log_min) / log_range * 100))
        out.append(PageRankEntry(
            url=url,
            pagerank=round(score, 8),
            pagerank_score=max(0, min(100, normalized)),
            in_degree=int(in_degs.get(url, 0)),
            out_degree=int(out_degs.get(url, 0)),
        ))
    out.sort(key=lambda e: -e.pagerank)
    return out


def _degree_fallback(edges: list[tuple[str, str]]) -> list[PageRankEntry]:
    """networkx-missing fallback. Uses raw in-degree as the proxy.
    Worse than real PageRank but lets the UI render something."""
    from collections import Counter
    in_c: Counter = Counter()
    out_c: Counter = Counter()
    nodes: set[str] = set()
    for src, dst in edges:
        in_c[dst] += 1
        out_c[src] += 1
        nodes.add(src)
        nodes.add(dst)
    if not nodes:
        return []
    max_in = max(in_c.values()) if in_c else 1
    return sorted(
        [
            PageRankEntry(
                url=u,
                pagerank=in_c.get(u, 0) / sum(in_c.values()) if in_c else 0.0,
                pagerank_score=int(round(in_c.get(u, 0) / max_in * 100)) if max_in else 0,
                in_degree=in_c.get(u, 0),
                out_degree=out_c.get(u, 0),
            )
            for u in nodes
        ],
        key=lambda e: -e.in_degree,
    )


def all_entries() -> list[PageRankEntry]:
    """Return the full PageRank table. Cached per discovered-CSV mtime."""
    path = settings.data_path / "crawl_discovered.csv"
    mtime = path.stat().st_mtime if path.exists() else 0
    cached = _CACHE.get(mtime)
    if cached is not None:
        return cached
    entries = _compute(_load_edges())
    _CACHE.clear()
    _CACHE[mtime] = entries
    return entries


def top_n(n: int = 20) -> list[dict[str, Any]]:
    """Top-N URLs by PageRank, as JSON-safe dicts."""
    cap = max(1, min(int(n), 500))
    return [
        {
            "url": e.url,
            "pagerank": e.pagerank,
            "pagerank_score": e.pagerank_score,
            "in_degree": e.in_degree,
            "out_degree": e.out_degree,
        }
        for e in all_entries()[:cap]
    ]


def orphans(*, max_in_degree: int = 0) -> list[dict[str, Any]]:
    """URLs with no inbound internal links (or below a threshold).
    Returns slim dicts ordered by out_degree desc (orphans that
    THEMSELVES link out are higher value to fix)."""
    out: list[PageRankEntry] = [
        e for e in all_entries() if e.in_degree <= max_in_degree
    ]
    out.sort(key=lambda e: -e.out_degree)
    return [
        {
            "url": e.url,
            "in_degree": e.in_degree,
            "out_degree": e.out_degree,
            "pagerank_score": e.pagerank_score,
        }
        for e in out[:200]
    ]


def summary() -> dict[str, Any]:
    """Dashboard tile aggregates."""
    entries = all_entries()
    if not entries:
        return {
            "computed": False,
            "node_count": 0,
            "edge_count": 0,
            "top_url": None,
            "orphan_count": 0,
        }
    return {
        "computed": True,
        "node_count": len(entries),
        "edge_count": sum(e.out_degree for e in entries),
        "top_url": entries[0].url,
        "top_score": entries[0].pagerank_score,
        "orphan_count": sum(1 for e in entries if e.in_degree == 0),
    }
