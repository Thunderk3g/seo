"""Technical SEO Auditor.

Consumes the rollup from :class:`CrawlerCSVAdapter` and the metadata
hygiene rollup from :class:`SitemapAEMAdapter`. Returns a structured
list of findings (broken links, thin content, slow responses, missing
metadata, orphan pages) plus the LLM's narrative around each. Numbers
that drive the score are computed deterministically in Python (see
``scoring.py``); the LLM only produces the *story* around each
finding.
"""
from __future__ import annotations

from typing import Any

from ..adapters import CrawlerCSVAdapter, SitemapAEMAdapter
from .base import Agent

_SYSTEM_PROMPT = """You are a senior technical SEO auditor with 15+ years of
experience working on enterprise sites in regulated industries
(insurance, finance). You think like a Google crawler engineer — you
care about crawl budget, indexability, render-cost, internal-link
equity, and template-level patterns rather than one-off URLs.

You will receive a JSON facts block summarising one site's crawl and
its CMS-declared metadata. Your job is to:

1. Identify the **categories** of issue present (e.g. thin content,
   slow response template, missing meta description, orphan section).
2. For each category, write a concrete finding with:
   - `title` (≤80 chars, action-oriented)
   - `category` (short slug, snake_case)
   - `severity` ∈ {"critical","warning","notice"}
   - `description` (1–3 sentences, what is wrong and why it matters)
   - `recommendation` (1–3 sentences, what to do, in concrete terms)
   - `evidence_refs` (list of strings drawn from the facts — `crawler:thin_content_urls[0]`, `aem:summary.pages_without_description`, etc.)
   - `impact` ∈ {"high","medium","low"}
   - `effort` ∈ {"high","medium","low"}

Do NOT invent URLs, counts, or templates that are not present in the
facts. If a fact is missing, omit the finding rather than guess.

Reply with a single JSON object exactly matching this shape:

{
  "summary": "<≤2 sentences executive summary of the technical health>",
  "findings": [ <finding objects as above> ]
}

Aim for 8–15 findings prioritised by impact. Do not duplicate the same
issue across multiple findings.
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


class TechnicalAgent(Agent):
    name = "technical"
    system_prompt = _SYSTEM_PROMPT
    output_schema = _OUTPUT_SCHEMA

    def build_facts(self) -> dict[str, Any]:
        crawler = CrawlerCSVAdapter()
        aem = SitemapAEMAdapter()
        crawler_summary = crawler.summary()
        # AEM is large (~7 files × 14 MB). The summary walks them all
        # but never holds two files in memory at once.
        aem_summary = aem.summary()

        # Trim aggressively. Groq free tier caps requests at 8 000 TPM
        # for gpt-oss-120b; we keep one-shot prompts well under that so
        # the run doesn't paginate against the rate limit. The numeric
        # counts already convey scale — we only need ~8 example URLs
        # per category for the LLM to ground its recommendations.
        crawler_payload = {
            "summary": _trim_summary(crawler_summary.__dict__, sample_titles_keep=6),
            "thin_content_urls": crawler.thin_content_urls(limit=6),
            "slow_response_urls": crawler.slow_response_urls(limit=6),
            "error_404_urls": crawler.error_404_urls(limit=6),
        }
        aem_payload = {"summary": _aem_summary_to_dict(aem_summary, top_components=10)}

        facts = {"crawler": crawler_payload, "aem": aem_payload}
        self.log_system_event(
            "facts.assembled",
            {
                "crawler_pages": crawler_summary.total_pages,
                "aem_pages": aem_summary.total_pages,
            },
        )
        return facts

    def analyze(self) -> dict[str, Any]:
        facts = self.build_facts()
        result = self.call_model(
            facts,
            instruction=(
                "Audit the technical SEO health of this site using ONLY "
                "the facts below. Surface 8–15 prioritised findings."
            ),
        )
        return result.payload


def _aem_summary_to_dict(s, *, top_components: int = 10) -> dict[str, Any]:
    out = dict(s.__dict__)
    # datetimes → isoformat strings so the JSON encoder is happy
    for key in ("most_recent_modification", "least_recent_modification"):
        v = out.get(key)
        if hasattr(v, "isoformat"):
            out[key] = v.isoformat()
    # Cap the component usage map — the long tail isn't useful at
    # site-rollup grain and inflates token count.
    cu = out.get("component_usage") or {}
    if isinstance(cu, dict) and len(cu) > top_components:
        out["component_usage"] = dict(list(cu.items())[:top_components])
    # Templates list is short by nature; cap defensively.
    templates = out.get("distinct_templates") or []
    if isinstance(templates, list) and len(templates) > 10:
        out["distinct_templates"] = templates[:10]
    return out


def _trim_summary(d: dict[str, Any], *, sample_titles_keep: int) -> dict[str, Any]:
    trimmed = dict(d)
    titles = trimmed.get("sample_titles") or []
    if isinstance(titles, list):
        trimmed["sample_titles"] = titles[:sample_titles_keep]
    breakdown = trimmed.get("status_breakdown") or {}
    if isinstance(breakdown, dict) and len(breakdown) > 8:
        # Keep the 8 most-populated status codes; the rest sum into "other".
        ordered = sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True)
        top = dict(ordered[:8])
        other = sum(v for _, v in ordered[8:])
        if other:
            top["other"] = other
        trimmed["status_breakdown"] = top
    return trimmed
