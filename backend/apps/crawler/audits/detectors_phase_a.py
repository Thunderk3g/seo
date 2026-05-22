"""Phase A — Screaming Frog parity detectors.

22 new detectors covering security headers, redirect chains,
canonical chains, title/meta pixel-widths, image audit. Each reads
a single field on the result row and decides if the URL is in
violation.

Detector contract matches ``catalog.IssueDef``: a pure function from
``list[row]`` → matched subset. Rows are dicts because the audit
runner reads from CSV (string-typed fields) — detectors coerce as
needed.

Fields read here are written by ``audits/sf_parity_helpers.py``
at crawl time, then flow through CSV → audit → detector.
"""
from __future__ import annotations

import re

from .catalog import (
    IssueDef,
    Severity,
    _is_ok,
    _to_int,
)


# ── shared helpers ───────────────────────────────────────────────


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return s in ("1", "true", "yes", "t", "y")


def _has_value(row: dict, key: str) -> bool:
    return bool((row.get(key) or "").strip())


# ─────────────────────────────────────────────────────────────────
# A.1 — Security headers (7 detectors)
# ─────────────────────────────────────────────────────────────────


def _detect_missing_hsts(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and (r.get("url") or "").startswith("https://")
        and not _has_value(r, "hsts")
    ]


def _detect_missing_csp(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and not _has_value(r, "csp")]


def _detect_missing_x_frame_options(rows: list[dict]) -> list[dict]:
    # Modern browsers prefer CSP frame-ancestors, but X-Frame-Options
    # remains widely checked. Fire only when CSP also lacks
    # frame-ancestors.
    out: list[dict] = []
    for r in rows:
        if not _is_ok(r):
            continue
        if _has_value(r, "x_frame_options"):
            continue
        csp = (r.get("csp") or "").lower()
        if "frame-ancestors" in csp:
            continue
        out.append(r)
    return out


def _detect_missing_x_content_type_options(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and (r.get("x_content_type_options") or "").lower() != "nosniff"
    ]


def _detect_missing_referrer_policy(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and not _has_value(r, "referrer_policy")]


def _detect_mixed_content(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_bool(r.get("has_mixed_content"))]


def _detect_insecure_form(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_bool(r.get("has_insecure_form"))]


# ─────────────────────────────────────────────────────────────────
# A.2 — Redirect chains (3 detectors)
# ─────────────────────────────────────────────────────────────────


def _detect_redirect_chain(rows: list[dict]) -> list[dict]:
    # Screaming Frog fires this on 3+ hop chains.
    return [r for r in rows if _to_int(r.get("redirect_hops")) >= 3]


def _detect_redirect_loop(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_bool(r.get("redirect_loop"))]


def _detect_long_redirect(rows: list[dict]) -> list[dict]:
    # Less strict than chain — fires on 2+ hops where the chain is
    # technically valid but wastes PageRank.
    return [
        r for r in rows
        if _to_int(r.get("redirect_hops")) == 2
        and not _to_bool(r.get("redirect_loop"))
    ]


# ─────────────────────────────────────────────────────────────────
# A.3 — Title + meta pixel widths (2 detectors)
# ─────────────────────────────────────────────────────────────────


# Google truncates desktop titles at ~580px. ~565 is a safe upper
# bound that mirrors SF's default.
_TITLE_PX_OVER = 580
# Meta descriptions truncate at ~920px desktop / ~680px mobile.
_META_PX_OVER = 920


def _detect_title_over_pixel_width(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_int(r.get("title_pixel_width")) > _TITLE_PX_OVER
    ]


def _detect_meta_over_pixel_width(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_int(r.get("meta_description_pixel_width")) > _META_PX_OVER
    ]


# ─────────────────────────────────────────────────────────────────
# A.4 — Canonical chain (5 detectors)
# ─────────────────────────────────────────────────────────────────


def _detect_multiple_canonicals(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_bool(r.get("multiple_canonicals"))]


def _detect_canonical_mismatch(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_bool(r.get("canonical_mismatch"))]


def _detect_missing_canonical(rows: list[dict]) -> list[dict]:
    """Indexable page without any canonical declared at all. Lower-
    severity than mismatch but a routine SEO miss."""
    return [
        r for r in rows
        if _is_ok(r)
        and not _has_value(r, "canonical_html")
        and not _has_value(r, "canonical_http")
        # Skip URLs Google already excluded for other reasons.
        and (r.get("indexed_status") or "") not in ("excluded", "not_indexed")
    ]


def _detect_canonical_chain(rows: list[dict]) -> list[dict]:
    # Once we wire the multi-hop walker the chain length gets stored.
    # Phase A.4.1 stores the immediate canonical; A.4.2 (later commit)
    # walks the chain. For now this fires when a row's canonical
    # points at a different URL whose canonical points elsewhere again
    # — populated post-pass.
    return [r for r in rows if _to_int(r.get("canonical_chain_length")) >= 2]


