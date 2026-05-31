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


def _cwv_record_to_columns(record) -> dict:
    """Map a CWVRecord (lab_*/field_*/performance_score) to page CWV column
    suffixes. Prefers CrUX field data, falls back to Lighthouse lab. The
    old code read non-existent names (lcp_ms/pagespeed_score) and silently
    wrote nothing — this is the corrected mapping."""
    def pick(*vals):
        for v in vals:
            if v is not None and v != "":
                return v
        return None
    score = getattr(record, "performance_score", None)
    out = {
        "lcp_ms": pick(record.field_lcp_ms, record.lab_lcp_ms),
        "cls": pick(record.field_cls, record.lab_cls),
        "inp_ms": record.field_inp_ms,
        "fcp_ms": pick(record.field_fcp_ms, record.lab_fcp_ms),
        "ttfb_ms": pick(record.field_ttfb_ms, record.lab_ttfb_ms),
        "tbt_ms": record.lab_tbt_ms,
        "si_ms": record.lab_si_ms,
        "pagespeed_score": round(score * 100) if score is not None else None,
        "lcp_category": record.field_lcp_category or None,
        "cls_category": record.field_cls_category or None,
        "inp_category": record.field_inp_category or None,
        "has_field_data": record.has_field_data,
    }
    return {k: v for k, v in out.items() if v is not None and v != ""}


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


def _fallback_competitor_fetch(domain: str, seed_urls: list[str] | None = None) -> dict:
    """Last-resort competitor fetch when the Scrapy walk pulls 0 pages.

    Some competitors (e.g. ICICI behind Cloudflare, or sites that detect
    headless Chrome) block the Scrapy/Playwright engine but still answer a
    plain requests call with a browser UA. This uses the SEPARATE
    requests-based CompetitorCrawler to grab the homepage + a few seed URLs
    and persists them as real competitor CrawlerPageResult rows, so a
    blocked rival is never silently empty. Returns counts; marks the run
    'blocked' (honestly) when even this fails. Never raises, never loops.
    """
    import os
    from urllib.parse import urlparse

    from django.utils import timezone as _tz

    from apps.crawler.models import CrawlSnapshot, CrawlerPageResult

    from .adapters.competitor_crawler import CompetitorCrawler

    max_urls = max(1, int(os.environ.get("COMPETITOR_FALLBACK_MAX_URLS", "8")))
    # Build a small, de-duped URL list: homepage variants first, then seeds.
    candidates = [f"https://www.{domain}/", f"https://{domain}/"] + list(seed_urls or [])
    urls: list[str] = []
    seen: set[str] = set()
    for u in candidates:
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
        if len(urls) >= max_urls:
            break

    try:
        crawler = CompetitorCrawler()           # requests-based, browser UA
        pages = crawler.fetch_pages(urls)
    except Exception as exc:  # noqa: BLE001 — never crash the roster
        logger.warning("fallback fetch failed to init for %s: %s", domain, exc)
        return {"ok_pages": 0, "attempted": len(urls), "blocked": True, "error": str(exc)[:200]}

    snap = None
    ok_pages = 0
    for page in pages:
        if page is None or getattr(page, "error", None):
            continue
        if (page.status_code or 0) != 200 or not (page.body_text or page.title):
            continue
        if snap is None:
            snap = CrawlSnapshot.objects.create(
                kind=CrawlSnapshot.Kind.COMPETITOR,
                target_domain=domain,
                status=CrawlSnapshot.Status.RUNNING,
                engine=CrawlSnapshot.Engine.LEGACY,
                seed_url=urls[0],
                allowed_domains=[domain],
                notes="requests fallback (primary crawl blocked/empty)",
            )
        page_url = (page.url or "")[:2048]
        CrawlerPageResult.objects.update_or_create(
            snapshot=snap, url=page_url,
            defaults={
                "final_url": (page.final_url or page_url)[:2048],
                "status_code": str(page.status_code or "")[:4],
                "status": "ok",
                "content_type": "text/html",
                "response_time_ms": int(page.response_time_ms or 0),
                "title": (page.title or "")[:1024],
                "word_count": int(page.word_count or 0),
                "body_text": page.body_text or "",
                "meta_description": (page.meta_description or "")[:1024],
                "canonical": (page.canonical or "")[:2048],
                "meta_robots": (page.meta_robots or "")[:256],
                "subdomain": "",
                "page_type": "",
                "from_sitemap": False,
                "indexed_status": CrawlerPageResult.IndexedStatus.UNKNOWN,
                "headings_json": list(getattr(page, "headings", None) or []),
                "internal_links_json": list(getattr(page, "internal_links", None) or []),
                "external_links_json": list(getattr(page, "external_links", None) or []),
                "images_json": list(getattr(page, "images", None) or []),
                "videos_json": list(getattr(page, "videos", None) or []),
                "jsonld_types": list(getattr(page, "schema_types", None) or []),
                "jsonld_count": len(getattr(page, "schema_types", None) or []),
            },
        )
        ok_pages += 1

    if snap is not None:
        CrawlSnapshot.objects.filter(id=snap.id).update(
            status=CrawlSnapshot.Status.COMPLETE,
            pages_attempted=len(urls),
            pages_ok=ok_pages,
            finished_at=_tz.now(),
        )
    return {"ok_pages": ok_pages, "attempted": len(urls), "blocked": ok_pages == 0}


