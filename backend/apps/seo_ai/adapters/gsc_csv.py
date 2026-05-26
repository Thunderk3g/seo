"""Google Search Console CSV adapter — full surface.

Reads the per-site CSVs produced by ``backend/scripts/gsc_pull.py`` plus
the manual UI export under ``coverage/_gsc_export_*/``. The Search
Console API output is one CSV per ``(search_type × dimension_set)`` —
the adapter exposes every shape we actually have on disk so the
dashboard can render the full data set without a second pull.

The adapter is **purely file-backed**. It never issues live API calls
— refreshing the data is the ``gsc_pull.py`` script's responsibility.
This separation lets us serve the dashboard even when GSC access is
temporarily frozen (operator-level OAuth revoked, key rotated, etc.)
— the cached CSVs are still the source of truth.

Public surface — overview:

    GSCCSVAdapter(site_dirname="www.bajajlifeinsurance.com")
      Single-dimension readers (rows newest-clicks-first by default):
        .queries(limit)              -> list[GSCQueryRow]
        .pages(limit)                -> list[GSCPageRow]
        .countries(limit)            -> list[GSCCountryRow]
        .devices()                   -> list[GSCDeviceRow]
        .daily(limit)                -> list[GSCDateRow]
        .search_appearances()        -> list[GSCSearchAppearanceRow]
      Two-dimension readers:
        .query_country(limit)        -> list[GSCQueryCountryRow]
        .query_device(limit)         -> list[GSCQueryDeviceRow]
        .page_country(limit)         -> list[GSCPageCountryRow]
        .page_device(limit)          -> list[GSCPageDeviceRow]
        .date_country(limit)         -> list[GSCDateCountryRow]
        .date_device(limit)          -> list[GSCDateDeviceRow]
      Image-search variants (same shapes, "image_" prefix on accessors).
      Aggregates:
        .summary(sample_size)        -> GSCSummary (web-search rollup)
        .branded_split()             -> GSCBrandedSplit
        .indexation_report()         -> GSCIndexationReport (manual UI export)
        .sitemaps()                  -> list[GSCSitemapRow]
        .available_files()           -> dict[str, int]   # filename -> row_count

Industry CTR curve is shared (``_expected_ctr``) so underperforming-
query detection stays consistent across surfaces.
"""
from __future__ import annotations

import csv
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from django.conf import settings

logger = logging.getLogger("seo.ai.adapters.gsc")

# A handful of pulled CSVs exceed Python's default 128KB field limit
# (e.g. URLs encoded with multiple query strings) — same posture as the
# crawler's repository reader.
csv.field_size_limit(sys.maxsize)


# ── shared dataclasses ───────────────────────────────────────────────────


@dataclass
class GSCQueryRow:
    query: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCPageRow:
    page: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCCountryRow:
    country: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCDeviceRow:
    device: str       # MOBILE / DESKTOP / TABLET
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCDateRow:
    date: str         # YYYY-MM-DD
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCSearchAppearanceRow:
    """One row per rich-result type GSC categorised our pages under.

    Common values: ``REVIEW_SNIPPET``, ``FAQ``, ``HOW_TO``, ``VIDEO``,
    ``TRANSLATED_RESULT``, ``WEB_LIGHT``. Empty CSV means Google isn't
    recognising any rich-result types on our pages.
    """
    search_appearance: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCQueryCountryRow:
    query: str
    country: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCQueryDeviceRow:
    query: str
    device: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCPageCountryRow:
    page: str
    country: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCPageDeviceRow:
    page: str
    device: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCDateCountryRow:
    date: str
    country: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCDateDeviceRow:
    date: str
    device: str
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass
class GSCSummary:
    """Web-search rollup. Numbers are over the full GSC retention window."""

    total_queries: int
    total_pages: int
    total_clicks: int
    total_impressions: int
    avg_ctr: float
    avg_position: float
    top_queries_by_clicks: list[GSCQueryRow]
    underperforming_queries: list[GSCQueryRow]
    high_impression_low_click_queries: list[GSCQueryRow]
    top_pages_by_clicks: list[GSCPageRow]
    snapshot_path: str


