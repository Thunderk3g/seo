"""Crawler CSV adapter.

Reads the file-backed crawler outputs already produced by
``apps.crawler.engine`` (``backend/data/crawl_results.csv`` and
siblings). The crawler is the canonical source of truth for "what does
our site look like to a crawl bot" — every other agent layer reads
through this adapter rather than re-opening the CSVs, so cache logic
and column-rename migrations have one place to live.

Returned shapes are plain dicts / dataclasses, never pandas — pandas
adds a chunky dependency for ≤200 k row datasets and the rest of the
agent pipeline is dict-oriented.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from django.conf import settings

logger = logging.getLogger("seo.ai.adapters.crawler")


@dataclass
class CrawlerSummary:
    """Site-level rollup the Technical Auditor consumes as its input."""

    total_pages: int
    ok_pages: int
    error_pages: int
    redirect_pages: int
    status_breakdown: dict[str, int]  # "200" -> 3500
    avg_word_count: float
    median_response_ms: float
    thin_content_count: int            # < 300 words
    fat_response_count: int            # > 2000 ms
    title_missing_count: int
    error_404_count: int
    error_5xx_count: int
    connection_error_count: int
    orphan_url_count: int              # discovered but never crawled
    discovered_edge_count: int
    sample_titles: list[str]           # first ~20 for prompt context
    snapshot_path: str                 # for evidence_refs


class CrawlerCSVAdapter:
    """Read-only access to the crawler's CSV outputs."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else settings.SEO_AI["data_dir"]

    def _path(self, name: str) -> Path:
        return self.data_dir / name

    # ── Low-level readers ─────────────────────────────────────────────

    def _iter_csv(self, filename: str) -> Iterable[dict[str, str]]:
        path = self._path(filename)
        if not path.exists():
            logger.warning("crawler csv missing: %s", path)
            return iter(())
        return _iter_rows(path)

    # ── High-level rollup ─────────────────────────────────────────────

    def summary(self) -> CrawlerSummary:
        status_breakdown: dict[str, int] = {}
        word_counts: list[int] = []
        response_times: list[int] = []
        thin = 0
        fat = 0
        title_missing = 0
        ok = 0
        errors = 0
        redirects = 0
        connection_err = 0
        e404 = 0
        e5xx = 0
        sample_titles: list[str] = []
        seen_urls: set[str] = set()

        for row in self._iter_csv("crawl_results.csv"):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            seen_urls.add(url)
            status = (row.get("status_code") or "").strip()
            status_breakdown[status] = status_breakdown.get(status, 0) + 1
            wc = _safe_int(row.get("word_count"))
            if wc is not None:
                word_counts.append(wc)
                if wc < 300:
                    thin += 1
            rt = _safe_int(row.get("response_time_ms"))
            if rt is not None:
                response_times.append(rt)
                if rt > 2000:
                    fat += 1
            title = (row.get("title") or "").strip()
            if not title:
                title_missing += 1
            elif len(sample_titles) < 20:
                sample_titles.append(title[:120])
            try:
                code = int(status)
            except (TypeError, ValueError):
                code = 0
            if 200 <= code < 300:
                ok += 1
            elif 300 <= code < 400:
                redirects += 1
            elif code == 404:
                e404 += 1
                errors += 1
            elif 500 <= code < 600:
                e5xx += 1
                errors += 1
            elif code >= 400:
                errors += 1

        for _ in self._iter_csv("crawl_errors_connectionerror.csv"):
            connection_err += 1

        edges = 0
        discovered_urls: set[str] = set()
        for row in self._iter_csv("crawl_discovered.csv"):
            edges += 1
            target = (row.get("target_url") or row.get("url") or "").strip()
            if target:
                discovered_urls.add(target)

        orphan = max(0, len(discovered_urls - seen_urls))
        total = len(seen_urls)

        return CrawlerSummary(
            total_pages=total,
            ok_pages=ok,
            error_pages=errors,
            redirect_pages=redirects,
            status_breakdown=status_breakdown,
            avg_word_count=(sum(word_counts) / len(word_counts)) if word_counts else 0.0,
            median_response_ms=_median(response_times),
            thin_content_count=thin,
            fat_response_count=fat,
            title_missing_count=title_missing,
            error_404_count=e404,
            error_5xx_count=e5xx,
            connection_error_count=connection_err,
            orphan_url_count=orphan,
            discovered_edge_count=edges,
            sample_titles=sample_titles,
            snapshot_path=str(self.data_dir),
        )

    def thin_content_urls(self, limit: int = 25) -> list[dict[str, object]]:
        """Sample of pages with word_count < 300, for evidence references."""
        rows: list[dict[str, object]] = []
        for row in self._iter_csv("crawl_results.csv"):
            wc = _safe_int(row.get("word_count"))
            if wc is None or wc >= 300:
                continue
            rows.append(
                {
                    "url": row.get("url", ""),
                    "title": (row.get("title") or "")[:120],
                    "word_count": wc,
                    "status_code": row.get("status_code"),
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def slow_response_urls(self, limit: int = 25) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for row in self._iter_csv("crawl_results.csv"):
            rt = _safe_int(row.get("response_time_ms"))
            if rt is None or rt <= 2000:
                continue
            rows.append(
                {
                    "url": row.get("url", ""),
                    "response_time_ms": rt,
                    "title": (row.get("title") or "")[:120],
                }
            )
            if len(rows) >= limit:
                break
        rows.sort(key=lambda r: r["response_time_ms"], reverse=True)
        return rows[:limit]

    def error_404_urls(self, limit: int = 25) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for row in self._iter_csv("crawl_404_errors.csv"):
            rows.append(
                {
                    "url": row.get("url", ""),
                    "found_on": row.get("source_url") or row.get("referer") or "",
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def state_summary(self) -> dict[str, object]:
        """Read crawl_state.json if present (last crawl meta)."""
        path = self._path("crawl_state.json")
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("crawl_state.json unreadable: %s", exc)
            return {}


# ── helpers ─────────────────────────────────────────────────────────────


def _iter_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def _safe_int(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _median(xs: list[int]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    if n % 2 == 1:
        return float(s[n // 2])
    return (s[n // 2 - 1] + s[n // 2]) / 2
