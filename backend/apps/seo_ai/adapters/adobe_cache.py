"""Per-section disk cache for Adobe Analytics 2.0 reports.

Adobe's API is rate-limited, slow on cold pulls (~2-3 s per report ×
20 reports = ~40-60 s on a fresh dashboard load), and prone to token
churn / outages. The dashboard composes ~20 distinct reports per
render — we don't want a single transient failure to wipe a section
in the UI, and we don't want every page refresh to burn 60 seconds
of API time.

Strategy: each report writes its payload to a JSON file after a
successful pull, and reads it back on failure. The composer tracks
per-section freshness ("live" | "cached" | "missing") so the UI can
render a banner ("Showing cached data from 14h ago — Adobe API
unreachable") without dropping the section.

Cache files live under ``<DATA_DIR>/_adobe_cache/<rsid>/`` so multiple
report suites coexist cleanly. Atomic writes via .tmp + rename keep
partial-write garbage out of disk.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("apps.seo_ai.adapters.adobe_cache")


def _cache_root() -> Path:
    """Resolve <DATA_DIR>/_adobe_cache lazily — django.conf may not be
    importable at module load in some Celery worker contexts."""
    from django.conf import settings

    root = Path(settings.BASE_DIR) / "data" / "_adobe_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _slug(s: str) -> str:
    """Cache-key sanitiser. Anything outside [a-z0-9._-] becomes _."""
    s = (s or "").strip().lower()
    out = []
    for ch in s:
        if ch.isalnum() or ch in (".", "_", "-"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "_"


def _path(rsid: str, key: str) -> Path:
    """Path for a section's cache file under the rsid subdir."""
    sub = _cache_root() / _slug(rsid)
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{_slug(key)}.json"


def _to_jsonable(value: Any) -> Any:
    """Convert dataclasses / lists / dicts of dataclasses to plain JSON."""
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def write(rsid: str, key: str, data: Any, *, lookback_days: int = 0, limit: int = 0) -> None:
    """Persist a section payload to disk. Atomic via .tmp + rename so
    a reader never sees half-written JSON."""
    if not rsid or not key:
        return
    payload = {
        "data": _to_jsonable(data),
        "ts": int(time.time()),
        "lookback_days": int(lookback_days or 0),
        "limit": int(limit or 0),
        "rsid": rsid,
        "key": key,
    }
    path = _path(rsid, key)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("adobe cache write failed (%s/%s): %s", rsid, key, exc)


def read(rsid: str, key: str) -> dict | None:
    """Load a section's cache. Returns the whole envelope (data + ts)
    so callers can render a "cached N min ago" banner."""
    if not rsid or not key:
        return None
    path = _path(rsid, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("adobe cache read failed (%s/%s): %s", rsid, key, exc)
        return None


def freshness_age_sec(envelope: dict | None) -> int | None:
    """How old is this cached payload? Returns None when missing."""
    if not envelope or "ts" not in envelope:
        return None
    try:
        return max(0, int(time.time() - int(envelope["ts"])))
    except (TypeError, ValueError):
        return None


def try_or_cache(rsid: str, key: str, fetch_fn, *, lookback_days: int = 0, limit: int = 0):
    """Call ``fetch_fn``; on success update cache and tag the section
    "live"; on failure return the most recent cached payload tagged
    "cached"; if nothing is cached, return None tagged "missing".

    Returns (data, status, age_sec) where:
      data       — JSON-serialisable payload (dataclasses already
                   converted via ``_to_jsonable``)
      status     — "live" | "cached" | "missing"
      age_sec    — seconds since the cache write, or None when status
                   is "live" (the data is current).
    """
    try:
        data = fetch_fn()
        jsonable = _to_jsonable(data)
        write(rsid, key, jsonable, lookback_days=lookback_days, limit=limit)
        return jsonable, "live", None
    except Exception as exc:  # noqa: BLE001 - any failure → fall back
        logger.warning(
            "adobe pull %s/%s failed (%s); falling back to cache",
            rsid, key, exc,
        )
        env = read(rsid, key)
        if env is None:
            return None, "missing", None
        return env.get("data"), "cached", freshness_age_sec(env)


def cached_sections(rsid: str) -> dict[str, dict]:
    """List every cached section for an rsid → {key: envelope}.

    Used by the dashboard view's "data on disk" panel so the operator
    can see exactly which sections have a fall-back available.
    """
    sub = _cache_root() / _slug(rsid)
    if not sub.exists():
        return {}
    out: dict[str, dict] = {}
    for p in sorted(sub.glob("*.json")):
        try:
            env = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out[p.stem] = {
            "ts": env.get("ts"),
            "lookback_days": env.get("lookback_days", 0),
            "limit": env.get("limit", 0),
            "size_bytes": p.stat().st_size,
            "age_sec": freshness_age_sec(env),
        }
    return out
