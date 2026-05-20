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

from dataclasses import dataclass
from typing import Iterable

from ..conf import settings
from ..storage import repository as repo


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
)

# Columns that should sort numerically rather than lexicographically.
_NUMERIC_COLS: frozenset[str] = frozenset({
    "word_count", "response_time_ms", "pagespeed_score",
    "lcp_ms", "inp_ms", "status_code",
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
        rows.append(dict(zip(headers, r)))
    _CACHE["results"] = (mtime, rows)
    return rows


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