def _detect_canonical_to_noindex(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_ok(r) and _to_bool(r.get("canonical_to_noindex"))]


# ─────────────────────────────────────────────────────────────────
# A.5 — Image audit (5 detectors)
# ─────────────────────────────────────────────────────────────────


def _detect_images_missing_alt_attribute(rows: list[dict]) -> list[dict]:
    """At least one <img> on the page has no alt attribute at all
    (different from alt=""). Google treats absent alt as worse than
    empty alt because the latter signals 'decorative image'."""
    return [r for r in rows if _to_int(r.get("image_missing_alt")) > 0]


def _detect_images_empty_alt(rows: list[dict]) -> list[dict]:
    """Pages with content images using empty alt (alt=""). OK for
    purely decorative images but suspicious when every image is
    empty-alt — usually a CMS misconfiguration."""
    # Fire only when at least 3+ empties OR every image on the page
    # is empty-alt. Reduces false positives on hero-banner-only pages.
    return [
        r for r in rows
        if _to_int(r.get("image_empty_alt")) >= 3
        or (
            _to_int(r.get("image_empty_alt")) >= 1
            and _to_int(r.get("image_empty_alt")) == _to_int(r.get("image_count"))
        )
    ]


def _detect_oversized_images(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("image_oversized_count")) > 0]


def _detect_broken_images(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("image_broken_count")) > 0]


def _detect_images_high_count(rows: list[dict]) -> list[dict]:
    # Pages with > 30 images often signal infinite scroll, image
    # gallery without lazy-load, or template misuse.
    return [r for r in rows if _to_int(r.get("image_count")) > 30]


# ─────────────────────────────────────────────────────────────────
# Catalogue
# ─────────────────────────────────────────────────────────────────


