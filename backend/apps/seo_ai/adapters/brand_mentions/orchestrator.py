"""Brand-mentions orchestrator.

Top-level entry point used by:
  * ``apps.seo_ai.management.commands.pull_brand_mentions`` — CLI
  * The "Refresh now" button (POST /brand-mentions/refresh/)
  * Future Celery beat schedule (daily 03:00 UTC)

Owns the contract:
  1. Iterate the configured sub-adapters (RSS, SerpAPI, future CC).
  2. Merge their outputs.
  3. Score sentiment in a single batched Groq pass over net-new
     items (skipping items already in the DB to avoid re-spending).
  4. Persist via ``update_or_create`` keyed on ``source_url`` so the
     same article doesn't get duplicated across sources.

Returns a structured ``PullResult`` summarising counts + cost so the
UI can render "Last pull: 42 new mentions across 3 sources at 03:14
UTC".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from ...models import (
    BrandMention,
    MentionDiscoveredVia,
    MentionSentiment,
)
from .classify import is_own_property
from .page_fetch import enrich_mention
from .rss_news import fetch_rss_mentions, FeedItem
from .serpapi_daily import fetch_serpapi_mentions, SerpItem
from .sentiment import score_sentiments

log = logging.getLogger("apps.seo_ai.adapters.brand_mentions.orchestrator")


@dataclass
class SourceCount:
    """Per-source result counts surfaced to the UI."""
    source: str
    fetched: int = 0
    new: int = 0
    updated: int = 0
    error: str = ""


@dataclass
class PullResult:
    """End-to-end summary of one pull run."""
    sources: list[SourceCount] = field(default_factory=list)
    sentiment_scored: int = 0
    sentiment_skipped: int = 0
    total_fetched: int = 0
    total_new: int = 0
    total_updated: int = 0
    total_excluded_own_property: int = 0
    pages_enriched: int = 0
    pages_enrich_failed: int = 0
    started_at: str = ""
    finished_at: str = ""


def run_brand_mentions_pull(
    *,
    sources: Iterable[str] | None = None,
    force_serpapi: bool = False,
) -> PullResult:
    """Run every requested sub-adapter, persist matches, sentiment-score
    net-new rows.

    ``sources`` accepts {"rss", "serp", "all"} (or any subset). Default
    ``None`` = all configured sources.
    """
    from datetime import datetime, timezone

    requested = {s.strip().lower() for s in (sources or ["all"])}
    run_all = "all" in requested

    result = PullResult(
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    raw_records: list[dict] = []

    # ── 1. RSS ──────────────────────────────────────────────────────
    if run_all or "rss" in requested:
        count = SourceCount(source="rss")
        try:
            items = fetch_rss_mentions()
            count.fetched = len(items)
            raw_records.extend(_normalize_rss(items))
        except Exception as exc:  # noqa: BLE001
            count.error = str(exc)[:300]
            log.warning("orchestrator: rss source failed: %s", exc)
        result.sources.append(count)

    # ── 2. SerpAPI daily ───────────────────────────────────────────
    if run_all or "serp" in requested or "serpapi" in requested:
        count = SourceCount(source="serpapi")
        try:
            items = fetch_serpapi_mentions(force=force_serpapi)
            count.fetched = len(items)
            raw_records.extend(_normalize_serpapi(items))
        except Exception as exc:  # noqa: BLE001
            count.error = str(exc)[:300]
            log.warning("orchestrator: serpapi source failed: %s", exc)
        result.sources.append(count)

    # ── 3. (Future) Common Crawl ──────────────────────────────────
    # Wired but the live pull is the same 16-hour batch as the
    # backlinks adapter — to be enabled in a follow-up.

    # ── Filter out our own properties ──────────────────────────────
    # Strip anything pointing at a Bajaj-family domain, our own social
    # pages on third-party platforms, our own app store listings.
    pre_filter = len(raw_records)
    raw_records = [
        r for r in raw_records
        if not is_own_property(
            r.get("source_url") or "", r.get("source_domain") or "",
        )
    ]
    result.total_excluded_own_property = pre_filter - len(raw_records)
    if result.total_excluded_own_property:
        log.info(
            "orchestrator: filtered %d own-property mentions",
            result.total_excluded_own_property,
        )

    # ── De-dupe within this run ────────────────────────────────────
    by_url: dict[str, dict] = {}
    for rec in raw_records:
        u = rec.get("source_url") or ""
        if not u:
            continue
        if u in by_url:
            # Prefer entries with longer snippets (more context) on
            # ties between sources.
            if len(rec.get("snippet") or "") > len(by_url[u].get("snippet") or ""):
                by_url[u] = rec
        else:
            by_url[u] = rec

    result.total_fetched = pre_filter
    log.info(
        "orchestrator: fetched=%d excluded_own=%d unique=%d sources=%s",
        result.total_fetched, result.total_excluded_own_property,
        len(by_url), [s.source for s in result.sources],
    )

    # ── Persist + flag net-new for sentiment ───────────────────────
    new_rows: list[BrandMention] = []
    updated_count = 0
    new_count = 0
    for url, rec in by_url.items():
        defaults = {
            "source_domain": (rec.get("source_domain") or "")[:255],
            "source_title": (rec.get("source_title") or "")[:512],
            "snippet": rec.get("snippet") or "",
            "brand_variant": rec.get("brand_variant"),
            "source_tier": rec.get("source_tier"),
            "discovered_via": rec.get("discovered_via"),
            "raw_payload": rec.get("raw_payload") or {},
        }
        if rec.get("published_at"):
            defaults["published_at"] = rec["published_at"]
        try:
            obj, created = BrandMention.objects.update_or_create(
                source_url=url[:2000],
                defaults=defaults,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("persist failed for %s: %s", url, exc)
            continue
        if created:
            new_count += 1
            new_rows.append(obj)
        else:
            updated_count += 1
            # Re-score sentiment if it's currently UNSCORED, even on
            # updates — gives us a free retry on Groq failures.
            if obj.sentiment == MentionSentiment.UNSCORED:
                new_rows.append(obj)

    result.total_new = new_count
    result.total_updated = updated_count
    for src in result.sources:
        src.new = sum(
            1 for r in new_rows
            if r.discovered_via == src.source
        )
        src.updated = max(0, src.fetched - src.new)

    # ── Page-fetch second pass on net-new rows ─────────────────────
    # Deeper signal extraction: paragraph around brand mention,
    # is_linked + anchor_texts, schema.org structured data,
    # author/publisher entity, co-mentioned competitor brands,
    # page language. Per-host rate-limited to 1s — a daily run with
    # 30 new mentions takes ~60-90 seconds.
    if new_rows:
        for row in new_rows:
            try:
                _changed, enrichment = enrich_mention(row)
                if enrichment.error and not enrichment.body_excerpt:
                    result.pages_enrich_failed += 1
                else:
                    result.pages_enriched += 1
                row.save(update_fields=[
                    "body_excerpt", "is_linked", "anchor_texts",
                    "structured_data", "author", "publisher",
                    "co_mentioned_brands", "language",
                    "rating_value", "rating_max",
                    "published_at", "page_fetched_at",
                ])
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "orchestrator: page_fetch crashed for %s (%s)",
                    row.source_url[:80], exc,
                )
                result.pages_enrich_failed += 1

    # ── Sentiment scoring on net-new + previously-unscored ─────────
    # Run sentiment on the *enriched* body_excerpt when available
    # (better context than SERP snippet); fall back to snippet
    # otherwise. Sentiment quality jumps materially with the longer
    # paragraph text.
    if new_rows:
        texts: list[str] = []
        for r in new_rows:
            texts.append(r.body_excerpt or r.snippet or r.source_title or "")
        scores = score_sentiments(texts)
        scored = 0
        for row, score in zip(new_rows, scores):
            row.sentiment = score.sentiment
            row.sentiment_confidence = score.confidence
            row.save(update_fields=["sentiment", "sentiment_confidence"])
            if score.sentiment != MentionSentiment.UNSCORED:
                scored += 1
        result.sentiment_scored = scored
        result.sentiment_skipped = len(new_rows) - scored

    result.finished_at = datetime.now(timezone.utc).isoformat()
    log.info(
        "orchestrator: done — new=%d updated=%d scored=%d/%d",
        result.total_new, result.total_updated,
        result.sentiment_scored, result.sentiment_scored + result.sentiment_skipped,
    )
    return result


# ── normalisers — turn per-source dataclasses into uniform dicts ─────


def _normalize_rss(items: list[FeedItem]) -> list[dict]:
    return [
        {
            "source_url": it.source_url,
            "source_domain": it.source_domain,
            "source_title": it.source_title,
            "snippet": it.snippet,
            "brand_variant": it.brand_variant,
            "source_tier": it.source_tier,
            "published_at": it.published_at,
            "discovered_via": MentionDiscoveredVia.RSS,
            "raw_payload": it.raw_payload,
        }
        for it in items
    ]


def _normalize_serpapi(items: list[SerpItem]) -> list[dict]:
    return [
        {
            "source_url": it.source_url,
            "source_domain": it.source_domain,
            "source_title": it.source_title,
            "snippet": it.snippet,
            "brand_variant": it.brand_variant,
            "source_tier": it.source_tier,
            "discovered_via": MentionDiscoveredVia.SERPAPI,
            "raw_payload": it.raw_payload,
        }
        for it in items
    ]
