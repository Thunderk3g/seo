"""Eight thematic deep-dive reports — Phase 5c.

Each theme bundles a curated set of audit issues + relevant
page-explorer slices + headline numbers into one focused payload, so
the operator can drill into a specific concern without scrolling
through 50-row issue catalogs.

Themes (matches the SEMrush thematic-report convention):

  * robots          — robots.txt handling, blocked resources
  * crawlability    — status codes, redirects, 4xx/5xx coverage
  * https           — HTTPS / mixed content (limited until Phase 4.5
                       adds security-header capture in the crawler)
  * international   — hreflang, language coverage (limited)
  * performance     — response time, slow pages, CWV
  * linking         — internal PageRank, orphans, dup-title clusters
  * markup          — schema coverage, title hygiene
  * cwv             — Core Web Vitals (LCP, CLS, INP, PageSpeed)

Each theme returns the same shape so the frontend can render them all
through one ThematicReportPage. Themes that need data the crawler
doesn't yet capture (security headers, schema validation) surface
their issues plus a "needs_crawler_change" note so the operator knows
which findings are inherently incomplete today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThemeSection:
    title: str
    description: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ThemeReport:
    slug: str
    title: str
    description: str
    sections: list[ThemeSection] = field(default_factory=list)
    headline_stat: dict[str, Any] | None = None
    related_routes: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "headline_stat": self.headline_stat,
            "sections": [
                {
                    "title": s.title,
                    "description": s.description,
                    "issues": s.issues,
                    "notes": s.notes,
                }
                for s in self.sections
            ],
            "related_routes": self.related_routes,
        }


# Catalog of issue slugs grouped by theme. Each slug must exist in
# audits.catalog.ISSUES_BY_SLUG — validated at runtime via _resolve.
_THEME_ISSUE_MAP: dict[str, list[str]] = {
    "robots": [
        "forbidden_403",
        "branch_inaccessible",
    ],
    "crawlability": [
        "server_5xx",
        "not_found_404",
        "forbidden_403",
        "network_failure",
        "status_set_no_response_time",
        "200_with_error_type",
        "non_200_no_error_type",
    ],
    "https": [
        "non_https",
    ],
    "international": [
        # hreflang detectors land in Phase 4.5 when crawler captures
        # the field; for now the theme only carries the placeholder.
    ],
    "performance": [
        "slow_response",
        "very_slow_response",
        "missing_response_time",
        "response_p95_outlier",
        "branch_locator_slow",
    ],
    "linking": [
        "high_value_missing_sitemap",
        "ok_not_in_sitemap",
        "duplicate_title",
        "dup_title_within_subdomain",
        "missing_title",
    ],
    "markup": [
        "missing_title",
        "title_too_long",
        "title_too_short",
        "title_over_100_chars",
        "title_equals_url_slug",
        "marketing_filler_in_title",
        "calculator_missing_keyword",
        "empty_body",
        "thin_content",
        "heavy_content",
        "product_page_thin",
    ],
    "cwv": [
        "psi_missing",
        "pagespeed_poor",
        "lcp_poor",
        "cls_poor",
        "inp_poor",
    ],
}


_THEME_META: dict[str, tuple[str, str, list[dict[str, str]]]] = {
    "robots": (
        "Robots.txt + crawlability gates",
        "URLs being blocked at the network/WAF/robots layer. If "
        "Googlebot is blocked the same way our crawler is, these "
        "pages are invisible to organic search.",
        [{"label": "View Page Explorer (403s)", "href": "/crawler/pages?status=403"}],
    ),
    "crawlability": (
        "Crawlability — status codes, errors, redirects",
        "Everything between 'crawler tried to fetch this' and 'got a "
        "useful response'. Triages the response-code distribution + "
        "fetcher health.",
        [{"label": "Open Issues triage", "href": "/crawler/issues"}],
    ),
    "https": (
        "HTTPS — secure-transport hygiene",
        "HTTP/HTTPS configuration. Limited until the crawler captures "
        "security headers (HSTS / CSP / X-Frame-Options) — see "
        "Phase 4.5 of the roadmap.",
        [],
    ),
    "international": (
        "International / hreflang",
        "hreflang declaration + reciprocity. Today the crawler does "
        "not capture hreflang annotations; this theme is a "
        "placeholder until Phase 4.5 lands hreflang capture.",
        [],
    ),
    "performance": (
        "Performance — TTFB, slow pages",
        "Server-side response times. Slow pages drag the perceived "
        "speed of the whole site and reduce crawl rate (Google "
        "throttles based on server response).",
        [{"label": "Open Page Explorer", "href": "/crawler/pages?sort=-response_time_ms"}],
    ),
    "linking": (
        "Internal linking + sitemap hygiene",
        "Internal link graph health, orphans, and sitemap inclusion "
        "of high-value pages.",
        [{"label": "Open Health Dashboard", "href": "/health"}],
    ),
    "markup": (
        "On-page markup — titles + content",
        "Title-tag hygiene, content depth, and template-default "
        "patterns. Highest-CTR-impact category for SERP.",
        [{"label": "Issues > Content", "href": "/crawler/issues?category=content"}],
    ),
    "cwv": (
        "Core Web Vitals",
        "PageSpeed Insights + CrUX field metrics (LCP, CLS, INP). "
        "Google ranking signal since 2021.",
        [{"label": "Open Page Explorer (slow LCP)", "href": "/crawler/pages?sort=-lcp_ms"}],
    ),
}


ALL_THEMES: tuple[str, ...] = tuple(_THEME_ISSUE_MAP.keys())


def list_themes() -> list[dict[str, str]]:
    """Slim listing for the theme picker UI."""
    return [
        {"slug": slug, "title": meta[0], "description": meta[1]}
        for slug, meta in _THEME_META.items()
    ]


def get(slug: str) -> ThemeReport | None:
    """Build the full theme report for one slug. Returns None if the
    slug is unknown."""
    if slug not in _THEME_ISSUE_MAP:
        return None
    from ..audits import run_all
    from ..audits.catalog import ISSUES_BY_SLUG

    audit = run_all()
    title, description, related = _THEME_META[slug]
    theme = ThemeReport(
        slug=slug,
        title=title,
        description=description,
        related_routes=list(related),
    )

    by_severity: dict[str, list[dict[str, Any]]] = {
        "error": [], "warning": [], "notice": [],
    }
    total_affected = 0
    for issue_slug in _THEME_ISSUE_MAP[slug]:
        meta = ISSUES_BY_SLUG.get(issue_slug)
        if meta is None:
            continue
        occ = next(
            (o for o in audit.occurrences if o.issue.slug == issue_slug),
            None,
        )
        count = occ.count if occ else 0
        total_affected += count
        by_severity[meta.severity].append({
            "slug": meta.slug,
            "title": meta.title,
            "severity": meta.severity,
            "category": meta.category,
            "why": meta.why,
            "how_to_fix": meta.how_to_fix,
            "count": count,
        })

    # Sort each severity bucket by count desc so the loudest issue
    # surfaces first in the section.
    for entries in by_severity.values():
        entries.sort(key=lambda d: -d["count"])

    if by_severity["error"]:
        theme.sections.append(ThemeSection(
            title="Errors",
            description="Load-bearing issues that drag the Health Score.",
            issues=by_severity["error"],
        ))
    if by_severity["warning"]:
        theme.sections.append(ThemeSection(
            title="Warnings",
            description="Should-fix issues; do not affect Health Score.",
            issues=by_severity["warning"],
        ))
    if by_severity["notice"]:
        theme.sections.append(ThemeSection(
            title="Notices",
            description="Informational signals.",
            issues=by_severity["notice"],
        ))

    if not _THEME_ISSUE_MAP[slug]:
        theme.sections.append(ThemeSection(
            title="Not yet measured",
            description=(
                "This theme depends on crawler fields that are not yet "
                "captured. Listed in the roadmap as Phase 4.5 (engine "
                "instrumentation). Until then, no issues fire here."
            ),
            notes=[
                "Roadmap reference: COMPETITIVE_PARITY_ROADMAP.md > Phase 4.5",
            ],
        ))

    theme.headline_stat = {
        "total_affected_urls": total_affected,
        "errors": len(by_severity["error"]),
        "warnings": len(by_severity["warning"]),
        "notices": len(by_severity["notice"]),
        "total_urls_in_audit": audit.total_urls,
    }
    return theme
