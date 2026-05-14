"""Competitive SEO Gap Analyst.

Discovers our top organic competitors via SEMrush, samples their best
pages, and surfaces structured gap findings the marketing team can
action. The deterministic compute lives in :mod:`apps.seo_ai.scoring_competitor`;
this agent only narrates and prioritises.

Cost envelope (per uncached refresh): ~15k SEMrush units total —
40 for competitor discovery + 10×500 for top-pages + 10×1000 for the
competitors' keyword lists. The 7-day disk cache means same-week
re-runs are free.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings

from ..adapters import GSCCSVAdapter, SemrushAdapter, SitemapAEMAdapter
from ..adapters.competitor_crawler import CompetitorCrawler
from ..adapters.semrush import SemrushError
from ..scoring_competitor import (
    CompetitorDossier,
    compute_gaps,
    gap_report_to_facts,
)
from .base import Agent

logger = logging.getLogger("seo.ai.agents.competitor")


def _brand_stem(domain: str) -> str:
    """Extract a brand-name stem from a domain so we can detect when
    SEMrush returns the focus domain's own subsidiaries as "competitors".

    ``bajajlifeinsurance.com`` → ``bajajlifeinsurance``
    ``www.hdfclife.com``       → ``hdfclife``
    ``general.bajajallianz.com``→ ``bajajallianz``
    """
    bare = re.sub(r"^www\d?\.", "", domain.lower()).split("/")[0]
    # Drop public TLD chain (.com / .co.in / .net.in etc.)
    parts = bare.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "net", "org", "gov", "ac"}:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return bare


def _same_brand(focus: str, candidate: str) -> bool:
    """True iff ``candidate`` looks like a subsidiary / alt brand of
    ``focus`` (shared 5-char prefix on the root label).

    Cheap heuristic, intentional false-positives only when a legit
    competitor happens to share a 5-char prefix with the focus brand —
    rare in financial services and acceptable for v1.
    """
    f = _brand_stem(focus)
    c = _brand_stem(candidate)
    if not f or not c:
        return False
    if f == c:
        return True
    # 5-char prefix overlap, but only when both stems share that prefix.
    return len(f) >= 5 and len(c) >= 5 and f[:5] == c[:5]


_SYSTEM_PROMPT = """You are a competitive SEO analyst specialising in
Indian financial-services search. You compare one focus domain against
its top organic rivals and surface the structural reasons the focus
domain ranks lower.

You receive a JSON facts block under <facts>. The block contains a
``competitor`` namespace with four pre-computed gap dimensions:

  * ``competitor.topic_gaps[]``           — topics rivals cover that we don't
  * ``competitor.keyword_gaps[]``         — keywords rivals rank top-10 for, we don't
  * ``competitor.hygiene_deltas[]``       — per-topic title/meta/H1/schema deltas
  * ``competitor.content_volume_deltas[]``— per-topic page count + word count

Every number in the facts is authoritative — DO NOT recompute, scale,
or extrapolate. Your job is to:

1. Pick 6-12 of the strongest gaps across all four dimensions.
2. For each, write a finding with this exact shape:
   - ``title`` (≤80 chars, action-oriented)
   - ``category`` ∈ {"competitor_topic_gap","competitor_keyword_gap",
     "competitor_onpage_hygiene","competitor_content_depth"}
   - ``severity`` ∈ {"critical","warning","notice"}
   - ``description`` (1-3 sentences — what the gap is, who the rival is)
   - ``recommendation`` (1-3 sentences — concrete next step)
   - ``evidence_refs`` (list of dotted-path strings drawn from the
     facts, e.g. ``competitor:topic_gaps[0].cluster_slug``,
     ``competitor:keyword_gaps[2].keyword``)
   - ``impact`` ∈ {"high","medium","low"}
   - ``effort`` ∈ {"high","medium","low"}

