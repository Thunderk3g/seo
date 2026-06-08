"""Page Explorer service — Ahrefs-style sortable/filterable URL inventory.

Phase 2 implementation reads ``crawl_results.csv`` directly (with an
in-process LRU cache keyed by file mtime so repeated requests are
~5 ms instead of ~300 ms). Phase 3 swaps the data source to the
Postgres ``crawler_pageresult`` ORM model with the same query contract,
so the frontend never has to change.

Query contract (matches the view's params):

  * ``sort``       — one of: url, status_code, title, word_count,
                      response_time_ms, content_type, subdomain,
                      page_type, indexed_status, pagespeed_score,
                      lcp_ms, cls, inp_ms. Prefix with ``-`` for
                      descending (e.g., ``-word_count``).
  * ``status``     — comma-separated status codes to keep
                      ("200,301,404").
  * ``subdomain``  — comma-separated subdomain values.
  * ``page_type``  — comma-separated page type values.
  * ``indexed``    — comma-separated indexed_status values.
  * ``has_psi``    — "1" / "true" → only rows with non-empty
                      pagespeed_score. "0" / "false" → only rows
                      MISSING PSI.
  * ``q``          — substring filter against url + title (case-
                      insensitive).
  * ``limit``      — 1-500, default 50.
  * ``offset``     — 0-based pagination offset.

Returns a dict with ``total`` (count before pagination), ``returned``
(after limit), ``rows`` (list of dicts), and ``columns`` (the canonical
column list so the frontend can render headers consistently).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from ..conf import settings
from ..storage import repository as repo


def _json_len(val) -> int:
    """Length of a JSON-array field that may arrive as a Python list
    (ORM JSONField) or a JSON-encoded string (CSV cell). Returns 0 for
    anything empty/unparseable so a malformed cell never breaks the row.
    """
    if not val:
        return 0
    if isinstance(val, list):
        return len(val)
    if isinstance(val, str):
        s = val.strip()
        if not s or s in ("[]", "null"):
            return 0
        try:
            parsed = json.loads(s)
        except (ValueError, TypeError):
            return 0
        return len(parsed) if isinstance(parsed, list) else 0
    return 0


def _stamp_link_counts(row: dict) -> None:
    """Derive internal/external on-page link counts from the *_links_json
    columns and stamp them onto the row (in place) as string values so
    they sort + render like the other Page Explorer columns."""
    row["internal_links_count"] = str(_json_len(row.get("internal_links_json")))
    row["external_links_count"] = str(_json_len(row.get("external_links_json")))


# Canonical ordered column list for the Page Explorer UI. Must match
# RESULTS_FIELDS from storage/csv_writer.py exactly so the UI table
# renders all available columns.
COLUMNS: tuple[str, ...] = (
    "url",
    "status_code",
    "status",
    "title",
    "word_count",
    "response_time_ms",
    "content_type",
    "error_type",
    "error_message",
    "subdomain",
    "page_type",
    "category_key",
    "from_sitemap",
    "indexed_status",
    "pagespeed_score",
    "lcp_ms",
    "cls",
    "inp_ms",
    # On-page outbound link counts derived from *_links_json (see
    # _stamp_link_counts). "internal" = links to the same host;
    # "external" = links off-site.
    "internal_links_count",
    "external_links_count",
)

# Columns that should sort numerically rather than lexicographically.
_NUMERIC_COLS: frozenset[str] = frozenset({
    "word_count", "response_time_ms", "pagespeed_score",
    "lcp_ms", "inp_ms", "status_code",
    "internal_links_count", "external_links_count",
})
_FLOAT_COLS: frozenset[str] = frozenset({"cls"})


@dataclass(frozen=True)
class _Filters:
    """Resolved filter parameters; built once per request."""
    status: set[str] | None
    subdomain: set[str] | None
    page_type: set[str] | None
    indexed: set[str] | None
    has_psi: bool | None
    q: str | None


def _split_csv(value: str | None) -> set[str] | None:
    if not value:
        return None
    items = {v.strip() for v in value.split(",") if v.strip()}
    return items or None


def _bool_or_none(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_filters(params: dict) -> _Filters:
    return _Filters(
        status=_split_csv(params.get("status")),
        subdomain=_split_csv(params.get("subdomain")),
        page_type=_split_csv(params.get("page_type")),
        indexed=_split_csv(params.get("indexed")),
        has_psi=_bool_or_none(params.get("has_psi")),
        q=(params.get("q") or "").strip().lower() or None,
    )


def _row_matches(row: dict, f: _Filters) -> bool:
    if f.status and (row.get("status_code") or "") not in f.status:
        return False
    if f.subdomain and (row.get("subdomain") or "") not in f.subdomain:
        return False
    if f.page_type and (row.get("page_type") or "") not in f.page_type:
        return False
    if f.indexed and (row.get("indexed_status") or "unknown") not in f.indexed:
        return False
    if f.has_psi is not None:
        has = bool((row.get("pagespeed_score") or "").strip())
        if has != f.has_psi:
            return False
    if f.q:
        haystack = f"{row.get('url') or ''} {row.get('title') or ''}".lower()
        if f.q not in haystack:
            return False
    return True


def _sort_key(row: dict, column: str):
    """Return a sort-safe value: numeric columns coerce to int/float;
    blanks sort last regardless of direction (we use a tuple so a
    sentinel high value applies to missing data)."""
    raw = (row.get(column) or "").strip()
    if not raw:
        # Missing data sorts last in ascending order; sort direction
        # is applied by the caller via reverse=True.
        if column in _NUMERIC_COLS:
            return (1, 0)
        if column in _FLOAT_COLS:
            return (1, 0.0)
        return (1, "")
    if column in _NUMERIC_COLS:
        try:
            return (0, int(raw))
        except ValueError:
            return (1, 0)
    if column in _FLOAT_COLS:
        try:
            return (0, float(raw))
        except ValueError:
            return (1, 0.0)
    return (0, raw.lower())


# ── In-process cache keyed by CSV mtime ────────────────────────────────
#
# 10k-row reads via repository.read_csv take ~250-400 ms on warm disk.
# We cache the materialised dict-rows keyed by file mtime so back-to-
# back paginated requests hit the cache. Invalidates automatically on
# the next crawl (file mtime changes) without manual coordination.

_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _load_rows() -> list[dict]:
    """Source-routed page row loader.

    Phase 3c routing:
      * ``settings.engine == 'scrapy'`` AND a completed CrawlSnapshot
        exists → read CrawlerPageResult rows from Postgres. Sub-100 ms
        on 10k rows thanks to the (snapshot, …) composite indexes.
      * Otherwise (default) → read crawl_results.csv as before (with
        the in-process mtime cache).
    """
    if (getattr(settings, "engine", "legacy") == "scrapy"):
        orm_rows = _load_rows_from_orm()
        if orm_rows is not None:
            return orm_rows

    path = settings.data_path / "crawl_results.csv"
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    cached = _CACHE.get("results")
    if cached and cached[0] == mtime:
        return cached[1]

    payload = repo.read_csv("results")
    headers = payload.get("headers") or []
    rows: list[dict] = []
    for r in payload.get("rows") or []:
        if not r:
            continue
        if len(r) < len(headers):
            r = list(r) + [""] * (len(headers) - len(r))
        row = dict(zip(headers, r))
        _stamp_link_counts(row)
        rows.append(row)
    _CACHE["results"] = (mtime, rows)
    return rows


def _load_rows_from_orm() -> list[dict] | None:
    """Load CrawlerPageResult rows from the latest completed snapshot
    and re-shape them into the dict-of-strings format the detectors
    + Page Explorer expect (matches the CSV row schema 1:1).

    Returns ``None`` when no snapshot exists / Postgres unreachable
    so the caller can fall back to CSV silently.
    """
    try:
        from .snapshot import latest_completed_snapshot_id
        from ..models import CrawlerPageResult
        snap_id = latest_completed_snapshot_id()
        if not snap_id:
            return None
        qs = CrawlerPageResult.objects.filter(snapshot_id=snap_id).only(
            "url", "status_code", "status", "title", "word_count",
            "response_time_ms", "content_type", "error_type",
            "error_message", "subdomain", "page_type", "category_key",
            "from_sitemap", "indexed_status",
            "pagespeed_score", "lcp_ms", "cls", "inp_ms",
            "internal_links_json", "external_links_json",
        )
        out: list[dict] = []
        for p in qs.iterator(chunk_size=1000):
            out.append({
                "url": p.url,
                "status_code": p.status_code or "",
                "status": p.status or "",
                "title": p.title or "",
                "word_count": str(p.word_count or 0),
                "response_time_ms": str(p.response_time_ms or 0),
                "content_type": p.content_type or "",
                "error_type": p.error_type or "",
                "error_message": p.error_message or "",
                "subdomain": p.subdomain or "",
                "page_type": p.page_type or "",
                "category_key": p.category_key or "",
                "from_sitemap": "1" if p.from_sitemap else "0",
                "indexed_status": p.indexed_status or "unknown",
                "pagespeed_score": "" if p.pagespeed_score is None else str(p.pagespeed_score),
                "lcp_ms": "" if p.lcp_ms is None else str(p.lcp_ms),
                "cls": "" if p.cls is None else str(p.cls),
                "inp_ms": "" if p.inp_ms is None else str(p.inp_ms),
                "internal_links_count": str(_json_len(p.internal_links_json)),
                "external_links_count": str(_json_len(p.external_links_json)),
            })
        return out
    except Exception:  # noqa: BLE001
        return None


# ── Public query API ───────────────────────────────────────────────────


def query(
    *,
    params: dict | None = None,
    sort: str = "url",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Execute a Page Explorer query and return a paginated payload.

    ``params`` may contain any of the filter keys above. Bad sort
    columns fall back to ``url`` ascending; bad limit/offset are
    clamped to the valid range.
    """
    p = params or {}
    filters = _parse_filters(p)

    # Resolve sort column + direction.
    requested = (sort or "url").strip()
    reverse = requested.startswith("-")
    column = requested.lstrip("-")
    if column not in COLUMNS:
        column = "url"
        reverse = False

    try:
        lim = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        lim = 50
    try:
        off = max(0, int(offset))
    except (TypeError, ValueError):
        off = 0

    rows = _load_rows()
    matched = [r for r in rows if _row_matches(r, filters)]
    matched.sort(key=lambda r: _sort_key(r, column), reverse=reverse)
    sliced = matched[off : off + lim]

    return {
        "total": len(matched),
        "returned": len(sliced),
        "limit": lim,
        "offset": off,
        "sort": ("-" if reverse else "") + column,
        "rows": [
            {col: (r.get(col) or "") for col in COLUMNS} for r in sliced
        ],
        "columns": list(COLUMNS),
    }


def facets() -> dict:
    """Return distinct values for the filterable enum columns so the
    UI can populate dropdowns without a separate sweep over the CSV."""
    rows = _load_rows()
    out: dict[str, list[str]] = {
        "status_code": sorted({(r.get("status_code") or "").strip() for r in rows if r.get("status_code")}),
        "subdomain":  sorted({(r.get("subdomain") or "").strip() for r in rows if r.get("subdomain")}),
        "page_type":  sorted({(r.get("page_type") or "").strip() for r in rows if r.get("page_type")}),
        "indexed_status": sorted({(r.get("indexed_status") or "unknown") for r in rows}),
    }
    # Strip empties.
    return {k: [v for v in vs if v] for k, vs in out.items()}
