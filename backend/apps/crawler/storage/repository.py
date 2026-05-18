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
from pathlib import Path
from typing import Iterable

from ..conf import settings
from . import url_classifier

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
    "errors_connection": {
        "file": "crawl_errors_connectionerror.csv",
        "label": "Connection Errors",
        "icon": "wifi_off",
        "description": "TCP / DNS / refused-connection failures.",
        "categorized": False,
    },
    "errors_chunked": {
        "file": "crawl_errors_chunkedencodingerror.csv",
        "label": "Chunked Encoding Errors",
        "icon": "broken_image",
        "description": "Responses with malformed chunked transfer encoding.",
        "categorized": False,
    },
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
    r = read_csv("results")
    e = read_csv("errors")
    e404 = read_csv("errors_404")
    con = read_csv("console")
    disc = read_csv("discovered")
    ok = sum(1 for row in r["rows"] if row and len(row) > 1 and row[1] == "200")
    state = read_state()
    return {
        "pages_crawled": r["count"],
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
    """Aggregate the results CSV by subdomain and category.

    Drives the Reports landing page badges and the Excel pivot. Computed by
    a single streaming pass so we don't load the whole CSV into memory.
    """
    by_subdomain: dict[str, dict] = {}
    by_category: dict[str, dict] = {}
    noise_branch_404 = 0
    for row in iter_rows("results"):
        sub = row.get("subdomain") or "external"
        cat = row.get("category_key") or "unknown"
        by_subdomain.setdefault(sub, _zero_counts())
        by_category.setdefault(cat, _zero_counts())
        _bump(by_subdomain[sub], row)
        _bump(by_category[cat], row)
        if (sub == "branch"
                and row.get("status_code") == "404"
                and row.get("indexed_status") != "indexed"):
            noise_branch_404 += 1
    # Add per-category metadata so the UI doesn't have to mirror CATEGORY_DEFS.
    cat_meta = {c["key"]: c for c in url_classifier.CATEGORY_DEFS}
    categories = []
    for c in url_classifier.CATEGORY_DEFS:
        counts = by_category.get(c["key"], _zero_counts())
        categories.append({**c, "counts": counts})
    # Also expose any unexpected categories that snuck in (defensive).
    for k, counts in by_category.items():
        if k not in cat_meta:
            categories.append({"key": k, "label": k, "subdomain": "external",
                               "icon": "help_outline", "counts": counts})
    return {
        "by_subdomain": by_subdomain,
        "by_category": {c["key"]: c["counts"] for c in categories},
        "categories": categories,
        "noise_404_branch_not_indexed": noise_branch_404,
    }
