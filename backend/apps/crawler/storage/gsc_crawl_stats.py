"""GSC Crawl Stats loader — ingests the Search Console *Crawl stats* export.

The Crawl Stats report (GSC → Settings → Crawl stats) is **export-only** —
Google does not expose it through the Search Console API. The UI's "Export"
button produces a bundle of CSVs (or a .zip of them). Drop the extracted
files into ``backend/data/gsc_crawl_stats/`` (the loader also looks one
sub-directory deep, so dropping the whole exported folder works too).

Expected filenames (exactly as Google names them):

    Summary crawl stats chart.csv   Date, Total crawl requests,
                                     Total download size (Bytes),
                                     Average response time (ms)
    Response table.csv              Response, Total requests ratio
    File type table.csv             File type, Total requests ratio
    Googlebot type table.csv        Googlebot type, Total requests ratio
    Hosts table.csv                 Host, Crawl requests, Status
    Purpose table.csv               Purpose, Total requests ratio

Every table is optional — the loader degrades gracefully and returns
whatever it finds. ``{"present": False}`` when nothing is on disk yet.

Cached at module level, invalidated on the newest file's mtime (mirrors
``gsc_loader`` / ``pagerank``).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from ..conf import settings
from ..logger import get_logger

log = get_logger(__name__)


# Canonical (lower-cased) filenames → which parser handles them.
_SUMMARY_FILE = "summary crawl stats chart.csv"
_RESPONSE_FILE = "response table.csv"
_FILETYPE_FILE = "file type table.csv"
_BOTTYPE_FILE = "googlebot type table.csv"
_HOSTS_FILE = "hosts table.csv"
_PURPOSE_FILE = "purpose table.csv"

_RATIO_FILES = (_RESPONSE_FILE, _FILETYPE_FILE, _BOTTYPE_FILE, _PURPOSE_FILE)


# ── Module-level cache ─────────────────────────────────────────────────────
_lock = Lock()
_cache: dict | None = None  # {"mtime": float, "payload": dict}


def crawl_stats_dir() -> Path:
    return settings.data_path / "gsc_crawl_stats"


def _discover_files() -> dict[str, Path]:
    """Map canonical lower-cased filename → Path. Searches the drop dir
    and one level of sub-directories (so an extracted export folder, or
    several of them, all resolve). On duplicates the newest file wins."""
    root = crawl_stats_dir()
    if not root.exists():
        return {}
    found: dict[str, Path] = {}
    candidates = list(root.glob("*.csv")) + list(root.glob("*/*.csv"))
    for p in candidates:
        key = p.name.lower()
        prev = found.get(key)
        try:
            if prev is None or p.stat().st_mtime > prev.stat().st_mtime:
                found[key] = p
        except OSError:
            continue
    return found


def _latest_mtime(files: dict[str, Path]) -> float:
    best = 0.0
    for p in files.values():
        try:
            best = max(best, p.stat().st_mtime)
        except OSError:
            continue
    return best


# ── Public API ─────────────────────────────────────────────────────────────
def load() -> dict:
    """Return the parsed crawl-stats payload (cached, mtime-invalidated).

    Shape::

        {
          "present": bool,
          "source_dir": str,
          "files": [filename, ...],
          "exported_at": iso8601 | "",   # newest file's mtime
          "totals": {total_requests, avg_response_time_ms,
                     total_download_bytes, date_start, date_end, days},
          "series": [{date, requests, download_bytes, avg_response_ms}],
          "by_response": [{label, ratio, pct}],     # sorted desc
          "by_file_type": [...],
          "by_googlebot_type": [...],
          "by_purpose": [...],
          "hosts": [{host, requests, status}],
        }
    """
    global _cache
    with _lock:
        files = _discover_files()
        if not files:
            _cache = None
            return {"present": False, "source_dir": str(crawl_stats_dir())}
        mtime = _latest_mtime(files)
        if _cache and _cache.get("mtime") == mtime:
            return _cache["payload"]
        payload = _build_payload(files, mtime)
        _cache = {"mtime": mtime, "payload": payload}
        log.info(
            "gsc_crawl_stats: loaded %d table(s) from %s",
            len(files), crawl_stats_dir(),
        )
        return payload


def refresh() -> None:
    """Drop the cache so the next load() re-reads from disk. Called after
    the operator drops a fresh export."""
    global _cache
    with _lock:
        _cache = None


# ── Parsers ─────────────────────────────────────────────────────────────────
def _build_payload(files: dict[str, Path], mtime: float) -> dict:
    series = _parse_summary(files.get(_SUMMARY_FILE))
    hosts = _parse_hosts(files.get(_HOSTS_FILE))

    payload = {
        "present": True,
        "source_dir": str(crawl_stats_dir()),
        "files": sorted(p.name for p in files.values()),
        "exported_at": _iso(mtime),
        "series": series,
        "totals": _totals(series, hosts),
        "by_response": _parse_ratio(files.get(_RESPONSE_FILE), "Response"),
        "by_file_type": _parse_ratio(files.get(_FILETYPE_FILE), "File type"),
        "by_googlebot_type": _parse_ratio(files.get(_BOTTYPE_FILE), "Googlebot type"),
        "by_purpose": _parse_ratio(files.get(_PURPOSE_FILE), "Purpose"),
        "hosts": hosts,
    }
    return payload


def _parse_summary(path: Path | None) -> list[dict]:
    """Daily series: Date, Total crawl requests, Total download size
    (Bytes), Average response time (ms)."""
    if path is None:
        return []
    out: list[dict] = []
    for row in _read_dicts(path):
        date = (row.get("Date") or "").strip()
        if not date:
            continue
        out.append({
            "date": date,
            "requests": _to_int(row.get("Total crawl requests")),
            "download_bytes": _to_int(row.get("Total download size (Bytes)")),
            "avg_response_ms": _to_int(row.get("Average response time (ms)")),
        })
    out.sort(key=lambda r: r["date"])
    return out


def _parse_ratio(path: Path | None, label_col: str) -> list[dict]:
    """A breakdown table: <label_col>, Total requests ratio. Returns rows
    sorted by ratio desc with a convenience ``pct`` (0-100, 2 dp)."""
    if path is None:
        return []
    out: list[dict] = []
    for row in _read_dicts(path):
        label = (row.get(label_col) or "").strip()
        if not label:
            # Tolerate a renamed first column by falling back to the first
            # value in the row.
            vals = [v for v in row.values() if v]
            label = (vals[0].strip() if vals else "")
        if not label:
            continue
        ratio = _to_float(row.get("Total requests ratio"))
        out.append({
            "label": label,
            "ratio": ratio,
            "pct": round(ratio * 100, 2),
        })
    out.sort(key=lambda r: r["ratio"], reverse=True)
    return out


def _parse_hosts(path: Path | None) -> list[dict]:
    """Host, Crawl requests, Status."""
    if path is None:
        return []
    out: list[dict] = []
    for row in _read_dicts(path):
        host = (row.get("Host") or "").strip()
        if not host:
            continue
        out.append({
            "host": host,
            "requests": _to_int(row.get("Crawl requests")),
            "status": (row.get("Status") or "").strip(),
        })
    out.sort(key=lambda r: r["requests"], reverse=True)
    return out


def _totals(series: list[dict], hosts: list[dict]) -> dict:
    """Roll-up headline numbers. Total requests prefers the Hosts-table
    sum (Google's authoritative per-host count) and falls back to the
    summed daily series."""
    host_total = sum(h["requests"] for h in hosts) if hosts else 0
    series_total = sum(r["requests"] for r in series) if series else 0
    total_requests = host_total or series_total

    download_total = sum(r["download_bytes"] for r in series) if series else 0
    # Request-weighted mean response time across the window.
    weighted = sum(r["avg_response_ms"] * r["requests"] for r in series)
    avg_response = round(weighted / series_total) if series_total else 0

    return {
        "total_requests": total_requests,
        "total_download_bytes": download_total,
        "avg_response_time_ms": avg_response,
        "date_start": series[0]["date"] if series else "",
        "date_end": series[-1]["date"] if series else "",
        "days": len(series),
    }


# ── small helpers ───────────────────────────────────────────────────────────
def _read_dicts(path: Path) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError as exc:
        log.warning("gsc_crawl_stats: cannot read %s: %s", path, exc)
        return []


def _to_int(val) -> int:
    if val is None:
        return 0
    try:
        return int(float(str(val).strip().replace(",", "")))
    except (ValueError, TypeError):
        return 0


def _to_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(str(val).strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _iso(mtime: float) -> str:
    if not mtime:
        return ""
    try:
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""
