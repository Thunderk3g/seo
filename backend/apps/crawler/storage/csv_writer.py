"""Streaming CSV + JSON persistence.

Rows are appended to their CSV files as soon as they are produced (O(1) per
row) instead of rewriting whole files at every checkpoint, so crawls of
100k+ pages do not degrade into O(n^2) disk churn. ``crawl_state.json``
is written periodically so a crawl can resume after a crash.

Every row is enriched at write-time with five trailing columns so reports
can filter by category, sitemap-source, and Google index status without
re-scanning the raw HTML:

    subdomain        — www / branch / investmentcorner / external
    page_type        — within www: product / knowledge / calculators / ...
    category_key     — flat key combining subdomain + page-type
    from_sitemap     — "1" if URL was harvested from sitemap.xml else "0"
    indexed_status   — indexed / not_indexed / excluded / unknown

If the CSV files on disk pre-date this schema, ``open_streams()`` auto-runs
the one-shot migration before any new rows are appended so the headers
match.
"""
from __future__ import annotations

import csv
import json
import threading
from pathlib import Path

from ..conf import settings
from ..logger import get_logger
from ..state import STATE
from . import gsc_loader, url_classifier

log = get_logger(__name__)

# Five enrichment columns appended to every stream's schema.
_ENRICH_FIELDS = [
    "subdomain", "page_type", "category_key",
    "from_sitemap", "indexed_status",
]

# Per-strategy CWV column suffixes — mobile_/desktop_ versions of these
# are stamped onto every PSI-enriched row. Keep in sync with
# ``apps.crawler.engine.psi_capture.PSI_STRATEGY_SUFFIXES``.
_PSI_SUFFIXES = (
    "pagespeed_score", "lcp_ms", "cls", "inp_ms",
    "fcp_ms", "ttfb_ms", "tbt_ms", "si_ms",
    "lcp_category", "cls_category", "inp_category",
    "has_field_data",
)
PSI_STRATEGIES = ("mobile", "desktop")
PSI_FIELDS = [
    f"{strat}_{sfx}" for strat in PSI_STRATEGIES for sfx in _PSI_SUFFIXES
]

# ── Phase A — Screaming Frog parity columns ──────────────────────
# Stamped onto every result row by the fetcher's call into
# `audits.sf_parity_helpers`. JSON-typed columns (redirect_chain,
# image_audit_extra) are stored as JSON strings in CSV; Postgres
# dual-write converts them via json.loads.
PHASE_A_FIELDS = [
    # Security headers (6 captured + 2 derived flags).
    "hsts", "csp", "x_frame_options", "x_content_type_options",
    "referrer_policy", "permissions_policy",
    "has_mixed_content", "has_insecure_form",
    # Redirect chain.
    "redirect_hops", "redirect_chain", "redirect_final_url", "redirect_loop",
    # Title + meta pixel widths (and meta description text).
    "meta_description", "title_pixel_width", "meta_description_pixel_width",
    # Canonical signals (HTML vs HTTP-header + flags).
    "canonical_html", "canonical_http", "canonical_mismatch",
    "multiple_canonicals", "canonical_chain_length", "canonical_to_noindex",
    # Image audit aggregates (per-image detail goes in extra JSONB).
    "image_count", "image_missing_alt", "image_empty_alt",
    "image_oversized_count", "image_broken_count", "image_audit_extra",
]

# ── Phase B — Hreflang + schema.org JSON-LD ──────────────────────
# JSON-typed columns (hreflang_entries, jsonld_blocks etc.) are stored
# as JSON strings in CSV; Postgres dual-write parses them back via
# _row_json. Booleans pass through _row_bool.
PHASE_B_FIELDS = [
    "hreflang_count", "hreflang_entries", "hreflang_has_x_default",
    "hreflang_invalid_codes", "hreflang_self_reference",
    "jsonld_count", "jsonld_types", "jsonld_blocks",
    "jsonld_invalid_count", "jsonld_missing_required",
    "jsonld_rich_result_eligible", "microdata_count", "rdfa_count",
]

