"""Celery tasks for SEO grading.

The synchronous entrypoint lives in :mod:`agents.orchestrator`; this
module is the thin async wrapper so the API can return 202 + a run id
and have the worker do the actual LLM calls.
"""
from __future__ import annotations

import logging

from celery import shared_task

from .agents.orchestrator import Orchestrator
from .gap_pipeline.orchestrator import GapPipelineOrchestrator
from .models import GapPipelineRun, SEORun

logger = logging.getLogger("seo.ai.tasks")


@shared_task(name="seo_ai.run_grade", bind=True, max_retries=0)
def run_grade_task(self, run_id: str) -> str:
    """Execute a grading run that was already created in the DB.

    Pattern: API view creates the SEORun row (so the client can poll it
    immediately), then enqueues this task. The task picks the row up
    and runs the orchestrator. Splitting creation from execution means
    we never lose track of a run that fails before the worker can pick
    it up — the row already exists.
    """
    try:
        run = SEORun.objects.get(id=run_id)
    except SEORun.DoesNotExist:
        logger.error("run_grade_task: SEORun %s not found", run_id)
        return "not_found"
    Orchestrator(run).execute()
    return str(run.status)


@shared_task(name="seo_ai.run_gap_pipeline", bind=True, max_retries=0)
def run_gap_pipeline_task(
    self, run_id: str, *, top_n: int = 10, query_count: int = 24
) -> str:
    """Execute a gap-detection pipeline run that's already in the DB.

    Same split-create-then-execute pattern as :func:`run_grade_task`:
    the API view creates the ``GapPipelineRun`` row so the client can
    poll its status immediately, then enqueues this task. The 6-stage
    pipeline writes intermediate data into child tables and updates
    ``stage_status`` after each stage, which is what the polling UI
    reads to render live progress.
    """
    try:
        run = GapPipelineRun.objects.get(id=run_id)
    except GapPipelineRun.DoesNotExist:
        logger.error("run_gap_pipeline_task: GapPipelineRun %s not found", run_id)
        return "not_found"
    GapPipelineOrchestrator(run).execute(top_n=top_n, query_count=query_count)
    return str(run.status)


# ── Periodic tasks (Celery beat) ─────────────────────────────────────


