"""GSC Coverage CSV loader — indexed-vs-not-indexed status per URL.

The Google Search Console UI lets you export the Pages / Coverage report as
CSV. Drop the file(s) into ``backend/data/gsc/coverage/`` (any filename
matching ``coverage_*.csv``); the most-recently-modified file wins. The map
is cached at module level and invalidated automatically when the underlying
file changes (mtime check).

Used by:
    * ``csv_writer.append()`` to stamp ``indexed_status`` onto every row
      emitted by the live crawler.
    * ``migrate_reports`` to backfill the same column onto rows already on
      disk from previous crawls.
    * ``views.gsc_coverage_refresh_view`` to flush the cache after the user
      drops a fresh export.
"""
from __future__ import annotations

import csv
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from ..conf import settings
from ..logger import get_logger

log = get_logger(__name__)


# ── Status mapping. Anything not listed becomes "unknown". ─────────────────
_STATUS_MAP: dict[str, str] = {
    # indexed
    "submitted and indexed": "indexed",
    "indexed, not submitted in sitemap": "indexed",
    "indexed": "indexed",
    # not indexed (only emitted when Google explicitly says so — via the
    # Coverage UI export or URL Inspection API, never derived heuristically)
    "crawled - currently not indexed": "not_indexed",
    "discovered - currently not indexed": "not_indexed",
    # excluded (by directive, redirect, alt canonical, or unreachable)
    "excluded": "excluded",
    "url is not on google": "excluded",
    "page with redirect": "excluded",
    "alternate page with proper canonical tag": "excluded",
    "duplicate without user-selected canonical": "excluded",
    "duplicate, google chose different canonical than user": "excluded",
    "not found (404)": "excluded",
    "soft 404": "excluded",
    "blocked by robots.txt": "excluded",
    "excluded by 'noindex' tag": "excluded",
    "server error (5xx)": "excluded",
    "blocked due to access forbidden (403)": "excluded",
    "blocked due to unauthorized request (401)": "excluded",
    # derived: crawler found it, no GSC performance signal, but URL is
    # not yet definitively classified. Stays "unknown" so the UI doesn't
    # mislabel low-traffic indexed pages as "not indexed".
    "no gsc signal": "unknown",
}

# Tracking / campaign params to strip during URL normalisation. Anything not
# in this set is preserved so we don't accidentally collapse distinct URLs.
_DROP_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "yclid", "mc_cid", "mc_eid", "ref",
}


# ── Module-level cache ─────────────────────────────────────────────────────
_lock = Lock()
_cache: dict | None = None  # {"path": Path, "mtime": float, "map": dict[str, str]}


# ── Public API ─────────────────────────────────────────────────────────────
def coverage_dir() -> Path:
    return settings.data_path / "gsc" / "coverage"


def normalize_url(url: str) -> str:
    """Canonicalise a URL for cross-source lookup.

    * lowercase scheme + host
    * strip default ports
    * collapse trailing slash (except for root "/")
    * drop fragment
    * drop UTM / click-tracking query params
    """
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except (ValueError, TypeError):
        return url.strip()
    scheme = (p.scheme or "https").lower()
    host = (p.hostname or "").lower()
    if p.port and not ((scheme == "http" and p.port == 80) or
                       (scheme == "https" and p.port == 443)):
        host = f"{host}:{p.port}"
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    kept = [(k, v) for (k, v) in parse_qsl(p.query, keep_blank_values=True)
            if k.lower() not in _DROP_QUERY_KEYS]
    query = urlencode(kept) if kept else ""
    return urlunparse((scheme, host, path, "", query, ""))


def load_coverage_map() -> dict[str, str]:
    """Return ``{normalized_url: indexed | not_indexed | excluded}``.

    Returns an empty dict (so every lookup returns ``"unknown"``) when no
    coverage CSV is present. Cached with mtime invalidation; reload is
    automatic the next call after the file changes.
    """
    global _cache
    with _lock:
        latest = _latest_csv()
        if latest is None:
            _cache = None
            return {}
        try:
            mtime = latest.stat().st_mtime
        except OSError:
            _cache = None
            return {}
        if _cache and _cache["path"] == latest and _cache["mtime"] == mtime:
            return _cache["map"]
        data = _parse_csv(latest)
        _cache = {"path": latest, "mtime": mtime, "map": data}
        log.info("gsc_loader: loaded %s URLs from %s", len(data), latest.name)
        return data


def invalidate_cache() -> None:
    """Drop the cache so the next call re-reads the latest CSV."""
    global _cache
    with _lock:
        _cache = None


def status_for(url: str) -> str:
    """One-shot helper: lookup with normalisation + 'unknown' fallback."""
    if not url:
        return "unknown"
    return load_coverage_map().get(normalize_url(url), "unknown")


# ── Internals ──────────────────────────────────────────────────────────────
def _latest_csv() -> Path | None:
    d = coverage_dir()
    if not d.exists():
        return None
    candidates = sorted(
        (p for p in d.glob("coverage_*.csv") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _parse_csv(path: Path) -> dict[str, str]:
    """Read a GSC export. Column names vary by export variant; we sniff."""
    out: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            url_col = _pick_col(reader.fieldnames or [],
                                ("url", "page", "pages"))
            status_col = _pick_col(reader.fieldnames or [],
                                   ("indexing status", "coverage state",
                                    "status", "issue", "issue type",
                                    "validation"))
            if not url_col or not status_col:
                log.warning(
                    "gsc_loader: %s has unrecognised columns %s",
                    path.name, reader.fieldnames,
                )
                return out
            for row in reader:
                u = (row.get(url_col) or "").strip()
                s = (row.get(status_col) or "").strip().lower()
                if not u:
                    continue
                key = normalize_url(u)
                out[key] = _STATUS_MAP.get(s, "unknown")
    except Exception as exc:  # noqa: BLE001
        log.warning("gsc_loader: failed to parse %s: %s", path, exc)
    return out


def _pick_col(headers: list[str], wanted: tuple[str, ...]) -> str | None:
    lowered = {h.lower().strip(): h for h in headers}
    for w in wanted:
        if w in lowered:
            return lowered[w]
    return None