@dataclass
class GSCBrandedSplit:
    """Branded vs unbranded breakdown of web__query.csv.

    Critical KPI for "are we earning new traffic?" — if branded clicks
    massively dominate, we're invisible for non-brand queries.
    """
    branded_queries: int
    unbranded_queries: int
    branded_clicks: int
    unbranded_clicks: int
    branded_impressions: int
    unbranded_impressions: int
    branded_avg_position: float
    unbranded_avg_position: float
    branded_ratio_clicks: float     # branded / total clicks
    branded_ratio_queries: float
    tokens: list[str]               # the brand tokens used for matching
    top_unbranded_queries: list[GSCQueryRow]


@dataclass
class GSCSitemapRow:
    """One submitted sitemap, as returned by ``sitemaps.list``."""
    path: str
    last_submitted: str
    last_downloaded: str
    is_pending: bool
    is_sitemaps_index: bool
    sitemap_type: str
    warnings: int
    errors: int
    contents: list[dict]            # [{type, submitted, indexed}]


@dataclass
class GSCIndexationIssue:
    """One row from the manual UI export's ``Critical issues.csv`` /
    ``Non-critical issues.csv``."""
    reason: str
    source: str               # "Website" / "Google systems"
    validation: str           # "Failed" / "Not Started" / "Passed" / "N/A"
    pages: int


@dataclass
class GSCIndexationChartPoint:
    """One day from the manual UI export's ``Chart.csv``."""
    date: str
    not_indexed: int
    indexed: int
    impressions: int


@dataclass
class GSCIndexationReport:
    """Manual GSC UI export (Indexing → Pages → Export).

    Sat under ``backend/data/gsc/coverage/_gsc_export_*/``. The
    public API can't produce these counts at the same fidelity — the
    manual export is the source of truth for ``Crawled but not
    indexed``, ``Duplicate, Google chose different canonical``, etc.
    """
    export_dir: str
    critical_issues: list[GSCIndexationIssue]
    noncritical_issues: list[GSCIndexationIssue]
    chart: list[GSCIndexationChartPoint]
    latest_indexed: int
    latest_not_indexed: int
    latest_impressions: int
    metadata: dict


# ── adapter ──────────────────────────────────────────────────────────────