@shared_task(
    name="seo_ai.walk_competitor",
    bind=True,
    max_retries=0,
    time_limit=4 * 3600,
    soft_time_limit=4 * 3600 - 60,
)
def walk_competitor_task(
    self,
    domain: str,
    seeds: list[str] | None = None,
    *,
    mode: str = "sitemap",
    max_depth: int = 0,
    max_pages: int = 0,
    sitemap_url_cap: int = 5000,
) -> dict:
    """Re-crawl one competitor domain.

    Three modes:

      * ``mode='sitemap'`` (default, recommended) — fetch every URL in
        the competitor's ``/sitemap.xml`` + ``/sitemap_index.xml`` and
        crawl them all. ``max_depth=0`` (no link-walking; the sitemap
        is already authoritative). ``sitemap_url_cap`` bounds how many
        URLs we'll seed from the sitemap (default 5000 — covers most
        Indian insurer sites in full).

      * ``mode='walk'`` — start from ``seeds`` (default homepage) and
        follow internal links up to ``max_depth`` / ``max_pages``. Use
        when a competitor's sitemap is missing or stale.

      * ``mode='urls'`` — fetch exactly the URLs in ``seeds``, no
        following. Used by the gap-pipeline path that already knows
        which URLs it wants.

    The CompetitorDualWritePipeline's close_spider hook invokes
    ChangeWatcher, so this task's side-effects are:

      * Fresh CrawlerPageResult rows for the competitor (kind='competitor').
      * Append-only CompetitorPageHistory revisions.
      * CompetitorChangeEvent rows for every title/content/structure
        flip + new + removed URL.
    """
    from .adapters.competitor_crawler import CompetitorCrawler
    from .adapters.competitor_crawler_scrapy import CompetitorCrawlerScrapy
    from .adapters.sitemap_xml import SitemapXMLAdapter

    domain = (domain or "").strip().lower().lstrip("www.")
    if not domain:
        return {"ok": False, "error": "domain required"}
    mode = (mode or "sitemap").lower()

    # Resolve seeds based on mode. Sitemap mode discovers them; the
    # other modes use whatever the caller passed (or the homepage).
    sitemap_count = 0
    if mode == "sitemap":
        try:
            urls = SitemapXMLAdapter().discover_urls(
                domain, limit=int(sitemap_url_cap),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("sitemap discover failed for %s (%s)", domain, exc)
            urls = []
        if not urls:
            # No sitemap → fall back to homepage walk so we still pull
            # *something*. Operator can see "0 sitemap URLs, fell back
            # to walk" in the return dict and dig in.
            logger.info(
                "%s: no sitemap URLs found, falling back to walk mode", domain,
            )
            mode = "walk"
            seeds = seeds or [f"https://{domain}/"]
            max_depth = max_depth or 2
            max_pages = max_pages or 500
        else:
            sitemap_count = len(urls)
            seeds = urls
            max_depth = 0    # sitemap is authoritative; no link-following
            max_pages = 0    # unlimited — we have the exact seed list
            logger.info(
                "walk_competitor: domain=%s mode=sitemap seeds=%d",
                domain, sitemap_count,
            )
    else:
        if not seeds:
            seeds = [f"https://{domain}/"]
        logger.info(
            "walk_competitor: domain=%s mode=%s seeds=%d max_depth=%d max_pages=%d",
            domain, mode, len(seeds), max_depth, max_pages,
        )

    crawler = CompetitorCrawler()
    if not isinstance(crawler, CompetitorCrawlerScrapy):
        return {
            "ok": False,
            "error": "walk requires COMPETITOR_ENGINE=scrapy",
        }
    pages = crawler.walk_domain(
        domain=domain,
        seeds=seeds,
        max_depth=max_depth,
        max_pages=max_pages,
    )
    ok = sum(1 for p in pages if (p.status_code or 0) == 200)
    return {
        "ok": True,
        "domain": domain,
        "mode": mode,
        "sitemap_seed_count": sitemap_count,
        "pages": len(pages),
        "ok_pages": ok,
        "max_depth": max_depth,
        "max_pages": max_pages,
    }


@shared_task(
    name="seo_ai.walk_competitor_roster",
    bind=True,
    max_retries=0,
    time_limit=8 * 3600,
)
def walk_competitor_roster_task(
    self,
    domains: list[str] | None = None,
    *,
    mode: str = "sitemap",
    sitemap_url_cap: int = 5000,
) -> dict:
    """Fan out walks across the configured competitor roster.

    Default ``mode='sitemap'`` pulls every URL in each competitor's
    sitemap. ``sitemap_url_cap`` defaults to 5000 per competitor —
    covers most Indian life-insurance sites in full.

    Runs sequentially (not via ``.delay()`` fan-out) so the worker
    doesn't open eight Playwright browsers at once — Scrapy already
    concurrent-crawls within a single domain.
    """
    from django.conf import settings as dj_settings

    if domains is None:
        cfg = getattr(dj_settings, "COMPETITOR", {}) or {}
        domains = list(cfg.get("roster") or [])
    if not domains:
        return {"ok": False, "error": "no domains configured"}

    results: list[dict] = []
    for d in domains:
        try:
            res = walk_competitor_task.run(
                d, None, mode=mode, sitemap_url_cap=sitemap_url_cap,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("walk_competitor failed for %s", d)
            res = {"ok": False, "domain": d, "error": str(exc)}
        results.append(res)
    return {"ok": True, "domains": len(results), "results": results}


@shared_task(
    name="seo_ai.refresh_content_map",
    bind=True,
    max_retries=0,
    time_limit=30 * 60,
)
def refresh_content_map_task(self, *, snapshot_id: str = "") -> dict:
    """Re-embed + re-project the latest Bajaj snapshot for the 3D map.

    Thin Celery wrapper around the ``refresh_content_map`` management
    command. Scheduled to fire ~30 min after the daily Bajaj crawl so
    fresh CrawlerPageResult rows land in PageEmbedding + UMAP coords
    without manual intervention.
    """
    from django.core.management import call_command

    args = []
    if snapshot_id:
        args.extend(["--snapshot", snapshot_id])
    try:
        call_command("refresh_content_map", *args)
        return {"ok": True, "snapshot_id": snapshot_id or "latest"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("refresh_content_map_task failed")
        return {"ok": False, "error": str(exc)}


@shared_task(
    name="seo_ai.gc_competitor_history",
    bind=True,
    max_retries=0,
    time_limit=600,
)
def gc_competitor_history_task(self, *, retain_days: int = 90) -> dict:
    """Prune CompetitorPageHistory + CompetitorChangeEvent rows older
    than ``retain_days``.

    History is append-only and grows roughly linearly with crawl
    frequency × URL count × competitor count. 90 days is plenty for
    the operator-visible "what changed" timeline; longer-horizon
    analysis can ship to a warehouse on its own cadence.
    """
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    from .models import CompetitorChangeEvent, CompetitorPageHistory

    cutoff = dj_tz.now() - timedelta(days=int(retain_days))
    deleted_events, _ = CompetitorChangeEvent.objects.filter(
        detected_at__lt=cutoff,
    ).delete()
    deleted_history, _ = CompetitorPageHistory.objects.filter(
        seen_at__lt=cutoff,
    ).delete()
    logger.info(
        "gc_competitor_history: pruned %d events, %d history rows older than %dd",
        deleted_events, deleted_history, retain_days,
    )
    return {
        "ok": True,
        "retain_days": retain_days,
        "deleted_events": deleted_events,
        "deleted_history": deleted_history,
    }
