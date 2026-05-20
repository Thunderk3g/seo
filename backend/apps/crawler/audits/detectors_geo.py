"""Phase 6 GEO-specific audit detectors.

Two issue types that target AI-search readiness rather than classic
SEO. Operate on the existing crawl_results.csv schema so they need
no crawler instrumentation.

  * missing_llms_txt              — no /llms.txt at site root
  * low_citation_density_title    — title lacks markers AI engines
                                     reward for citation (definitions,
                                     numbers, comparison signals)

The fuller per-page citation-density scoring (definitions in first
1500 chars, lists, tables, Q&A blocks) needs body-text capture in
the in-house crawler. That lands in a separate engine-instrumentation
commit; this file gets the catalog primed with the issue types so
the dashboard surfaces them as "needs crawler change" until then.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .catalog import IssueDef, _is_ok


_TITLE_CITATION_MARKERS = re.compile(
    r"\b(what\s+is|how\s+to|guide|definition|meaning|"
    r"types?\s+of|compare|comparison|vs\.?|versus|"
    r"calculator|cost|premium|step\s*-?by\s*-?step|\d+\s*(?:lakh|crore|%))\b",
    re.IGNORECASE,
)


def _detect_low_citation_density_title(rows: list[dict]) -> list[dict]:
    """OK pages whose title has none of the citation-friendly markers
    AI search engines reward. Lower bound — pages without ANY of these
    are statistically less likely to appear in AI Overview citations
    per the GEO research."""
    return [
        r for r in rows
        if _is_ok(r)
        and (r.get("title") or "").strip()
        and not _TITLE_CITATION_MARKERS.search(r.get("title") or "")
        and (r.get("subdomain") or "") == "www"
    ]


# We can't crawl /llms.txt from within a row-by-row detector — that
# requires a network round-trip. The "detector" therefore returns a
# single synthetic "row" with the audit URL when the file is missing,
# so the Health Score formula counts a single error for the whole
# site rather than per-URL. The full audit lives in the
# services/llms_txt.py audit() entry point.

def _detect_missing_llms_txt(rows: list[dict]) -> list[dict]:
    """Stub: returns one synthetic row when llms.txt audit shows
    missing. Cached in module state to avoid hitting the network on
    every audit run — the periodic snapshot_metrics task refreshes
    by clearing the cache."""
    global _LLMS_TXT_CACHE
    if _LLMS_TXT_CACHE is not None:
        return list(_LLMS_TXT_CACHE)
    try:
        from ..services.llms_txt import audit as audit_llms_txt
        result = audit_llms_txt()
    except Exception:  # noqa: BLE001
        _LLMS_TXT_CACHE = []
        return []
    if not result.found:
        _LLMS_TXT_CACHE = [{
            "url": result.url,
            "status_code": str(result.status_code) if result.status_code else "0",
            "title": "/llms.txt site-wide audit",
            "word_count": "0",
            "response_time_ms": "0",
            "subdomain": "www",
            "page_type": "compliance",
            "category_key": "geo",
            "from_sitemap": "0",
            "indexed_status": "unknown",
            "error_type": "MissingLlmsTxt",
            "error_message": (result.issues or [""])[0][:200],
            "pagespeed_score": "", "lcp_ms": "", "cls": "", "inp_ms": "",
        }]
    else:
        _LLMS_TXT_CACHE = []
    return list(_LLMS_TXT_CACHE)


_LLMS_TXT_CACHE: list[dict] | None = None


def clear_llms_txt_cache() -> None:
    """Force a refresh on next detector run. Called by snapshot_metrics
    so the daily snapshot picks up live changes when the operator
    publishes a new llms.txt."""
    global _LLMS_TXT_CACHE
    _LLMS_TXT_CACHE = None


GEO_ISSUES: tuple[IssueDef, ...] = (
    IssueDef(
        slug="missing_llms_txt",
        title="No /llms.txt at site root",
        severity="warning",
        category="compliance",
        why=(
            "llms.txt is the AI-search equivalent of robots.txt — a "
            "single Markdown file at site root that ChatGPT browsing, "
            "Claude, and Perplexity consume at inference time to "
            "navigate the site. Missing it means AI clients have no "
            "curated index of canonical pages."
        ),
        how_to_fix=(
            "Generate a draft via /api/v1/seo/llms-txt/draft or chat "
            "tool generate_llms_txt. Review the draft, commit it to "
            "AEM, publish at https://yourdomain/llms.txt."
        ),
        detector=_detect_missing_llms_txt,
    ),
    IssueDef(
        slug="low_citation_density_title",
        title="Title lacks AI-citation markers",
        severity="notice",
        category="content",
        why=(
            "AI search engines preferentially cite pages whose titles "
            "signal definition / how-to / comparison / numeric intent "
            "(GEO research from Princeton + others). Titles without ANY "
            "of these markers (what is / how to / guide / vs / types of "
            "/ N lakh, etc.) get fewer Citations in AI Overview."
        ),
        how_to_fix=(
            "Rewrite the title to include the user's literal query "
            "intent. Example: 'Term Insurance' -> 'Term Insurance: "
            "What It Is + How Premium Is Calculated (Worked Example)'."
        ),
        detector=_detect_low_citation_density_title,
    ),
)
