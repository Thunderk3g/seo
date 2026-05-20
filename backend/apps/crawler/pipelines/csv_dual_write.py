"""Scrapy item pipeline — write to CSV + dual-write to Postgres.

Single funnel for the Scrapy port: every item yielded by BajajSpider.parse
gets written via ``storage.csv_writer.append`` exactly as the legacy
engine does. That triggers the same auto-enrichment (subdomain, page_type,
category_key, from_sitemap, indexed_status) and the same Phase 3c
dual-write to the Postgres CrawlerPageResult table.

Net effect: both engines populate the same crawl_results.csv + the same
Postgres tables with zero divergence in row shape.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("apps.crawler.pipelines.csv_dual_write")


class CsvDualWritePipeline:
    """One method open_spider + one method close_spider + one process_item.

    The Scrapy contract: pipelines receive each yielded item plus a
    reference to the spider. We pass the item through to csv_writer
    which handles all the existing legacy + dual-write logic.
    """

    def open_spider(self, spider) -> None:
        """Open streaming CSV handles + start a CrawlSnapshot row.

        ``resume=False`` truncates the CSV so the snapshot represents
        a fresh crawl. Operators wanting a resumable crawl should set
        the spider's start_requests differently and pass ``resume=True``
        through here in a future iteration.
        """
        from ..storage import csv_writer
        from ..services import snapshot as snapshot_svc
        from ..conf import settings as crawler_settings

        # Start the snapshot row. The dual-write hook in csv_writer.append
        # will pick this up automatically via current_snapshot_id().
        snap_id = snapshot_svc.start_snapshot(
            engine="scrapy",
            seed_url=crawler_settings.seed_url,
            allowed_domains=list(crawler_settings.allowed_domains),
            config={
                "concurrent_requests": spider.custom_settings.get(
                    "CONCURRENT_REQUESTS"
                ),
                "depth_limit": spider.custom_settings.get("DEPTH_LIMIT"),
                "page_cap": spider.custom_settings.get("CLOSESPIDER_PAGECOUNT"),
            },
        )
        spider.logger.info("CsvDualWritePipeline: snapshot=%s", snap_id)

        try:
            csv_writer.open_streams(resume=False)
        except Exception as exc:  # noqa: BLE001
            spider.logger.error("csv_writer.open_streams failed: %s", exc)

        # Counters tracked here so the close_spider hook can stamp the
        # snapshot with the same per-status counts that the legacy
        # engine reports.
        spider._counters = {"crawled": 0, "ok": 0, "errors": 0}

    def process_item(self, item: dict[str, Any], spider) -> dict[str, Any]:
        """One Scrapy item per URL. Funnel through csv_writer.append so
        the legacy enrichment + Phase 3c dual-write run unchanged."""
        from ..storage import csv_writer

        # Route by status to the right CSV stream (mirrors legacy
        # engine._ingest behaviour).
        status_code = str(item.get("status_code") or "")
        url = item.get("url") or ""

        # Update spider-level counters.
        if hasattr(spider, "_counters"):
            spider._counters["crawled"] += 1
            if status_code == "200":
                spider._counters["ok"] += 1
            elif status_code and status_code != "200":
                spider._counters["errors"] += 1

        # Write to the results CSV — dual-write fires inside append().
        try:
            csv_writer.append("results", dict(item))
        except Exception as exc:  # noqa: BLE001
            spider.logger.warning("csv_writer.append(results) failed for %s: %s", url, exc)

        # Mirror legacy error-stream behaviour: also write 404s + HTTP
        # errors to dedicated CSVs so the existing /tables endpoints
        # keep returning the same data.
        try:
            if status_code == "404":
                csv_writer.append("error_404", {
                    "timestamp": _iso_now(),
                    "url": url,
                    "error_type": "HTTP404",
                    "error_message": item.get("error_message") or "Not Found",
                })
            elif status_code and status_code.startswith(("4", "5")) and status_code != "404":
                csv_writer.append("error_http", {
                    "timestamp": _iso_now(),
                    "url": url,
                    "error_type": f"HTTP{status_code}",
                    "error_message": item.get("error_message") or "",
                })
            elif status_code == "0" or item.get("error_type"):
                csv_writer.append("errors", {
                    "timestamp": _iso_now(),
                    "url": url,
                    "error_type": item.get("error_type") or "NetworkError",
                    "error_message": item.get("error_message") or "",
                })
        except Exception as exc:  # noqa: BLE001
            spider.logger.debug("csv_writer error-stream append failed: %s", exc)

        return item

    def close_spider(self, spider) -> None:
        """Flush + close CSV handles, finalise snapshot."""
        from ..storage import csv_writer
        from ..services import snapshot as snapshot_svc
        from ..services.health_score import compute as compute_health

        try:
            csv_writer.flush_streams()
            csv_writer.close_streams()
        except Exception as exc:  # noqa: BLE001
            spider.logger.warning("csv_writer.close_streams failed: %s", exc)

        counters = getattr(spider, "_counters", {}) or {}
        hs = None
        try:
            hs = compute_health()
        except Exception:  # noqa: BLE001
            hs = None

        snapshot_svc.finish_snapshot(
            status="complete",
            pages_attempted=counters.get("crawled", 0),
            pages_ok=counters.get("ok", 0),
            pages_errored=counters.get("errors", 0),
            health_score=hs.score if hs else None,
            health_tier=hs.tier if hs else "",
        )
        spider.logger.info(
            "CsvDualWritePipeline: closed snapshot — crawled=%d ok=%d errors=%d hs=%s",
            counters.get("crawled", 0),
            counters.get("ok", 0),
            counters.get("errors", 0),
            hs.score if hs else "?",
        )


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
