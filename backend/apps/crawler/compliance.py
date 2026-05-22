"""Compliance dashboard data builder.

Aggregates the subset of audit detectors that map to formal
compliance regimes — WCAG 2.1, GDPR/DPDPA, browser-security best
practices — into a single payload the frontend can render as a
manager-facing report.

The audit runner produces occurrences for every detector; this
module re-shapes the WCAG / privacy / security subset, attaches
the formal standard reference (e.g. WCAG SC 1.3.1) to each rule,
and surfaces per-URL evidence (which counter was non-zero on
which URL — the smoking gun for a remediation ticket).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


# ── Standard-rule references ──────────────────────────────────────


# Each detector slug → list of formal references (WCAG SC, GDPR
# article, RFC, etc.). Empty list means no formal mapping (still
# worth tracking but not a regulatory citation).
_RULE_REFS: dict[str, list[dict]] = {
    # WCAG 2.1 — Accessibility-lite (D.3)
    "a11y_missing_html_lang": [
        {"standard": "WCAG 2.1", "ref": "3.1.1", "level": "A",
         "name": "Language of Page"},
    ],
    "a11y_multiple_h1": [
        {"standard": "WCAG 2.1", "ref": "1.3.1", "level": "A",
         "name": "Info and Relationships"},
    ],
    "a11y_missing_h1": [
        {"standard": "WCAG 2.1", "ref": "2.4.6", "level": "AA",
         "name": "Headings and Labels"},
    ],
    "a11y_heading_skips": [
        {"standard": "WCAG 2.1", "ref": "1.3.1", "level": "A",
         "name": "Info and Relationships"},
    ],
    "a11y_form_input_no_label": [
        {"standard": "WCAG 2.1", "ref": "1.3.1", "level": "A",
         "name": "Info and Relationships"},
        {"standard": "WCAG 2.1", "ref": "4.1.2", "level": "A",
         "name": "Name, Role, Value"},
    ],
    "a11y_link_no_text": [
        {"standard": "WCAG 2.1", "ref": "2.4.4", "level": "A",
         "name": "Link Purpose (In Context)"},
    ],
    "a11y_link_generic_text": [
        {"standard": "WCAG 2.1", "ref": "2.4.4", "level": "A",
         "name": "Link Purpose (In Context)"},
        {"standard": "WCAG 2.1", "ref": "2.4.9", "level": "AAA",
         "name": "Link Purpose (Link Only)"},
    ],
    "a11y_invalid_aria_role": [
        {"standard": "WCAG 2.1", "ref": "4.1.2", "level": "A",
         "name": "Name, Role, Value"},
    ],
    # Phase E — AXE color contrast (computed, not heuristic).
    "color_contrast_failures": [
        {"standard": "WCAG 2.1", "ref": "1.4.3", "level": "AA",
         "name": "Contrast (Minimum)"},
    ],
    # Phase E — LanguageTool grammar / typos.
    "grammar_errors_high": [
        {"standard": "Bajaj editorial", "ref": "Brand voice",
         "name": "Grammar quality"},
    ],
    # Existing image-alt detector (Phase A.5) is also WCAG-mapped.
    "images_missing_alt": [
        {"standard": "WCAG 2.1", "ref": "1.1.1", "level": "A",
         "name": "Non-text Content"},
    ],
    # Privacy / cookies (D.1) — GDPR / DPDPA
    "cookie_insecure": [
        {"standard": "OWASP", "ref": "ASVS V3.4.1",
         "name": "Cookie Secure flag"},
    ],
    "cookie_no_samesite": [
        {"standard": "OWASP", "ref": "ASVS V3.4.3",
         "name": "Cookie SameSite"},
    ],
    "cookie_no_httponly_session": [
        {"standard": "OWASP", "ref": "ASVS V3.4.2",
         "name": "Cookie HttpOnly"},
    ],
    "cookie_tracker_no_consent": [
        {"standard": "GDPR", "ref": "Art. 7",
         "name": "Conditions for consent"},
        {"standard": "DPDPA 2023", "ref": "Sec. 6",
         "name": "Consent of Data Principal"},
    ],
    # Security headers (Phase A.1) — already in compliance category
    "missing_hsts": [
        {"standard": "OWASP", "ref": "Secure Headers",
         "name": "Strict-Transport-Security"},
    ],
    "missing_csp": [
        {"standard": "OWASP", "ref": "Secure Headers",
         "name": "Content-Security-Policy"},
    ],
    "missing_x_frame_options": [
        {"standard": "OWASP", "ref": "Secure Headers",
         "name": "Clickjacking protection"},
    ],
    "missing_x_content_type_options": [
        {"standard": "OWASP", "ref": "Secure Headers",
         "name": "MIME-sniffing protection"},
    ],
    "missing_referrer_policy": [
        {"standard": "OWASP", "ref": "Secure Headers",
         "name": "Referrer-Policy"},
    ],
    "mixed_content": [
        {"standard": "OWASP", "ref": "ASVS V9.1.1",
         "name": "Mixed Content"},
    ],
    "insecure_form": [
        {"standard": "OWASP", "ref": "ASVS V9.1.1",
         "name": "Form action over HTTP"},
    ],
}


# Section taxonomy. Each section bundles the detector slugs that
# belong to one regulatory regime, in display order.
_SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("wcag", "WCAG 2.1 Accessibility", (
        "a11y_missing_html_lang",
        "a11y_missing_h1",
        "a11y_multiple_h1",
        "a11y_heading_skips",
        "a11y_form_input_no_label",
        "a11y_link_no_text",
        "a11y_link_generic_text",
        "a11y_invalid_aria_role",
        "images_missing_alt",
        # Phase E — AXE browser-computed color contrast.
        "color_contrast_failures",
    )),
    ("privacy", "Privacy & Cookies (GDPR / DPDPA)", (
        "cookie_insecure",
        "cookie_no_samesite",
        "cookie_no_httponly_session",
        "cookie_tracker_no_consent",
    )),
    ("security_headers", "Security Headers (OWASP)", (
        "missing_hsts",
        "missing_csp",
        "missing_x_frame_options",
        "missing_x_content_type_options",
        "missing_referrer_policy",
        "mixed_content",
        "insecure_form",
    )),
)


# Per-detector "evidence field" — the row column that holds the
# concrete count or value to show in the per-URL drill-down.
_EVIDENCE_FIELDS: dict[str, tuple[str, str]] = {
    "a11y_missing_html_lang": ("html_lang", "html lang attribute"),
    "a11y_multiple_h1": ("h1_count", "h1 tag count"),
    "a11y_missing_h1": ("h1_count", "h1 tag count"),
    "a11y_heading_skips": ("heading_skip_count", "heading-level skips"),
    "a11y_form_input_no_label": ("form_inputs_no_label", "unlabeled form inputs"),
    "a11y_link_no_text": ("links_no_text", "links with no text"),
    "a11y_link_generic_text": ("links_generic_text", "generic-text links"),
    "a11y_invalid_aria_role": ("invalid_aria_roles", "invalid ARIA roles"),
    "images_missing_alt": ("image_missing_alt", "images missing alt"),
    "color_contrast_failures": (
        "color_contrast_violations_count", "color-contrast WCAG failures",
    ),
    "grammar_errors_high": (
        "grammar_error_count", "grammar / typo findings",
    ),
    "cookie_insecure": ("cookies_insecure_count", "cookies without Secure flag"),
    "cookie_no_samesite": ("cookies_no_samesite_count", "cookies without SameSite"),
    "cookie_no_httponly_session": (
        "cookies_no_httponly_session_count", "session cookies without HttpOnly",
    ),
    "cookie_tracker_no_consent": (
        "cookies_tracker_count", "tracker cookies set",
    ),
    "missing_hsts": ("hsts", "HSTS header value"),
    "missing_csp": ("csp", "CSP header value"),
    "missing_x_frame_options": ("x_frame_options", "X-Frame-Options header"),
    "missing_x_content_type_options": (
        "x_content_type_options", "X-Content-Type-Options header",
    ),
    "missing_referrer_policy": ("referrer_policy", "Referrer-Policy header"),
    "mixed_content": ("has_mixed_content", "mixed-content present"),
    "insecure_form": ("has_insecure_form", "insecure form present"),
}


def _evidence_for(rule_slug: str, row: dict) -> str:
    field, label = _EVIDENCE_FIELDS.get(rule_slug, ("", ""))
    if not field:
        return ""
    raw = row.get(field)
    if raw is None or raw == "":
        return f"({label}: empty)"
    if isinstance(raw, list):
        if not raw:
            return ""
        return f"{label}: {', '.join(str(x) for x in raw[:5])}"
    return f"{label}: {raw}"


def build_compliance_payload(max_urls_per_rule: int = 50) -> dict:
    """Return the full compliance dashboard payload.

    Shape:
        {
            "started_at": ISO timestamp,
            "summary": {
                "total_violations": int,
                "unique_rules_failed": int,
                "pages_audited": int,
                "pages_with_any_violation": int,
                "by_severity": {"error": int, "warning": int, "notice": int},
                "by_section": {"wcag": int, "privacy": int, "security_headers": int},
            },
            "sections": [
                {
                    "key": "wcag",
                    "title": "WCAG 2.1 Accessibility",
                    "rules": [
                        {
                            "slug": "a11y_form_input_no_label",
                            "title": "...",
                            "severity": "error",
                            "why": "...",
                            "how_to_fix": "...",
                            "references": [{"standard": "WCAG 2.1", ...}, ...],
                            "count": int,
                            "affected_urls": [
                                {"url": ..., "evidence": ..., ...}
                            ],
                        }
                    ]
                }
            ]
        }
    """
    from .audits import run_all, ISSUES_BY_SLUG

    audit = run_all()
    occs_by_slug = {o.issue.slug: o for o in audit.occurrences}

    sections_out: list[dict] = []
    total_violations = 0
    unique_rules_failed = 0
    by_severity = {"error": 0, "warning": 0, "notice": 0}
    by_section: dict[str, int] = {}
    pages_with_any_violation: set[str] = set()

    for section_key, section_title, slugs in _SECTIONS:
        section_rules: list[dict] = []
        section_count = 0
        for slug in slugs:
            issue = ISSUES_BY_SLUG.get(slug)
            if issue is None:
                continue
            occ = occs_by_slug.get(slug)
            count = occ.count if occ else 0
            affected = []
            if occ:
                for r in occ.affected_urls[:max_urls_per_rule]:
                    url = (r.get("url") or "").strip()
                    if url:
                        pages_with_any_violation.add(url)
                    affected.append({
                        "url": url,
                        "title": (r.get("title") or "").strip(),
                        "subdomain": r.get("subdomain") or "",
                        "page_type": r.get("page_type") or "",
                        "evidence": _evidence_for(slug, r),
                    })
            rule_payload = {
                "slug": issue.slug,
                "title": issue.title,
                "severity": issue.severity,
                "category": issue.category,
                "why": issue.why,
                "how_to_fix": issue.how_to_fix,
                "references": _RULE_REFS.get(slug, []),
                "count": count,
                "affected_urls": affected,
            }
            section_rules.append(rule_payload)
            section_count += count
            if count > 0:
                unique_rules_failed += 1
                by_severity[issue.severity] = by_severity.get(issue.severity, 0) + count
                total_violations += count
        sections_out.append({
            "key": section_key,
            "title": section_title,
            "total_violations": section_count,
            "rules": section_rules,
        })
        by_section[section_key] = section_count

    return {
        "started_at": audit.started_at,
        "summary": {
            "total_violations": total_violations,
            "unique_rules_failed": unique_rules_failed,
            "pages_audited": len(audit.rows) if hasattr(audit, "rows") else 0,
            "pages_with_any_violation": len(pages_with_any_violation),
            "by_severity": by_severity,
            "by_section": by_section,
        },
        "sections": sections_out,
    }


def build_compliance_csv() -> str:
    """Flat CSV: one row per (rule, url). Suitable for emailing to the
    engineering team."""
    import csv
    import io

    payload = build_compliance_payload(max_urls_per_rule=10_000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "section", "rule_slug", "rule_title", "severity",
        "standard", "ref", "url", "page_type", "evidence",
    ])
    for section in payload["sections"]:
        for rule in section["rules"]:
            ref_str = "; ".join(
                f'{r["standard"]} {r["ref"]}' for r in rule["references"]
            )
            for url_row in rule["affected_urls"]:
                writer.writerow([
                    section["title"],
                    rule["slug"],
                    rule["title"],
                    rule["severity"],
                    ref_str,
                    "",
                    url_row["url"],
                    url_row["page_type"],
                    url_row["evidence"],
                ])
    return buf.getvalue()