# ── Phase C — render-delta, PDF, custom extractors, readability ──
PHASE_C_FIELDS = [
    # C.1 JS render-delta
    "js_rendered", "content_delta_ratio",
    "link_delta_ratio", "jsonld_delta_ratio",
    # C.2 PDF metadata
    "pdf_title", "pdf_author", "pdf_subject", "pdf_page_count",
    "pdf_language", "pdf_has_text_layer", "pdf_is_encrypted",
    "pdf_byte_size",
    # C.3 Custom extractors (JSON dict keyed by extractor name)
    "custom_extracted",
    # C.4 Readability + spelling
    "flesch_score", "grade_level", "readable_word_count",
    "readable_sentence_count", "spelling_error_count", "spelling_errors",
]

# ── Phase E — LanguageTool grammar + AXE color contrast ──────────
PHASE_E_FIELDS = [
    "grammar_error_count", "grammar_errors", "grammar_categories",
    "grammar_lang_detected", "grammar_tool_used",
    "color_contrast_violations_count", "color_contrast_violations",
    "axe_tool_used",
]


# ── Phase D — cookies + AMP + accessibility ──────────────────────
PHASE_D_FIELDS = [
    # D.1 cookies
    "cookie_count", "cookies", "cookies_insecure_count",
    "cookies_no_samesite_count", "cookies_no_httponly_session_count",
    "cookies_third_party_count", "cookies_tracker_count",
    "has_consent_banner",
    # D.2 AMP
    "is_amp_page", "has_amp_alternate", "amp_alternate_url",
    "amp_canonical_target", "amp_required_missing", "amp_invalid",
    # D.3 accessibility
    "html_lang", "h1_count", "heading_skip_count",
    "form_inputs_no_label", "links_no_text", "links_generic_text",
    "invalid_aria_roles", "has_skip_link",
]

RESULTS_FIELDS = [
    "url", "status_code", "status", "title", "word_count",
    "response_time_ms", "content_type", "error_type", "error_message",
    *_ENRICH_FIELDS,
    # PSI / Core Web Vitals — LEGACY headline columns (mobile-only).
    "pagespeed_score", "lcp_ms", "cls", "inp_ms",
    # Full dual-strategy CWV (Mobile + Desktop, lab + field metrics).
    *PSI_FIELDS,
    # Phase A — Screaming Frog parity columns.
    *PHASE_A_FIELDS,
    # Phase B — hreflang + schema.org JSON-LD.
    *PHASE_B_FIELDS,
    # Phase C — render-delta, PDF, extractors, readability.
    *PHASE_C_FIELDS,
    # Phase D — cookies + AMP + accessibility.
    *PHASE_D_FIELDS,
    # Phase E — LanguageTool grammar + AXE color contrast.
    *PHASE_E_FIELDS,
]
ERROR_FIELDS = ["timestamp", "url", "error_type", "error_message",
                *_ENRICH_FIELDS]
CONSOLE_FIELDS = ["timestamp", "url", "error", *_ENRICH_FIELDS]
DISCOVERED_FIELDS = ["url", "discovered_from", "depth", *_ENRICH_FIELDS]

# stream name -> (filename, fieldnames)
_STREAMS: dict[str, tuple[str, list[str]]] = {
    "results": ("crawl_results.csv", RESULTS_FIELDS),
    "errors": ("crawl_errors.csv", ERROR_FIELDS),
    "error_404": ("crawl_404_errors.csv", ERROR_FIELDS),
    "error_http": ("crawl_errors_httperror.csv", ERROR_FIELDS),
    # error_connection / error_chunked streams retired — no UI surface
    # was consuming them. Existing CSVs on disk are left alone.
    "console_logs": ("crawl_console_log.csv", CONSOLE_FIELDS),
    "discovered_edges": ("crawl_discovered.csv", DISCOVERED_FIELDS),
}

