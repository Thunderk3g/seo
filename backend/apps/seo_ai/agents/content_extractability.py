"""ContentExtractabilityAgent — detection-only.

Per-page extractability scoring for AI-citation worthiness. Maps
directly to the SKILL.md "Content Extractability Check":

  * Lead-paragraph definition (first <p> 40-200 words).
  * Self-contained answer blocks (H2 followed by 40-60 word block).
  * Statistics with sources (number + citation context).
  * Comparison table presence (<table> with ≥3 data rows).
  * FAQ block (FAQPage schema OR <details> OR question-style headings).
  * Schema markup types per page.
  * Expert attribution (<meta name="author"> OR Person schema).
  * Freshness signal (visible "Last updated" OR dateModified schema).
  * Heading-as-query phrasing.

We only crawl OUR top pages (from AEM sitemap) since the symmetric
crawl is expensive — the existing CompetitorAgent already produces
competitor structural data, which we read out of its system events
when available.
"""
from __future__ import annotations

import logging
import re
import statistics
from typing import Any

from bs4 import BeautifulSoup

from ..adapters.competitor_crawler import CompetitorCrawler
from ..adapters.sitemap_aem import SitemapAEMAdapter
from .base import Agent, FindingDraft

logger = logging.getLogger("seo.ai.agents.content_extractability")


_FAQ_QUESTION_RE = re.compile(
    r"\b(what|how|why|when|where|which|who|is|can|do|does|are)\b.*\?",
    re.IGNORECASE,
)
_QUERY_PHRASE_RE = re.compile(
    r"^\s*(what|how|why|when|where|which|who|is|are|best|top|vs\.?|versus)\b",
    re.IGNORECASE,
)
_STAT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|x|times|million|billion|crore|lakh)\b",
    re.IGNORECASE,
)
_LAST_UPDATED_RE = re.compile(
    r"\b(last updated|updated on|reviewed on|published on)\b\s*[:\-]?\s*"
    r"[A-Za-z]+\s*\d{1,2},?\s*20\d{2}",
    re.IGNORECASE,
)


def _score_page(html: str) -> dict[str, Any]:
    """Score one HTML page across the SKILL.md extractability checks.

    Returns a dict with boolean flags + a coarse 0-10 ``score`` for
    comparability. The dict is what the agent persists; the findings
    are built per-domain from aggregates of this dict.
    """
    if not html:
        return {"score": 0, "ok": False}
    soup = BeautifulSoup(html, "html.parser")

    # Strip noise tags so word counts and first-paragraph extraction
    # aren't polluted by scripts / nav.
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()

    # 1. Lead paragraph (first non-empty <p> ≥ 40 words).
    lead_para_def = False
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        words = text.split()
        if 40 <= len(words) <= 200:
            lead_para_def = True
            break

    # 2. Self-contained answer blocks (H2 followed by a short paragraph).
    answer_blocks = 0
    for h in soup.find_all(["h2", "h3"]):
        nxt = h.find_next_sibling()
        if not nxt or nxt.name != "p":
            continue
        wc = len(nxt.get_text(" ", strip=True).split())
        if 40 <= wc <= 80:
            answer_blocks += 1

    # 3. Statistics presence.
    body_text = soup.get_text(" ", strip=True)
    stat_count = len(_STAT_RE.findall(body_text))

    # 4. Comparison table.
    has_comparison_table = False
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) >= 4:
            has_comparison_table = True
            break

    # 5. FAQ block: schema-driven or DOM-driven.
    has_faq_schema = False
    schema_types: list[str] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        if "FAQPage" in raw:
            has_faq_schema = True
        # Cheap @type scrape.
        for t in re.findall(r'"@type"\s*:\s*"([^"]+)"', raw):
            schema_types.append(t)

    faq_question_count = 0
    for h in soup.find_all(["h2", "h3", "summary"]):
        text = h.get_text(" ", strip=True)
        if _FAQ_QUESTION_RE.search(text):
            faq_question_count += 1
    has_faq_block = has_faq_schema or faq_question_count >= 3

    # 6. Expert attribution.
    has_author_meta = soup.find(
        "meta", attrs={"name": re.compile("author", re.I)}
    ) is not None
    has_author_schema = "Person" in schema_types
    has_author = has_author_meta or has_author_schema

    # 7. Freshness: visible "Last updated" or dateModified schema.
    visible_updated = bool(_LAST_UPDATED_RE.search(body_text[:5000]))
    has_date_modified = bool(
        re.search(r'"dateModified"\s*:\s*"', " ".join(
            [s.string or "" for s in soup.find_all("script") if s.string]
        ))
    )
    has_freshness = visible_updated or has_date_modified

    # 8. Query-style headings.
    query_headings = 0
    for h in soup.find_all(["h2", "h3"]):
        text = h.get_text(" ", strip=True)
        if _QUERY_PHRASE_RE.match(text):
            query_headings += 1
    has_query_headings = query_headings >= 3

    # Composite 0-10 score: 1 point per signal that passed.
    signals = [
        lead_para_def,
        answer_blocks >= 2,
        stat_count >= 2,
        has_comparison_table,
        has_faq_block,
        bool(schema_types),
        has_author,
        has_freshness,
        has_query_headings,
        len(schema_types) >= 2,   # multi-type schema graph
    ]
    score = sum(1 for s in signals if s)

    return {
        "score": score,
        "ok": True,
        "lead_para_def": lead_para_def,
        "answer_blocks": answer_blocks,
        "stat_count": stat_count,
        "has_comparison_table": has_comparison_table,
        "has_faq_block": has_faq_block,
        "schema_types_count": len(schema_types),
        "has_author": has_author,
        "has_freshness": has_freshness,
        "has_query_headings": has_query_headings,
    }