# ── Periodic tasks (Celery beat) ─────────────────────────────────────


@shared_task(
    name="seo_ai.walk_competitor",
    bind=True,
    max_retries=0,
    time_limit=4 * 3600,
    soft_time_limit=4 * 3600 - 60,
    # acks_late=False (overrides the global late-ack): a multi-hour crawl
    # must NOT be redelivered when the worker is recycled/restarted, or it
    # re-spawns forever and leaves orphaned 'running' snapshots. It is
    # idempotent and re-runs on the next manual/scheduled cycle anyway.
    acks_late=False,
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
    fallback_path = ""
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
            # *something*. We try a few common homepage variants because
            # some sites only respond to one (e.g. an apex-only host
            # refuses the www subdomain, or vice versa). The Scrapy walk
            # filters non-host links anyway, so a couple of extra seeds
            # is cheap insurance against a single 404 wiping the run.
            logger.info(
                "%s: no sitemap URLs found, falling back to walk mode", domain,
            )
            mode = "walk"
            fallback_path = "sitemap_empty"
            candidate_seeds = seeds or [
                f"https://{domain}/",
                f"https://www.{domain}/" if not domain.startswith("www.") else f"https://{domain.removeprefix('www.')}/",
                f"https://{domain}/index.html",
            ]
            # De-duplicate while preserving order — set() would scramble it.
            seen: set[str] = set()
            seeds = [s for s in candidate_seeds if s and not (s in seen or seen.add(s))]
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

    # Fallback: the Scrapy/Playwright engine got 0 usable pages (blocked
    # WAF, headless detection, or no sitemap + dead homepage). Try the
    # separate requests-based engine before giving up, so a rival is never
    # silently empty. Runs once; the roster moves on regardless (no loop).
    fallback_info = None
    if ok == 0:
        logger.info("walk_competitor: %s got 0 pages via %s — trying requests fallback", domain, mode)
        fallback_info = _fallback_competitor_fetch(domain, seeds)
        ok = int(fallback_info.get("ok_pages", 0) or 0)

    # Chain follow-ups: find the just-created snapshot for this domain
    # and kick off PSI enrichment + content-map refresh. Both are
    # best-effort — failures here log but don't fail the crawl result.
    follow_ups: dict[str, str] = {}
    try:
        from apps.crawler.models import CrawlSnapshot
        snap = (
            CrawlSnapshot.objects
            .filter(kind="competitor", target_domain__iexact=domain)
            .order_by("-started_at")
            .first()
        )
        if snap is not None:
            try:
                psi_task = psi_enrich_snapshot_task.delay(str(snap.id))
                follow_ups["psi_task"] = psi_task.id
            except Exception as exc:  # noqa: BLE001
                logger.warning("psi follow-up enqueue failed: %s", exc)
            try:
                map_task = refresh_content_map_task.delay(
                    competitor_domain=domain,
                )
                follow_ups["content_map_task"] = map_task.id
            except Exception as exc:  # noqa: BLE001
                logger.warning("content-map follow-up enqueue failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.info("walk_competitor follow-up lookup failed: %s", exc)

    return {
        "ok": True,
        "domain": domain,
        "mode": mode,
        "fallback_path": fallback_path,
        "sitemap_seed_count": sitemap_count,
        "pages": len(pages),
        "ok_pages": ok,
        "max_depth": max_depth,
        "max_pages": max_pages,
        "follow_ups": follow_ups,
        "fallback": fallback_info,
        "blocked": bool(fallback_info and fallback_info.get("blocked")),
    }


@shared_task(
    name="seo_ai.walk_competitor_roster",
    bind=True,
    max_retries=0,
    time_limit=8 * 3600,
    # See walk_competitor_task — never redeliver an 8h roster crawl.
    acks_late=False,
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

    Operator pause toggle: if SystemSetting('competitor_walk_paused')
    is true, the task returns early without doing anything. Lets the
    dashboard freeze the 03:00 IST cron during incidents (e.g. a
    competitor's WAF is throwing 429s and we don't want to keep
    hammering them) without re-deploying or editing the beat schedule.
    """
    from django.conf import settings as dj_settings

    from apps.crawler.models import SystemSetting

    if SystemSetting.get_bool("competitor_walk_paused", default=False):
        logger.info(
            "walk_competitor_roster: paused via SystemSetting toggle "
            "— skipping this run",
        )
        return {
            "ok": True,
            "paused": True,
            "reason": "competitor_walk_paused setting is True",
        }

    if domains is None:
        cfg = getattr(dj_settings, "COMPETITOR", {}) or {}
        domains = list(cfg.get("roster") or [])
    if not domains:
        return {"ok": False, "error": "no domains configured"}

    results: list[dict] = []
    for d in domains:
        # Re-check the pause flag BETWEEN domains so an operator can halt a
        # long roster walk mid-flight (not only before it starts).
        if SystemSetting.get_bool("competitor_walk_paused", default=False):
            logger.info("walk_competitor_roster: paused mid-run — stopping after %d domains", len(results))
            return {"ok": True, "paused_midrun": True, "domains": len(results), "results": results}
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
    time_limit=2 * 60 * 60,  # 2h envelope — competitor refresh adds time
)
def refresh_content_map_task(
    self,
    *,
    snapshot_id: str = "",
    include_competitors: bool = True,
    competitor_domain: str = "",
) -> dict:
    """Re-embed + re-project snapshot(s) for the 3D content map.

    Defaults to refreshing the latest Bajaj snapshot AND every
    competitor snapshot (one map per competitor). Pass
    ``competitor_domain='hdfclife.com'`` to refresh just one.

    Scheduled to fire ~30 min after the daily Bajaj crawl. Each
    competitor's embeddings live under its own snapshot_id so per-
    competitor content maps stay isolated.
    """
    from django.core.management import call_command

    args = []
    if snapshot_id:
        args.extend(["--snapshot", snapshot_id])
    if competitor_domain:
        args.extend(["--competitor-domain", competitor_domain])
    elif include_competitors:
        args.append("--include-competitors")
    try:
        call_command("refresh_content_map", *args)
        return {
            "ok": True,
            "snapshot_id": snapshot_id or "latest",
            "competitor_domain": competitor_domain or None,
            "include_competitors": include_competitors and not competitor_domain,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("refresh_content_map_task failed")
        return {"ok": False, "error": str(exc)}


@shared_task(
    name="seo_ai.psi_enrich_snapshot",
    bind=True,
    max_retries=0,
    time_limit=2 * 60 * 60,
    # See walk_competitor_task — never redeliver a long PSI enrichment.
    acks_late=False,
)
def psi_enrich_snapshot_task(
    self,
    snapshot_id: str,
    *,
    max_urls: int = 25,
    strategies: tuple[str, ...] = ("mobile", "desktop"),
) -> dict:
    """Enrich every page in ``snapshot_id`` with Core Web Vitals via PSI.

    Designed for the Scrapy-walked competitor flow which writes
    structural data but skips CWV. Picks the top ``max_urls`` pages of
    the snapshot (ordered by word_count desc — proxies "important"
    pages) and calls PSI mobile + desktop for each, writing back to
    CrawlerPageResult's mobile_* / desktop_* columns.

    Best-effort: per-page PSI failures are logged and skipped; the task
    never raises so it can be chained from walk_competitor_task without
    breaking the crawl envelope.
    """
    from apps.crawler.models import CrawlerPageResult, CrawlSnapshot

    from .adapters.cwv_psi import AdapterDisabledError, PSIAdapter

    snap = CrawlSnapshot.objects.filter(id=snapshot_id).first()
    if snap is None:
        return {"ok": False, "error": "snapshot not found"}

    try:
        psi = PSIAdapter()
    except AdapterDisabledError as exc:
        logger.info("psi disabled: %s", exc)
        return {"ok": False, "skipped": True, "reason": str(exc)}

    pages = list(
        CrawlerPageResult.objects.filter(
            snapshot=snap, status_code="200",
        )
        .order_by("-word_count")[:max_urls]
    )
    enriched = errors = 0
    for page in pages:
        for strategy in strategies:
            try:
                record = psi.fetch(page.url, strategy=strategy)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "psi %s for %s failed: %s", strategy, page.url, exc,
                )
                errors += 1
                continue
            if record.error:
                continue
            prefix = "mobile_" if strategy == "mobile" else "desktop_"
            colvals = _cwv_record_to_columns(record)
            for suffix, val in colvals.items():
                setattr(page, f"{prefix}{suffix}", val)
            # Legacy mirror columns (mobile-only) that the page-detail UI reads.
            if strategy == "mobile":
                for fld in ("pagespeed_score", "lcp_ms", "cls", "inp_ms"):
                    if fld in colvals:
                        setattr(page, fld, colvals[fld])
            if colvals:
                enriched += 1
        try:
            page.save(update_fields=[
                "pagespeed_score", "lcp_ms", "cls", "inp_ms",
                "mobile_pagespeed_score", "mobile_lcp_ms", "mobile_cls",
                "mobile_inp_ms", "mobile_fcp_ms", "mobile_ttfb_ms",
                "mobile_tbt_ms", "mobile_si_ms",
                "mobile_lcp_category", "mobile_cls_category",
                "mobile_inp_category", "mobile_has_field_data",
                "desktop_pagespeed_score", "desktop_lcp_ms", "desktop_cls",
                "desktop_inp_ms", "desktop_fcp_ms", "desktop_ttfb_ms",
                "desktop_tbt_ms", "desktop_si_ms",
                "desktop_lcp_category", "desktop_cls_category",
                "desktop_inp_category", "desktop_has_field_data",
            ])
        except Exception as exc:  # noqa: BLE001
            logger.warning("psi save for %s failed: %s", page.url, exc)
    return {
        "ok": True,
        "snapshot_id": str(snap.id),
        "domain": snap.target_domain,
        "pages_attempted": len(pages),
        "enriched_strategy_count": enriched,
        "errors": errors,
    }


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
