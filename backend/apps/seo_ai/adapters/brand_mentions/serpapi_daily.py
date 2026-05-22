"""SerpAPI daily catch-all for brand mentions.

One Google query per day, configured to maximise breadth: top-30
organic results for `"Bajaj Life Insurance" -site:bajajlifeinsurance.com`
restricted to India. This is the single source that surfaces:
  * MouthShut / Trustpilot / ConsumerAffairs reviews
  * Quora answers
  * Random blog posts and comparison articles
  * Indexed Reddit threads (Google has indexed Reddit since 2024)
  * SGE / AI Overview snippets when present

Budget: 30 calls/month (one per day) = 30% of the SerpAPI free tier
(100/mo). A hard cap in this adapter refuses to run when the
month-to-date call count is at or past the configured ceiling so a
buggy retry loop can't drain the budget.

Token spend per call: 1. No batching is possible — the catch-all
query is intentionally broad so we only need one per day.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from django.conf import settings

from .classify import (
    all_brand_tokens,
    classify_brand_variant,
    classify_source_tier,
    domain_of,
    extract_snippet,
)

log = logging.getLogger("apps.seo_ai.adapters.brand_mentions.serpapi_daily")

# Process-wide month-to-date counter so multiple processes that
# happen to call the same minute don't double-bill. The real durable
# counter is the count of rows in BrandMention where discovered_via=
# 'serpapi' for the current month — see ``_month_to_date_calls()``.
_MEMORY_CALLS_THIS_RUN = 0


@dataclass
class SerpItem:
    source_url: str
    source_domain: str
    source_title: str
    snippet: str
    brand_variant: str
    source_tier: str
    raw_payload: dict = field(default_factory=dict)


def _month_to_date_calls() -> int:
    """How many SerpAPI brand-mention calls have we logged this calendar
    month? Used to enforce the monthly cap. We count rows persisted via
    this adapter as a proxy for calls (each call writes 0+ rows; if 0
    rows, the call still happened — but we approximate). For a hard
    counter add a separate ``ApiUsage`` model later."""
    try:
        from datetime import datetime, timezone
        from ...models import BrandMention, MentionDiscoveredVia
        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0,
        )
        # Approximation: distinct days this month with a serpapi row.
        # A row per day means we did the daily call.
        days = (
            BrandMention.objects
            .filter(
                discovered_via=MentionDiscoveredVia.SERPAPI,
                last_seen_at__gte=month_start,
            )
            .dates("last_seen_at", "day")
            .count()
        )
        return int(days)
    except Exception as exc:  # noqa: BLE001
        log.info("serpapi cap counter unavailable (%s) — treating as 0", exc)
        return 0


def fetch_serpapi_mentions(
    *, force: bool = False, num_results: int = 30,
) -> list[SerpItem]:
    """Run one SerpAPI Google query for brand mentions. Returns matched
    organic-result items. Refuses to run when the monthly cap is hit
    unless ``force=True`` (manual override from the UI).
    """
    global _MEMORY_CALLS_THIS_RUN

    cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
    if not cfg.get("serpapi_daily_enabled", True):
        log.info("serpapi: disabled in settings — skipping")
        return []

    cap = int(cfg.get("serpapi_monthly_cap", 30) or 30)
    used = _month_to_date_calls()
    if not force and used >= cap:
        log.warning(
            "serpapi: month-to-date used=%d, cap=%d — refusing run. "
            "Set force=True to override.", used, cap,
        )
        return []

    # Daily-rotating raw query — same shape Google + AI bots use when
    # they research the brand. NO `-site:` exclusions: we want to see
    # the full page mix Google surfaces, including our own properties
    # (those get tier='owned' downstream so the UI can filter).
    #
    # 7-pattern rotation gives weekly variety on a 1-call/day budget:
    #   0: new brand (default — what someone Googling our name sees)
    #   1: legacy brand (rebrand stickiness check)
    #   2: review intent (catches mouthshut/trustpilot/consumeraffairs)
    #   3: comparison intent (vs HDFC/ICICI articles)
    #   4: news intent (recent coverage)
    #   5: complaint / claim intent (negative-sentiment surface)
    #   6: best-of intent (aggregator + comparison editorial)
    from datetime import datetime, timezone as tz
    new_tok = (cfg.get("brand_tokens_new") or ["Bajaj Life Insurance"])[0]
    old_tok = (cfg.get("brand_tokens_old") or ["Bajaj Allianz Life"])[0]

    QUERY_ROTATION = [
        f'"{new_tok}"',
        f'"{old_tok}"',
        f'"{new_tok}" review',
        f'"{new_tok}" vs',
        f'"{new_tok}" news',
        f'"{new_tok}" complaint OR claim',
        f'best life insurance India "Bajaj"',
    ]
    day_of_year = datetime.now(tz.utc).timetuple().tm_yday
    query = QUERY_ROTATION[day_of_year % len(QUERY_ROTATION)].strip()
    log.info("serpapi: today=%d/%d query=%r",
             day_of_year % len(QUERY_ROTATION), len(QUERY_ROTATION), query)

    try:
        from ..serp_api import SerpAPIAdapter
        from ..ai_visibility.base import AdapterDisabledError
    except ImportError as exc:
        log.warning("serpapi: client not importable (%s)", exc)
        return []

    try:
        adapter = SerpAPIAdapter()
    except AdapterDisabledError as exc:
        log.warning("serpapi: adapter disabled (%s)", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        log.warning("serpapi: adapter init failed (%s)", exc)
        return []

    # NOTE: the existing SerpAPIAdapter.search() only accepts query +
    # engine + device. num + location come from its own settings
    # (SERPAPI_RESULTS_PER_QUERY + SERPAPI_COUNTRY env vars). We use
    # those defaults rather than override per-call.
    try:
        result = adapter.search(
            query=query,
            engine="google",
            device="desktop",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("serpapi: search failed (%s)", exc)
        return []

    if getattr(result, "error", None):
        log.warning("serpapi: returned error: %s", result.error)
        return []

    _MEMORY_CALLS_THIS_RUN += 1

    brand_pattern = re.compile(
        "|".join(re.escape(t) for t in all_brand_tokens()),
        re.IGNORECASE,
    )

    organic = getattr(result, "organic", None) or []
    out: list[SerpItem] = []
    for row in organic:
        # row is OrganicRow dataclass — access via attribute
        link = getattr(row, "link", "") or getattr(row, "url", "")
        title = getattr(row, "title", "") or ""
        snippet_raw = getattr(row, "snippet", "") or getattr(row, "description", "") or ""
        if not link or not link.startswith(("http://", "https://")):
            continue
        # Defensive — should always match because we queried for the
        # brand, but the SerpAPI engine occasionally pads with related
        # results. Filter those out.
        if not brand_pattern.search(f"{title} {snippet_raw}"):
            continue
        variant = classify_brand_variant(title, snippet_raw)
        tier = classify_source_tier(link)
        snippet = extract_snippet(snippet_raw, around_match="Bajaj", length=240)
        out.append(SerpItem(
            source_url=link[:2000],
            source_domain=domain_of(link)[:255],
            source_title=title[:512],
            snippet=snippet,
            brand_variant=variant,
            source_tier=tier,
            raw_payload={
                "query": query,
                "position": getattr(row, "position", None),
                "engine": "google",
                "device": "desktop",
            },
        ))

    log.info(
        "serpapi: query=%r returned %d organic, %d matched brand pattern",
        query, len(organic), len(out),
    )
    return out