class GSCCSVAdapter:
    """Read-only access to the GSC CSV directory.

    ``site_url`` matches the directory name produced by
    ``gsc_pull.safe_name`` — typically ``www.bajajlifeinsurance.com``.
    """

    def __init__(
        self,
        root_dir: Path | str | None = None,
        *,
        site_dirname: str = "www.bajajlifeinsurance.com",
        brand_tokens: Iterable[str] | None = None,
    ) -> None:
        self.root_dir = (
            Path(root_dir) if root_dir else settings.SEO_AI["gsc_data_dir"]
        )
        self.site_dir = self.root_dir / site_dirname
        # Brand tokens drive the branded/unbranded split. We sniff
        # settings for the new/old/parent lists so the same source of
        # truth as the brand_mentions adapter is used here.
        if brand_tokens is not None:
            self.brand_tokens = [t.lower() for t in brand_tokens if t]
        else:
            cfg = getattr(settings, "BRAND_MENTIONS", None) or {}
            tokens: list[str] = []
            for key in ("brand_tokens_new", "brand_tokens_old", "brand_tokens_parent"):
                for t in (cfg.get(key) or []):
                    if t and isinstance(t, str):
                        tokens.append(t.lower())
            if not tokens:
                tokens = [
                    "bajaj life insurance",
                    "bajaj life",
                    "bajaj allianz life insurance",
                    "bajaj allianz life",
                    "bajaj allianz",
                    "bajaj",
                ]
            self.brand_tokens = tokens

    def _path(self, name: str) -> Path:
        return self.site_dir / name

    # ── readers, web search ───────────────────────────────────────────

    def queries(self, *, limit: int | None = None) -> list[GSCQueryRow]:
        return _read_csv(
            self._path("web__query.csv"),
            ["query"], GSCQueryRow, limit,
        )

    def pages(self, *, limit: int | None = None) -> list[GSCPageRow]:
        return _read_csv(
            self._path("web__page.csv"),
            ["page"], GSCPageRow, limit,
        )

    def countries(self, *, limit: int | None = None) -> list[GSCCountryRow]:
        return _read_csv(
            self._path("web__country.csv"),
            ["country"], GSCCountryRow, limit,
        )

    def devices(self) -> list[GSCDeviceRow]:
        return _read_csv(
            self._path("web__device.csv"),
            ["device"], GSCDeviceRow, None,
        )

    def daily(self, *, limit: int | None = None) -> list[GSCDateRow]:
        rows = _read_csv(
            self._path("web__date.csv"),
            ["date"], GSCDateRow, None,
        )
        rows.sort(key=lambda r: r.date)
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        return rows

    def search_appearances(self) -> list[GSCSearchAppearanceRow]:
        return _read_csv(
            self._path("web__searchAppearance.csv"),
            ["searchAppearance"], GSCSearchAppearanceRow, None,
        )

    def query_country(self, *, limit: int | None = 500) -> list[GSCQueryCountryRow]:
        return _read_csv(
            self._path("web__query_country.csv"),
            ["query", "country"], GSCQueryCountryRow, limit,
        )

    def query_device(self, *, limit: int | None = 500) -> list[GSCQueryDeviceRow]:
        return _read_csv(
            self._path("web__query_device.csv"),
            ["query", "device"], GSCQueryDeviceRow, limit,
        )

    def page_country(self, *, limit: int | None = 500) -> list[GSCPageCountryRow]:
        return _read_csv(
            self._path("web__page_country.csv"),
            ["page", "country"], GSCPageCountryRow, limit,
        )

    def page_device(self, *, limit: int | None = 500) -> list[GSCPageDeviceRow]:
        return _read_csv(
            self._path("web__page_device.csv"),
            ["page", "device"], GSCPageDeviceRow, limit,
        )

    def date_country(self, *, limit: int | None = None) -> list[GSCDateCountryRow]:
        rows = _read_csv(
            self._path("web__date_country.csv"),
            ["date", "country"], GSCDateCountryRow, None,
        )
        rows.sort(key=lambda r: r.date)
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        return rows

    def date_device(self, *, limit: int | None = None) -> list[GSCDateDeviceRow]:
        rows = _read_csv(
            self._path("web__date_device.csv"),
            ["date", "device"], GSCDateDeviceRow, None,
        )
        rows.sort(key=lambda r: r.date)
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        return rows

    # ── readers, image search ─────────────────────────────────────────
    # Bajaj actually ranks in Google Images ("bajaj life logo" → pos
    # 5.8). Same shapes as web; method names prefixed image_ to keep
    # the two surfaces distinct.

    def image_queries(self, *, limit: int | None = None) -> list[GSCQueryRow]:
        return _read_csv(
            self._path("image__query.csv"),
            ["query"], GSCQueryRow, limit,
        )

    def image_pages(self, *, limit: int | None = None) -> list[GSCPageRow]:
        return _read_csv(
            self._path("image__page.csv"),
            ["page"], GSCPageRow, limit,
        )

    def image_countries(self, *, limit: int | None = None) -> list[GSCCountryRow]:
        return _read_csv(
            self._path("image__country.csv"),
            ["country"], GSCCountryRow, limit,
        )

    def image_devices(self) -> list[GSCDeviceRow]:
        return _read_csv(
            self._path("image__device.csv"),
            ["device"], GSCDeviceRow, None,
        )

    def image_daily(self, *, limit: int | None = None) -> list[GSCDateRow]:
        rows = _read_csv(
            self._path("image__date.csv"),
            ["date"], GSCDateRow, None,
        )
        rows.sort(key=lambda r: r.date)
        if limit and len(rows) > limit:
            rows = rows[-limit:]
        return rows

    # ── readers, other surfaces (mostly empty for Bajaj but exposed) ─

    def news_daily(self) -> list[GSCDateRow]:
        rows = _read_csv(
            self._path("news__date.csv"),
            ["date"], GSCDateRow, None,
        )
        rows.sort(key=lambda r: r.date)
        return rows

    def discover_daily(self) -> list[GSCDateRow]:
        rows = _read_csv(
            self._path("discover__date.csv"),
            ["date"], GSCDateRow, None,
        )
        rows.sort(key=lambda r: r.date)
        return rows

    def video_daily(self) -> list[GSCDateRow]:
        rows = _read_csv(
            self._path("video__date.csv"),
            ["date"], GSCDateRow, None,
        )
        rows.sort(key=lambda r: r.date)
        return rows

    def google_news_daily(self) -> list[GSCDateRow]:
        rows = _read_csv(
            self._path("googleNews__date.csv"),
            ["date"], GSCDateRow, None,
        )
        rows.sort(key=lambda r: r.date)
        return rows

    # ── aggregates ────────────────────────────────────────────────────

    def summary(self, *, sample_size: int = 50) -> GSCSummary:
        queries = self.queries()
        pages = self.pages()
        total_clicks = sum(q.clicks for q in queries)
        total_impr = sum(q.impressions for q in queries)
        avg_ctr = (total_clicks / total_impr) if total_impr else 0.0
        avg_pos = (
            sum(q.position * q.impressions for q in queries) / total_impr
            if total_impr
            else 0.0
        )

        top_clicks = sorted(queries, key=lambda r: r.clicks, reverse=True)[:sample_size]

        underperforming = [
            q
            for q in queries
            if 4.0 <= q.position <= 15.0
            and q.impressions >= 500
            and q.ctr < _expected_ctr(q.position) * 0.6
        ]
        underperforming.sort(key=lambda r: r.impressions, reverse=True)

        hi_imp_low_clk = [
            q
            for q in queries
            if q.impressions >= 1000 and q.clicks <= max(2, int(q.impressions * 0.005))
        ]
        hi_imp_low_clk.sort(key=lambda r: r.impressions, reverse=True)

        top_pages = sorted(pages, key=lambda r: r.clicks, reverse=True)[:sample_size]

        return GSCSummary(
            total_queries=len(queries),
            total_pages=len(pages),
            total_clicks=total_clicks,
            total_impressions=total_impr,
            avg_ctr=avg_ctr,
            avg_position=avg_pos,
            top_queries_by_clicks=top_clicks,
            underperforming_queries=underperforming[:sample_size],
            high_impression_low_click_queries=hi_imp_low_clk[:sample_size],
            top_pages_by_clicks=top_pages,
            snapshot_path=str(self.site_dir),
        )

    def branded_split(self, *, sample_size: int = 50) -> GSCBrandedSplit:
        """Aggregate web__query.csv into branded vs unbranded buckets.

        A query is branded iff any brand_token appears in it
        (case-insensitive, substring match). Top unbranded queries are
        returned so the operator can act on them.
        """
        queries = self.queries()
        tokens = self.brand_tokens
        branded: list[GSCQueryRow] = []
        unbranded: list[GSCQueryRow] = []
        for q in queries:
            qlow = (q.query or "").lower()
            if any(tok in qlow for tok in tokens):
                branded.append(q)
            else:
                unbranded.append(q)

        def _agg(rows: list[GSCQueryRow]):
            tc = sum(r.clicks for r in rows)
            ti = sum(r.impressions for r in rows)
            avg_pos = (
                sum(r.position * r.impressions for r in rows) / ti if ti else 0.0
            )
            return tc, ti, avg_pos

        bc, bi, bpos = _agg(branded)
        uc, ui, upos = _agg(unbranded)
        total_clicks = bc + uc
        total_queries = len(branded) + len(unbranded)
        top_unbranded = sorted(unbranded, key=lambda r: r.clicks, reverse=True)[:sample_size]
        return GSCBrandedSplit(
            branded_queries=len(branded),
            unbranded_queries=len(unbranded),
            branded_clicks=bc,
            unbranded_clicks=uc,
            branded_impressions=bi,
            unbranded_impressions=ui,
            branded_avg_position=bpos,
            unbranded_avg_position=upos,
            branded_ratio_clicks=(bc / total_clicks) if total_clicks else 0.0,
            branded_ratio_queries=(len(branded) / total_queries) if total_queries else 0.0,
            tokens=tokens,
            top_unbranded_queries=top_unbranded,
        )

    def indexation_report(self) -> GSCIndexationReport | None:
        """Parse the latest manual UI export under coverage/_gsc_export_*.

        Returns None when no manual export exists. The export folder is
        chosen by lexical sort on name (date-stamped suffix).
        """
        coverage_root = self.root_dir / "coverage"
        if not coverage_root.exists():
            return None
        exports = sorted(
            [p for p in coverage_root.iterdir() if p.is_dir() and p.name.startswith("_gsc_export")],
            key=lambda p: p.name,
        )
        if not exports:
            return None
        latest = exports[-1]

        critical = _read_issues_csv(latest / "Critical issues.csv")
        noncritical = _read_issues_csv(latest / "Non-critical issues.csv")
        chart = _read_chart_csv(latest / "Chart.csv")
        metadata = _read_metadata_csv(latest / "Metadata.csv")

        latest_idx = latest_not = latest_impr = 0
        if chart:
            tail = chart[-1]
            latest_idx = tail.indexed
            latest_not = tail.not_indexed
            latest_impr = tail.impressions

        return GSCIndexationReport(
            export_dir=str(latest),
            critical_issues=critical,
            noncritical_issues=noncritical,
            chart=chart,
            latest_indexed=latest_idx,
            latest_not_indexed=latest_not,
            latest_impressions=latest_impr,
            metadata=metadata,
        )

    def sitemaps(self) -> list[GSCSitemapRow]:
        """Submitted sitemaps from the cached sitemaps.json."""
        path = self._path("sitemaps.json")
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("gsc sitemaps.json read failed: %s", exc)
            return []
        out: list[GSCSitemapRow] = []
        for s in data or []:
            try:
                out.append(GSCSitemapRow(
                    path=s.get("path", ""),
                    last_submitted=s.get("lastSubmitted", "") or "",
                    last_downloaded=s.get("lastDownloaded", "") or "",
                    is_pending=bool(s.get("isPending")),
                    is_sitemaps_index=bool(s.get("isSitemapsIndex")),
                    sitemap_type=s.get("type", "") or "",
                    warnings=int(s.get("warnings") or 0),
                    errors=int(s.get("errors") or 0),
                    contents=list(s.get("contents") or []),
                ))
            except (TypeError, ValueError):
                continue
        return out

    # ── meta ──────────────────────────────────────────────────────────

    def available_files(self) -> dict[str, int]:
        """Inventory of every CSV under the site dir → row count.

        Used by the dashboard's "data audit" panel so the operator can
        see exactly which slices have data and which are empty.
        """
        out: dict[str, int] = {}
        if not self.site_dir.exists():
            return out
        for p in sorted(self.site_dir.glob("*.csv")):
            try:
                # -1 to discount the header row; min 0 to be safe.
                n = max(0, sum(1 for _ in p.open("r", encoding="utf-8")) - 1)
            except OSError:
                n = 0
            out[p.name] = n
        return out


