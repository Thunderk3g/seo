"""Postgres dual-write pipeline for competitor-side Scrapy items.

One CrawlSnapshot per spider run (= per competitor domain). Each item
yielded by CompetitorSpider becomes one CrawlerPageResult row tagged
``kind='competitor'`` with the full body_text persisted. The legacy
audit detectors and Health Score formula already operate on the
CrawlerPageResult table, so flipping a competitor crawl through this
pipeline gives us per-competitor Health Score for free.

On close_spider:

  * Counts get tallied (attempted / ok / errored).
  * Health Score is recomputed against this snapshot's rows only.
  * Snapshot row is finalised with status=complete + counters + score.

The pipeline is best-effort: if Postgres is unreachable, items still
flow back through ``spider.captured_items`` so the synchronous façade
can return them to the gap-pipeline caller. Persistence failures log
once per spider, never crash the crawl.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

log = logging.getLogger("apps.seo_ai.pipelines.competitor_postgres")


class CompetitorDualWritePipeline:
    """Scrapy item pipeline contract: open_spider / process_item /
    close_spider. State (snapshot id, counters) lives on the spider
    so multiple spider instances in one process don't collide."""

    def open_spider(self, spider) -> None:
        from django.db import close_old_connections

        from apps.crawler.models import CrawlSnapshot

        # Reset stale connections — Scrapy can keep workers alive
        # across many requests; Django's per-request close hook never
        # fires here, so connections age out without this nudge.
        try:
            close_old_connections()
        except Exception:  # noqa: BLE001
            pass

        spider._cdw_counters = {"crawled": 0, "ok": 0, "errors": 0}
        spider._cdw_snapshot_id = None
        try:
            seed = spider._urls[0] if getattr(spider, "_urls", None) else ""
            seed_host = ""
            if seed:
                try:
                    seed_host = (urlparse(seed).netloc or "").lower()
                except ValueError:
                    seed_host = ""
            target = (getattr(spider, "target_domain", "") or "").lower()
            snap = CrawlSnapshot.objects.create(
                engine=CrawlSnapshot.Engine.SCRAPY_COMPETITOR,
                kind=CrawlSnapshot.Kind.COMPETITOR,
                seed_url=seed[:2048] if seed else "",
                target_domain=target or seed_host or "",
                allowed_domains=[target] if target else [],
                status=CrawlSnapshot.Status.RUNNING,
                config_snapshot={
                    "url_count": len(getattr(spider, "_urls", []) or []),
                    "playwright_enabled": bool(getattr(spider, "_playwright_enabled", False)),
                    "body_text_max_chars": int(getattr(spider, "body_text_max_chars", 0) or 0),
                },
            )
            spider._cdw_snapshot_id = str(snap.id)
            spider.logger.info(
                "CompetitorDualWritePipeline: snapshot=%s target=%s urls=%d",
                snap.id, target, len(getattr(spider, "_urls", []) or []),
            )
        except Exception as exc:  # noqa: BLE001
            spider.logger.warning(
                "CompetitorDualWritePipeline: snapshot create failed (%s) "
                "— degrading to capture-only mode", exc,
            )

    def process_item(self, item: dict, spider) -> dict:
        # Track captured items on the spider so the synchronous façade
        # can return them regardless of Postgres availability.
        try:
            spider.captured_items.append(dict(item))
        except Exception:  # noqa: BLE001
            pass

        counters = getattr(spider, "_cdw_counters", None)
        if counters is not None:
            counters["crawled"] += 1
            sc = str(item.get("status_code") or "")
            if sc == "200":
                counters["ok"] += 1
            elif sc and sc != "200":
                counters["errors"] += 1

        snap_id = getattr(spider, "_cdw_snapshot_id", None)
        if not snap_id:
            return item

        try:
            from apps.crawler.models import CrawlerPageResult

            url = (item.get("url") or "")[:2048]
            if not url:
                return item

            indexed_status = CrawlerPageResult.IndexedStatus.UNKNOWN
            extra = {
                "title_length": int(item.get("title_length") or 0),
                "meta_description_length": int(
                    item.get("meta_description_length") or 0
                ),
                "h1_texts": item.get("h1_texts") or [],
                "h2_texts": item.get("h2_texts") or [],
                "h2_count": int(item.get("h2_count") or 0),
                "h3_count": int(item.get("h3_count") or 0),
                "internal_link_count": int(item.get("internal_link_count") or 0),
                "external_link_count": int(item.get("external_link_count") or 0),
                "image_count": int(item.get("image_count") or 0),
                "image_alt_pct": float(item.get("image_alt_pct") or 0.0),
                "cta_count": int(item.get("cta_count") or 0),
                "schema_types": item.get("schema_types") or [],
                "has_schema_org": bool(item.get("has_schema_org")),
                "last_modified": item.get("last_modified") or "",
                "target_domain": item.get("target_domain") or "",
            }

            CrawlerPageResult.objects.update_or_create(
                snapshot_id=snap_id,
                url=url,
                defaults={
                    "final_url": (item.get("final_url") or url)[:2048],
                    "status_code": str(item.get("status_code") or "")[:4],
                    "status": str(item.get("status") or "")[:64],
                    "content_type": (item.get("content_type") or "")[:128],
                    "response_time_ms": int(item.get("response_time_ms") or 0),
                    "title": (item.get("title") or "")[:1024],
                    "word_count": int(item.get("word_count") or 0),
                    "body_text": item.get("body_text") or "",
                    "meta_description": (item.get("meta_description") or "")[:1024],
                    "canonical": (item.get("canonical") or "")[:2048],
                    "meta_robots": (item.get("meta_robots") or "")[:256],
                    "error_type": (item.get("error_type") or "")[:64],
                    "error_message": (item.get("error_message") or "")[:4000],
                    "subdomain": "competitor",
                    "page_type": "",
                    "category_key": (item.get("target_domain") or "")[:128],
                    "from_sitemap": False,
                    "indexed_status": indexed_status,
                    "playwright_used": bool(item.get("playwright_used")),
                    "extra": extra,
                },
            )
        except Exception as exc:  # noqa: BLE001
            spider.logger.debug(
                "CompetitorDualWritePipeline: persist failed for %s (%s)",
                item.get("url"), exc,
            )
        return item

    def close_spider(self, spider) -> None:
        from django.db import close_old_connections
        from django.utils import timezone as dj_tz

        try:
            close_old_connections()
        except Exception:  # noqa: BLE001
            pass

        snap_id = getattr(spider, "_cdw_snapshot_id", None)
        counters = getattr(spider, "_cdw_counters", None) or {}
        if not snap_id:
            return

        # Per-competitor Health Score — compute over this snapshot only.
        health_score = None
        health_tier = ""
        try:
            from apps.crawler.services.health_score import (
                compute_for_snapshot,
            )
            hs = compute_for_snapshot(snap_id)
            if hs is not None:
                health_score = hs.score
                health_tier = hs.tier or ""
        except ImportError:
            # compute_for_snapshot not yet wired — fall back silently.
            spider.logger.debug(
                "compute_for_snapshot unavailable — leaving health_score NULL"
            )
        except Exception as exc:  # noqa: BLE001
            spider.logger.warning("competitor health score compute failed: %s", exc)

        try:
            from apps.crawler.models import CrawlSnapshot
            CrawlSnapshot.objects.filter(pk=snap_id).update(
                status=CrawlSnapshot.Status.COMPLETE,
                finished_at=dj_tz.now(),
                pages_attempted=counters.get("crawled", 0),
                pages_ok=counters.get("ok", 0),
                pages_errored=counters.get("errors", 0),
                health_score=health_score,
                health_tier=health_tier,
            )
        except Exception as exc:  # noqa: BLE001
            spider.logger.warning(
                "CompetitorDualWritePipeline: finalise failed for %s (%s)",
                snap_id, exc,
            )

        spider.logger.info(
            "CompetitorDualWritePipeline: closed snapshot=%s crawled=%d "
            "ok=%d errors=%d hs=%s",
            snap_id, counters.get("crawled", 0), counters.get("ok", 0),
            counters.get("errors", 0), health_score,
        )
