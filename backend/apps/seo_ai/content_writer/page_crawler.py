"""Single-page deep crawler — fetch ONE URL with full structural capture.

A thin parallel-fetch layer over ``apps.crawler.views.crawl_live``. The
crawler already extracts everything we need (title, meta, headings,
internal/external links with anchor + section context, images with alt
text, videos, JSON-LD types, word count). This module just orchestrates
N parallel fetches and shapes the rows into a clean dataclass for the
downstream analyzer.

Deliberately scoped to ONE page per competitor — for a page-revamp we
only care about the ranking URL, not the brand's whole site.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("seo.ai.content_writer.page_crawler")


@dataclass
class CrawledPage:
    """A single-page deep-crawl result, normalized for the analyzer."""

    url: str
    final_url: str
    status_code: str
    title: str
    meta_description: str
    body_text: str
    word_count: int
    headings: list[dict[str, Any]] = field(default_factory=list)
    internal_links: list[dict[str, Any]] = field(default_factory=list)
    external_links: list[dict[str, Any]] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    videos: list[dict[str, Any]] = field(default_factory=list)
    jsonld_types: list[str] = field(default_factory=list)
    content_size_bytes: int = 0
    snapshot_id: str = ""
    error: str = ""


def _row_to_page(row) -> CrawledPage:
    return CrawledPage(
        url=row.url,
        final_url=getattr(row, "final_url", "") or row.url,
        status_code=str(getattr(row, "status_code", "") or ""),
        title=row.title or "",
        meta_description=row.meta_description or "",
        body_text=row.body_text or "",
        word_count=int(row.word_count or 0),
        headings=list(row.headings_json or []),
        internal_links=list(row.internal_links_json or []),
        external_links=list(row.external_links_json or []),
        images=list(row.images_json or []),
        videos=list(row.videos_json or []),
        jsonld_types=list(row.jsonld_types or []),
        content_size_bytes=int(getattr(row, "content_bytes", 0) or 0),
        snapshot_id=str(row.snapshot_id) if row.snapshot_id else "",
    )


def crawl_one(url: str) -> CrawledPage:
    """Live-fetch ``url`` and return a normalized ``CrawledPage``.

    On any error returns a CrawledPage with ``error`` set and empty
    structural fields — the caller still proceeds so a single bad URL
    doesn't kill the whole pipeline.
    """
    from apps.crawler.views import CrawlLiveError, crawl_live

    try:
        _snap, row = crawl_live(url)
    except CrawlLiveError as exc:
        return CrawledPage(
            url=url, final_url=url, status_code=str(exc.status_code or ""),
            title="", meta_description="", body_text="",
            word_count=0, error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - never crash pipeline
        logger.exception("crawl_one unexpected failure for %s", url)
        return CrawledPage(
            url=url, final_url=url, status_code="",
            title="", meta_description="", body_text="",
            word_count=0, error=f"{type(exc).__name__}: {exc}",
        )
    if row is None:
        return CrawledPage(
            url=url, final_url=url, status_code="",
            title="", meta_description="", body_text="", word_count=0,
            error="crawl_live returned no row",
        )
    return _row_to_page(row)


def crawl_many(urls: list[str], *, max_workers: int = 5) -> list[CrawledPage]:
    """Parallel-fetch a list of URLs. Preserves input order.

    ``max_workers`` defaults to 5 — politeness floor across competitor
    hosts and matches our typical top-5 comp set.
    """
    if not urls:
        return []
    results: dict[str, CrawledPage] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as ex:
        future_map = {ex.submit(crawl_one, u): u for u in urls}
        for fut in as_completed(future_map):
            u = future_map[fut]
            try:
                results[u] = fut.result(timeout=120)
            except Exception as exc:  # noqa: BLE001
                logger.warning("crawl_many fut crashed for %s: %s", u, exc)
                results[u] = CrawledPage(
                    url=u, final_url=u, status_code="",
                    title="", meta_description="", body_text="", word_count=0,
                    error=f"{type(exc).__name__}: {exc}",
                )
    return [results[u] for u in urls if u in results]


def to_dict(p: CrawledPage) -> dict[str, Any]:
    """Serializable shape — caps body_text so persisted runs don't bloat."""
    return {
        "url": p.url,
        "final_url": p.final_url,
        "status_code": p.status_code,
        "title": p.title,
        "meta_description": p.meta_description,
        "body_excerpt": (p.body_text or "")[:4000],
        "word_count": p.word_count,
        "headings": p.headings,
        "internal_links_count": len(p.internal_links),
        "external_links_count": len(p.external_links),
        "images_count": len(p.images),
        "videos_count": len(p.videos),
        "jsonld_types": p.jsonld_types,
        "content_size_bytes": p.content_size_bytes,
        "snapshot_id": p.snapshot_id,
        "error": p.error,
    }