# ── helpers ──────────────────────────────────────────────────────────────


def _read_csv(
    path: Path,
    dim_fields: list[str],
    schema,
    limit: int | None,
):
    """Generic GSC CSV reader.

    ``dim_fields`` is the dimension column names in CSV order; metric
    columns are always (clicks, impressions, ctr, position). Returns a
    list of ``schema`` instances ordered as the file was written
    (GSC's natural ordering is clicks DESC for query/page surfaces).
    """
    if not path.exists():
        logger.debug("gsc csv missing: %s", path)
        return []
    out = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                kwargs = {}
                for dim in dim_fields:
                    val = row.get(dim, "") or ""
                    # The dataclass field names match the dim except
                    # for "searchAppearance" which becomes search_appearance.
                    field_name = (
                        "search_appearance"
                        if dim == "searchAppearance" else dim
                    )
                    kwargs[field_name] = val
                kwargs["clicks"] = int(float(row.get("clicks") or 0))
                kwargs["impressions"] = int(float(row.get("impressions") or 0))
                kwargs["ctr"] = float(row.get("ctr") or 0)
                kwargs["position"] = float(row.get("position") or 0)
                out.append(schema(**kwargs))
            except (KeyError, ValueError, TypeError):
                continue
            if limit and len(out) >= limit:
                break
    return out


