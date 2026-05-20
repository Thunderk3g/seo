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

RESULTS_FIELDS = [
    "url", "status_code", "status", "title", "word_count",
    "response_time_ms", "content_type", "error_type", "error_message",
    *_ENRICH_FIELDS,
    # PSI / Core Web Vitals (mobile strategy by default). Populated by
    # the end-of-crawl PSI phase via _merge_into_results_csv. Empty for
    # rows that weren't in the PSI subset (skipped, non-200, capped by
    # PSI_MAX_URLS_PER_RUN). lcp/inp are p75 field values when CrUX has
    # data; lab values are used as a fallback.
    "pagespeed_score", "lcp_ms", "cls", "inp_ms",
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

        CrawlerPageResult.objects.update_or_create(
            snapshot_id=snap_id,
            url=url[:2048],
            defaults={
                "status_code": (row.get("status_code") or "")[:4],
                "status": (row.get("status") or "")[:64],
                "content_type": (row.get("content_type") or "")[:128],
                "response_time_ms": _i(row.get("response_time_ms")),
                "title": (row.get("title") or "")[:1024],
                "word_count": _i(row.get("word_count")),
                "error_type": (row.get("error_type") or "")[:64],
                "error_message": (row.get("error_message") or "")[:4000],
                "subdomain": (row.get("subdomain") or "")[:64],
                "page_type": (row.get("page_type") or "")[:64],
                "category_key": (row.get("category_key") or "")[:128],
                "from_sitemap": (row.get("from_sitemap") or "0") == "1",
                "indexed_status": (row.get("indexed_status") or "unknown")[:16],
                "pagespeed_score": _opt_i(row.get("pagespeed_score")),
                "lcp_ms": _opt_i(row.get("lcp_ms")),
                "cls": _opt_f(row.get("cls")),
                "inp_ms": _opt_i(row.get("inp_ms")),
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