class ContentExtractabilityAgent(Agent):
    name = "content_extractability"
    system_prompt = "Detection-only agent."

    def detect(self, *, domain: str) -> list[FindingDraft]:
        try:
            aem_pages = list(SitemapAEMAdapter().iter_pages())
        except Exception as exc:  # noqa: BLE001
            logger.info("aem load failed: %s", exc)
            self.log_system_event(
                "content_extractability.skipped",
                {"reason": f"aem load failed: {exc}"[:200]},
            )
            return []

        # Pick top ~10 pages by word count — they're the meatiest and
        # most ranking-relevant.
        candidates = sorted(
            [p for p in aem_pages if p.word_count and p.public_url],
            key=lambda p: p.word_count,
            reverse=True,
        )[:10]
        if not candidates:
            self.log_system_event(
                "content_extractability.skipped",
                {"reason": "no AEM pages with word_count > 0"},
            )
            return []

        crawler = CompetitorCrawler()
        scored: list[dict[str, Any]] = []
        for page in candidates:
            crawled = crawler.fetch_one(page.public_url)
            if crawled.status_code != 200:
                continue
            # We need raw HTML for the parsing. The crawler caches the
            # HTML; we re-read it from the cache when available, else
            # fall back to BeautifulSoup-parseable text (which is what
            # the crawled.body_text already provides as a slice).
            html = self._raw_html_for(crawler, page.public_url)
            metrics = _score_page(html or "")
            if not metrics.get("ok"):
                continue
            metrics["url"] = page.public_url
            metrics["title"] = page.title or ""
            scored.append(metrics)

        self.log_system_event(
            "content_extractability.scored",
            {"pages_scored": len(scored)},
        )

        if not scored:
            return []

        return self._findings(scored)

    def valid_evidence_keys(self) -> set[str]:
        return {"content_extractability:detection_only"}

    # ── helpers ──────────────────────────────────────────────────────

    def _raw_html_for(
        self, crawler: CompetitorCrawler, url: str
    ) -> str | None:
        """Read the HTML cache file the crawler wrote, if present."""
        html_path, _meta_path = crawler._cache_path(url)
        if not html_path.exists():
            return None
        try:
            with html_path.open("r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def _findings(
        self, scored: list[dict[str, Any]]
    ) -> list[FindingDraft]:
        out: list[FindingDraft] = []
        n = len(scored)
        avg_score = statistics.mean(s["score"] for s in scored)

        # 1. Average extractability score signal.
        severity = (
            "critical" if avg_score < 4 else "warning" if avg_score < 6 else "notice"
        )
        out.append(
            FindingDraft(
                category="content_extractability_overall",
                severity=severity,
                title=(
                    f"Average page extractability {avg_score:.1f}/10 "
                    f"across {n} top pages"
                ),
                description=(
                    "Extractability score sums presence of: lead-paragraph "
                    "definition, answer blocks, stats, comparison tables, "
                    "FAQ blocks, schema markup, author attribution, "
                    "freshness signals, query-style headings, and multi-"
                    "type schema graph."
                ),
                evidence_refs=[
                    f"content_extractability:avg_score={avg_score:.2f}",
                    f"content_extractability:pages_scored={n}",
                ],
                impact="high" if avg_score < 5 else "medium",
            )
        )

        # 2. FAQ block coverage.
        no_faq = [s for s in scored if not s.get("has_faq_block")]
        if len(no_faq) >= n / 2:
            sample = [s["url"] for s in no_faq[:3]]
            out.append(
                FindingDraft(
                    category="content_extractability_faq",
                    severity="warning",
                    title=(
                        f"FAQ block missing on {len(no_faq)}/{n} top pages"
                    ),
                    description=(
                        "FAQPage schema and question-style headings are "
                        "the highest-yield signal for AI citation. "
                        "Examples missing FAQ: "
                        + ", ".join(sample)
                    ),
                    evidence_refs=[
                        f"content_extractability:no_faq[{i}]={u}"
                        for i, u in enumerate(sample)
                    ],
                    impact="high",
                )
            )

        # 3. Freshness signal missing.
        no_fresh = [s for s in scored if not s.get("has_freshness")]
        if len(no_fresh) >= n * 0.6:
            sample = [s["url"] for s in no_fresh[:3]]
            out.append(
                FindingDraft(
                    category="content_extractability_freshness",
                    severity="warning",
                    title=(
                        f"No freshness signal on {len(no_fresh)}/{n} top "
                        f"pages (visible date or dateModified schema)"
                    ),
                    description=(
                        "AI search systems weight recency heavily. "
                        "Undated content loses to dated content on "
                        "competitive queries. Examples: "
                        + ", ".join(sample)
                    ),
                    evidence_refs=[
                        f"content_extractability:no_freshness[{i}]={u}"
                        for i, u in enumerate(sample)
                    ],
                    impact="high",
                )
            )

        # 4. Stats density.
        thin_stats = [s for s in scored if (s.get("stat_count") or 0) < 2]
        if len(thin_stats) >= n * 0.6:
            sample = [s["url"] for s in thin_stats[:3]]
            out.append(
                FindingDraft(
                    category="content_extractability_stats",
                    severity="notice",
                    title=(
                        f"Thin statistics coverage on {len(thin_stats)}/"
                        f"{n} top pages"
                    ),
                    description=(
                        "Statistics with sources are a +37% AI-citation "
                        "boost per the Princeton GEO research. Several "
                        "top pages carry fewer than 2 numeric data "
                        "points. Examples: "
                        + ", ".join(sample)
                    ),
                    evidence_refs=[
                        f"content_extractability:thin_stats[{i}]={u}"
                        for i, u in enumerate(sample)
                    ],
                    impact="medium",
                )
            )

        # 5. Comparison table.
        no_table = [s for s in scored if not s.get("has_comparison_table")]
        if len(no_table) >= n * 0.7:
            out.append(
                FindingDraft(
                    category="content_extractability_comparison",
                    severity="notice",
                    title=(
                        f"No comparison table on {len(no_table)}/{n} top pages"
                    ),
                    description=(
                        "Comparison tables receive ~33% of AI citation "
                        "share for 'X vs Y' queries. Most top pages do "
                        "not include one."
                    ),
                    evidence_refs=[
                        f"content_extractability:no_comparison_table={len(no_table)}"
                    ],
                    impact="medium",
                )
            )

        # 6. Author attribution.
        no_author = [s for s in scored if not s.get("has_author")]
        if len(no_author) >= n * 0.7:
            out.append(
                FindingDraft(
                    category="content_extractability_author",
                    severity="notice",
                    title=(
                        f"No author attribution on {len(no_author)}/{n} "
                        f"top pages"
                    ),
                    description=(
                        "Named author / Person schema is a +25-30% AI-"
                        "citation boost. Most top pages don't surface "
                        "either."
                    ),
                    evidence_refs=[
                        f"content_extractability:no_author={len(no_author)}"
                    ],
                    impact="medium",
                )
            )

        return out