_lock = threading.Lock()
_handles: dict[str, tuple] = {}      # name -> (file_obj, csv.DictWriter)
_writes_since_flush = 0
_FLUSH_EVERY = 50


def _write_json(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)  # atomic swap so a crash mid-write can't corrupt it


def open_streams(resume: bool) -> None:
    """Open every CSV stream for appending.

    ``resume=True`` keeps any rows already on disk; otherwise the files are
    truncated and a fresh header written. If a file we want to resume has
    an older header (pre-enrichment), the migration is auto-run first so the
    new appends line up with the new schema.

    If a single file is locked at the OS level (Windows: someone has it
    open in Excel, an indexer is scanning it, etc.) we **skip that stream**
    rather than crashing the whole crawl. Rows that would have gone to that
    stream are silently dropped for this run — the in-memory STATE still
    accumulates them so they show up via the API; only the CSV-on-disk
    misses out until the lock is released and the crawl is re-run.
    """
    d = settings.data_path
    d.mkdir(parents=True, exist_ok=True)
    if resume:
        _ensure_migrated(d)
    skipped: list[str] = []
    with _lock:
        _close_locked()
        for name, (fname, fields) in _STREAMS.items():
            path = d / fname
            keep = resume and path.exists() and path.stat().st_size > 0
            mode = "a" if keep else "w"
            try:
                f = open(path, mode, newline="", encoding="utf-8")
            except PermissionError as exc:
                log.warning(
                    "csv_writer: %s is locked (%s) — skipping this stream "
                    "for the current run. Close whatever has the file open "
                    "(Excel, viewer, indexer) and re-run to capture it.",
                    fname, exc,
                )
                skipped.append(fname)
                continue
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if not keep:
                try:
                    w.writeheader()
                    f.flush()
                except OSError as exc:
                    log.warning(
                        "csv_writer: header write failed on %s: %s — "
                        "skipping stream.", fname, exc,
                    )
                    f.close()
                    skipped.append(fname)
                    continue
            _handles[name] = (f, w)
    if skipped:
        log.warning(
            "csv_writer: %s/%s streams skipped due to file locks: %s",
            len(skipped), len(_STREAMS), ", ".join(skipped),
        )


def _ensure_migrated(data_dir: Path) -> None:
    """Heal any CSV whose header no longer matches the current schema.

    Two paths:
      1. Legacy enrichment migration — triggers when a file is missing
         the historical ``category_key`` column. Delegates to the
         purpose-built ``migrate_reports.run()`` which knows how to
         re-classify rows for that specific schema bump.
      2. Generic column-add — for any other missing field in the
         current ``_STREAMS`` schema (e.g. the four PSI columns
         ``pagespeed_score`` / ``lcp_ms`` / ``cls`` / ``inp_ms`` added
         in 2026-05-20), we just append the missing columns with empty
         values. Idempotent: re-running is a no-op once the header
         matches. Atomic via temp+rename so a crash mid-rewrite can't
         corrupt the file.
    """
    # Phase 1 — legacy enrichment migration
    needs_legacy_migration = False
    for _name, (fname, _fields) in _STREAMS.items():
        p = data_dir / fname
        if not p.exists() or p.stat().st_size == 0:
            continue
        try:
            with open(p, "r", encoding="utf-8", newline="") as f:
                header = next(csv.reader(f), [])
            if "category_key" not in header:
                needs_legacy_migration = True
                break
        except Exception:  # noqa: BLE001
            continue
    if needs_legacy_migration:
        try:
            from . import migrate_reports
            migrate_reports.run(data_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("csv_writer: legacy migration failed: %s", exc)

    # Phase 2 — generic column add. Run AFTER legacy migration so we
    # operate on the post-legacy schema if both were needed.
    for name, (fname, fields) in _STREAMS.items():
        p = data_dir / fname
        if not p.exists() or p.stat().st_size == 0:
            continue
        try:
            _add_missing_columns_inplace(p, fields)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "csv_writer: column-add migration failed on %s: %s", fname, exc
            )


