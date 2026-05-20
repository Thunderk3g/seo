"""Typed issue catalogue for the crawler audit engine — Phase 1 (30 detectors).

Each :class:`IssueDef` describes one SEO problem the crawler can detect from
the existing ``crawl_results.csv`` schema. The detector is a pure function
that takes the loaded list of result rows and returns the subset of URLs the
issue applies to.

Severity model mirrors Ahrefs/SEMrush conventions:

  * **error**   — load-bearing; counts against the Health Score formula
                  ``(URLs without errors / total URLs) × 100``.
  * **warning** — should fix but doesn't tank the score.
  * **notice**  — information only.

Categories map to the eight thematic reports we'll add in Phase 5:
crawlability, indexability, content, titles, performance, cwv, urls,
compliance. Each detector reads only fields that already exist in
``RESULTS_FIELDS`` from ``storage/csv_writer.py`` — no schema change.

Adding a new issue is a one-liner: define an ``IssueDef`` with a detector
function and append to ``ALL_ISSUES``. Phase 4 adds ~120 more across new
audit categories.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Literal

Severity = Literal["error", "warning", "notice"]
Category = Literal[
    "crawlability", "indexability", "content", "titles",
    "performance", "cwv", "urls", "compliance",
]

SEVERITY_ORDER: dict[Severity, int] = {"error": 0, "warning": 1, "notice": 2}

CATEGORIES: tuple[Category, ...] = (
    "crawlability", "indexability", "content", "titles",
    "performance", "cwv", "urls", "compliance",
)

# Detector takes the full row list and returns the matching subset. We pass
# the whole list (not a single row) so cross-row checks (e.g., duplicate
# titles) can compose without re-iterating.
Detector = Callable[[list[dict]], list[dict]]


@dataclass(frozen=True)
class IssueDef:
    slug: str                  # url-safe: e.g., "duplicate_title"
    title: str                 # short, human, e.g., "Duplicate page titles"
    severity: Severity
    category: Category
    why: str                   # 1-2 sentences explaining the impact
    how_to_fix: str            # 1-3 sentences with concrete action
    detector: Detector


# ── helper predicates ────────────────────────────────────────────────────
def _is_ok(row: dict) -> bool:
    return (row.get("status_code") or "").strip() == "200"


def _to_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip()).lower()


_MARKETING_FILLERS = re.compile(
    r"\b(buy(?:\s+now)?|best|top|cheap(?:est)?|click\s+here|free|"
    r"#1|number\s*one|hot|amazing|incredible|guaranteed)\b",
    re.IGNORECASE,
)


# ── detectors ────────────────────────────────────────────────────────────
# 1. CRAWLABILITY (4)

def _detect_5xx(rows: list[dict]) -> list[dict]:
    return [r for r in rows if (r.get("status_code") or "").startswith("5")]


def _detect_404(rows: list[dict]) -> list[dict]:
    return [r for r in rows if (r.get("status_code") or "").strip() == "404"]


def _detect_403(rows: list[dict]) -> list[dict]:
    return [r for r in rows if (r.get("status_code") or "").strip() == "403"]


def _detect_network_failure(rows: list[dict]) -> list[dict]:
    return [r for r in rows if (r.get("status_code") or "").strip() in ("0", "")]


# 2. INDEXABILITY (3)

def _detect_unknown_index(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and (r.get("indexed_status") or "unknown") == "unknown"
    ]


def _detect_excluded_from_index(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and (r.get("indexed_status") or "") == "excluded"
    ]


def _detect_ok_not_in_sitemap(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r)
        and (r.get("from_sitemap") or "0") != "1"
        and (r.get("subdomain") or "") == "www"
    ]


# 3. CONTENT (5)

def _detect_missing_title(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and not (r.get("title") or "").strip()]


def _detect_duplicate_title(rows: list[dict]) -> list[dict]:
    counter: Counter[str] = Counter()
    for r in rows:
        if not _is_ok(r):
            continue
        t = _norm_title(r.get("title") or "")
        if t:
            counter[t] += 1
    dup_titles = {t for t, n in counter.items() if n > 1}
    return [
        r for r in rows
        if _is_ok(r) and _norm_title(r.get("title") or "") in dup_titles
    ]


def _detect_empty_body(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_int(r.get("word_count")) == 0]


def _detect_thin_content(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and 0 < _to_int(r.get("word_count")) < 300
    ]


def _detect_heavy_content(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_int(r.get("word_count")) > 8000]


# 4. TITLES (3)

def _detect_title_too_long(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and len((r.get("title") or "").strip()) > 70
    ]


def _detect_title_too_short(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r)
        and 0 < len((r.get("title") or "").strip()) < 30
    ]


def _detect_marketing_filler_in_title(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _MARKETING_FILLERS.search(r.get("title") or "")
    ]


# 5. PERFORMANCE (3)

def _detect_slow_response(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_int(r.get("response_time_ms")) > 3000
    ]


def _detect_very_slow_response(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_int(r.get("response_time_ms")) > 10_000
    ]


def _detect_missing_response_time(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_int(r.get("response_time_ms")) == 0
    ]


# 6. CWV (5)

def _has_psi(row: dict) -> bool:
    return bool((row.get("pagespeed_score") or "").strip())


def _detect_psi_missing(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and not _has_psi(r)]


def _detect_pagespeed_poor(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _has_psi(r) and _to_int(r.get("pagespeed_score")) < 50
    ]


def _detect_lcp_poor(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _has_psi(r) and _to_int(r.get("lcp_ms")) > 2500
    ]


def _detect_cls_poor(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _has_psi(r) and _to_float(r.get("cls")) > 0.1
    ]


def _detect_inp_poor(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _has_psi(r) and _to_int(r.get("inp_ms")) > 200
    ]


# 7. URLs (3)

def _detect_long_url(rows: list[dict]) -> list[dict]:
    return [r for r in rows if len(r.get("url") or "") > 200]


def _detect_query_stuffing(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if (r.get("url") or "").count("&") > 4
        or (r.get("url") or "").count("?") > 1
    ]


def _detect_non_https(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if (r.get("url") or "").startswith("http://")
    ]


# 8. COMPLIANCE (2) — Bajaj / IRDAI specific

_IRDAI_REGULATORY_PATTERNS = re.compile(
    r"/(financialinformation|public-disclosure|policy-document|"
    r"distribution.?channels|active.?agent|terminated.?agent|"
    r"insurance.?marketing.?firms)/?",
    re.IGNORECASE,
)


def _detect_broken_regulatory_pdf(rows: list[dict]) -> list[dict]:
    """IRDAI-mandated PDFs that should be reachable but 404. Single biggest
    legal-risk issue we've seen in the data (5 such 404s on /content/dam/
    balic-web/pdf/financialinformation/Distribution Channels List/)."""
    return [
        r for r in rows
        if (r.get("status_code") or "").strip() == "404"
        and _IRDAI_REGULATORY_PATTERNS.search(r.get("url") or "")
    ]


def _detect_branch_inaccessible(rows: list[dict]) -> list[dict]:
    """All branch.* pages returning 403 — Cloudflare/WAF blocking the
    crawler (and likely Googlebot). Local-SEO blind spot."""
    return [
        r for r in rows
        if (r.get("subdomain") or "") == "branch"
        and (r.get("status_code") or "").strip() == "403"
    ]


# ── the catalogue ────────────────────────────────────────────────────────
ALL_ISSUES: tuple[IssueDef, ...] = (
    # ── CRAWLABILITY ──
    IssueDef(
        slug="server_5xx",
        title="Server errors (5xx)",
        severity="error",
        category="crawlability",
        why=(
            "5xx responses mean the server is broken on these URLs. Google "
            "demotes pages that consistently 5xx and may de-index them."
        ),
        how_to_fix=(
            "Check application logs for the affected URLs. Fix the underlying "
            "bug (usually a missing template, a PHP fatal, or a stale "
            "dependency) and re-deploy. Add to monitoring."
        ),
        detector=_detect_5xx,
    ),
    IssueDef(
        slug="not_found_404",
        title="404 Not Found",
        severity="error",
        category="crawlability",
        why=(
            "404s waste crawl budget and break user journeys. When linked "
            "internally, they also dilute internal-PageRank."
        ),
        how_to_fix=(
            "Audit where the broken URL is linked from (see Discovered Edges "
            "table). Either restore the resource or 301-redirect to the "
            "closest live page. Remove the broken internal links."
        ),
        detector=_detect_404,
    ),
    IssueDef(
        slug="forbidden_403",
        title="Forbidden (403)",
        severity="error",
        category="crawlability",
        why=(
            "403s on internal URLs usually mean a CDN/WAF rule is blocking "
            "our crawler (and likely Googlebot too). The pages exist but are "
            "invisible to search engines."
        ),
        how_to_fix=(
            "Test the URL with the Googlebot User-Agent. If the 403 "
            "reproduces, allow-list the Googlebot IP ranges in the WAF. If "
            "only our crawler is blocked, update its UA header."
        ),
        detector=_detect_403,
    ),
    IssueDef(
        slug="network_failure",
        title="Network failures (DNS / connection)",
        severity="error",
        category="crawlability",
        why=(
            "URLs that never returned an HTTP status — DNS failure, "
            "connection reset, TLS handshake failure. Google can't index "
            "what it can't reach."
        ),
        how_to_fix=(
            "Verify the domain resolves. Check TLS cert validity. If the "
            "host is intermittently up, raise with infra to investigate "
            "stability."
        ),
        detector=_detect_network_failure,
    ),

    # ── INDEXABILITY ──
    IssueDef(
        slug="unknown_index_status",
        title="Index status unknown",
        severity="warning",
        category="indexability",
        why=(
            "We crawled the page but haven't checked Google's index for it. "
            "Without index status, we can't tell whether SEO efforts are "
            "translating to actual SERP presence."
        ),
        how_to_fix=(
            "Run the GSC URL Inspection backfill on these URLs. The Search "
            "Console API allows 2,000 inspections/day. Prioritize www pages."
        ),
        detector=_detect_unknown_index,
    ),
    IssueDef(
        slug="excluded_from_index",
        title="Excluded from Google's index",
        severity="warning",
        category="indexability",
        why=(
            "Google saw the URL but chose not to index it — usually because "
            "of duplicate content, low quality, or canonicalisation."
        ),
        how_to_fix=(
            "Inspect the URL in Search Console. If duplicate, set canonical. "
            "If low quality, enrich content or noindex it. If canonicalised "
            "away intentionally, no action."
        ),
        detector=_detect_excluded_from_index,
    ),
    IssueDef(
        slug="ok_not_in_sitemap",
        title="OK pages missing from sitemap",
        severity="warning",
        category="indexability",
        why=(
            "Pages absent from sitemap.xml are discovered later by Google, "
            "if at all. Inclusion accelerates indexing."
        ),
        how_to_fix=(
            "Add the URL to the appropriate sitemap. For AEM-published "
            "pages, ensure the publish hook fires the sitemap rebuild."
        ),
        detector=_detect_ok_not_in_sitemap,
    ),

    # ── CONTENT ──
    IssueDef(
        slug="missing_title",
        title="Missing <title> tag",
        severity="error",
        category="content",
        why=(
            "Title is the single strongest on-page ranking signal and the "
            "SERP click target. A missing title means Google synthesises "
            "one from page content — often unflattering."
        ),
        how_to_fix=(
            "Add a unique <title> tag in the page <head>, 30-60 characters, "
            "including the primary keyword and the brand."
        ),
        detector=_detect_missing_title,
    ),
    IssueDef(
        slug="duplicate_title",
        title="Duplicate page titles",
        severity="error",
        category="content",
        why=(
            "Pages sharing identical titles cannibalise each other in "
            "search results. Google picks one as canonical and drops the "
            "rest from the SERP."
        ),
        how_to_fix=(
            "Make every title unique. For templated pages (branch locator, "
            "product variants), inject location/product into the template "
            "so each rendered page has a distinct title."
        ),
        detector=_detect_duplicate_title,
    ),
    IssueDef(
        slug="empty_body",
        title="Pages with zero body content",
        severity="error",
        category="content",
        why=(
            "200-status pages with no extractable text are either broken "
            "templates, JS-rendered shells, or non-HTML responses misrouted. "
            "They cannot rank for anything."
        ),
        how_to_fix=(
            "Inspect a sample URL in the browser. If JS-rendered, ensure "
            "server-side rendering or static prerendering. If broken "
            "template, fix the template. If non-HTML, set noindex."
        ),
        detector=_detect_empty_body,
    ),
    IssueDef(
        slug="thin_content",
        title="Thin content (under 300 words)",
        severity="warning",
        category="content",
        why=(
            "Pages with fewer than 300 words rarely rank for competitive "
            "queries. Especially weak in finance/insurance where E-E-A-T "
            "demands depth."
        ),
        how_to_fix=(
            "Expand the content to 600+ words: add a definition paragraph, "
            "an FAQ, comparison tables, an example, and authoritative "
            "citations (IRDAI, RBI)."
        ),
        detector=_detect_thin_content,
    ),
    IssueDef(
        slug="heavy_content",
        title="Heavy content (over 8000 words)",
        severity="notice",
        category="content",
        why=(
            "Very long pages can dilute focus and slow page load. May "
            "indicate the page should be split into a pillar + sub-articles."
        ),
        how_to_fix=(
            "Review the page. If it covers multiple sub-topics, split into "
            "linked sub-pages with the original as a pillar/index."
        ),
        detector=_detect_heavy_content,
    ),

    # ── TITLES ──
    IssueDef(
        slug="title_too_long",
        title="Title over 70 characters",
        severity="warning",
        category="titles",
        why=(
            "Titles longer than ~60 characters get truncated in Google's "
            "SERP with an ellipsis. The truncated part is wasted real estate."
        ),
        how_to_fix=(
            "Trim to 50-60 characters. Lead with the primary keyword. Move "
            "the brand to the end."
        ),
        detector=_detect_title_too_long,
    ),
    IssueDef(
        slug="title_too_short",
        title="Title under 30 characters",
        severity="notice",
        category="titles",
        why=(
            "Very short titles miss an opportunity to communicate value "
            "and include long-tail keywords."
        ),
        how_to_fix=(
            "Expand to 40-60 characters. Add the primary keyword plus a "
            "qualifying benefit or differentiator."
        ),
        detector=_detect_title_too_short,
    ),
    IssueDef(
        slug="marketing_filler_in_title",
        title="Marketing filler in title",
        severity="notice",
        category="titles",
        why=(
            "Words like 'buy', 'best', 'click here', 'free', '#1' read as "
            "promotional and tend to perform worse in CTR than descriptive "
            "titles."
        ),
        how_to_fix=(
            "Replace promotional words with descriptive ones. Communicate "
            "what the page is about, not how good it is."
        ),
        detector=_detect_marketing_filler_in_title,
    ),

    # ── PERFORMANCE ──
    IssueDef(
        slug="slow_response",
        title="Slow server response (over 3 s)",
        severity="warning",
        category="performance",
        why=(
            "Slow TTFB delays the first byte to the user, hurts Core Web "
            "Vitals (LCP), and Google's crawl rate scales inversely with "
            "response time."
        ),
        how_to_fix=(
            "Profile the page. Common causes: uncached database queries, "
            "blocking third-party fetches, CDN miss. Cache aggressively at "
            "the edge."
        ),
        detector=_detect_slow_response,
    ),
    IssueDef(
        slug="very_slow_response",
        title="Very slow response (over 10 s)",
        severity="error",
        category="performance",
        why=(
            "Responses beyond 10 seconds risk timing out for users and "
            "search engines. These pages effectively don't exist for SEO."
        ),
        how_to_fix=(
            "Treat as a P0 production incident. Profile the request path, "
            "fix the bottleneck, add a timeout + circuit breaker."
        ),
        detector=_detect_very_slow_response,
    ),
    IssueDef(
        slug="missing_response_time",
        title="Response time not recorded",
        severity="notice",
        category="performance",
        why=(
            "Without response timing, we can't include the URL in "
            "performance trend analysis."
        ),
        how_to_fix=(
            "Investigate why the crawler didn't record timing — usually a "
            "non-HTTP response or fetcher bug."
        ),
        detector=_detect_missing_response_time,
    ),

    # ── CWV ──
    IssueDef(
        slug="psi_missing",
        title="No PageSpeed Insights data",
        severity="warning",
        category="cwv",
        why=(
            "Without PSI/CrUX data, we can't see Core Web Vitals for the "
            "page. Google uses CWV as a ranking signal."
        ),
        how_to_fix=(
            "PSI is rate-limited to 25,000 calls/day free. Prioritise high-"
            "impression pages (use GSC × crawl join) for daily refresh."
        ),
        detector=_detect_psi_missing,
    ),
    IssueDef(
        slug="pagespeed_poor",
        title="PageSpeed score below 50",
        severity="error",
        category="cwv",
        why=(
            "PageSpeed under 50 is in the 'Poor' tier. Almost certainly "
            "missing on CWV thresholds and ranking signals."
        ),
        how_to_fix=(
            "Open the PSI report for the URL. Address top opportunities: "
            "render-blocking resources, oversized images, unused JS, "
            "third-party script weight."
        ),
        detector=_detect_pagespeed_poor,
    ),
    IssueDef(
        slug="lcp_poor",
        title="LCP over 2.5 s",
        severity="warning",
        category="cwv",
        why=(
            "Largest Contentful Paint above 2.5 seconds fails Google's "
            "Core Web Vitals threshold."
        ),
        how_to_fix=(
            "Identify the LCP element (PSI shows it). Optimize its load: "
            "preconnect, preload, smaller image format, server-render text."
        ),
        detector=_detect_lcp_poor,
    ),
    IssueDef(
        slug="cls_poor",
        title="CLS over 0.1",
        severity="warning",
        category="cwv",
        why=(
            "Cumulative Layout Shift above 0.1 means content jumps around "
            "during load — frustrating users and failing CWV."
        ),
        how_to_fix=(
            "Reserve space for images and ads with explicit width/height "
            "or aspect-ratio CSS. Avoid injecting content above existing "
            "content after page load."
        ),
        detector=_detect_cls_poor,
    ),
    IssueDef(
        slug="inp_poor",
        title="INP over 200 ms",
        severity="warning",
        category="cwv",
        why=(
            "Interaction to Next Paint above 200 ms means the page feels "
            "laggy when users interact."
        ),
        how_to_fix=(
            "Break up long JS tasks (use scheduler.yield, requestIdleCallback). "
            "Defer non-critical third-party scripts."
        ),
        detector=_detect_inp_poor,
    ),

    # ── URLs ──
    IssueDef(
        slug="long_url",
        title="URL over 200 characters",
        severity="notice",
        category="urls",
        why=(
            "Very long URLs are hard to share, copy, and remember; they "
            "also indicate parameter stuffing or poor information "
            "architecture."
        ),
        how_to_fix=(
            "Shorten the URL slug. Move parameter values into the path or "
            "the page body where possible."
        ),
        detector=_detect_long_url,
    ),
    IssueDef(
        slug="query_stuffing",
        title="URL has 4+ query parameters",
        severity="notice",
        category="urls",
        why=(
            "Excessive query strings often indicate tracking pollution or "
            "faceted-search explosion. These URLs are duplicate-content "
            "magnets."
        ),
        how_to_fix=(
            "Canonicalise the param-heavy URL to its clean form. Use "
            "rel=canonical or robots.txt disallow for purely-tracking "
            "variants."
        ),
        detector=_detect_query_stuffing,
    ),
    IssueDef(
        slug="non_https",
        title="URL served over HTTP",
        severity="error",
        category="urls",
        why=(
            "HTTP URLs receive a small ranking penalty and trigger 'Not "
            "Secure' badges in Chrome."
        ),
        how_to_fix=(
            "Force a 301 redirect from HTTP to HTTPS at the edge. Update "
            "any internal links to use HTTPS directly."
        ),
        detector=_detect_non_https,
    ),

    # ── COMPLIANCE ──
    IssueDef(
        slug="broken_regulatory_pdf",
        title="Broken IRDAI-mandated regulatory PDF",
        severity="error",
        category="compliance",
        why=(
            "IRDAI requires public disclosure of distribution channels, "
            "active/terminated agents, and insurance marketing firms. A "
            "404 on these is a compliance risk, not just SEO."
        ),
        how_to_fix=(
            "Notify Compliance immediately. Restore the file at the linked "
            "path, or 301-redirect to the current location. Audit every "
            "regulatory link quarterly."
        ),
        detector=_detect_broken_regulatory_pdf,
    ),
    IssueDef(
        slug="branch_inaccessible",
        title="Branch subdomain pages inaccessible (Cloudflare 403)",
        severity="error",
        category="compliance",
        why=(
            "All branch.* pages 403 the crawler — likely a WAF rule. If "
            "Googlebot is also blocked, the entire branch locator is "
            "invisible to local-SEO queries ('insurance near me')."
        ),
        how_to_fix=(
            "Test branch URLs with the Googlebot User-Agent. If 403, allow-"
            "list Googlebot IP ranges in Cloudflare WAF. If 200, update our "
            "crawler UA."
        ),
        detector=_detect_branch_inaccessible,
    ),
)


# Phase 4 expansion — appended after the original 28. Import is at
# the bottom of the file to avoid circular-import risk; the new module
# imports IssueDef + helper predicates from this one.
from . import detectors_phase4 as _phase4  # noqa: E402
# Phase 6 GEO suite additions — llms.txt + citation density.
from . import detectors_geo as _geo  # noqa: E402

ALL_ISSUES = ALL_ISSUES + _phase4.PHASE_4_ISSUES + _geo.GEO_ISSUES

ISSUES_BY_SLUG: dict[str, IssueDef] = {i.slug: i for i in ALL_ISSUES}