def _read_issues_csv(path: Path) -> list[GSCIndexationIssue]:
    """Parse 'Critical issues.csv' / 'Non-critical issues.csv' from a
    manual UI export."""
    if not path.exists():
        return []
    out: list[GSCIndexationIssue] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pages = int(row.get("Pages") or 0)
            except (TypeError, ValueError):
                pages = 0
            out.append(GSCIndexationIssue(
                reason=(row.get("Reason") or "").strip(),
                source=(row.get("Source") or "").strip(),
                validation=(row.get("Validation") or "").strip(),
                pages=pages,
            ))
    return out


def _read_chart_csv(path: Path) -> list[GSCIndexationChartPoint]:
    """Parse 'Chart.csv' (Date, Not indexed, Indexed, Impressions)."""
    if not path.exists():
        return []
    out: list[GSCIndexationChartPoint] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                out.append(GSCIndexationChartPoint(
                    date=(row.get("Date") or "").strip(),
                    not_indexed=int(row.get("Not indexed") or 0),
                    indexed=int(row.get("Indexed") or 0),
                    impressions=int(row.get("Impressions") or 0),
                ))
            except (TypeError, ValueError):
                continue
    out.sort(key=lambda r: r.date)
    return out


def _read_metadata_csv(path: Path) -> dict:
    """Parse 'Metadata.csv' from a manual UI export — usually just a
    'Property,Url' header + one row of key/value pairs."""
    if not path.exists():
        return {}
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        keys = next(reader, [])
        for row in reader:
            entry = {}
            for i, k in enumerate(keys):
                entry[k.strip()] = (row[i] if i < len(row) else "").strip()
            rows.append(entry)
    if not rows:
        return {}
    if len(rows) == 1:
        return rows[0]
    return {"rows": rows}


# Industry CTR curve by SERP position (web, average across verticals).
# Used to flag rankings that under-click — i.e. the page is visible but
# the title/meta is not earning the clicks Google's traffic distribution
# would predict. Numbers are commonly cited Advanced Web Ranking 2024.
_CTR_CURVE: list[float] = [
    0.0,   # index 0 placeholder
    0.395, # pos 1
    0.184, # pos 2
    0.108, # pos 3
    0.073, # pos 4
    0.053, # pos 5
    0.040, # pos 6
    0.032, # pos 7
    0.026, # pos 8
    0.022, # pos 9
    0.019, # pos 10
    0.016, # pos 11
    0.014, # pos 12
    0.012, # pos 13
    0.010, # pos 14
    0.008, # pos 15
]


def _expected_ctr(position: float) -> float:
    """Linear-interpolated CTR for a (fractional) average position."""
    if position <= 1:
        return _CTR_CURVE[1]
    if position >= 15:
        return _CTR_CURVE[15]
    low = int(position)
    frac = position - low
    return _CTR_CURVE[low] * (1 - frac) + _CTR_CURVE[low + 1] * frac