def _add_missing_columns_inplace(path: Path, expected_fields: list[str]) -> None:
    """Append any missing columns from ``expected_fields`` to a CSV's
    header (and pad each existing row with empty cells) so reads via
    csv.DictReader / DictWriter line up. No-op if every expected field
    is already present.

    Implementation: read-rewrite-rename. Streams row-by-row so a 100k
    row file doesn't materialise in memory.
    """
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            current_header = next(reader)
        except StopIteration:
            return
        missing = [c for c in expected_fields if c not in current_header]
        if not missing:
            return
        new_header = current_header + missing
        empty_pad = [""] * len(missing)
        tmp = path.with_suffix(path.suffix + ".colmig.tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(new_header)
            for row in reader:
                # Pad to length of new_header in case prior rows are
                # short (legacy data). Then add the empties for new cols.
                pad_to_current = max(0, len(current_header) - len(row))
                writer.writerow(row + [""] * pad_to_current + empty_pad)
    tmp.replace(path)
    log.info(
        "csv_writer: added %d missing column(s) %s to %s",
        len(missing), missing, path.name,
    )


def _enrich(row: dict) -> dict:
    """Stamp the five trailing columns onto a row in-place.

    Called from ``append()`` so the engine itself never has to know about
    categories. Idempotent — if a key is already set (e.g. the caller pre-
    populated it during migration), it is preserved.
    """
    url = row.get("url")
    if not url:
        return row
    if "category_key" not in row:
        c = url_classifier.classify(url)
        row.setdefault("subdomain", c["subdomain"])
        row.setdefault("page_type", c["page_type"])
        row.setdefault("category_key", c["category_key"])
    if "from_sitemap" not in row:
        # STATE.sitemap_urls is set during engine._seed(). Empty during
        # tests / standalone calls — defaults to "0".
        row["from_sitemap"] = "1" if url in STATE.sitemap_urls else "0"
    if "indexed_status" not in row:
        try:
            row["indexed_status"] = gsc_loader.status_for(url)
        except Exception:  # noqa: BLE001  (defensive — bad coverage CSV must never break a crawl)
            row["indexed_status"] = "unknown"
    return row


def append(stream: str, row: dict) -> None:
    """Append one row to a stream. Flushes periodically.

    Phase 3 — when ``stream == 'results'`` we ALSO dual-write to the
    Postgres CrawlerPageResult ORM table via ``_dual_write_pageresult``.
    Best-effort and idempotent: when Postgres is down, snapshot isn't
    started, or the dual-write flag is off, this no-ops silently and
    the CSV path keeps working untouched.
    """
    global _writes_since_flush
    _enrich(row)
    with _lock:
        h = _handles.get(stream)
        if h is None:
            return
        _, writer = h
        writer.writerow(row)
        _writes_since_flush += 1
        if _writes_since_flush >= _FLUSH_EVERY:
            for f, _ in _handles.values():
                f.flush()
            _writes_since_flush = 0
    if stream == "results":
        _dual_write_pageresult(row)


def _dual_write_pageresult(row: dict) -> None:
    """Best-effort write of a results row into CrawlerPageResult.

    Skipped when:
      * dual_write_postgres flag is False
      * no current CrawlSnapshot (Postgres unreachable at crawl start)
      * the URL+snapshot pair already exists (idempotent on retry)
      * any DB error fires — logged once at WARNING level

    Type-coercion mirrors the model field types: integers for status
    columns, FloatField for cls, BooleanField for from_sitemap, etc.
    """
    if not getattr(settings, "dual_write_postgres", True):
        return
    try:
        from ..services import snapshot as snapshot_svc
        snap_id = snapshot_svc.current_snapshot_id()
        if not snap_id:
            return
        from ..models import CrawlerPageResult
        url = (row.get("url") or "").strip()
        if not url:
            return

        def _i(v):
            try:
                return int(v) if v not in ("", None) else 0
            except (TypeError, ValueError):
                return 0

        def _opt_i(v):
            if v in ("", None):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        def _opt_f(v):
            if v in ("", None):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _row_bool(v) -> bool:
            """Coerce CSV string ('True'/'False'/'1') OR native bool
            from Scrapy/legacy engine into a Python bool."""
            if isinstance(v, bool):
                return v
            s = str(v or "").strip().lower()
            return s in ("1", "true", "yes", "t", "y")

        def _s(v, max_len: int | None = None) -> str:
            """Defensive string coercion + optional max-length slice.

            Replaces the brittle `(row.get(k) or "")[:N]` pattern that
            blows up with ``'int' object is not subscriptable`` whenever
            the engine path passes a native int (e.g. status_code=200,
            response_time_ms=125) instead of the CSV-serialised string.

            ``None``/``""`` → ``""``. Everything else stringifies via
            ``str()`` then slices.
            """
            if v is None:
                return ""
            s = v if isinstance(v, str) else str(v)
            if max_len is not None:
                return s[:max_len]
            return s

        def _row_json(v, *, default=None):
            """Phase A JSONField values may arrive as native Python
            (Scrapy spider) or as JSON-encoded strings (CSV path).
            Return the parsed structure; ``default`` (empty list or
            dict) on parse failure."""
            if default is None:
                default = []
            if v in (None, ""):
                return default
            if isinstance(v, (list, dict)):
                return v
            try:
                import json as _json
                return _json.loads(str(v))
            except (ValueError, TypeError):
                return default

        # Phase 3e: Scrapy spider passes Playwright metadata as
        # native types (bool / int / None), not CSV strings. Coerce
        # defensively for both shapes.
        playwright_used_raw = row.get("playwright_used")
        if isinstance(playwright_used_raw, bool):
            playwright_used = playwright_used_raw
        elif isinstance(playwright_used_raw, str):
            playwright_used = playwright_used_raw.lower() in ("1", "true", "yes")
        else:
            playwright_used = False

        # Build the dual-strategy CWV column dict — picks up
        # mobile_*/desktop_* values when the PSI scheduler ran both.
        cwv_cols: dict = {}
        for strat in ("mobile", "desktop"):
            cwv_cols[f"{strat}_pagespeed_score"] = _opt_i(row.get(f"{strat}_pagespeed_score"))
            cwv_cols[f"{strat}_lcp_ms"] = _opt_i(row.get(f"{strat}_lcp_ms"))
            cwv_cols[f"{strat}_cls"] = _opt_f(row.get(f"{strat}_cls"))
            cwv_cols[f"{strat}_inp_ms"] = _opt_i(row.get(f"{strat}_inp_ms"))
            cwv_cols[f"{strat}_fcp_ms"] = _opt_i(row.get(f"{strat}_fcp_ms"))
            cwv_cols[f"{strat}_ttfb_ms"] = _opt_i(row.get(f"{strat}_ttfb_ms"))
            cwv_cols[f"{strat}_tbt_ms"] = _opt_i(row.get(f"{strat}_tbt_ms"))
            cwv_cols[f"{strat}_si_ms"] = _opt_i(row.get(f"{strat}_si_ms"))
            cwv_cols[f"{strat}_lcp_category"] = (
                row.get(f"{strat}_lcp_category") or ""
            )[:24]
            cwv_cols[f"{strat}_cls_category"] = (
                row.get(f"{strat}_cls_category") or ""
            )[:24]
            cwv_cols[f"{strat}_inp_category"] = (
                row.get(f"{strat}_inp_category") or ""
            )[:24]
            cwv_cols[f"{strat}_has_field_data"] = (
                str(row.get(f"{strat}_has_field_data") or "0") == "1"
            )

        CrawlerPageResult.objects.update_or_create(
            snapshot_id=snap_id,
            url=url[:2048],
            defaults={
                # _s() coerces native types (int/bool/None) to safe strings
                # before slicing — prevents "'int' object is not
                # subscriptable" when engine passes raw ints in.
                "status_code": _s(row.get("status_code"), 4),
                "status": _s(row.get("status"), 64),
                "content_type": _s(row.get("content_type"), 128),
                "response_time_ms": _i(row.get("response_time_ms")),
                "title": _s(row.get("title"), 1024),
                "word_count": _i(row.get("word_count")),
                "error_type": _s(row.get("error_type"), 64),
                "error_message": _s(row.get("error_message"), 4000),
                "subdomain": _s(row.get("subdomain"), 64),
                "page_type": _s(row.get("page_type"), 64),
                "category_key": _s(row.get("category_key"), 128),
                "from_sitemap": _s(row.get("from_sitemap"), 1) in ("1", "True", "true"),
                "indexed_status": _s(row.get("indexed_status") or "unknown", 16),
                # Legacy headline columns (mobile aliases for back-compat).
                "pagespeed_score": _opt_i(row.get("pagespeed_score")),
                "lcp_ms": _opt_i(row.get("lcp_ms")),
                "cls": _opt_f(row.get("cls")),
                "inp_ms": _opt_i(row.get("inp_ms")),
                # Full dual-strategy CWV — 24 columns of mobile + desktop
                # lab + field metrics. Populated when PSI ran both
                # strategies for the URL.
                **cwv_cols,
                # Phase 3e Playwright fields
                "static_word_count": _opt_i(row.get("static_word_count")),
                "rendered_word_count": _opt_i(row.get("rendered_word_count")),
                "playwright_used": playwright_used,
                # ── Phase A — Screaming Frog parity ──────────────
                "hsts": _s(row.get("hsts"), 512),
                "csp": (row.get("csp") or ""),
                "x_frame_options": _s(row.get("x_frame_options"), 128),
                "x_content_type_options": _s(row.get("x_content_type_options"), 64),
                "referrer_policy": _s(row.get("referrer_policy"), 128),
                "permissions_policy": (row.get("permissions_policy") or ""),
                "has_mixed_content": _row_bool(row.get("has_mixed_content")),
                "has_insecure_form": _row_bool(row.get("has_insecure_form")),
                "redirect_hops": _i(row.get("redirect_hops")),
                "redirect_chain": _row_json(row.get("redirect_chain")),
                "redirect_final_url": _s(row.get("redirect_final_url"), 2048),
                "redirect_loop": _row_bool(row.get("redirect_loop")),
                "title_pixel_width": _i(row.get("title_pixel_width")),
                "meta_description_pixel_width": _i(row.get("meta_description_pixel_width")),
                "canonical_html": _s(row.get("canonical_html"), 2048),
                "canonical_http": _s(row.get("canonical_http"), 2048),
                "canonical_mismatch": _row_bool(row.get("canonical_mismatch")),
                "multiple_canonicals": _row_bool(row.get("multiple_canonicals")),
                "canonical_chain_length": _i(row.get("canonical_chain_length")),
                "canonical_to_noindex": _row_bool(row.get("canonical_to_noindex")),
                "image_count": _i(row.get("image_count")),
                "image_missing_alt": _i(row.get("image_missing_alt")),
                "image_empty_alt": _i(row.get("image_empty_alt")),
                "image_oversized_count": _i(row.get("image_oversized_count")),
                "image_broken_count": _i(row.get("image_broken_count")),
                "image_audit_extra": _row_json(row.get("image_audit_extra"), default={}),
                # ── Phase B — hreflang ──
                "hreflang_count": _i(row.get("hreflang_count")),
                "hreflang_entries": _row_json(row.get("hreflang_entries"), default=[]),
                "hreflang_has_x_default": _row_bool(row.get("hreflang_has_x_default")),
                "hreflang_invalid_codes": _row_json(row.get("hreflang_invalid_codes"), default=[]),
                "hreflang_self_reference": _row_bool(row.get("hreflang_self_reference")),
                # ── Phase B — schema.org JSON-LD ──
                "jsonld_count": _i(row.get("jsonld_count")),
                "jsonld_types": _row_json(row.get("jsonld_types"), default=[]),
                "jsonld_blocks": _row_json(row.get("jsonld_blocks"), default=[]),
                "jsonld_invalid_count": _i(row.get("jsonld_invalid_count")),
                "jsonld_missing_required": _row_json(row.get("jsonld_missing_required"), default=[]),
                "jsonld_rich_result_eligible": _row_json(row.get("jsonld_rich_result_eligible"), default=[]),
                "microdata_count": _i(row.get("microdata_count")),
                "rdfa_count": _i(row.get("rdfa_count")),
                # ── Phase C.1 JS render-delta ──
                "js_rendered": _row_bool(row.get("js_rendered")),
                "content_delta_ratio": _opt_f(row.get("content_delta_ratio")) or 0.0,
                "link_delta_ratio": _opt_f(row.get("link_delta_ratio")) or 0.0,
                "jsonld_delta_ratio": _opt_f(row.get("jsonld_delta_ratio")) or 0.0,
                # ── Phase C.2 PDF ──
                "pdf_title": _s(row.get("pdf_title"), 512),
                "pdf_author": _s(row.get("pdf_author"), 256),
                "pdf_subject": _s(row.get("pdf_subject"), 512),
                "pdf_page_count": _i(row.get("pdf_page_count")),
                "pdf_language": _s(row.get("pdf_language"), 32),
                "pdf_has_text_layer": _row_bool(row.get("pdf_has_text_layer")),
                "pdf_is_encrypted": _row_bool(row.get("pdf_is_encrypted")),
                "pdf_byte_size": _i(row.get("pdf_byte_size")),
                # ── Phase C.3 Custom extractors ──
                "custom_extracted": _row_json(row.get("custom_extracted"), default={}),
                # ── Phase C.4 Readability + spelling ──
                "flesch_score": _opt_f(row.get("flesch_score")) or 0.0,
                "grade_level": _opt_f(row.get("grade_level")) or 0.0,
                "readable_word_count": _i(row.get("readable_word_count")),
                "readable_sentence_count": _i(row.get("readable_sentence_count")),
                "spelling_error_count": _i(row.get("spelling_error_count")),
                "spelling_errors": _row_json(row.get("spelling_errors"), default=[]),
                # ── Phase D.1 cookies ──
                "cookie_count": _i(row.get("cookie_count")),
                "cookies": _row_json(row.get("cookies"), default=[]),
                "cookies_insecure_count": _i(row.get("cookies_insecure_count")),
                "cookies_no_samesite_count": _i(row.get("cookies_no_samesite_count")),
                "cookies_no_httponly_session_count": _i(row.get("cookies_no_httponly_session_count")),
                "cookies_third_party_count": _i(row.get("cookies_third_party_count")),
                "cookies_tracker_count": _i(row.get("cookies_tracker_count")),
                "has_consent_banner": _row_bool(row.get("has_consent_banner")),
                # ── Phase D.2 AMP ──
                "is_amp_page": _row_bool(row.get("is_amp_page")),
                "has_amp_alternate": _row_bool(row.get("has_amp_alternate")),
                "amp_alternate_url": _s(row.get("amp_alternate_url"), 2048),
                "amp_canonical_target": _s(row.get("amp_canonical_target"), 2048),
                "amp_required_missing": _row_json(row.get("amp_required_missing"), default=[]),
                "amp_invalid": _row_bool(row.get("amp_invalid")),
                # ── Phase D.3 accessibility ──
                "html_lang": _s(row.get("html_lang"), 16),
                "h1_count": _i(row.get("h1_count")),
                "heading_skip_count": _i(row.get("heading_skip_count")),
                "form_inputs_no_label": _i(row.get("form_inputs_no_label")),
                "links_no_text": _i(row.get("links_no_text")),
                "links_generic_text": _i(row.get("links_generic_text")),
                "invalid_aria_roles": _row_json(row.get("invalid_aria_roles"), default=[]),
                "has_skip_link": _row_bool(row.get("has_skip_link")),
                # ── Phase E LanguageTool grammar ──
                "grammar_error_count": _i(row.get("grammar_error_count")),
                "grammar_errors": _row_json(row.get("grammar_errors"), default=[]),
                "grammar_categories": _row_json(row.get("grammar_categories"), default={}),
                "grammar_lang_detected": _s(row.get("grammar_lang_detected"), 16),
                "grammar_tool_used": _s(row.get("grammar_tool_used"), 24),
                # ── Phase E AXE color contrast ──
                "color_contrast_violations_count": _i(row.get("color_contrast_violations_count")),
                "color_contrast_violations": _row_json(row.get("color_contrast_violations"), default=[]),
                "axe_tool_used": _s(row.get("axe_tool_used"), 24),
                # ── Phase 2A.5 — Structural mirror parity ──
                # Persists the per-page heading/link/image inventory the
                # parser builds via _extract_structured(). Required by the
                # ContentWriter + LayoutAgent + StructureAgent. Defaults
                # to [] so older crawls without these row keys don't fail.
                "headings_json": _row_json(row.get("headings_json"), default=[]),
                "internal_links_json": _row_json(row.get("internal_links_json"), default=[]),
                "external_links_json": _row_json(row.get("external_links_json"), default=[]),
                "images_json": _row_json(row.get("images_json"), default=[]),
                # Page-level scalars the in-house parser collects but the
                # legacy CSV path didn't persist to DB. Adding here closes
                # the audit_completeness gap for meta_description/canonical.
                "meta_description": _s(row.get("meta_description"), 1024),
                "canonical": _s(row.get("canonical"), 2048),
                "meta_robots": _s(row.get("meta_robots"), 256),
                "body_text": (row.get("body_text") or ""),
            },
        )
    except Exception as exc:  # noqa: BLE001 — never block the CSV path
        # Throttle log spam: only log the FIRST failure per process.
        global _dual_write_warned
        if not _dual_write_warned:
            log.warning(
                "csv_writer: dual-write to Postgres failed (%s) — "
                "continuing with CSV-only writes for this process. "
                "Set CRAWLER_DUAL_WRITE_POSTGRES=false to silence.",
                exc,
            )
            _dual_write_warned = True


_dual_write_warned = False


def flush_streams() -> None:
    with _lock:
        for f, _ in _handles.values():
            try:
                f.flush()
            except Exception:  # noqa: BLE001
                pass


def _close_locked() -> None:
    for f, _ in _handles.values():
        try:
            f.flush()
            f.close()
        except Exception:  # noqa: BLE001
            pass
    _handles.clear()


def close_streams() -> None:
    with _lock:
        _close_locked()


def _results_json_from_csv(path: Path) -> list[dict]:
    """Rebuild the full results list from crawl_results.csv (covers resumed runs)."""
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                out.append(dict(row))
    except Exception:  # noqa: BLE001
        return out
    return out


def save_state(final: bool = False) -> None:
    """Persist crawl_state.json (resume snapshot + live stats).

    On ``final`` also (re)writes crawl_results.json from the CSV so it reflects
    the whole crawl, including pages fetched in earlier (resumed) runs.
    """
    d = settings.data_path
    with STATE.lock:
        state_obj = {
            "visited": list(STATE.visited),
            "queued": list(STATE.queued),
            "queue": [list(item) for item in STATE.queue],
            "stats": STATE.stats.as_dict(),
        }
    try:
        _write_json(state_obj, d / "crawl_state.json")
        if final:
            _write_json(_results_json_from_csv(d / "crawl_results.csv"),
                        d / "crawl_results.json")
    except Exception as exc:  # noqa: BLE001
        log.warning("save_state failed: %s", exc)


# Backwards-compatible alias: older call sites used flush_all() to checkpoint.
def flush_all() -> None:
    flush_streams()
    save_state(final=True)
