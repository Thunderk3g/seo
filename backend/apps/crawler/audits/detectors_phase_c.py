"""Phase C — SF parity detectors for JS render-delta, PDF metadata,
custom extractors, and spelling/readability.

15 detectors total:

  JS render-delta (4)
    * js_dependent_content   — > 50% words appear only after JS render
    * js_dependent_links     — > 50% links appear only after JS render
    * js_dependent_schema    — JSON-LD only present after JS render
    * soft_404_after_render  — page rendered but body < 100 words

  PDF (4)
    * pdf_missing_title      — PDF /Title metadata empty
    * pdf_scanned_no_text    — PDF has no text layer (scanned image)
    * pdf_encrypted          — encrypted PDF Google can't index
    * pdf_oversized          — PDF > 5 MB

  Custom extractors (1 detector + per-extractor view)
    * custom_extractor_empty — at least one user-defined selector
                               returned empty across the crawl

  Readability + spelling (6)
    * hard_to_read           — Flesch 30-50 (college-level)
    * very_hard_to_read      — Flesch < 30 (post-graduate)
    * grade_level_too_high   — Flesch-Kincaid grade > 14
    * spelling_errors_high   — > 10 unique spelling errors
    * page_too_thin_content  — < 100 readable words (was: poor_content
                               in older catalogue but explicit)
    * single_sentence_page   — page has only 1 sentence (likely a stub)
"""
from __future__ import annotations

from .catalog import IssueDef, Severity, _is_ok, _to_int


def _to_float(v) -> float:
    try:
        return float(v) if v not in ("", None) else 0.0
    except (TypeError, ValueError):
        return 0.0


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


def _row_dict(v):
    if isinstance(v, dict):
        return v
    if not v:
        return {}
    try:
        import json as _json
        parsed = _json.loads(str(v))
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _is_pdf(row: dict) -> bool:
    return "pdf" in (row.get("content_type") or "").lower()


# ── C.1 JS render-delta ────────────────────────────────────────────


def _detect_js_dependent_content(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _to_bool(r.get("js_rendered"))
        and _to_float(r.get("content_delta_ratio")) > 0.5
    ]


def _detect_js_dependent_links(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _to_bool(r.get("js_rendered"))
        and _to_float(r.get("link_delta_ratio")) > 0.5
    ]


def _detect_js_dependent_schema(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _to_bool(r.get("js_rendered"))
        and _to_float(r.get("jsonld_delta_ratio")) > 0.5
    ]


def _detect_soft_404_after_render(rows: list[dict]) -> list[dict]:
    """Page returned 200 + went through Playwright, but rendered body
    is still < 100 words. Common SPA-shell soft-404 pattern."""
    return [
        r for r in rows
        if _is_ok(r) and _to_bool(r.get("js_rendered"))
        and _to_int(r.get("word_count")) < 100
    ]


# ── C.2 PDF ────────────────────────────────────────────────────────


def _detect_pdf_missing_title(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_pdf(r) and not (r.get("pdf_title") or "").strip()
    ]


def _detect_pdf_scanned_no_text(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_pdf(r) and _to_int(r.get("pdf_page_count")) > 0
        and not _to_bool(r.get("pdf_has_text_layer"))
    ]


def _detect_pdf_encrypted(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _is_pdf(r) and _to_bool(r.get("pdf_is_encrypted"))]


def _detect_pdf_oversized(rows: list[dict]) -> list[dict]:
    # SF default warning threshold: 5 MB
    return [r for r in rows if _is_pdf(r) and _to_int(r.get("pdf_byte_size")) > 5_000_000]


# ── C.3 Custom extractors ──────────────────────────────────────────


def _detect_custom_extractor_empty(rows: list[dict]) -> list[dict]:
    """Page where any defined custom extractor returned ''. Useful
    for selector-drift detection: if 80% of pages used to populate
    `price` and now most are blank, the template changed."""
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        extracted = _row_dict(r.get("custom_extracted"))
        if not extracted:
            continue
        if any(v == "" for v in extracted.values()):
            out.append(r)
    return out


# ── C.4 Readability + spelling ─────────────────────────────────────


