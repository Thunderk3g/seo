"""End-to-end orchestrator — one URL in, full revamp out.

Stages (each writes its result into the run record so the UI can render
panel-by-panel without re-running anything):

  1. live-crawl our URL                  → CrawlerPageResult row
  2. SERP discovery                      → SerpDiscoveryResult
  3. crawl every discovered URL          → list[CrawledPage]
  4. structural analyzer on all pages    → PageAnalysis dicts
  5. LLM section clustering on all pages → section payloads
  6. multi-dim gap engine                → RevampGap
  7. SEO best-practices overlay on ours  → issues + score
  8. writer agent                        → revamp JSON

Single entry: :func:`run_revamp`. The function is synchronous and
~30-90 seconds end-to-end depending on competitor count and provider.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

from . import gap_engine
from . import page_analyzer
from . import page_crawler
from . import seo_overlay
from . import serp_discovery
from . import writer
from .section_clusterer import cluster_page_sections

logger = logging.getLogger("seo.ai.content_writer.orchestrator")


def _bare(host: str) -> str:
    host = (host or "").lower().lstrip(".")
    return host[4:] if host.startswith("www.") else host


def run_revamp(
    *,
    our_url: str,
    operator_prompt: str = "",
    max_competitors: int = 5,
    provider=None,
    on_stage=None,         # optional callback(stage_name, payload_dict)
) -> dict[str, Any]:
    """Execute the full content_writer pipeline for ``our_url``.

    Returns a dict shaped for both the API response and DB persistence:

      {
        "our_url": str,
        "operator_prompt": str,
        "stages": {
          "serp_discovery": {...},
          "our_page_analysis": {...},
          "competitor_analyses": [{"domain": ..., "analysis": {...}}, ...],
          "our_sections": {...},
          "competitor_sections": {url: {...}},
          "gap_report": {...},
          "seo_overlay": {...},
          "revamp": {...},     # writer output
        },
        "telemetry": {
          "wall_time_seconds": float,
          "model_used": str,
          "tokens_in": int,
          "tokens_out": int,
          "cost_usd": float,
        },
        "warnings": [str, ...],
      }

    Any per-stage failure is captured into ``warnings`` and the pipeline
    proceeds — the writer is happy with sparse evidence (will note the
    degradation in its ``rewrite_strategy``).
    """
    from django.conf import settings

    from apps.crawler.models import CrawlerPageResult
    from apps.crawler.views import CrawlLiveError, crawl_live

    from .cost_budget import CostBudget
    from ..llm import get_content_writer_provider

    cw = getattr(settings, "CONTENT_WRITER", None) or {}
    if provider is None:
        provider = get_content_writer_provider()
    is_anthropic = getattr(provider, "name", "") == "anthropic"
    # Only push Claude model ids when the provider is actually Anthropic.
    cheap_model = cw.get("cheap_model") if is_anthropic else None
    min_comp = int(cw.get("min_competitors", 4))
    budget = CostBudget(float(cw.get("max_cost_usd", 0.75)))
    EST_CLUSTER_USD = 0.02  # rough Haiku per-page clustering cost

    warnings: list[str] = []
    t0 = time.monotonic()

    def emit(stage: str, payload: dict[str, Any]) -> None:
        if on_stage is not None:
            try:
                on_stage(stage, payload)
            except Exception:  # noqa: BLE001 — non-fatal
                logger.exception("on_stage callback for %s crashed", stage)

    # ── Stage 1: live-crawl ours ────────────────────────────────────
    our_row = None
    try:
        _snap, our_row = crawl_live(our_url)
    except CrawlLiveError as exc:
        # If live-crawl fails, fall back to most-recent DB row.
        warnings.append(f"live crawl failed for our URL: {exc}; using prior crawl row")
        our_row = (
            CrawlerPageResult.objects.filter(url=our_url)
            .order_by("-snapshot__started_at")
            .first()
        )
    if our_row is None:
        raise RuntimeError(
            f"cannot proceed — no crawl row for {our_url} and live fetch failed"
        )

    # ── Stage 2: SERP discovery (multi-query + Bajaj + web search) ──
    serp = serp_discovery.find_serp_competitors(
        our_url=our_url,
        operator_prompt=operator_prompt,
        top_n=max_competitors,
        provider=provider,
        budget=budget,
    )
    serp_payload = serp_discovery.to_dict(serp)
    emit("serp_discovery", serp_payload)
    if serp.serp_error:
        warnings.append(f"SERP discovery: {serp.serp_error}")

    # ── Stage 3: crawl competitors, substituting blocked ones ───────
    primary_urls = [c.url for c in serp.competitors]
    crawled = page_crawler.crawl_many(primary_urls, max_workers=5) if primary_urls else []
    crawled_ok = [c for c in crawled if not c.error and c.title]
    for c in crawled:
        if c.error:
            warnings.append(f"competitor crawl failed: {c.url} — {c.error}")

    # Substitution: a blocked competitor (e.g. ICICI/Cloudflare 403)
    # shouldn't shrink the benchmark — pull the next ranking insurer from
    # the over-fetched pool until we hit ``min_comp`` successful crawls.
    seen_urls = {c.url for c in crawled}
    for sub in serp.substitution_pool:
        if len(crawled_ok) >= max(min_comp, len(primary_urls)):
            break
        if sub.url in seen_urls:
            continue
        seen_urls.add(sub.url)
        sp = page_crawler.crawl_one(sub.url)
        crawled.append(sp)
        if not sp.error and sp.title:
            crawled_ok.append(sp)
            warnings.append(f"substituted a blocked competitor with {sp.url}")
        else:
            warnings.append(f"substitute crawl failed: {sub.url} — {sp.error}")

    if primary_urls or crawled:
        emit("competitor_crawls", {
            "requested": len(primary_urls),
            "succeeded": len(crawled_ok),
            "pages": [page_crawler.to_dict(c) for c in crawled],
        })

    # ── Stage 4: structural analysis (ours + comps) ─────────────────
    our_analysis = page_analyzer.analyze_page(our_row)
    # Keep the CrawledPage alongside (domain, analysis) so we can build
    # the per-competitor structure payload after clustering.
    competitor_triples: list[tuple[str, page_analyzer.PageAnalysis, Any]] = []
    for c in crawled_ok:
        a = page_analyzer.analyze_page(c)
        domain = _bare(urlparse(c.url).hostname or "")
        competitor_triples.append((domain, a, c))
    competitor_analyses = [(d, a) for (d, a, _c) in competitor_triples]
    emit("structural_analyses", {
        "ours": page_analyzer.to_dict(our_analysis),
        "competitors": [
            {"domain": d, "analysis": page_analyzer.to_dict(a)}
            for d, a in competitor_analyses
        ],
    })

    # ── Stage 5: LLM section clustering (ours + comps, via Claude) ──
    # Sequential — one Haiku call per page. Ours + the first two comps
    # always cluster; remaining comps skip if the budget is tight.
    our_sections = cluster_page_sections(our_row, provider=provider, model=cheap_model)
    if our_sections and not our_sections.get("cached"):
        budget.add_usd(our_sections.get("cost_usd") or 0.0)

    competitor_sections: dict[str, dict[str, Any]] = {}
    for idx, (domain, _a, c) in enumerate(competitor_triples):
        if idx >= 2 and budget.would_exceed(EST_CLUSTER_USD):
            competitor_sections[c.url] = {"sections": [], "skipped_for_budget": True}
            budget.note(f"skipped clustering {domain} to stay under ${budget.cap_usd:.2f}")
            continue
        row = None
        if c.snapshot_id:
            try:
                row = (
                    CrawlerPageResult.objects
                    .filter(snapshot_id=c.snapshot_id, url=c.url)
                    .first()
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("competitor cluster lookup failed for %s: %s", c.url, exc)
        if row is None:
            competitor_sections[c.url] = {"sections": [], "error": "no crawler row to cluster"}
            continue
        payload = cluster_page_sections(row, provider=provider, model=cheap_model)
        if payload and not payload.get("cached"):
            budget.add_usd(payload.get("cost_usd") or 0.0)
        competitor_sections[c.url] = payload
    emit("section_clusters", {
        "ours": our_sections,
        "competitors": competitor_sections,
    })

    # ── Stage 6: gap engine ─────────────────────────────────────────
    gap = gap_engine.compute_revamp_gap(
        our_analysis=our_analysis,
        our_sections=our_sections,
        competitor_analyses=competitor_analyses,
        competitor_sections=competitor_sections,
    )
    gap_dict = gap_engine.to_dict(gap)
    emit("gap_report", gap_dict)

    # ── Stage 7: SEO overlay on ours ────────────────────────────────
    overlay = seo_overlay.run_seo_overlay(our_analysis)
    emit("seo_overlay", overlay)

    # ── Assemble per-page structure payloads for the UI dropdowns ───
    our_structure = page_analyzer.to_structure_dict(our_analysis, our_row)
    our_structure["clusters"] = (our_sections or {}).get("sections") or []
    competitor_structures: dict[str, dict[str, Any]] = {}
    for domain, a, c in competitor_triples:
        st = page_analyzer.to_structure_dict(a, c)
        st["domain"] = domain
        st["clusters"] = (competitor_sections.get(c.url) or {}).get("sections") or []
        competitor_structures[domain] = st

    # ── Stage 8: writer agent ───────────────────────────────────────
    wr = writer.generate_revamp(
        our_url=our_url,
        our_analysis=our_analysis,
        our_page_row=our_row,
        our_sections=our_sections,
        competitor_analyses=competitor_analyses,
        competitor_sections=competitor_sections,
        gap_report_dict=gap_dict,
        seo_overlay_dict=overlay,
        serp_snapshot=serp_payload,
        operator_prompt=operator_prompt,
        provider=provider,
    )
    if wr.error:
        warnings.append(f"writer: {wr.error}")
    budget.add_usd(wr.cost_usd)
    emit("revamp", wr.rewrite)

    # Fold budget degradations into operator-visible warnings.
    for note in budget.notes():
        warnings.append(f"budget: {note}")

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "content_writer.run_revamp ok in %.1fs for %s — comps=%d cost=$%.4f/$%.2f",
        elapsed, our_url, len(competitor_analyses), budget.spent(), budget.cap_usd,
    )
    return {
        "our_url": our_url,
        "operator_prompt": operator_prompt,
        "stages": {
            "serp_discovery": serp_payload,
            "our_page_analysis": page_analyzer.to_dict(our_analysis),
            "competitor_analyses": [
                {"domain": d, "analysis": page_analyzer.to_dict(a)}
                for d, a in competitor_analyses
            ],
            "our_sections": our_sections,
            "competitor_sections": competitor_sections,
            "our_structure": our_structure,
            "competitor_structures": competitor_structures,
            "gap_report": gap_dict,
            "seo_overlay": overlay,
            "revamp": wr.rewrite,
            "revamp_error": wr.error,
        },
        "telemetry": {
            "wall_time_seconds": elapsed,
            "model_used": wr.model_used,
            "tokens_in": wr.tokens_in,
            "tokens_out": wr.tokens_out,
            # Cumulative spend across query synth + web search + clustering
            # + writer — not just the writer call.
            "cost_usd": round(budget.spent(), 4),
            "writer_cost_usd": round(wr.cost_usd, 4),
            "writer_latency_seconds": wr.latency_seconds,
            "budget_cap_usd": budget.cap_usd,
            "degraded": budget.degraded(),
        },
        "warnings": warnings,
    }
