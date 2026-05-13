"""SERP & Keyword Intelligence Agent.

Consumes the Google Search Console rollup + (optionally) the SEMrush
domain overview. Produces a structured list of opportunities:

- High-impression / low-click queries — title or meta is failing to
  earn clicks at the position the page already ranks at.
- Underperforming positions (4–15) where moving up 1–3 spots compounds.
- Featured-snippet candidates (top 5 + question-like queries).
- Cannibalisation hints from query→page distributions (Phase 2 — we
  surface the queries but flag this category as exploratory).
"""
from __future__ import annotations

from typing import Any

from django.conf import settings

from ..adapters import GSCCSVAdapter, SemrushAdapter
from .base import Agent

_SYSTEM_PROMPT = """You are a SERP analyst who has worked on enterprise
search verticals (insurance, fintech) where small rank moves convert to
real revenue. You read Search Console data like a CFO reads a balance
sheet: looking for where impressions are being earned but clicks are
being lost, and where rankings are within striking distance of step
changes.

You will receive a facts block with three GSC slices and (when
available) a SEMrush domain overview:

- `gsc.summary` — site rollup (totals, average position, average CTR).
- `gsc.top_queries_by_clicks` — the workhorse queries.
- `gsc.underperforming_queries` — positions 4–15 where CTR is below
  the industry curve by 40%+ (likely title/meta issue).
- `gsc.high_impression_low_click_queries` — visibility without clicks.
- `gsc.top_pages_by_clicks` — top landing pages.
- `semrush.overview` — competitive context (may be absent).

Your job is to surface 8–15 actionable findings. Each must:

- Cite the underlying fact via `evidence_refs` (e.g.
  `gsc:underperforming_queries[3].query`).
- State the *specific* query / page involved, not a generic theme.
- Suggest a concrete action (rewrite title, add FAQ block, build
  internal link from page X, etc.).

Do NOT invent queries or numbers not in the facts. Do not recommend
buying ads — this is organic-search analysis.

Reply ONLY with a single JSON object:

{
  "summary": "<2-sentence executive summary>",
  "findings": [
    {
      "title": "...",
      "category": "...",
      "severity": "critical|warning|notice",
      "description": "...",
      "recommendation": "...",
      "evidence_refs": ["..."],
      "impact": "high|medium|low",
      "effort": "high|medium|low"
    }
  ]
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
                    "impact": {"type": "string", "enum": ["high", "medium", "low"]},
                    "effort": {"type": "string", "enum": ["high", "medium", "low"]},
                },
            },
        },
    },
}


class KeywordAgent(Agent):
    name = "keyword"
    system_prompt = _SYSTEM_PROMPT
    output_schema = _OUTPUT_SCHEMA

    def build_facts(self, *, domain: str) -> dict[str, Any]:
        gsc = GSCCSVAdapter()
        try:
            # Keep each slice ≤10 rows; Groq free tier (8 000 TPM) is
            # tight, and the LLM doesn't need long lists — it needs
            # representative examples plus the totals to reason from.
            gsc_summary = gsc.summary(sample_size=10)
            gsc_payload = {
                "summary": {
                    "total_queries": gsc_summary.total_queries,
                    "total_pages": gsc_summary.total_pages,
                    "total_clicks": gsc_summary.total_clicks,
                    "total_impressions": gsc_summary.total_impressions,
                    "avg_ctr": round(gsc_summary.avg_ctr, 4),
                    "avg_position": round(gsc_summary.avg_position, 2),
                },
                "top_queries_by_clicks": [
                    q.__dict__ for q in gsc_summary.top_queries_by_clicks[:8]
                ],
                "underperforming_queries": [
                    q.__dict__ for q in gsc_summary.underperforming_queries[:8]
                ],
                "high_impression_low_click_queries": [
                    q.__dict__
                    for q in gsc_summary.high_impression_low_click_queries[:8]
                ],
                "top_pages_by_clicks": [
                    p.__dict__ for p in gsc_summary.top_pages_by_clicks[:8]
                ],
                "snapshot_path": gsc_summary.snapshot_path,
            }
        except FileNotFoundError:
            gsc_payload = {"error": "gsc data dir not found"}

        semrush_payload: dict[str, Any] = {}
        if settings.SEMRUSH["api_key"]:
            try:
                semrush = SemrushAdapter()
                overview = semrush.domain_overview(domain)
                semrush_payload = {"overview": overview.__dict__}
            except Exception as exc:  # pragma: no cover - external
                semrush_payload = {"error": str(exc)}

        facts = {"gsc": gsc_payload, "semrush": semrush_payload}
        self.log_system_event(
            "facts.assembled",
            {
                "gsc_queries": gsc_payload.get("summary", {}).get("total_queries"),
                "semrush_present": bool(semrush_payload.get("overview")),
            },
        )
        return facts

    def analyze(self, *, domain: str) -> dict[str, Any]:
        facts = self.build_facts(domain=domain)
        return self.call_model(
            facts,
            instruction=(
                "Identify 8–15 high-value SERP and keyword opportunities "
                "based ONLY on the facts. Prioritise by impact."
            ),
        ).payload
