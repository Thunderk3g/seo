"""Deterministic SEO best-practice overlay.

Run against a :class:`page_analyzer.PageAnalysis` to emit a flat list of
``SEOIssue`` rows. The writer prompt is fed a compact summary so the
rewrite explicitly fixes these — and the UI renders them as a checklist
above the generated draft.

Why deterministic, not LLM
--------------------------
"Title between 50-60 characters" is not a judgement call. Pushing this
to the LLM wastes tokens and invites the model to hallucinate
"compliance". Keep the rules here, frozen, version-controlled, easy to
unit-test. The LLM gets the *outcome* ("title is 73 chars, target
50-60") and rewrites against it.

Severity scale
--------------
* ``critical`` — blocks ranking parity (no H1, no meta, multiple H1).
* ``warning``  — measurable signal loss (oversized title, low alt %).
* ``notice``   — polish (slightly long URL, missing breadcrumb schema).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class SEOIssue:
    code: str
    severity: str           # critical | warning | notice
    dimension: str          # title | meta | heading | image | schema | url | content
    message: str
    current_value: str = ""
    target: str = ""


# ── individual checks ───────────────────────────────────────────────


def _check_title(a) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    if not a.title:
        issues.append(SEOIssue(
            code="title.missing", severity="critical", dimension="title",
            message="Page is missing a <title> tag.",
            target="50-60 characters, primary keyword near the start",
        ))
        return issues
    if a.title_length < 30:
        issues.append(SEOIssue(
            code="title.too_short", severity="warning", dimension="title",
            message=f"Title is {a.title_length} characters — under the 30-char floor.",
            current_value=a.title, target="50-60 characters",
        ))
    elif a.title_length > 65:
        issues.append(SEOIssue(
            code="title.too_long", severity="warning", dimension="title",
            message=f"Title is {a.title_length} characters — risk of truncation in SERP.",
            current_value=a.title, target="50-60 characters",
        ))
    if "bajaj" not in a.title.lower():
        issues.append(SEOIssue(
            code="title.no_brand", severity="notice", dimension="title",
            message="Title doesn't mention 'Bajaj' — brand recall loss in SERP.",
            current_value=a.title, target="Include 'Bajaj Life Insurance' once",
        ))
    return issues


def _check_meta(a) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    if not a.meta_description:
        issues.append(SEOIssue(
            code="meta.missing", severity="critical", dimension="meta",
            message="Page is missing a meta description.",
            target="140-160 characters, includes primary keyword + CTA",
        ))
        return issues
    if a.meta_description_length < 110:
        issues.append(SEOIssue(
            code="meta.too_short", severity="warning", dimension="meta",
            message=f"Meta description is {a.meta_description_length} characters — under-utilized.",
            current_value=a.meta_description, target="140-160 characters",
        ))
    elif a.meta_description_length > 170:
        issues.append(SEOIssue(
            code="meta.too_long", severity="warning", dimension="meta",
            message=f"Meta description is {a.meta_description_length} characters — SERP will truncate.",
            current_value=a.meta_description, target="140-160 characters",
        ))
    return issues


def _check_headings(a) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    if a.h1_count == 0:
        issues.append(SEOIssue(
            code="heading.no_h1", severity="critical", dimension="heading",
            message="Page has no H1.",
            target="Exactly one H1 carrying the primary keyword",
        ))
    elif a.h1_count > 1:
        issues.append(SEOIssue(
            code="heading.multiple_h1", severity="warning", dimension="heading",
            message=f"Page has {a.h1_count} H1 tags — collapse to one.",
            target="Exactly one H1",
        ))
    if a.h2_count < 3:
        issues.append(SEOIssue(
            code="heading.thin_h2", severity="warning", dimension="heading",
            message=f"Only {a.h2_count} H2 sections — thin topical coverage.",
            target="At least 5 H2 sections covering distinct sub-topics",
        ))
    if a.h2_count >= 5 and a.h3_count == 0:
        issues.append(SEOIssue(
            code="heading.no_subsections", severity="notice", dimension="heading",
            message="No H3 sub-headings under your H2 sections.",
            target="At least 1 H3 per major H2 to break up scannable content",
        ))
    return issues


def _check_content_size(a) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    if a.word_count < 600:
        issues.append(SEOIssue(
            code="content.thin", severity="critical", dimension="content",
            message=f"Page has only {a.word_count} words — thin-content risk.",
            target="≥ 1,200 words for product / category pages; ≥ 1,800 for guides",
        ))
    elif a.word_count < 1200:
        issues.append(SEOIssue(
            code="content.moderate", severity="warning", dimension="content",
            message=f"Page has {a.word_count} words — below typical ranking depth.",
            target="≥ 1,500 words",
        ))
    return issues


def _check_links(a) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    if a.internal_link_count < 5:
        issues.append(SEOIssue(
            code="links.thin_internal", severity="warning", dimension="content",
            message=f"Only {a.internal_link_count} internal links — weak topic-cluster signal.",
            target="≥ 10 contextual internal links per long-form page",
        ))
    if a.internal_link_density_per_1k_words < 5 and a.word_count > 500:
        issues.append(SEOIssue(
            code="links.low_density", severity="notice", dimension="content",
            message=f"Internal-link density {a.internal_link_density_per_1k_words}/1k words.",
            target="5-15 internal links per 1,000 words",
        ))
    return issues


def _check_images(a) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    if a.image_count == 0:
        issues.append(SEOIssue(
            code="images.none", severity="warning", dimension="image",
            message="No images on the page.",
            target="≥ 3 supporting visuals (hero, infographic, CTA banner)",
        ))
    elif a.image_alt_coverage_pct < 80:
        issues.append(SEOIssue(
            code="images.alt_low", severity="warning", dimension="image",
            message=f"Only {a.image_alt_coverage_pct:.0f}% of images have alt text.",
            target="100% — every image needs descriptive alt text",
        ))
    return issues


def _check_schema(a) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    if not a.trusted_schema_present:
        issues.append(SEOIssue(
            code="schema.none", severity="critical", dimension="schema",
            message="No structured-data markup detected.",
            target="At minimum: WebPage, Organization, BreadcrumbList. "
                   "Product pages add Product + Offer; guide pages add Article + FAQPage.",
        ))
        return issues
    if not a.has_faq_schema and a.faq_question_count >= 3:
        issues.append(SEOIssue(
            code="schema.no_faq", severity="warning", dimension="schema",
            message=(
                f"Page has {a.faq_question_count} FAQ-style questions but no "
                "FAQPage schema — losing rich-result eligibility."
            ),
            target="Add FAQPage JSON-LD wrapping the existing Q&A",
        ))
    if not a.has_organization_schema:
        issues.append(SEOIssue(
            code="schema.no_organization", severity="notice", dimension="schema",
            message="No Organization schema — Bajaj brand panel quality suffers.",
            target="Add Organization JSON-LD with logo + sameAs links",
        ))
    if not a.has_breadcrumb_schema:
        issues.append(SEOIssue(
            code="schema.no_breadcrumb", severity="notice", dimension="schema",
            message="No BreadcrumbList schema — site-hierarchy SERP feature missed.",
            target="Add BreadcrumbList JSON-LD reflecting the URL path",
        ))
    return issues


def _check_url(a) -> list[SEOIssue]:
    issues: list[SEOIssue] = []
    try:
        path = urlparse(a.url).path
    except ValueError:
        return issues
    if len(path) > 100:
        issues.append(SEOIssue(
            code="url.too_long", severity="notice", dimension="url",
            message=f"URL path is {len(path)} characters — long URLs hurt CTR.",
            current_value=path, target="≤ 75 characters, keyword-focused",
        ))
    if re.search(r"[A-Z]", path):
        issues.append(SEOIssue(
            code="url.mixed_case", severity="warning", dimension="url",
            message="URL contains uppercase characters — non-canonical.",
            current_value=path, target="Lowercase, hyphen-separated",
        ))
    return issues


# ── public ──────────────────────────────────────────────────────────


def run_seo_overlay(analysis) -> dict[str, Any]:
    """Run every check against ``analysis`` and return the bundle.

    Returns a dict the writer prompt + UI consume directly:
      {
        "issues": [...],
        "counts": {"critical": n, "warning": n, "notice": n},
        "score": 0-100,
      }

    Score is 100 minus 12 per critical, 6 per warning, 2 per notice
    (capped at 0). A page with no flagged issues scores 100. This is a
    "best-practice cleanliness" score, NOT a ranking forecast.
    """
    issues: list[SEOIssue] = []
    issues.extend(_check_title(analysis))
    issues.extend(_check_meta(analysis))
    issues.extend(_check_headings(analysis))
    issues.extend(_check_content_size(analysis))
    issues.extend(_check_links(analysis))
    issues.extend(_check_images(analysis))
    issues.extend(_check_schema(analysis))
    issues.extend(_check_url(analysis))

    counts = {"critical": 0, "warning": 0, "notice": 0}
    for i in issues:
        counts[i.severity] = counts.get(i.severity, 0) + 1
    score = max(
        0,
        100 - 12 * counts["critical"] - 6 * counts["warning"] - 2 * counts["notice"],
    )
    return {
        "issues": [i.__dict__ for i in issues],
        "counts": counts,
        "score": score,
    }
