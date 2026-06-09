"""Read-only access to persisted CSVs for the API.

Beyond the basic ``read_csv(key)`` for unfiltered table dumps, the module
exposes ``read_csv(key, filters=...)`` which applies streaming filters at
read time (no full materialisation when filtered) and ``summary_breakdown()``
which aggregates counts per subdomain / category / indexed_status so the
Reports landing page can render tab badges without re-reading the CSVs on
every render.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterable, Iterator

from ..conf import settings
from . import url_classifier

# Phase 2A.5 structural JSON fields (body_text + internal_links_json
# with 100+ entries + images_json) can exceed Python's default 128 KB
# csv field-size limit once the writer serializes lists/dicts to JSON
# strings. Raise the cap to sys.maxsize so the reader doesn't choke on
# legitimately wide rows. Side effect is process-wide which is fine —
# we never read attacker-controlled CSVs.
csv.field_size_limit(sys.maxsize)

# Master registry — single source of truth for UI table keys.
#
# ``categorized: True`` means the table is the full-truth dataset (results /
# errors / 404s / discovered / console) and supports filtering by
# subdomain / category / indexed_status / from_sitemap. The per-error-type
# files are already a subset view of "errors" so they're flagged False.
CATALOG: dict[str, dict] = {
    "results": {
        "file": "crawl_results.csv",
        "label": "Crawl Results",
        "icon": "check_circle",
        "description": "Every URL crawled with status, title, size and timing.",
        "categorized": True,
    },
    "errors": {
        "file": "crawl_errors.csv",
        "label": "All Errors",
        "icon": "error",
        "description": "Union of every failure observed during the crawl.",
        "categorized": True,
    },
    "errors_404": {
        "file": "crawl_404_errors.csv",
        "label": "404 Not Found",
        "icon": "link_off",
        "description": "Internal links that returned HTTP 404.",
        "categorized": True,
    },
    "errors_http": {
        "file": "crawl_errors_httperror.csv",
        "label": "HTTP Errors",
        "icon": "http",
        "description": "Non-404 HTTP error responses (5xx, 4xx other).",
        "categorized": False,
    },
    # Removed unused tables: errors_connection / errors_chunked. They added
    # noise to the raw-data drawer without informing any UI surface. The
    # CSVs may still exist on disk from prior crawls; they're no longer
    # written or read by this app.
    "console": {
        "file": "crawl_console_log.csv",
        "label": "Console Log",
        "icon": "terminal",
        "description": "Heuristic JS console errors found in page source.",
        "categorized": True,
    },
    "discovered": {
        "file": "crawl_discovered.csv",
        "label": "Discovered Edges",
        "icon": "account_tree",
        "description": "Every in-domain link and the page it was found on.",
        "categorized": True,
    },
}


# ── Path / existence helpers ───────────────────────────────────────────────
def _path(filename: str) -> Path:
    return settings.data_path / filename


# ── Lean projection + memo for full-scan aggregates ────────────────────────
# summary() and summary_breakdown() only need a handful of small columns, but
# crawl_results.csv carries per-row *_json columns (internal_links_json /
# images_json / headings_json) that balloon it to hundreds of MB. On the
# Windows Docker bind mount a single raw read of that file costs ~40s, so the
# dashboard's IndexCoveragePanel appeared to hang on mount.
#
# Fix: keep a tiny sidecar ("…lean.csv") holding only the small columns the
# aggregates AND the Page Explorer touch, with the on-page link *counts*
# pre-derived from the *_links_json arrays so the raw (huge) JSON never lands
# in the projection. We rebuild it in one pass whenever the master file
# changes (guarded by a single-flight lock so concurrent dashboard requests
# don't each re-scan), then every reader gets the few-MB lean file in well
# under a second. An in-memory memo on top makes warm polls effectively free.
#
# _LEAN_DIRECT_COLS are copied straight across; the two link-count columns are
# computed during the build. Together they are exactly Page Explorer's COLUMNS.
_LEAN_DIRECT_COLS = [
    "url", "status_code", "status", "title", "word_count",
    "response_time_ms", "content_type", "error_type", "error_message",
    "subdomain", "page_type", "category_key", "from_sitemap",
    "indexed_status", "pagespeed_score", "lcp_ms", "cls", "inp_ms",
    # Redirect + PDF columns — small, kept so the live Reports sections
    # (redirects / PDF health) read the lean instead of the 400 MB master.
    "redirect_hops", "redirect_chain", "redirect_final_url", "redirect_loop",
    "pdf_title", "pdf_page_count", "pdf_has_text_layer", "pdf_is_encrypted",
    "pdf_byte_size",
]
_LEAN_OUTPUT_COLS = _LEAN_DIRECT_COLS + [
    "internal_links_count", "external_links_count",
]
_LEAN_FILE = "balic_crawl_results.lean.csv"
# During a live crawl the master grows every few seconds; rebuilding the lean
# (a ~40s read of the 300-400 MB master over the bind mount) on every request
# would be ruinous. So while the master is actively newer than the lean, we
# rebuild at most once per throttle window and serve the slightly-stale lean in
# between — aggregates only need to be approximately fresh mid-crawl, and the
# live cards read /status anyway. Once the crawl settles, the next rebuild lands
# the final rows and the lean becomes current (mtime >= master) for good.
_LEAN_REBUILD_THROTTLE_SEC = 90.0
_lean_lock = threading.Lock()
_lean_last_build = 0.0  # time.monotonic() of the last successful rebuild
_AGG_CACHE: dict[str, tuple] = {}


def _results_signature() -> tuple:
    """Cheap change-token for crawl_results.csv (no read of the body)."""
    p = _path(CATALOG["results"]["file"])
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def _lean_path() -> Path:
    """Where the lean projection lives.

    Deliberately the container-local temp dir, NOT settings.data_path: that
    dir is a Windows bind mount (slow IO) *and* is watched by the dev-server
    auto-reloader, so writing the projection there would both crawl and
    trigger a reload that wipes our throttle state — a rebuild loop. /tmp is
    fast, unwatched, and an ephemeral derived cache is fine to lose on restart.
    """
    return Path(tempfile.gettempdir()) / _LEAN_FILE


def _json_array_len(cell: str) -> int:
    """Count elements in a JSON-array CSV cell; 0 for empty/unparseable."""
    if not cell:
        return 0
    s = cell.strip()
    if not s or s in ("[]", "null"):
        return 0
    try:
        parsed = json.loads(s)
    except (ValueError, TypeError):
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


def _build_lean(master: Path, lean: Path) -> None:
    """One streaming pass: project the master CSV down to ``_LEAN_OUTPUT_COLS``.

    Direct columns are copied; ``internal_links_count`` / ``external_links_count``
    are derived from the (huge) ``*_links_json`` columns so the projection drops
    the raw JSON entirely. Written to a temp file then atomically replaced so a
    concurrent reader never sees a half-written projection.
    """
    tmp = lean.with_suffix(lean.suffix + ".tmp")
    with open(master, "r", encoding="utf-8", newline="") as fin, \
            open(tmp, "w", encoding="utf-8", newline="") as fout:
        reader = csv.reader(fin)
        header = next(reader, [])
        idx = {h: i for i, h in enumerate(header)}
        direct = [idx.get(c) for c in _LEAN_DIRECT_COLS]
        i_int = idx.get("internal_links_json")
        i_ext = idx.get("external_links_json")

        def _at(row: list, i: int | None) -> str:
            return row[i] if (i is not None and i < len(row)) else ""

        writer = csv.writer(fout)
        writer.writerow(_LEAN_OUTPUT_COLS)
        for row in reader:
            out = [_at(row, i) for i in direct]
            out.append(str(_json_array_len(_at(row, i_int))))
            out.append(str(_json_array_len(_at(row, i_ext))))
            writer.writerow(out)
    os.replace(tmp, lean)


def _spawn_rebuild(master: Path, lean: Path) -> None:
    """Rebuild the lean projection on a daemon thread, then release the lock.

    The caller MUST already hold ``_lean_lock`` (acquired non-blocking); the
    thread releases it when done so readers never wait on the ~40s scan.
    """
    global _lean_last_build

    def _run() -> None:
        global _lean_last_build
        try:
            _build_lean(master, lean)
            _lean_last_build = time.monotonic()
        except OSError:
            pass
        finally:
            _lean_lock.release()

    threading.Thread(target=_run, name="lean-rebuild", daemon=True).start()


def _ensure_lean() -> Path | None:
    """Return the path to the lean projection, refreshing it in the background.

    Readers NEVER block on the rebuild: if a (possibly slightly stale) lean
    already exists we return it immediately and, at most once per throttle
    window, kick off a background rebuild. Only the very first build — when no
    projection exists yet — runs synchronously. Returns ``None`` (callers then
    scan the master directly) if the master is missing or the build fails.
    """
    global _lean_last_build
    master = _path(CATALOG["results"]["file"])
    if not master.exists():
        return None
    lean = _lean_path()
    try:
        master_mtime = master.stat().st_mtime_ns
        if lean.exists():
            if lean.stat().st_mtime_ns >= master_mtime:
                return lean  # already current
            # Stale (mid-crawl growth / new crawl). Serve it now; rebuild in the
            # background if we haven't recently and no rebuild is already running.
            if (time.monotonic() - _lean_last_build) >= _LEAN_REBUILD_THROTTLE_SEC \
                    and _lean_lock.acquire(blocking=False):
                if (time.monotonic() - _lean_last_build) >= _LEAN_REBUILD_THROTTLE_SEC:
                    _spawn_rebuild(master, lean)   # releases the lock when done
                else:
                    _lean_lock.release()
            return lean
        # No projection yet — the first build has to be synchronous.
        with _lean_lock:
            if lean.exists() and lean.stat().st_mtime_ns >= master_mtime:
                return lean
            _build_lean(master, lean)
            _lean_last_build = time.monotonic()
        return lean
    except OSError:
        return None


def iter_results_lean() -> Iterator[dict]:
    """Yield result rows as dicts from the lean projection (``_LEAN_OUTPUT_COLS``,
    with link counts pre-derived). Shared by summary()/summary_breakdown() and
    the Page Explorer so none of them re-read the hundreds-of-MB master.

    Reads the small projection when available; otherwise streams the master
    (slow, but correct) so callers still work before the lean file exists — in
    that fallback the derived ``*_links_count`` columns are absent.
    """
    src = _ensure_lean() or _path(CATALOG["results"]["file"])
    if not src.exists():
        return
    with open(src, "r", encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def count_rows(key: str) -> int:
    """Row count for a table WITHOUT materialising it.

    For the (hundreds-of-MB) results table this counts the lean projection,
    so the Reports landing page no longer slurps the master just to show a
    badge count. Other tables are small and counted with a streaming pass.
    """
    if key == "results":
        return sum(1 for _ in iter_results_lean())
    meta = CATALOG.get(key)
    if not meta:
        return 0
    p = _path(meta["file"])
    if not p.exists():
        return 0
    with open(p, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        return sum(1 for row in reader if row)


def _memoize_on_results(key: str, compute):
    sig = _results_signature()
    cached = _AGG_CACHE.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    value = compute()
    _AGG_CACHE[key] = (sig, value)
    return value


def exists(key: str) -> bool:
    meta = CATALOG.get(key)
    return bool(meta) and _path(meta["file"]).exists()


# ── Filter parsing ─────────────────────────────────────────────────────────
def _normalise_filter_values(value) -> set[str] | None:
    """Turn ``"a,b,c"`` / list / set into ``{"a","b","c"}``. Empty -> None."""
    if value is None:
        return None
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",") if v.strip()]
    else:
        items = [str(v).strip() for v in value if str(v).strip()]
    return set(items) if items else None


def _parse_filters(filters: dict | None) -> dict:
    """Resolve a raw filter dict into membership sets the row-loop uses."""
    if not filters:
        return {}
    out = {
        "subdomain":      _normalise_filter_values(filters.get("subdomain")),
        "category_key":   _normalise_filter_values(filters.get("category_key")
                                                   or filters.get("category")),
        "page_type":      _normalise_filter_values(filters.get("page_type")),
        "indexed_status": _normalise_filter_values(filters.get("indexed_status")
                                                   or filters.get("indexed")),
        "from_sitemap":   _normalise_filter_values(filters.get("from_sitemap")),
    }
    out["hide_branch_404_noise"] = bool(filters.get("hide_branch_404_noise"))
    return out


def _classify_row(row: dict) -> dict:
    """Fall back to classifying on the fly for un-enriched rows (defensive).

    Production rows are enriched at write time, but if a stale CSV slipped
    past the migration we still want the filter to behave sensibly.
    """
    if row.get("category_key"):
        return row
    url = row.get("url") or ""
    c = url_classifier.classify(url)
    return {**row,
            "subdomain": row.get("subdomain") or c["subdomain"],
            "page_type": row.get("page_type") or c["page_type"],
            "category_key": c["category_key"],
            "from_sitemap": row.get("from_sitemap") or "unknown",
            "indexed_status": row.get("indexed_status") or "unknown"}


def _row_matches(row: dict, filt: dict) -> bool:
    if filt.get("subdomain") and row.get("subdomain") not in filt["subdomain"]:
        return False
    if filt.get("category_key") and row.get("category_key") not in filt["category_key"]:
        return False
    if filt.get("page_type") and row.get("page_type") not in filt["page_type"]:
        return False
    if filt.get("indexed_status") and row.get("indexed_status") not in filt["indexed_status"]:
        return False
    if filt.get("from_sitemap") and row.get("from_sitemap") not in filt["from_sitemap"]:
        return False
    if filt.get("hide_branch_404_noise"):
        is_branch = row.get("subdomain") == "branch"
        is_404 = (row.get("status_code") == "404"
                  or row.get("error_message", "").strip() == "HTTP 404")
        if is_branch and is_404 and row.get("indexed_status") != "indexed":
            return False
    return True


# ── Public read API ────────────────────────────────────────────────────────
def read_csv(key: str, filters: dict | None = None) -> dict:
    """Return ``{headers, rows, count}`` for one catalog entry.

    ``rows`` is a list-of-lists matching ``headers`` (the long-standing API
    shape). Filtering is applied row-by-row at read time so callers can
    pipe huge CSVs without materialising the full file.
    """
    meta = CATALOG.get(key)
    if not meta:
        return {"headers": [], "rows": [], "count": 0}
    path = _path(meta["file"])
    if not path.exists():
        return {"headers": [], "rows": [], "count": 0}
    parsed = _parse_filters(filters)
    has_filters = any(v for v in parsed.values()) or parsed.get("hide_branch_404_noise")
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
        if not has_filters:
            rows = list(reader)
            return {"headers": headers, "rows": rows, "count": len(rows)}
        dict_iter = (dict(zip(headers, row)) for row in reader if row)
        kept_rows = []
        for d in dict_iter:
            d = _classify_row(d)
            if _row_matches(d, parsed):
                kept_rows.append([d.get(h, "") for h in headers])
    return {"headers": headers, "rows": kept_rows, "count": len(kept_rows)}


def iter_rows(key: str, filters: dict | None = None) -> Iterable[dict]:
    """Streaming dict iterator over a table — used by the filtered CSV download."""
    meta = CATALOG.get(key)
    if not meta:
        return
    path = _path(meta["file"])
    if not path.exists():
        return
    parsed = _parse_filters(filters)
    has_filters = any(v for v in parsed.values()) or parsed.get("hide_branch_404_noise")
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if has_filters:
                row = _classify_row(row)
                if not _row_matches(row, parsed):
                    continue
            yield row


def read_state() -> dict | None:
    path = _path("crawl_state.json")
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def summary() -> dict:
    """High-level stats for dashboard cards. Unchanged shape (back-compat)."""
    return _memoize_on_results("summary", _compute_summary)


def _compute_summary() -> dict:
    # Count rows + HTTP-200s off the lean projection — avoids reading the
    # hundreds-of-MB master (and the OOM risk of list()-ing every wide row).
    pages = ok = 0
    for row in iter_results_lean():
        pages += 1
        if (row.get("status_code") or "") == "200":
            ok += 1
    e = read_csv("errors")
    e404 = read_csv("errors_404")
    con = read_csv("console")
    disc = read_csv("discovered")
    state = read_state()
    return {
        "pages_crawled": pages,
        "ok_pages": ok,
        "total_errors": e["count"],
        "errors_404": e404["count"],
        "console_entries": con["count"],
        "discovered_edges": disc["count"],
        "state": (state or {}).get("stats"),
    }


# ── Category-aware breakdown ───────────────────────────────────────────────
def _zero_counts() -> dict:
    return {"crawled": 0, "ok": 0, "errors": 0, "errors_404": 0,
            "indexed": 0, "not_indexed": 0, "excluded": 0,
            "unknown_index": 0, "from_sitemap": 0}


def _bump(bucket: dict, row: dict) -> None:
    bucket["crawled"] += 1
    code = (row.get("status_code") or "").strip()
    if code == "200":
        bucket["ok"] += 1
    elif code == "404":
        bucket["errors_404"] += 1
        bucket["errors"] += 1
    elif code and not code.startswith("2"):
        bucket["errors"] += 1
    idx = row.get("indexed_status") or "unknown"
    if idx == "indexed":
        bucket["indexed"] += 1
    elif idx == "not_indexed":
        bucket["not_indexed"] += 1
    elif idx == "excluded":
        bucket["excluded"] += 1
    else:
        bucket["unknown_index"] += 1
    if row.get("from_sitemap") == "1":
        bucket["from_sitemap"] += 1


def summary_breakdown() -> dict:
    """Aggregate the results CSV by subdomain, category, indexing status,
    and sitemap source.

    Drives the Reports landing page sections and the Excel pivot. Computed
    in a single streaming pass so we don't load the whole CSV into memory,
    then memoized on the results-file signature so repeat dashboard polls
    don't re-scan the (hundreds-of-MB) file.
    """
    return _memoize_on_results("breakdown", _compute_summary_breakdown)


def _compute_summary_breakdown() -> dict:
    by_subdomain: dict[str, dict] = {}
    by_category: dict[str, dict] = {}
    by_indexed: dict[str, int] = {
        "indexed": 0, "not_indexed": 0, "excluded": 0, "unknown": 0,
    }
    by_sitemap: dict[str, int] = {
        "from_sitemap": 0, "discovered_only": 0, "unknown_source": 0,
    }
    sitemap_failed = 0          # in sitemap but did not return HTTP 200
    sitemap_404 = 0             # in sitemap but 404 — broken sitemap entries
    noise_branch_404 = 0
    for row in iter_results_lean():
        sub = row.get("subdomain") or "external"
        cat = row.get("category_key") or "unknown"
        by_subdomain.setdefault(sub, _zero_counts())
        by_category.setdefault(cat, _zero_counts())
        _bump(by_subdomain[sub], row)
        _bump(by_category[cat], row)

        idx = row.get("indexed_status") or "unknown"
        if idx in by_indexed:
            by_indexed[idx] += 1
        else:
            by_indexed["unknown"] += 1

        src = row.get("from_sitemap") or ""
        code = row.get("status_code") or ""
        if src == "1":
            by_sitemap["from_sitemap"] += 1
            if code != "200":
                sitemap_failed += 1
            if code == "404":
                sitemap_404 += 1
        elif src == "0":
            by_sitemap["discovered_only"] += 1
        else:
            by_sitemap["unknown_source"] += 1

        if (sub == "branch"
                and code == "404"
                and idx != "indexed"):
            noise_branch_404 += 1

    # Per-error-type counts come from the small per-file CSVs, not a re-scan
    # of the full results — quicker and these are already populated.
    by_error_type = {
        "errors_404":  read_csv("errors_404")["count"],
        "errors_http": read_csv("errors_http")["count"],
        "console":     read_csv("console")["count"],
    }

    # Categories metadata so the UI can map keys -> labels in one place.
    cat_meta = {c["key"]: c for c in url_classifier.CATEGORY_DEFS}
    categories = []
    for c in url_classifier.CATEGORY_DEFS:
        counts = by_category.get(c["key"], _zero_counts())
        categories.append({**c, "counts": counts})
    for k, counts in by_category.items():
        if k not in cat_meta:
            categories.append({"key": k, "label": k, "subdomain": "external",
                               "icon": "help_outline", "counts": counts})

    return {
        "by_subdomain": by_subdomain,
        "by_category": {c["key"]: c["counts"] for c in categories},
        "categories": categories,
        "by_indexed_status": by_indexed,
        "by_sitemap_source": by_sitemap,
        "sitemap_failed_count": sitemap_failed,
        "sitemap_404_count": sitemap_404,
        "by_error_type": by_error_type,
        "noise_404_branch_not_indexed": noise_branch_404,
    }
