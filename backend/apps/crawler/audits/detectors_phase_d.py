"""Phase D — SF parity detectors for cookies, AMP, accessibility.

16 detectors total:

  Cookies (4)
    * cookie_insecure              — Secure flag missing on HTTPS site
    * cookie_no_samesite           — no SameSite attribute (CSRF risk)
    * cookie_no_httponly_session   — session cookie readable from JS
    * cookie_tracker_no_consent    — known tracker cookie set with no
                                     consent banner detected

  AMP (4)
    * amp_invalid                  — AMP page missing required tags
    * amp_canonical_mismatch       — AMP canonical doesn't match the
                                     non-AMP page's URL family
    * amp_alternate_404            — rel=amphtml target returns 4xx
    * amp_alternate_to_noindex     — AMP alternate is noindexed

  Accessibility (8)
    * a11y_missing_html_lang
    * a11y_multiple_h1
    * a11y_missing_h1
    * a11y_heading_skips
    * a11y_form_input_no_label
    * a11y_link_no_text
    * a11y_link_generic_text
    * a11y_invalid_aria_role
"""
from __future__ import annotations

from .catalog import IssueDef, Severity, _is_ok, _to_int


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "yes", "t", "y")


def _row_list(v):
    if isinstance(v, list):
        return v
    if not v:
        return []
    try:
        import json as _json
        parsed = _json.loads(str(v))
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


# ── D.1 cookies ────────────────────────────────────────────────────


def _detect_cookie_insecure(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("cookies_insecure_count")) > 0]


def _detect_cookie_no_samesite(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("cookies_no_samesite_count")) > 0]


def _detect_cookie_no_httponly_session(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("cookies_no_httponly_session_count")) > 0]


def _detect_cookie_tracker_no_consent(rows: list[dict]) -> list[dict]:
    """Tracker cookies set on a page that doesn't expose a consent
    banner — GDPR / DPDPA red flag."""
    return [
        r for r in rows
        if _to_int(r.get("cookies_tracker_count")) > 0
        and not _to_bool(r.get("has_consent_banner"))
    ]


# ── D.2 AMP ────────────────────────────────────────────────────────


def _detect_amp_invalid(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_bool(r.get("amp_invalid"))]


def _detect_amp_canonical_mismatch(rows: list[dict]) -> list[dict]:
    """AMP page's canonical points at a URL we crawled with a
    different content-language or status — usually a misconfiguration
    where the AMP target's canonical was forgotten."""
    by_url = {(r.get("url") or "").rstrip("/"): r for r in rows}
    out = []
    for r in rows:
        if not _to_bool(r.get("is_amp_page")):
            continue
        target = (r.get("amp_canonical_target") or "").rstrip("/")
        if not target:
            out.append(r)
            continue
        canon_page = by_url.get(target)
        if canon_page is None:
            continue  # external — we can't validate
        if _to_int(canon_page.get("status_code")) >= 400:
            out.append(r)
    return out


def _detect_amp_alternate_404(rows: list[dict]) -> list[dict]:
    by_url = {(r.get("url") or "").rstrip("/"): r for r in rows}
    out = []
    for r in rows:
        amp_alt = (r.get("amp_alternate_url") or "").rstrip("/")
        if not amp_alt:
            continue
        target = by_url.get(amp_alt)
        if target and _to_int(target.get("status_code")) >= 400:
            out.append(r)
    return out


def _detect_amp_alternate_to_noindex(rows: list[dict]) -> list[dict]:
    by_url = {(r.get("url") or "").rstrip("/"): r for r in rows}
    out = []
    for r in rows:
        amp_alt = (r.get("amp_alternate_url") or "").rstrip("/")
        if not amp_alt:
            continue
        target = by_url.get(amp_alt)
        if not target:
            continue
        robots = str(target.get("meta_robots") or "").lower()
        if "noindex" in robots:
            out.append(r)
    return out


# ── D.3 accessibility ─────────────────────────────────────────────


def _detect_missing_html_lang(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and not (r.get("html_lang") or "").strip()
    ]


def _detect_multiple_h1(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_int(r.get("h1_count")) > 1]


def _detect_missing_h1(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_int(r.get("h1_count")) == 0]


def _detect_heading_skips(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_int(r.get("heading_skip_count")) > 0]


def _detect_form_input_no_label(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("form_inputs_no_label")) > 0]


def _detect_link_no_text(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("links_no_text")) > 0]


def _detect_link_generic_text(rows: list[dict]) -> list[dict]:
    # Fire only when more than 2 generic-text links — single occurrences
    # are noise on rich content pages.
    return [r for r in rows if _to_int(r.get("links_generic_text")) > 2]