def _detect_hard_to_read(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        f = _to_float(r.get("flesch_score"))
        if 30 <= f < 50 and _to_int(r.get("readable_word_count")) >= 100:
            out.append(r)
    return out


def _detect_very_hard_to_read(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if not _is_ok(r):
            continue
        f = _to_float(r.get("flesch_score"))
        if 0 < f < 30 and _to_int(r.get("readable_word_count")) >= 100:
            out.append(r)
    return out


def _detect_grade_level_too_high(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_float(r.get("grade_level")) > 14
        and _to_int(r.get("readable_word_count")) >= 100
    ]


def _detect_spelling_errors_high(rows: list[dict]) -> list[dict]:
    return [r for r in rows if _to_int(r.get("spelling_error_count")) > 10]


def _detect_single_sentence_page(rows: list[dict]) -> list[dict]:
    return [
        r for r in rows
        if _is_ok(r) and _to_int(r.get("readable_sentence_count")) == 1
        and _to_int(r.get("readable_word_count")) >= 30
    ]


# ──────────────────────────────────────────────────────────────────
# Catalogue
# ──────────────────────────────────────────────────────────────────


PHASE_C_ISSUES: tuple[IssueDef, ...] = (
    # ── C.1 JS render-delta ──
    IssueDef(
        slug="js_dependent_content",
        title="> 50% of page content only appears after JS render",
        severity="warning",
        category="content",
        why=(
            "Googlebot does render JS, but with a delay (rendering "
            "queue) and a budget. Pages heavily dependent on client-"
            "side rendering risk being indexed with thin or missing "
            "content during the first pass."
        ),
        how_to_fix=(
            "Server-side render (SSR) or static-generate the page "
            "shell so the critical above-the-fold content lands in "
            "the initial HTML."
        ),
        detector=_detect_js_dependent_content,
    ),
    IssueDef(
        slug="js_dependent_links",
        title="> 50% of links only appear after JS render",
        severity="warning",
        category="crawlability",
        why=(
            "Internal links injected by JS are discovered by Google "
            "only after its render pass — delaying crawl of those "
            "URLs by hours-to-days. Direct authority flow is also "
            "diluted compared to native <a href> links."
        ),
        how_to_fix=(
            "Render navigation + content links server-side. Reserve "
            "JS-only links for non-critical UX."
        ),
        detector=_detect_js_dependent_links,
    ),
    IssueDef(
        slug="js_dependent_schema",
        title="JSON-LD only appears after JS render",
        severity="error",
        category="content",
        why=(
            "Google does execute JS for structured data but it's the "
            "slowest signal to be picked up. Rich-result eligibility "
            "may lag by weeks. Static JSON-LD is universally indexed."
        ),
        how_to_fix=(
            "Inject the <script type=\"application/ld+json\"> block "
            "into the SSR template head, not via client-side JS."
        ),
        detector=_detect_js_dependent_schema,
    ),
    IssueDef(
        slug="soft_404_after_render",
        title="Soft 404 — rendered page still has < 100 words",
        severity="error",
        category="indexability",
        why=(
            "The URL returns 200 OK and went through full JS "
            "rendering, but the resulting body is essentially empty. "
            "Google treats these as soft 404s and de-indexes them."
        ),
        how_to_fix=(
            "Either populate the page with real content or return "
            "a proper 404/410 status code."
        ),
        detector=_detect_soft_404_after_render,
    ),

    # ── C.2 PDF ──
    IssueDef(
        slug="pdf_missing_title",
        title="PDF missing /Title metadata",
        severity="warning",
        category="titles",
        why=(
            "Google uses the PDF /Title field as the SERP title. "
            "Without it, the URL or filename becomes the title — "
            "almost always less click-friendly."
        ),
        how_to_fix=(
            "Set the document Title via the PDF generator (Acrobat: "
            "File → Properties → Title; LaTeX: hyperref pdftitle; "
            "Word: File → Info → Title)."
        ),
        detector=_detect_pdf_missing_title,
    ),
    IssueDef(
        slug="pdf_scanned_no_text",
        title="PDF has no text layer (scanned image)",
        severity="error",
        category="content",
        why=(
            "Image-only scanned PDFs are uncrawlable. Google indexes "
            "them as files but cannot extract any content for "
            "ranking."
        ),
        how_to_fix=(
            "Run OCR (e.g. Acrobat Pro Recognize Text, Tesseract) to "
            "embed a text layer. Replace the original PDF."
        ),
        detector=_detect_pdf_scanned_no_text,
    ),
    IssueDef(
        slug="pdf_encrypted",
        title="PDF is encrypted (Google can't index)",
        severity="error",
        category="indexability",
        why=(
            "Encrypted PDFs cannot be parsed by Google. They appear "
            "in the index as URL + filename only, with no content "
            "ranking signals."
        ),
        how_to_fix=(
            "Remove the password / encryption from the PDF if it's "
            "public-facing. If the document genuinely needs to be "
            "protected, gate it behind login (and ensure it's not "
            "linked from public pages)."
        ),
        detector=_detect_pdf_encrypted,
    ),
    IssueDef(
        slug="pdf_oversized",
        title="PDF over 5 MB",
        severity="notice",
        category="performance",
        why=(
            "Large PDFs slow page-load when embedded inline and "
            "consume mobile-data quota when downloaded. Google may "
            "also skip oversized PDFs during initial discovery."
        ),
        how_to_fix=(
            "Compress the PDF (Acrobat Optimize PDF, Ghostscript "
            "-dPDFSETTINGS=/ebook). Split very long PDFs into "
            "topical chapters."
        ),
        detector=_detect_pdf_oversized,
    ),

    # ── C.3 custom extractors ──
    IssueDef(
        slug="custom_extractor_empty",
        title="Custom XPath/CSS extractor returned empty",
        severity="notice",
        category="content",
        why=(
            "A user-defined extractor matched no node. Either the "
            "selector is wrong, the template changed, or this page "
            "is a different template that doesn't have the field. "
            "Surface helps detect both bugs."
        ),
        how_to_fix=(
            "Review the extractor definition; if the selector is "
            "stale, fix it. If the page is a different template, "
            "narrow the extractor's URL scope."
        ),
        detector=_detect_custom_extractor_empty,
    ),

    # ── C.4 readability + spelling ──
    IssueDef(
        slug="hard_to_read",
        title="Hard to read (Flesch 30-50)",
        severity="notice",
        category="content",
        why=(
            "Flesch 30-50 is college-level reading. Acceptable for "
            "technical / financial content but reduces engagement on "
            "mainstream pages."
        ),
        how_to_fix=(
            "Shorten sentences. Replace polysyllabic words with "
            "simpler synonyms. Break long paragraphs."
        ),
        detector=_detect_hard_to_read,
    ),
    IssueDef(
        slug="very_hard_to_read",
        title="Very hard to read (Flesch < 30)",
        severity="warning",
        category="content",
        why=(
            "Flesch < 30 is post-graduate reading level. Bounce rate "
            "spikes on text this dense — most users won't finish."
        ),
        how_to_fix=(
            "Aggressive simplification. Target Flesch 60+ (plain "
            "English). Use the Hemingway editor or similar to "
            "identify hardest passages."
        ),
        detector=_detect_very_hard_to_read,
    ),
    IssueDef(
        slug="grade_level_too_high",
        title="Flesch-Kincaid grade level > 14",
        severity="notice",
        category="content",
        why=(
            "Grade 14 ≈ undergraduate junior year. Above this, "
            "comprehension drops sharply for general audiences."
        ),
        how_to_fix=(
            "Shorter sentences and shorter words. Aim for grade "
            "8-10 on consumer pages."
        ),
        detector=_detect_grade_level_too_high,
    ),
    IssueDef(
        slug="spelling_errors_high",
        title="More than 10 unique spelling errors",
        severity="warning",
        category="content",
        why=(
            "Spelling errors directly damage E-E-A-T (Expertise, "
            "Experience, Authoritativeness, Trustworthiness) — a "
            "Google quality signal. They also reduce CTR when they "
            "appear in titles or meta descriptions."
        ),
        how_to_fix=(
            "See `spelling_errors` column for the sample. Run the "
            "page through a spell checker; whitelist legitimate "
            "brand / product names."
        ),
        detector=_detect_spelling_errors_high,
    ),
    IssueDef(
        slug="single_sentence_page",
        title="Page contains only one sentence",
        severity="warning",
        category="content",
        why=(
            "A page with 30+ words but only one sentence is almost "
            "certainly a stub (legal one-liner, redirect notice, "
            "placeholder). These don't rank for anything."
        ),
        how_to_fix=(
            "Either flesh out the page with real content or remove "
            "it from the sitemap / set noindex."
        ),
        detector=_detect_single_sentence_page,
    ),
)