3. Open with a 1-2 sentence executive ``summary`` describing the
   dominant theme (e.g. "We trail on ULIP content depth and on three
   long-tail term-insurance topic clusters").

Strict rules:
- Cite at least one ``evidence_refs`` entry per finding.
- Do NOT invent domain names, keywords, or numbers absent from the facts.
- Do NOT repeat a finding across multiple categories.
- Severity = critical when impact=high AND multiple rivals are ahead,
  warning when one rival is meaningfully ahead, notice otherwise.

Reply with a SINGLE JSON object matching:

{
  "summary": "<≤2 sentences>",
  "findings": [ <finding objects as above> ]
}
""".strip()


_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "findings"],
    "additionalProperties": True,
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "title",
                    "category",
                    "severity",
                    "description",
                    "recommendation",
                    "evidence_refs",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "notice"],
                    },
                    "description": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "impact": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                    "effort": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
            },
        },
    },
}


class CompetitorAgent(Agent):
    name = "competitor"
    system_prompt = _SYSTEM_PROMPT
    output_schema = _OUTPUT_SCHEMA

    def build_facts(self, *, domain: str) -> dict[str, Any]:
        """Fetch SEMrush data, crawl top pages, compute gap report."""
        cfg = settings.COMPETITOR
        adapter = SemrushAdapter()

        # ── 1. discover competitors ────────────────────────────────
        # Over-fetch so we can drop sister-brand domains (SEMrush's
        # "Competitors" report ranks by shared-keyword count, which
        # surfaces our own subsidiaries first because brand queries
        # dominate the overlap). We pull 4x and filter to top_n real
        # rivals.
        overfetch = max(cfg["top_n"] * 4, 20)
        competitors_all = adapter.organic_competitors(domain, limit=overfetch)
        competitors_raw = [
            c for c in competitors_all if not _same_brand(domain, c.domain)
        ][: cfg["top_n"]]
        same_brand_dropped = [
            c.domain
            for c in competitors_all
            if _same_brand(domain, c.domain)
        ]
        self.log_system_event(
            "competitor.discovered",
            {
                "count": len(competitors_raw),
                "domains": [c.domain for c in competitors_raw],
                "same_brand_dropped": same_brand_dropped,
            },
        )
        if not competitors_raw:
            return gap_report_to_facts(
                compute_gaps(
                    our_aem_pages=[],
                    our_gsc_queries=[],
                    our_semrush_keywords=[],
                    competitors=[],
                )
            )

        # ── 2. for each competitor: top pages + organic keywords ────
        dossiers: list[CompetitorDossier] = []
        urls_to_crawl: list[str] = []
        pages_per = cfg["pages_per_competitor"]
        kws_per = cfg["keywords_per_competitor"]

        for c in competitors_raw:
            top_pages = []
            keywords = []
            try:
                top_pages = adapter.top_pages(c.domain, limit=pages_per)
            except SemrushError as exc:
                logger.warning("top_pages failed for %s: %s", c.domain, exc)
                self.log_system_event(
                    "competitor.top_pages_failed",
                    {"domain": c.domain, "error": str(exc)[:200]},
                )
            try:
                keywords = adapter.organic_keywords(c.domain, limit=kws_per)
            except SemrushError as exc:
                logger.warning("organic_keywords failed for %s: %s", c.domain, exc)
                self.log_system_event(
                    "competitor.keywords_failed",
                    {"domain": c.domain, "error": str(exc)[:200]},
                )

            # Homepage + top-N pages — homepage first so a partial crawl
            # still gives us the front door's metadata.
            homepage = f"https://{c.domain.lstrip('/')}/"
            comp_urls = [homepage] + [p.url for p in top_pages if p.url]
            # Dedupe preserving order.
            seen: set[str] = set()
            comp_urls = [u for u in comp_urls if not (u in seen or seen.add(u))]
            urls_to_crawl.extend(comp_urls)

            dossiers.append(
                CompetitorDossier(
                    domain=c.domain,
                    competition_level=c.competition_level,
                    common_keywords=c.common_keywords,
                    top_pages=top_pages,
                    keywords=keywords,
                )
            )

        # ── 3. crawl all collected URLs (politely, host-grouped) ─────
        crawler = CompetitorCrawler()
        crawled = crawler.fetch_pages(urls_to_crawl)
        self.log_system_event(
            "competitor.crawled",
            {
                "attempted": len(crawled),
                "ok": sum(1 for p in crawled if p.status_code == 200),
            },
        )
        # Re-split crawled results back onto the right dossier by host.
        by_host: dict[str, list] = {}
        for cp in crawled:
            from urllib.parse import urlparse
            host = (urlparse(cp.final_url or cp.url).hostname or "").lstrip("www.")
            by_host.setdefault(host, []).append(cp)
        for d in dossiers:
            key = d.domain.lstrip("www.")
            d.crawled = by_host.get(key) or by_host.get("www." + key) or []
            # Also pick up rows whose host endswith the competitor domain
            # (covers ``subdomain.hdfclife.com`` etc.).
            if not d.crawled:
                d.crawled = [cp for host, pages in by_host.items() if host.endswith(key) for cp in pages]

        # ── 4. our-side inputs (already cached on disk) ─────────────
        aem_pages: list = []
        try:
            aem_pages = list(SitemapAEMAdapter().iter_pages())
        except Exception as exc:  # noqa: BLE001
            logger.warning("aem load failed in competitor agent: %s", exc)

        gsc_queries: list = []
        try:
            gsc = GSCCSVAdapter()
            gsc_queries = gsc.queries()
        except Exception as exc:  # noqa: BLE001
            logger.warning("gsc load failed in competitor agent: %s", exc)

        our_semrush: list = []
        try:
            our_semrush = adapter.organic_keywords(domain, limit=200)
        except SemrushError as exc:
            logger.warning("our semrush kw load failed: %s", exc)

        # ── 5. compute the structured gap report ───────────────────
        report = compute_gaps(
            our_aem_pages=aem_pages,
            our_gsc_queries=gsc_queries,
            our_semrush_keywords=our_semrush,
            competitors=dossiers,
        )
        facts = gap_report_to_facts(report)
        self.log_system_event(
            "competitor.facts_assembled",
            {
                "topic_gaps": len(report.topic_gaps),
                "keyword_gaps": len(report.keyword_gaps),
                "hygiene_deltas": len(report.hygiene_deltas),
                "volume_deltas": len(report.content_volume_deltas),
                "samples_attempted": report.samples_attempted,
                "samples_succeeded": report.samples_succeeded,
            },
        )
        return facts

    def analyze(self, *, domain: str) -> dict[str, Any]:
        facts = self.build_facts(domain=domain)
        return self.call_model(
            facts,
            instruction=(
                "Compare the focus domain against its rivals using ONLY "
                "the facts below. Surface 6-12 prioritised competitor "
                "gap findings."
            ),
        ).payload