def _detect_invalid_aria_role(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _row_list(r.get("invalid_aria_roles"))]


# ──────────────────────────────────────────────────────────────────
# Catalogue
# ──────────────────────────────────────────────────────────────────


PHASE_D_ISSUES: tuple[IssueDef, ...] = (
    # ── D.1 cookies ──
    IssueDef(
        slug="cookie_insecure",
        title="Cookie set without Secure flag on HTTPS page",
        severity="warning",
        category="compliance",
        why=(
            "Cookies without the Secure flag will be sent over plain "
            "HTTP if a user accidentally visits the site without "
            "TLS — enabling session hijacking on open Wi-Fi networks."
        ),
        how_to_fix=(
            "Set the `Secure` attribute on every cookie. In Django: "
            "`SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`."
        ),
        detector=_detect_cookie_insecure,
    ),
    IssueDef(
        slug="cookie_no_samesite",
        title="Cookie missing SameSite attribute",
        severity="notice",
        category="compliance",
        why=(
            "Without SameSite, browsers may send the cookie on "
            "cross-site requests — a CSRF vector. Chrome defaults to "
            "Lax but explicit declaration is the security best-practice."
        ),
        how_to_fix=(
            "Add `SameSite=Lax` (or Strict for high-value cookies). "
            "Cookies declared with `SameSite=None` MUST also set Secure."
        ),
        detector=_detect_cookie_no_samesite,
    ),
    IssueDef(
        slug="cookie_no_httponly_session",
        title="Session cookie readable from JavaScript",
        severity="warning",
        category="compliance",
        why=(
            "Session cookies without HttpOnly are reachable via "
            "document.cookie, giving any XSS vulnerability the ability "
            "to steal session tokens."
        ),
        how_to_fix=(
            "Set the `HttpOnly` attribute on every session-style cookie. "
            "Django: `SESSION_COOKIE_HTTPONLY = True` (default)."
        ),
        detector=_detect_cookie_no_httponly_session,
    ),
    IssueDef(
        slug="cookie_tracker_no_consent",
        title="Tracking cookie set with no consent banner detected",
        severity="error",
        category="compliance",
        why=(
            "GDPR (EU) and DPDPA (India) require explicit user consent "
            "BEFORE setting analytics / tracking cookies. Setting them "
            "on page-load without a visible consent banner is a "
            "compliance violation that can incur fines."
        ),
        how_to_fix=(
            "Either remove the tracker entirely, OR add a consent "
            "banner (OneTrust, CookieYes, Cookiebot, Didomi, etc.) "
            "that holds the tracker tag until consent is given."
        ),
        detector=_detect_cookie_tracker_no_consent,
    ),

    # ── D.2 AMP ──
    IssueDef(
        slug="amp_invalid",
        title="AMP page missing required tags",
        severity="error",
        category="indexability",
        why=(
            "AMP pages must include the AMP runtime script, html ⚡ "
            "attribute, viewport meta, utf-8 charset, canonical link, "
            "and AMP boilerplate style. Pages missing any of these "
            "are rejected from the Google AMP cache."
        ),
        how_to_fix=(
            "See `amp_required_missing` for the specific tags absent. "
            "Validate with https://validator.ampproject.org/."
        ),
        detector=_detect_amp_invalid,
    ),
    IssueDef(
        slug="amp_canonical_mismatch",
        title="AMP page canonical missing or broken",
        severity="error",
        category="indexability",
        why=(
            "Every AMP page must declare a canonical pointing at the "
            "non-AMP version. A missing or 4xx canonical breaks the "
            "AMP/non-AMP cluster and confuses Google's URL selection."
        ),
        how_to_fix=(
            "Add `<link rel=\"canonical\" href=\"<non-AMP URL>\">` "
            "to the AMP page's <head>."
        ),
        detector=_detect_amp_canonical_mismatch,
    ),
    IssueDef(
        slug="amp_alternate_404",
        title="AMP alternate URL returns 4xx/5xx",
        severity="error",
        category="indexability",
        why=(
            "rel=amphtml points at the AMP version of the page — if "
            "that URL is broken, Google drops the AMP from the cache "
            "and may downrank the non-AMP page's mobile signal."
        ),
        how_to_fix=(
            "Restore the AMP URL or remove the rel=amphtml link."
        ),
        detector=_detect_amp_alternate_404,
    ),
    IssueDef(
        slug="amp_alternate_to_noindex",
        title="AMP alternate is noindexed",
        severity="warning",
        category="indexability",
        why=(
            "Pointing rel=amphtml at a noindexed page tells Google "
            "to skip the AMP entirely. Likely a misconfiguration."
        ),
        how_to_fix=(
            "Remove the noindex from the AMP target or drop the "
            "rel=amphtml link."
        ),
        detector=_detect_amp_alternate_to_noindex,
    ),

    # ── D.3 accessibility ──
    IssueDef(
        slug="a11y_missing_html_lang",
        title="<html> tag missing lang attribute",
        severity="warning",
        category="compliance",
        why=(
            "Screen readers use the lang attribute to choose the "
            "correct voice / pronunciation. Missing lang fails WCAG "
            "2.1 SC 3.1.1 (Language of Page)."
        ),
        how_to_fix=(
            "Add `<html lang=\"en\">` (or the appropriate ISO code) to "
            "the document."
        ),
        detector=_detect_missing_html_lang,
    ),
    IssueDef(
        slug="a11y_multiple_h1",
        title="Multiple <h1> tags on a page",
        severity="notice",
        category="content",
        why=(
            "HTML5 permits multiple h1 inside <section>, but most "
            "screen readers still expect one primary h1 per page. "
            "Multiple h1 also dilutes the keyword-relevance signal."
        ),
        how_to_fix=(
            "Demote secondary headings to h2/h3."
        ),
        detector=_detect_multiple_h1,
    ),
    IssueDef(
        slug="a11y_missing_h1",
        title="Page has no <h1>",
        severity="warning",
        category="content",
        why=(
            "h1 is the page's primary title for assistive tech and "
            "search engines. Pages without one fail WCAG 2.1 SC 2.4.6 "
            "and lose a strong on-page ranking signal."
        ),
        how_to_fix=(
            "Add an h1 — typically the page's main title."
        ),
        detector=_detect_missing_h1,
    ),
    IssueDef(
        slug="a11y_heading_skips",
        title="Heading hierarchy skips levels (e.g. h1 → h3)",
        severity="notice",
        category="content",
        why=(
            "Skipped heading levels confuse screen-reader users who "
            "navigate by heading. Fails WCAG 1.3.1 (Info and "
            "Relationships)."
        ),
        how_to_fix=(
            "Restructure headings so they descend in order — h1 "
            "followed by h2, h2 followed by h2 or h3, etc."
        ),
        detector=_detect_heading_skips,
    ),
    IssueDef(
        slug="a11y_form_input_no_label",
        title="Form input without associated label",
        severity="error",
        category="compliance",
        why=(
            "Form inputs without a <label for=>, aria-label, or "
            "aria-labelledby are unusable with screen readers. Fails "
            "WCAG 2.1 SC 1.3.1 + SC 4.1.2."
        ),
        how_to_fix=(
            "Add a visible <label for=\"input-id\"> or aria-label "
            "to each form control."
        ),
        detector=_detect_form_input_no_label,
    ),
    IssueDef(
        slug="a11y_link_no_text",
        title="Link with no accessible text",
        severity="error",
        category="compliance",
        why=(
            "Links with no text and no aria-label are read as 'link' "
            "by screen readers, giving the user no idea what's at the "
            "destination. Fails WCAG 2.4.4."
        ),
        how_to_fix=(
            "Add visible text inside the anchor, or aria-label / "
            "title attribute on it. Icon-only links also need alt "
            "text on the wrapped image."
        ),
        detector=_detect_link_no_text,
    ),
    IssueDef(
        slug="a11y_link_generic_text",
        title="Multiple links with generic text (\"click here\", \"read more\")",
        severity="notice",
        category="content",
        why=(
            "Screen-reader users navigate by listing links out of "
            "context. \"Click here\" / \"Read more\" tell the user "
            "nothing. Multiple instances on one page is a strong "
            "anti-pattern."
        ),
        how_to_fix=(
            "Replace with descriptive link text — e.g. \"Read the "
            "Q4 earnings report\" instead of \"Read more\"."
        ),
        detector=_detect_link_generic_text,
    ),
    IssueDef(
        slug="a11y_invalid_aria_role",
        title="Element has an invalid ARIA role",
        severity="warning",
        category="compliance",
        why=(
            "Browsers ignore unknown ARIA roles, often leaving the "
            "element with no accessible role at all. A common cause "
            "is typos (`role=\"butotn\"`) or non-existent roles."
        ),
        how_to_fix=(
            "See `invalid_aria_roles` column for the list. Replace "
            "with a valid WAI-ARIA 1.2 role or remove the attribute."
        ),
        detector=_detect_invalid_aria_role,
    ),
)
