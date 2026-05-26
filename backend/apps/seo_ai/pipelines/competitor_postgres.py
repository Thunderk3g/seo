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

        # Run the same Tier-1 product/page-type classifier we use on
        # Bajaj rows. The cross-insurer URL patterns added in
        # apps.crawler.content.rules make this insurer-agnostic so
        # ICICI/HDFC/Tata pages land with proper page_type + product.
        page_type_classified = ""
        primary_product = ""
        try:
            from apps.crawler.content.pipeline import classify_row

            classified = classify_row({
                "url": item.get("url") or "",
                "title": item.get("title") or "",
                "meta_description": item.get("meta_description") or "",
                "jsonld_types": item.get("schema_types") or [],
            })
            page_type_classified = classified.get("page_type") or ""
            products = classified.get("products") or []
            if products:
                primary_product = (products[0] or {}).get("label") or ""
        except Exception as exc:  # noqa: BLE001
            spider.logger.debug(
                "classify_row failed for %s (%s)", item.get("url"), exc,
            )

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
                    # Tier-1 classifier output — picks the page's product
                    # bucket (term/ulip/retirement/…) + page_type
                    # (product/calculator/blog_guide/faq_qa/legal/…).
                    "page_type": (page_type_classified or "")[:64],
                    # category_key carries (a) the competitor's apex
                    # domain for cross-snapshot grouping AND (b) the
                    # primary product label so SiteDiffer/Custodian
                    # queries can filter on it without re-classifying.
                    "category_key": (
                        f"{(item.get('target_domain') or '')[:80]}"
                        f"|{primary_product}"
                    )[:128],
                    "from_sitemap": False,
                    "indexed_status": indexed_status,
                    "playwright_used": bool(item.get("playwright_used")),
                    # Structural-mirror payload (Phase 2A.5) — drives the
                    # competitor Inspector UI + the ContentWriter agent's
                    # ``their:<host>:*`` evidence dict. Empty lists on
                    # error items are fine; the spider stamps them.
                    "headings_json": item.get("headings") or [],
                    "internal_links_json": item.get("internal_links") or [],
                    "external_links_json": item.get("external_links") or [],
                    "images_json": item.get("images") or [],
                    # Phase 2A.5b — video parity (native <video> +
                    # YouTube/Vimeo/Wistia <iframe> embeds).
                    "videos_json": item.get("videos") or [],
                    # Audit-field parity — security headers + redirect
                    # chain + hreflang + JSON-LD blocks + readability
                    # captured by the Phase-I competitor spider so the
                    # SiteDiffer / LayoutAgent / StructureAgent can
                    # reason about competitor pages the same way they
                    # do about our own.
                    "hsts": (item.get("hsts") or "")[:512],
                    "csp": item.get("csp") or "",
                    "x_frame_options": (item.get("x_frame_options") or "")[:128],
                    "x_content_type_options": (item.get("x_content_type_options") or "")[:64],
                    "referrer_policy": (item.get("referrer_policy") or "")[:128],
                    "permissions_policy": item.get("permissions_policy") or "",
                    "redirect_chain": item.get("redirect_chain") or [],
                    "redirect_hops": int(item.get("redirect_hops") or 0),
                    "redirect_loop": bool(item.get("redirect_loop") or False),
                    "redirect_final_url": (item.get("redirect_final_url") or "")[:2048],
                    "canonical_html": (item.get("canonical_html") or "")[:2048],
                    "hreflang_count": int(item.get("hreflang_count") or 0),
                    "hreflang_entries": item.get("hreflang_entries") or [],
                    "hreflang_has_x_default": bool(item.get("hreflang_has_x_default")),
                    "jsonld_count": int(item.get("jsonld_count") or 0),
                    "jsonld_blocks": item.get("jsonld_blocks") or [],
                    "jsonld_types": item.get("schema_types") or [],
                    "flesch_score": float(item.get("flesch_score") or 0.0),
                    "grade_level": float(item.get("grade_level") or 0.0),
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

        # ── ChangeWatcher: append history + emit change events ──────
        # Done in close_spider rather than process_item so we batch the
        # ORM work after all CrawlerPageResult rows are committed. A
        # failure here never blocks the crawl — the rows are already
        # persisted; the next snapshot's watcher run will catch up.
        watch_counters = {}
        try:
            from apps.seo_ai.services.change_watcher import (
                watch_removed_urls,
                watch_snapshot,
            )

            watch_counters = watch_snapshot(snap_id)
            # Also fire REMOVED events for any URL we previously saw
            # on this domain but which didn't appear in this fresh
            # crawl. Only sensible when the spider walked the full
            # site, not when it fetched a small URL list.
            target = getattr(spider, "target_domain", "") or ""
            mode = getattr(spider, "mode", "urls")
            if target and mode == "walk":
                fresh_urls = {
                    item.get("url") or ""
                    for item in getattr(spider, "captured_items", [])
                    if item.get("url")
                }
                removed = watch_removed_urls(
                    target, fresh_urls=fresh_urls,
                )
                watch_counters["removed_urls"] = len(removed)
        except Exception as exc:  # noqa: BLE001
            spider.logger.warning(
                "ChangeWatcher run failed for snapshot %s: %s", snap_id, exc,
            )

        spider.logger.info(
            "CompetitorDualWritePipeline: closed snapshot=%s crawled=%d "
            "ok=%d errors=%d hs=%s changes=%s",
            snap_id, counters.get("crawled", 0), counters.get("ok", 0),
            counters.get("errors", 0), health_score, watch_counters,
        )
