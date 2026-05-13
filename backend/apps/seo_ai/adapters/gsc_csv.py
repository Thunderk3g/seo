"""Google Search Console CSV adapter.

Reads the per-site CSVs produced by ``test/gsc_pull.py``. The script
emits one CSV per ``(search_type × dimension_set)`` combination — e.g.
``web__query.csv``, ``web__page.csv``, ``web__query_page.csv``. We
expose convenience methods for the slices the agents actually use:
top queries by clicks, top under-performing queries (ctr-below-curve),
and the page-level performance table.

The adapter is purely file-backed. Refreshing the data is the
``gsc_pull.py`` script's job — we just read what's on disk.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.conf import settings

logger = logging.getLogger("seo.ai.adapters.gsc")


@dataclass
class GSCQueryRow:
    query: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCPageRow:
    page: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCSummary:
    """Site-level rollup. Numbers are over the GSC retention window."""

    total_queries: int
    total_pages: int
    total_clicks: int
    total_impressions: int
    avg_ctr: float
    avg_position: float
    top_queries_by_clicks: list[GSCQueryRow]
    underperforming_queries: list[GSCQueryRow]      # position 4–15 with low CTR
    high_impression_low_click_queries: list[GSCQueryRow]
    top_pages_by_clicks: list[GSCPageRow]
    snapshot_path: str


class GSCCSVAdapter:
    """Read-only access to the GSC CSV directory.

    ``site_url`` matches the directory name produced by
    ``gsc_pull.safe_name`` — typically ``www.bajajlifeinsurance.com``.
    """

    def __init__(
        self,
        root_dir: Path | str | None = None,
        *,
        site_dirname: str = "www.bajajlifeinsurance.com",
    ) -> None:
        self.root_dir = (
            Path(root_dir) if root_dir else settings.SEO_AI["gsc_data_dir"]
        )
        self.site_dir = self.root_dir / site_dirname

    def _path(self, name: str) -> Path:
        return self.site_dir / name

    # ── readers ──────────────────────────────────────────────────────

    def queries(self, *, limit: int | None = None) -> list[GSCQueryRow]:
        return _read_query_csv(self._path("web__query.csv"), limit=limit)

    def pages(self, *, limit: int | None = None) -> list[GSCPageRow]:
        return _read_page_csv(self._path("web__page.csv"), limit=limit)

    # ── rollups ───────────────────────────────────────────────────────

    def summary(self, *, sample_size: int = 50) -> GSCSummary:
        queries = self.queries()
        pages = self.pages()
        total_clicks = sum(q.clicks for q in queries)
        total_impr = sum(q.impressions for q in queries)
        avg_ctr = (total_clicks / total_impr) if total_impr else 0.0
        avg_pos = (
            sum(q.position * q.impressions for q in queries) / total_impr
            if total_impr
            else 0.0
        )

        top_clicks = sorted(queries, key=lambda r: r.clicks, reverse=True)[:sample_size]

        underperforming = [
            q
            for q in queries
            if 4.0 <= q.position <= 15.0
            and q.impressions >= 500
            and q.ctr < _expected_ctr(q.position) * 0.6
        ]
        underperforming.sort(key=lambda r: r.impressions, reverse=True)

        hi_imp_low_clk = [
            q
            for q in queries
            if q.impressions >= 1000 and q.clicks <= max(2, int(q.impressions * 0.005))
        ]
        hi_imp_low_clk.sort(key=lambda r: r.impressions, reverse=True)

        top_pages = sorted(pages, key=lambda r: r.clicks, reverse=True)[:sample_size]

        return GSCSummary(
            total_queries=len(queries),
            total_pages=len(pages),
            total_clicks=total_clicks,
            total_impressions=total_impr,
            avg_ctr=avg_ctr,
            avg_position=avg_pos,
            top_queries_by_clicks=top_clicks,
            underperforming_queries=underperforming[:sample_size],
            high_impression_low_click_queries=hi_imp_low_clk[:sample_size],
            top_pages_by_clicks=top_pages,
            snapshot_path=str(self.site_dir),
        )


# ── helpers ──────────────────────────────────────────────────────────────


def _read_query_csv(path: Path, *, limit: int | None) -> list[GSCQueryRow]:
    if not path.exists():
        logger.warning("gsc csv missing: %s", path)
        return []
    out: list[GSCQueryRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                out.append(
                    GSCQueryRow(
                        query=row["query"],
                        clicks=int(float(row.get("clicks") or 0)),
                        impressions=int(float(row.get("impressions") or 0)),
                        ctr=float(row.get("ctr") or 0),
                        position=float(row.get("position") or 0),
                    )
                )
            except (KeyError, ValueError):
                continue
            if limit and len(out) >= limit:
                break
    return out


def _read_page_csv(path: Path, *, limit: int | None) -> list[GSCPageRow]:
    if not path.exists():
        logger.warning("gsc csv missing: %s", path)
        return []
    out: list[GSCPageRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                out.append(
                    GSCPageRow(
                        page=row["page"],
                        clicks=int(float(row.get("clicks") or 0)),
                        impressions=int(float(row.get("impressions") or 0)),
                        ctr=float(row.get("ctr") or 0),
                        position=float(row.get("position") or 0),
                    )
                )
            except (KeyError, ValueError):
                continue
            if limit and len(out) >= limit:
                break
    return out


# Industry CTR curve by SERP position (web, average across verticals).
# Used to flag rankings that under-click — i.e. the page is visible but
# the title/meta is not earning the clicks Google's traffic distribution
# would predict. Numbers are commonly cited Advanced Web Ranking 2024.
_CTR_CURVE: list[float] = [
    0.0,   # index 0 placeholder
    0.395, # pos 1
    0.184, # pos 2
    0.108, # pos 3
    0.073, # pos 4
    0.053, # pos 5
    0.040, # pos 6
    0.032, # pos 7
    0.026, # pos 8
    0.022, # pos 9
    0.019, # pos 10
    0.016, # pos 11
    0.014, # pos 12
    0.012, # pos 13
    0.010, # pos 14
    0.008, # pos 15
]


def _expected_ctr(position: float) -> float:
    """Linear-interpolated CTR for a (fractional) average position."""
    if position <= 1:
        return _CTR_CURVE[1]
    if position >= 15:
        return _CTR_CURVE[15]
    low = int(position)
    frac = position - low
    return _CTR_CURVE[low] * (1 - frac) + _CTR_CURVE[low + 1] * frac
