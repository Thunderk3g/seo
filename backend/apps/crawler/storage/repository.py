"""Read-only access to persisted CSVs for the API."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ..conf import settings

# Master registry — single source of truth for UI table keys
CATALOG: dict[str, dict] = {
    "results": {
        "file": "crawl_results.csv",
        "label": "Crawl Results",
        "icon": "check_circle",
        "description": "Every URL crawled with status, title, size and timing.",
    },
    "errors": {
        "file": "crawl_errors.csv",
        "label": "All Errors",
        "icon": "error",
        "description": "Union of every failure observed during the crawl.",
    },
    "errors_404": {
        "file": "crawl_404_errors.csv",
        "label": "404 Not Found",
        "icon": "link_off",
        "description": "Internal links that returned HTTP 404.",
    },
    "errors_http": {
        "file": "crawl_errors_httperror.csv",
        "label": "HTTP Errors",
        "icon": "http",
        "description": "Non-404 HTTP error responses (5xx, 4xx other).",
    },
    "errors_connection": {
        "file": "crawl_errors_connectionerror.csv",
        "label": "Connection Errors",
        "icon": "wifi_off",
        "description": "TCP / DNS / refused-connection failures.",
    },
    "errors_chunked": {
        "file": "crawl_errors_chunkedencodingerror.csv",
        "label": "Chunked Encoding Errors",
        "icon": "broken_image",
        "description": "Responses with malformed chunked transfer encoding.",
    },
    "console": {
        "file": "crawl_console_log.csv",
        "label": "Console Log",
        "icon": "terminal",
        "description": "Heuristic JS console errors found in page source.",
    },
    "discovered": {
        "file": "crawl_discovered.csv",
        "label": "Discovered Edges",
        "icon": "account_tree",
        "description": "Every in-domain link and the page it was found on.",
    },
}


def _path(filename: str) -> Path:
    return settings.data_path / filename


def exists(key: str) -> bool:
    meta = CATALOG.get(key)
    return bool(meta) and _path(meta["file"]).exists()


def read_csv(key: str) -> dict:
    """Return {headers, rows, count} or empty skeleton."""
    meta = CATALOG.get(key)
    if not meta:
        return {"headers": [], "rows": [], "count": 0}
    path = _path(meta["file"])
    if not path.exists():
        return {"headers": [], "rows": [], "count": 0}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
        rows = list(reader)
    return {"headers": headers, "rows": rows, "count": len(rows)}


def read_state() -> dict | None:
    path = _path("crawl_state.json")
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def summary() -> dict:
    """High-level stats for dashboard cards."""
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