PHASE_A_ISSUES: tuple[IssueDef, ...] = (
    # ── A.1 security headers ──
    IssueDef(
        slug="missing_hsts",
        title="Missing Strict-Transport-Security (HSTS) header",
        severity="warning",
        category="compliance",
        why=(
            "Without HSTS, a man-in-the-middle on an open Wi-Fi can "
            "downgrade users from HTTPS to HTTP and intercept the "
            "session. Google flags HSTS-less HTTPS sites as a "
            "best-practice gap in the Lighthouse Security audit."
        ),
        how_to_fix=(
            "Add `Strict-Transport-Security: max-age=31536000; "
            "includeSubDomains` at the edge (CDN / load balancer). "
            "Test with the SSL Labs scanner."
        ),
        detector=_detect_missing_hsts,
    ),
    IssueDef(
        slug="missing_csp",
        title="Missing Content-Security-Policy header",
        severity="notice",
        category="compliance",
        why=(
            "CSP defends against cross-site script injection by "
            "declaring which sources are allowed. Pages without CSP "
            "are an easier target for XSS attacks."
        ),
        how_to_fix=(
            "Add `Content-Security-Policy: default-src 'self'; ...` "
            "tuned to the page's actual asset hosts. Use Report-Only "
            "mode first to detect breakage."
        ),
        detector=_detect_missing_csp,
    ),
    IssueDef(
        slug="missing_x_frame_options",
        title="Missing X-Frame-Options (and no CSP frame-ancestors)",
        severity="warning",
        category="compliance",
        why=(
            "X-Frame-Options stops clickjacking. Modern browsers "
            "accept CSP frame-ancestors as an equivalent — we fire "
            "only when neither is present."
        ),
        how_to_fix=(
            "Add `X-Frame-Options: SAMEORIGIN` OR add "
            "`frame-ancestors 'self'` to the CSP header."
        ),
        detector=_detect_missing_x_frame_options,
    ),
    IssueDef(
        slug="missing_x_content_type_options",
        title="Missing X-Content-Type-Options: nosniff",
        severity="notice",
        category="compliance",
        why=(
            "Without nosniff, browsers may execute non-script "
            "responses as JavaScript when the MIME type is ambiguous. "
            "Low risk on a well-typed site but free to fix."
        ),
        how_to_fix=(
            "Add `X-Content-Type-Options: nosniff` to every HTML "
            "response at the edge."
        ),
        detector=_detect_missing_x_content_type_options,
    ),
    IssueDef(
        slug="missing_referrer_policy",
        title="Missing Referrer-Policy header",
        severity="notice",
        category="compliance",
        why=(
            "Without an explicit policy, browsers send the full URL "
            "(including query string) as Referer to third-party "
            "resources. Can leak PII; required for GDPR-class "
            "compliance reviews."
        ),
        how_to_fix=(
            "Add `Referrer-Policy: strict-origin-when-cross-origin` "
            "(or `same-origin` if no cross-domain analytics)."
        ),
        detector=_detect_missing_referrer_policy,
    ),
    IssueDef(
        slug="mixed_content",
        title="Mixed content — HTTPS page loads HTTP sub-resources",
        severity="error",
        category="compliance",
        why=(
            "Modern browsers block mixed active content (scripts, "
            "iframes) and show the user a 'Not secure' warning. Hurts "
            "the security badge in Chrome and breaks features."
        ),
        how_to_fix=(
            "Audit the affected URL with browser DevTools. Replace "
            "every `http://` reference with `https://` (or "
            "protocol-relative if the asset host supports both). Use "
            "Content-Security-Policy `upgrade-insecure-requests` as a "
            "catch-all."
        ),
        detector=_detect_mixed_content,
    ),
    IssueDef(
        slug="insecure_form",
        title="Form submits over insecure HTTP",
        severity="error",
        category="compliance",
        why=(
            "A form with `action=\"http://...\"` leaks credentials in "
            "plaintext on submit. Chrome warns users in red and "
            "browsers may eventually refuse the submission entirely."
        ),
        how_to_fix=(
            "Change the form's `action` to `https://`. Verify the "
            "target endpoint accepts HTTPS."
        ),
        detector=_detect_insecure_form,
    ),

    # ── A.2 redirect chains ──
    IssueDef(
        slug="redirect_chain",
        title="Redirect chain (3+ hops)",
        severity="warning",
        category="crawlability",
        why=(
            "Each redirect costs a round-trip + dilutes link equity. "
            "Google sometimes gives up on chains beyond 5 hops; even "
            "shorter chains slow page-load and waste crawl budget."
        ),
        how_to_fix=(
            "Shorten the chain to a single 301. Audit internal links "
            "pointing at the original URL and update them to the "
            "final destination directly."
        ),
        detector=_detect_redirect_chain,
    ),
    IssueDef(
        slug="redirect_loop",
        title="Redirect loop",
        severity="error",
        category="crawlability",
        why=(
            "Browsers and Googlebot give up after detecting a loop. "
            "Affected URLs are effectively de-indexed."
        ),
        how_to_fix=(
            "Trace the chain (see redirect_chain field). Break the "
            "loop by 301-redirecting the loop entry to the canonical "
            "final URL, then rebuilding the original redirect map."
        ),
        detector=_detect_redirect_loop,
    ),
    IssueDef(
        slug="long_redirect",
        title="Redirect (2 hops — minor)",
        severity="notice",
        category="crawlability",
        why=(
            "A 2-hop redirect (e.g. legacy URL → trailing-slash → "
            "canonical) wastes one round-trip per crawl. Common after "
            "migrations; not critical but worth cleaning."
        ),
        how_to_fix=(
            "Collapse to a single 301 hop. Update the original "
            "redirect rule to skip the intermediate URL."
        ),
        detector=_detect_long_redirect,
    ),

    # ── A.3 pixel widths ──
    IssueDef(
        slug="title_over_pixel_width",
        title="Title over 580 pixels (truncated in SERP)",
        severity="warning",
        category="titles",
        why=(
            "Google truncates desktop SERP titles around 580 pixels "
            "with an ellipsis. The truncated suffix is wasted real "
            "estate and reduces CTR."
        ),
        how_to_fix=(
            "Trim the title to fit ~560 pixels (Arial 20 px). Lead "
            "with the primary keyword. Move the brand to the end."
        ),
        detector=_detect_title_over_pixel_width,
    ),
    IssueDef(
        slug="meta_over_pixel_width",
        title="Meta description over 920 pixels (truncated in SERP)",
        severity="notice",
        category="titles",
        why=(
            "Google truncates meta descriptions at ~920 pixels on "
            "desktop. The cut-off part doesn't render in the snippet."
        ),
        how_to_fix=(
            "Trim to 150-155 characters or ~880 pixels. Front-load "
            "the value proposition and CTA."
        ),
        detector=_detect_meta_over_pixel_width,
    ),

    # ── A.4 canonicals ──
    IssueDef(
        slug="multiple_canonicals",
        title="Multiple rel=canonical declarations",
        severity="error",
        category="indexability",
        why=(
            "When a page declares two different canonical URLs Google "
            "picks unpredictably or ignores both. Often a CMS bug "
            "where two templates inject the tag."
        ),
        how_to_fix=(
            "Audit the page's <head>. Remove duplicate "
            "<link rel='canonical'> tags so only one remains."
        ),
        detector=_detect_multiple_canonicals,
    ),
    IssueDef(
        slug="canonical_mismatch",
        title="Canonical mismatch (HTML vs HTTP header)",
        severity="error",
        category="indexability",
        why=(
            "When the HTML <link rel=canonical> differs from the HTTP "
            "`Link: rel=canonical` header, Google uses the HTTP "
            "header. Usually the HTML is the authoring intent and the "
            "HTTP version is the bug."
        ),
        how_to_fix=(
            "Pick one source of truth. Remove the HTTP header at the "
            "edge if the HTML one is correct, or vice versa."
        ),
        detector=_detect_canonical_mismatch,
    ),
    IssueDef(
        slug="missing_canonical",
        title="Indexable page without rel=canonical",
        severity="warning",
        category="indexability",
        why=(
            "Without an explicit canonical, Google guesses. For "
            "templated pages (product variants, paginated lists) the "
            "guess often goes wrong and causes duplicate-content "
            "dilution."
        ),
        how_to_fix=(
            "Add `<link rel='canonical' href='...'>` pointing at the "
            "current URL (self-canonical) for unique pages, or at the "
            "primary variant for duplicates."
        ),
        detector=_detect_missing_canonical,
    ),
    IssueDef(
        slug="canonical_chain",
        title="Canonical chain (canonical points to canonicalised page)",
        severity="warning",
        category="indexability",
        why=(
            "When page A canonicals to B, and B canonicals to C, "
            "Google may not follow the chain — A could be ignored. "
            "Use 301 redirects for chains, canonicals for variants."
        ),
        how_to_fix=(
            "Identify the final canonical destination and point every "
            "intermediate canonical directly at it. Or convert the "
            "chain to 301 redirects."
        ),
        detector=_detect_canonical_chain,
    ),
    IssueDef(
        slug="canonical_to_noindex",
        title="Canonical points to a noindex page",
        severity="error",
        category="indexability",
        why=(
            "If the canonical destination is noindex, Google may "
            "de-index BOTH pages. A common bug when a noindex "
            "tag is left on a 'preferred version'."
        ),
        how_to_fix=(
            "Remove the noindex from the canonical target if the "
            "page should rank, or change the canonical to a page "
            "that should rank."
        ),
        detector=_detect_canonical_to_noindex,
    ),

    # ── A.5 image audit ──
    IssueDef(
        slug="images_missing_alt",
        title="Images missing alt attribute",
        severity="warning",
        category="content",
        why=(
            "Pages with <img> tags that have no alt attribute at all "
            "fail accessibility checks and lose image-search ranking. "
            "Different from alt='' which signals decorative."
        ),
        how_to_fix=(
            "Add an `alt` attribute to every <img>. Use descriptive "
            "text for content images; use `alt=''` for purely "
            "decorative ones."
        ),
        detector=_detect_images_missing_alt_attribute,
    ),
    IssueDef(
        slug="images_empty_alt",
        title="Multiple images with empty alt (alt='')",
        severity="notice",
        category="content",
        why=(
            "Many empty-alt images on one page usually indicate the "
            "CMS isn't populating alt text. Decorative images are "
            "fine — but several content images with no alt loses "
            "image-search traffic."
        ),
        how_to_fix=(
            "Inspect the affected page. For content images, write "
            "descriptive alt text. Keep `alt=''` only for purely "
            "decorative or background-style images."
        ),
        detector=_detect_images_empty_alt,
    ),
    IssueDef(
        slug="images_oversized",
        title="Images over 100 KB",
        severity="warning",
        category="performance",
        why=(
            "Large images blow up LCP and waste mobile data. Each "
            "100 KB image adds ~0.3s on a slow-4G connection."
        ),
        how_to_fix=(
            "Compress with mozjpeg / squoosh. Serve next-gen formats "
            "(WebP / AVIF) via `<picture>` with fallbacks. Use "
            "responsive `srcset` so mobile users get smaller files."
        ),
        detector=_detect_oversized_images,
    ),
    IssueDef(
        slug="images_broken",
        title="Broken images (4xx / 5xx on image URL)",
        severity="warning",
        category="content",
        why=(
            "Broken image references show as 'image unavailable' to "
            "users + Google sees a 404 in the asset crawl. Hurts both "
            "UX and image-search."
        ),
        how_to_fix=(
            "Find the broken `<img src>` references (see "
            "image_audit_extra). Fix or remove them; if the CMS "
            "moved an asset, update the reference."
        ),
        detector=_detect_broken_images,
    ),
    IssueDef(
        slug="images_high_count",
        title="More than 30 images on the page",
        severity="notice",
        category="performance",
        why=(
            "Pages with 30+ images usually load slowly and bloat the "
            "DOM. Often indicates missing lazy-load or an over-built "
            "gallery."
        ),
        how_to_fix=(
            "Add `loading='lazy'` to below-the-fold images. Convert "
            "decorative imagery to CSS where possible. Split long "
            "galleries into paginated views."
        ),
        detector=_detect_images_high_count,
    ),
)
