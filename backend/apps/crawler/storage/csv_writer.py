"""Streaming CSV + JSON persistence.

Rows are appended to their CSV files as soon as they are produced (O(1) per
row) instead of rewriting whole files at every checkpoint, so crawls of
100k+ pages do not degrade into O(n^2) disk churn. ``crawl_state.json``
is written periodically so a crawl can resume after a crash.
"""
from __future__ import annotations

import csv
import json
import threading
from pathlib import Path

from ..conf import settings
from ..logger import get_logger
from ..state import STATE

log = get_logger(__name__)

RESULTS_FIELDS = [
    "url", "status_code", "status", "title", "word_count",
    "response_time_ms", "content_type", "error_type", "error_message",
]
ERROR_FIELDS = ["timestamp", "url", "error_type", "error_message"]
CONSOLE_FIELDS = ["timestamp", "url", "error"]
DISCOVERED_FIELDS = ["url", "discovered_from", "depth"]

# stream name -> (filename, fieldnames)
_STREAMS: dict[str, tuple[str, list[str]]] = {
    "results": ("crawl_results.csv", RESULTS_FIELDS),
    "errors": ("crawl_errors.csv", ERROR_FIELDS),
    "error_404": ("crawl_404_errors.csv", ERROR_FIELDS),
    "error_http": ("crawl_errors_httperror.csv", ERROR_FIELDS),
    "error_connection": ("crawl_errors_connectionerror.csv", ERROR_FIELDS),
    "error_chunked": ("crawl_errors_chunkedencodingerror.csv", ERROR_FIELDS),
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
    truncated and a fresh header written.
    """
    d = settings.data_path
    d.mkdir(parents=True, exist_ok=True)
    with _lock:
        _close_locked()
        for name, (fname, fields) in _STREAMS.items():
            path = d / fname
            keep = resume and path.exists() and path.stat().st_size > 0
            f = open(path, "a" if keep else "w", newline="", encoding="utf-8")
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if not keep:
                w.writeheader()
                f.flush()
            _handles[name] = (f, w)


def append(stream: str, row: dict) -> None:
    """Append one row to a stream. Flushes periodically."""
    global _writes_since_flush
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
