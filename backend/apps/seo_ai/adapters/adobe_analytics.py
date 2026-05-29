"""Adobe Analytics 2.0 adapter — OAuth S2S + report execution.

Wraps the Analytics 2.0 REST API behind a small dataclass surface so
the dashboard view and the chat tools both pull through the same
auth path. The Bajaj integration is a Server-to-Server OAuth client
(grant_type=client_credentials) — credentials live in env vars and
flow through :mod:`config.settings.base.ADOBE_ANALYTICS`.

Endpoints exercised:

  * ``POST /ims/token/v3``                — bearer token (24-hour TTL)
  * ``GET /collections/suites/{rsid}``    — report-suite metadata
  * ``GET /dimensions`` + ``GET /metrics`` — what we can query
  * ``POST /reports``                     — page-views by page,
                                            visits / orders / lead
                                            funnels — Workspace's
                                            full surface

Token caching: a single process-wide token is kept in memory until
its ``expires_in`` minus a 60-second safety margin elapses. The
adapter is fully reentrant — every public method checks the cache
and re-authenticates only when the token is missing or stale.

Failure model mirrors the GSC / SEMrush adapters:

  * Missing credentials → :class:`AdapterDisabledError`
  * Network / auth fail  → :class:`AdobeAnalyticsError`
  * Per-call API error  → :class:`AdobeAnalyticsError` (wraps the
                          server's response body for debugging)

The dashboard view always converts these into JSON ``{"available":
false, "error": "..."}`` responses so the UI renders an empty state
gracefully instead of 500-ing.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from django.conf import settings

# Corp MITM proxy support — same pattern the competitor crawler uses.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

logger = logging.getLogger("apps.seo_ai.adapters.adobe_analytics")


# ── exceptions ────────────────────────────────────────────────────────


class AdapterDisabledError(RuntimeError):
    """Raised at adapter init when credentials aren't configured.

    The dashboard view converts this into ``{"available": false,
    "reason": "not configured"}`` so the frontend shows the
    onboarding empty state.
    """


class AdobeAnalyticsError(RuntimeError):
    """Generic adapter failure — auth refused, network, 4xx/5xx, or
    malformed response. ``status_code`` is the HTTP code when
    available, else 0. ``body`` carries the truncated server response
    for support handoff."""

    def __init__(
        self, message: str, *, status_code: int = 0, body: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ── dataclasses returned to the view ──────────────────────────────────


@dataclass
class TopPageRow:
    """One row of the "top pages by page-views" report."""
    page: str
    page_views: int
    item_id: str = ""


@dataclass
class ReportSuiteInfo:
    """Slim summary of the configured report suite."""
    rsid: str
    name: str
    collection_item_type: str = ""


@dataclass
class DailyPoint:
    """One day in the trend chart — page-views + visits side by side."""
    date: str           # ISO yyyy-mm-dd
    page_views: int
    visits: int


@dataclass
class ChannelRow:
    """Marketing channel slice — Organic / Paid / Direct / Email / Social /
    Internal / Referring / Other."""
    channel: str
    visits: int
    share_pct: float


@dataclass
class EntryPageRow:
    """One entry page with engagement signals. Bounce rate is fraction
    (0–1); time_on_page_sec is float seconds."""
    page: str
    entries: int
    bounces: int
    bounce_rate: float
    time_on_page_sec: float
    item_id: str = ""


@dataclass
class GeoRow:
    """Top geo slice — country, region, or city depending on query."""
    label: str
    visits: int
    share_pct: float


@dataclass
class DeviceRow:
    """Mobile / Tablet / Desktop / Other split."""
    device_type: str
    visits: int
    share_pct: float


@dataclass
class SiteSectionRow:
    """Roll-up of pages into a named section (Products / Blog / etc)."""
    section: str
    page_views: int
    visits: int
    share_pct: float


@dataclass
class ExitPageRow:
    """Pages where visits end."""
    page: str
    exits: int
    exit_rate: float
    item_id: str = ""


@dataclass
class InternalSearchRow:
    """What users typed into our on-site search."""
    term: str
    instances: int
    item_id: str = ""


@dataclass
class HourRow:
    """Hour of day (0-23) usage profile."""
    hour: str
    visits: int
    share_pct: float


@dataclass
class WeekdayRow:
    """Day of week (Mon-Sun) usage profile."""
    weekday: str
    visits: int
    share_pct: float


@dataclass
class LangRow:
    """Language preference detected from browser."""
    language: str
    visits: int
    share_pct: float


@dataclass
class BrowserRow:
    """Browser breakdown — full name (Chrome 124) when available."""
    browser: str
    visits: int
    share_pct: float


@dataclass
class OSRow:
    os_name: str
    visits: int
    share_pct: float


@dataclass
class ResolutionRow:
    resolution: str
    visits: int
    share_pct: float


@dataclass
class ReferrerDomainRow:
    domain: str
    visits: int
    share_pct: float


@dataclass
class SearchEngineRow:
    engine: str
    visits: int
    share_pct: float


@dataclass
class NotFoundRow:
    """URLs that returned 404 / page-not-found according to Adobe's
    page-not-found tracking."""
    url: str
    instances: int


@dataclass
class LeadEventRow:
    """One distinct value of the configured lead-hash eVar with hit
    counts. Without knowing the exact custom event ID for "lead
    submitted", we surface the dimension itself so the operator can see
    which hashes showed up in the window."""
    hash_value: str
    occurrences: int


@dataclass
class CatalogueItem:
    """Slim view of a segment or calculated metric from the workspace
    catalogue. Used to populate dropdowns in the UI — the operator can
    later apply these to any report."""
    id: str
    name: str
    description: str = ""
    owner: str = ""
    type: str = ""
    is_calculated: bool = False


@dataclass
class AdobeDashboard:
    """End-to-end dashboard payload — what the UI needs in one round trip."""
    available: bool
    rsid: str
    global_company_id: str
    lookback_days: int
    report_suite: ReportSuiteInfo | None = None
    totals: dict = field(default_factory=dict)
    top_pages: list[TopPageRow] = field(default_factory=list)
    # Tier-1 additions (visits/timeseries/channels/entries/geo/devices)
    daily_trend: list[DailyPoint] = field(default_factory=list)
    channels: list[ChannelRow] = field(default_factory=list)
    entry_pages: list[EntryPageRow] = field(default_factory=list)
    countries: list[GeoRow] = field(default_factory=list)
    devices: list[DeviceRow] = field(default_factory=list)
    dimension_count: int = 0
    metric_count: int = 0
    error: str = ""
    # ── Tier 1-3 expansion (audience, engagement, behaviour, time,
    # tech, geo-depth, conversion, catalogue). Every field maps to one
    # report — the dashboard composer pulls each with cache fallback.
    visitors_summary: dict = field(default_factory=dict)
    site_sections: list[SiteSectionRow] = field(default_factory=list)
    exit_pages: list[ExitPageRow] = field(default_factory=list)
    internal_searches: list[InternalSearchRow] = field(default_factory=list)
    page_not_found: list[NotFoundRow] = field(default_factory=list)
    hours: list[HourRow] = field(default_factory=list)
    weekdays: list[WeekdayRow] = field(default_factory=list)
    yoy_daily_trend: list[DailyPoint] = field(default_factory=list)
    regions: list[GeoRow] = field(default_factory=list)
    cities: list[GeoRow] = field(default_factory=list)
    languages: list[LangRow] = field(default_factory=list)
    browsers: list[BrowserRow] = field(default_factory=list)
    operating_systems: list[OSRow] = field(default_factory=list)
    resolutions: list[ResolutionRow] = field(default_factory=list)
    channel_detail: list[ChannelRow] = field(default_factory=list)
    referrer_domains: list[ReferrerDomainRow] = field(default_factory=list)
    search_engines: list[SearchEngineRow] = field(default_factory=list)
    lead_events: list[LeadEventRow] = field(default_factory=list)
    segments: list[CatalogueItem] = field(default_factory=list)
    calculated_metrics: list[CatalogueItem] = field(default_factory=list)
    # Per-section freshness map. Keys match the JSON payload keys; values
    # are "live" / "cached" / "missing". When a section is cached, the
    # corresponding *_age_sec entry carries the cache age so the UI can
    # render "data from 14h ago" banners.
    data_freshness: dict = field(default_factory=dict)
    data_age_sec: dict = field(default_factory=dict)
    cached_sections_on_disk: dict = field(default_factory=dict)


# ── auth ──────────────────────────────────────────────────────────────


def _resolve_ssl_verify(raw: str) -> bool | str:
    value = (raw or "").strip()
    if not value or value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    if os.path.exists(value):
        return value
    return True


# Process-wide token cache. Guarded by a lock so the first call after
# server boot doesn't issue duplicate IMS requests if multiple
# requests land at once.
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, Any] = {"token": "", "expires_at": 0.0}


# Adobe-published canonical scopes for Analytics S2S integrations.
_OAUTH_SCOPES = ",".join([
    "openid",
    "AdobeID",
    "read_organizations",
    "additional_info.projectedProductContext",
    "additional_info.job_function",
    "additional_info.roles",
    "session",
])


# ── adapter ───────────────────────────────────────────────────────────


class AdobeAnalyticsAdapter:
    """Thin wrapper around the Analytics 2.0 REST API."""

    def __init__(self) -> None:
        cfg = getattr(settings, "ADOBE_ANALYTICS", None) or {}
        if not cfg.get("enabled"):
            raise AdapterDisabledError(
                "Adobe Analytics adapter disabled — set ADOBE_CLIENT_ID, "
                "ADOBE_CLIENT_SECRET, ADOBE_GLOBAL_COMPANY_ID, ADOBE_RSID "
                "in your .env."
            )
        # Hard-require every secret. The view path catches the raised
        # AdapterDisabledError and renders the onboarding state.
        for k in ("client_id", "client_secret", "global_company_id", "rsid"):
            if not cfg.get(k):
                raise AdapterDisabledError(f"ADOBE_{k.upper()} is empty")

        self.client_id: str = cfg["client_id"]
        self.client_secret: str = cfg["client_secret"]
        self.global_company_id: str = cfg["global_company_id"]
        self.rsid: str = cfg["rsid"]
        self.ims_token_url: str = cfg.get(
            "ims_token_url", "https://ims-na1.adobelogin.com/ims/token/v3",
        )
        self.analytics_base: str = cfg.get(
            "analytics_base", "https://analytics.adobe.io/api",
        )
        self.verify = _resolve_ssl_verify(cfg.get("ssl_verify", ""))
        if self.verify is False:
            try:
                import urllib3
                urllib3.disable_warnings(
                    urllib3.exceptions.InsecureRequestWarning
                )
            except Exception:  # noqa: BLE001
                pass

    # ── token cache ───────────────────────────────────────────────────

    def _token(self) -> str:
        with _TOKEN_LOCK:
            now = time.time()
            cached = _TOKEN_CACHE.get("token") or ""
            expires_at = float(_TOKEN_CACHE.get("expires_at") or 0)
            # Refresh 60 s before formal expiry to absorb clock skew.
            if cached and expires_at - 60 > now:
                return cached
            # Cache miss / stale — fetch a new one.
            token, expires_in = self._authenticate()
            _TOKEN_CACHE["token"] = token
            _TOKEN_CACHE["expires_at"] = now + max(expires_in - 60, 60)
            return token

    def _authenticate(self) -> tuple[str, int]:
        try:
            resp = requests.post(
                self.ims_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": _OAUTH_SCOPES,
                },
                timeout=30,
                verify=self.verify,
            )
        except requests.RequestException as exc:
            raise AdobeAnalyticsError(
                f"IMS auth network failure: {exc}",
                status_code=0,
            ) from exc
        if resp.status_code != 200:
            raise AdobeAnalyticsError(
                f"IMS auth refused (HTTP {resp.status_code})",
                status_code=resp.status_code,
                body=_truncate(resp.text, 500),
            )
        try:
            body = resp.json()
        except ValueError as exc:
            raise AdobeAnalyticsError(
                "IMS returned non-JSON response",
                status_code=resp.status_code,
                body=_truncate(resp.text, 500),
            ) from exc
        token = body.get("access_token") or ""
        if not token:
            raise AdobeAnalyticsError(
                "IMS response missing access_token",
                status_code=resp.status_code,
                body=str(body)[:500],
            )
        expires_in = int(body.get("expires_in") or 3600)
        logger.info(
            "adobe analytics: new IMS token issued, ttl=%ds",
            expires_in,
        )
        return token, expires_in

    # ── low-level helpers ─────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "x-api-key": self.client_id,
            "x-proxy-global-company-id": self.global_company_id,
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.analytics_base}/{self.global_company_id}{path}"
        try:
            resp = requests.get(
                url, headers=self._headers(), params=params or {},
                timeout=30, verify=self.verify,
            )
        except requests.RequestException as exc:
            raise AdobeAnalyticsError(
                f"GET {path} network failure: {exc}",
            ) from exc
        if resp.status_code != 200:
            raise AdobeAnalyticsError(
                f"GET {path} → HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=_truncate(resp.text, 500),
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise AdobeAnalyticsError(
                f"GET {path} returned non-JSON",
            ) from exc

    def _post(self, path: str, payload: dict) -> Any:
        url = f"{self.analytics_base}/{self.global_company_id}{path}"
        headers = {**self._headers(), "Content-Type": "application/json"}
        try:
            resp = requests.post(
                url, headers=headers, json=payload,
                timeout=60, verify=self.verify,
            )
        except requests.RequestException as exc:
            raise AdobeAnalyticsError(
                f"POST {path} network failure: {exc}",
            ) from exc
        # Adobe 2.0 sometimes returns 206 Partial Content with a valid
        # JSON body when some requested metrics aren't available for the
        # suite (it strips them and returns whatever IS available). Treat
        # that as success — the parser will see fewer columns and adapt.
        if resp.status_code not in (200, 206):
            raise AdobeAnalyticsError(
                f"POST {path} → HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=_truncate(resp.text, 500),
            )
        if resp.status_code == 206:
            logger.info(
                "adobe POST %s returned 206 — partial response (some "
                "metrics/dimensions stripped by the server)", path,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise AdobeAnalyticsError(
                f"POST {path} returned non-JSON",
            ) from exc

    # ── public ────────────────────────────────────────────────────────

    def report_suite(self) -> ReportSuiteInfo:
        data = self._get(f"/collections/suites/{self.rsid}")
        return ReportSuiteInfo(
            rsid=str(data.get("rsid") or self.rsid),
            name=str(data.get("name") or ""),
            collection_item_type=str(data.get("collectionItemType") or ""),
        )

    def dimensions(self, limit: int = 25) -> list[dict]:
        data = self._get("/dimensions", params={"rsid": self.rsid, "limit": limit})
        # API returns a flat list of dimension definitions.
        return data if isinstance(data, list) else []

    def metrics(self, limit: int = 25) -> list[dict]:
        data = self._get("/metrics", params={"rsid": self.rsid, "limit": limit})
        return data if isinstance(data, list) else []

    # ── range helper ──────────────────────────────────────────────────

    def _date_range(self, lookback_days: int) -> str:
        """Build the Adobe-format date-range string for the trailing N
        days, expressed in UTC. End is "today 00:00" so the range covers
        the last *N* complete days."""
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=lookback_days)).isoformat() + "T00:00:00.000"
        end = today.isoformat() + "T00:00:00.000"
        return f"{start}/{end}"

    def _report(
        self,
        *,
        dimension: str,
        metrics: list[str],
        lookback_days: int,
        limit: int = 50,
        statistics: list[str] | None = None,
    ) -> dict:
        """Run a single-dimension Analytics 2.0 report. Returns the raw
        JSON body so the per-method parser can pluck whatever fields it
        needs (totals + rows + summaryData)."""
        payload = {
            "rsid": self.rsid,
            "globalFilters": [
                {"type": "dateRange", "dateRange": self._date_range(lookback_days)},
            ],
            "metricContainer": {
                "metrics": [
                    {"columnId": str(i), "id": m} for i, m in enumerate(metrics)
                ],
            },
            "dimension": dimension,
            "settings": {
                "countRepeatInstances": True,
                "limit": int(limit),
                "page": 0,
                "nonesBehavior": "exclude-nones",
            },
        }
        if statistics:
            payload["statistics"] = {"functions": statistics}
        return self._post("/reports", payload)

    def top_pages(
        self,
        *,
        lookback_days: int = 7,
        limit: int = 25,
    ) -> tuple[list[TopPageRow], dict]:
        """Top N pages by page-views over the trailing window. Returns
        (rows, summary) where summary carries totals + min/max."""
        data = self._report(
            dimension="variables/page",
            metrics=["metrics/pageviews"],
            lookback_days=lookback_days,
            limit=limit,
            statistics=["col-max", "col-min"],
        )
        rows: list[TopPageRow] = []
        for r in (data.get("rows") or []):
            try:
                pv = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                pv = 0
            rows.append(TopPageRow(
                page=str(r.get("value") or ""),
                page_views=pv,
                item_id=str(r.get("itemId") or ""),
            ))
        summary = {
            "total_pages": int(data.get("totalElements") or 0),
            "filtered_total_views": _safe_first(
                (data.get("summaryData") or {}).get("filteredTotals")
            ),
            "total_views": _safe_first(
                (data.get("summaryData") or {}).get("totals")
            ),
            "col_max": _safe_first(
                (data.get("summaryData") or {}).get("col-max")
            ),
            "col_min": _safe_first(
                (data.get("summaryData") or {}).get("col-min")
            ),
        }
        return rows, summary

    def daily_trend(self, *, lookback_days: int = 30) -> list[DailyPoint]:
        """Page-views + visits per day over the trailing window. Drives
        the time-series chart at the top of AdobePage. ``lookback_days``
        is clamped to [1, 90] — Adobe's daterangeday dimension caps
        practically around 90 days for a single report call."""
        n = max(1, min(int(lookback_days), 90))
        data = self._report(
            dimension="variables/daterangeday",
            metrics=["metrics/pageviews", "metrics/visits"],
            lookback_days=n,
            limit=n + 1,
        )
        out: list[DailyPoint] = []
        for r in (data.get("rows") or []):
            value = str(r.get("value") or "")
            # Adobe returns the day label as a long form like
            # "May 14, 2026" — fall back to itemId-derived ISO when
            # possible. The api also includes "value" as "yyyy-mm-dd" in
            # some configs. Try to parse both.
            iso = _coerce_iso_date(value, r.get("itemId"))
            try:
                pv = int((r.get("data") or [0, 0])[0] or 0)
                vt = int((r.get("data") or [0, 0])[1] or 0)
            except (TypeError, ValueError, IndexError):
                pv, vt = 0, 0
            out.append(DailyPoint(date=iso or value, page_views=pv, visits=vt))
        # Adobe returns days in chronological order already; defensively
        # sort by ISO date in case the server flips the ordering.
        out.sort(key=lambda d: d.date)
        return out

    def marketing_channels(
        self, *, lookback_days: int = 7, limit: int = 15,
    ) -> list[ChannelRow]:
        """Visits per marketing channel. The dimension name differs
        slightly across implementations — Bajaj uses the standard
        ``variables/marketingchannel``. Falls back to an empty list if
        the dimension isn't available."""
        try:
            data = self._report(
                dimension="variables/marketingchannel",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("marketing_channels report failed: %s", exc)
            return []
        rows: list[ChannelRow] = []
        for r in (data.get("rows") or []):
            try:
                visits = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                visits = 0
            rows.append(ChannelRow(
                channel=str(r.get("value") or "Unknown"),
                visits=visits,
                share_pct=0.0,
            ))
        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    def entry_pages(
        self, *, lookback_days: int = 7, limit: int = 25,
    ) -> list[EntryPageRow]:
        """Top entry pages with bounce-rate + avg time-on-page. Joinable
        with CrawlerPageResult.url for the cross-source view."""
        data = self._report(
            dimension="variables/entrypage",
            metrics=[
                "metrics/entries",
                "metrics/bounces",
                "metrics/bouncerate",
                "metrics/averagetimespentonpage",
            ],
            lookback_days=lookback_days,
            limit=limit,
        )
        rows: list[EntryPageRow] = []
        for r in (data.get("rows") or []):
            d = r.get("data") or []
            try:
                entries = int(d[0] or 0) if len(d) > 0 else 0
                bounces = int(d[1] or 0) if len(d) > 1 else 0
                bounce_rate = float(d[2] or 0.0) if len(d) > 2 else 0.0
                time_on_page = float(d[3] or 0.0) if len(d) > 3 else 0.0
            except (TypeError, ValueError, IndexError):
                entries = bounces = 0
                bounce_rate = time_on_page = 0.0
            rows.append(EntryPageRow(
                page=str(r.get("value") or ""),
                entries=entries,
                bounces=bounces,
                bounce_rate=round(bounce_rate, 4),
                time_on_page_sec=round(time_on_page, 2),
                item_id=str(r.get("itemId") or ""),
            ))
        return rows

    def top_countries(
        self, *, lookback_days: int = 7, limit: int = 15,
    ) -> list[GeoRow]:
        """Top countries by visits."""
        try:
            data = self._report(
                dimension="variables/geocountry",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("top_countries report failed: %s", exc)
            return []
        rows: list[GeoRow] = []
        for r in (data.get("rows") or []):
            try:
                visits = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                visits = 0
            rows.append(GeoRow(
                label=str(r.get("value") or "Unknown"),
                visits=visits, share_pct=0.0,
            ))
        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    def device_split(
        self, *, lookback_days: int = 7, limit: int = 10,
    ) -> list[DeviceRow]:
        """Visits by Mobile / Tablet / Desktop / Other."""
        try:
            data = self._report(
                dimension="variables/mobiledevicetype",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("device_split report failed: %s", exc)
            return []
        rows: list[DeviceRow] = []
        for r in (data.get("rows") or []):
            try:
                visits = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                visits = 0
            rows.append(DeviceRow(
                device_type=str(r.get("value") or "Unknown"),
                visits=visits, share_pct=0.0,
            ))
        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    # ── Tier 1-3 additions ───────────────────────────────────────────
    # Generic dimensional/metric pulls. Each method matches one Adobe
    # report so the dashboard composer can wrap it with cache fallback
    # via apps.seo_ai.adapters.adobe_cache.try_or_cache.

    def visitors_summary(self, *, lookback_days: int = 7) -> dict:
        """Audience-volume rollup — visitors, unique visitors,
        avg time-on-site, pages-per-visit, bounce rate, exit count.

        Returns a flat dict so the UI can render it as a single KPI
        strip without parsing nested rows.
        """
        data = self._report(
            dimension="variables/daterangeday",
            metrics=[
                "metrics/visitors",
                "metrics/uniquevisitors",
                "metrics/averagetimespentonsite",
                "metrics/pagesperVisit",
                "metrics/bouncerate",
                "metrics/exits",
            ],
            lookback_days=lookback_days,
            limit=lookback_days + 1,
        )
        totals = (data.get("summaryData") or {}).get("totals") or []
        # totals is a list aligned with the metrics array. Some Adobe
        # rollups return averages, some sums — we just surface the value
        # and let the UI label it.
        return {
            "visitors": int(totals[0] or 0) if len(totals) > 0 else 0,
            "unique_visitors": int(totals[1] or 0) if len(totals) > 1 else 0,
            "avg_time_on_site_sec": round(float(totals[2] or 0), 2) if len(totals) > 2 else 0.0,
            "pages_per_visit": round(float(totals[3] or 0), 2) if len(totals) > 3 else 0.0,
            "bounce_rate": round(float(totals[4] or 0), 4) if len(totals) > 4 else 0.0,
            "exits": int(totals[5] or 0) if len(totals) > 5 else 0,
        }

    def site_sections(
        self, *, lookback_days: int = 7, limit: int = 15,
    ) -> list[SiteSectionRow]:
        """Roll-up of pages into named sections (Products / Blog /
        Calculators / About). Depends on a Launch rule setting
        ``variables/sitesection`` — falls back to empty if not
        instrumented."""
        try:
            data = self._report(
                dimension="variables/sitesection",
                metrics=["metrics/pageviews", "metrics/visits"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("site_sections report failed: %s", exc)
            return []
        rows: list[SiteSectionRow] = []
        for r in (data.get("rows") or []):
            d = r.get("data") or []
            try:
                pv = int(d[0] or 0) if len(d) > 0 else 0
                vt = int(d[1] or 0) if len(d) > 1 else 0
            except (TypeError, ValueError):
                pv, vt = 0, 0
            rows.append(SiteSectionRow(
                section=str(r.get("value") or "Unknown"),
                page_views=pv,
                visits=vt,
                share_pct=0.0,
            ))
        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    def exit_pages(
        self, *, lookback_days: int = 7, limit: int = 25,
    ) -> list[ExitPageRow]:
        """Pages where visits ended. Funnel-leak diagnostic."""
        try:
            data = self._report(
                dimension="variables/exitpage",
                metrics=["metrics/exits", "metrics/exitrate"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("exit_pages report failed: %s", exc)
            return []
        rows: list[ExitPageRow] = []
        for r in (data.get("rows") or []):
            d = r.get("data") or []
            try:
                exits = int(d[0] or 0) if len(d) > 0 else 0
                rate = float(d[1] or 0.0) if len(d) > 1 else 0.0
            except (TypeError, ValueError):
                exits, rate = 0, 0.0
            rows.append(ExitPageRow(
                page=str(r.get("value") or ""),
                exits=exits,
                exit_rate=round(rate, 4),
                item_id=str(r.get("itemId") or ""),
            ))
        return rows

    def internal_searches(
        self, *, lookback_days: int = 7, limit: int = 30,
    ) -> list[InternalSearchRow]:
        """Top on-site search terms. Best content-gap signal Adobe gives
        us — what users want that we apparently don't surface clearly.
        Tries both ``internalsearch`` and ``internalsearchterms``
        because the dimension name varies across implementations."""
        for dim in ("variables/internalsearchterm", "variables/internalsearchterms"):
            try:
                data = self._report(
                    dimension=dim,
                    metrics=["metrics/searches"],
                    lookback_days=lookback_days,
                    limit=limit,
                )
            except AdobeAnalyticsError as exc:
                logger.info("internal_searches[%s] failed: %s", dim, exc)
                continue
            rows: list[InternalSearchRow] = []
            for r in (data.get("rows") or []):
                try:
                    n = int((r.get("data") or [0])[0] or 0)
                except (TypeError, ValueError, IndexError):
                    n = 0
                rows.append(InternalSearchRow(
                    term=str(r.get("value") or ""),
                    instances=n,
                    item_id=str(r.get("itemId") or ""),
                ))
            if rows:
                return rows
        return []

    def page_not_found(
        self, *, lookback_days: int = 7, limit: int = 25,
    ) -> list[NotFoundRow]:
        """Adobe's tracked 404 / page-not-found URLs."""
        try:
            data = self._report(
                dimension="variables/pagesnotfound",
                metrics=["metrics/pageviews"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("page_not_found report failed: %s", exc)
            return []
        rows: list[NotFoundRow] = []
        for r in (data.get("rows") or []):
            try:
                n = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                n = 0
            rows.append(NotFoundRow(
                url=str(r.get("value") or ""),
                instances=n,
            ))
        return rows

    def hour_of_day(
        self, *, lookback_days: int = 7,
    ) -> list[HourRow]:
        """Hour-of-day visit distribution. ``variables/hour`` returns 0-23.

        On Bajaj's suite (and many others) ``variables/hour`` is gated
        behind an unauthorized_dimension_global error — the service
        account lacks per-dimension permission. Fall back to
        ``variables/daterangehour`` which exposes the same data via
        per-hour-per-day rows and rarely has the same permission lock.
        We aggregate the (HH, date) rows into 24 hour buckets.
        """
        rows: list[HourRow] = []
        had_error = False
        try:
            data = self._report(
                dimension="variables/hour",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=24,
            )
            cols = data.get("columns") or {}
            if cols.get("columnErrors"):
                had_error = True
                logger.info(
                    "hour_of_day: variables/hour blocked (%s) — falling "
                    "back to variables/daterangehour",
                    cols["columnErrors"][0].get("errorCode"),
                )
            else:
                for r in (data.get("rows") or []):
                    try:
                        n = int((r.get("data") or [0])[0] or 0)
                    except (TypeError, ValueError, IndexError):
                        n = 0
                    rows.append(HourRow(
                        hour=str(r.get("value") or ""),
                        visits=n,
                        share_pct=0.0,
                    ))
        except AdobeAnalyticsError as exc:
            logger.info("hour_of_day variables/hour failed: %s", exc)
            had_error = True

        if not rows or (had_error and not any(r.visits > 0 for r in rows)):
            rows = self._hour_of_day_from_daterangehour(
                lookback_days=lookback_days,
            )

        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    def _hour_of_day_from_daterangehour(
        self, *, lookback_days: int = 7,
    ) -> list[HourRow]:
        """Bucket daterangehour rows into 24 hour-of-day rows.

        daterangehour returns one row per (hour, date), with value like
        ``"11:00 2026-05-22"``. We parse the HH prefix and sum visits
        across dates so the operator sees a 24-row Mon-aligned bucket.
        """
        try:
            data = self._report(
                dimension="variables/daterangehour",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=max(200, lookback_days * 24),
            )
        except AdobeAnalyticsError as exc:
            logger.info(
                "hour_of_day daterangehour fallback failed: %s", exc,
            )
            return []
        buckets: dict[int, int] = {h: 0 for h in range(24)}
        for r in (data.get("rows") or []):
            val = str(r.get("value") or "")
            # Format "HH:00 YYYY-MM-DD" — the hour is the first 2 chars
            # before the colon. Defensive parse in case Adobe ever
            # changes the format.
            try:
                hh = int(val.split(":", 1)[0])
            except (ValueError, IndexError):
                continue
            if 0 <= hh <= 23:
                try:
                    n = int((r.get("data") or [0])[0] or 0)
                except (TypeError, ValueError, IndexError):
                    n = 0
                buckets[hh] += n
        return [
            HourRow(hour=f"{h:02d}", visits=buckets[h], share_pct=0.0)
            for h in range(24)
        ]

    def day_of_week(
        self, *, lookback_days: int = 30,
    ) -> list[WeekdayRow]:
        """Mon-Sun visit distribution. Bigger lookback (30 days) by
        default so each weekday gets ~4 data points.

        Falls back to deriving weekday buckets from ``daily_trend`` when
        Adobe's native ``variables/dayofweek`` returns nothing — which
        happens on suites where the tag setup doesn't populate
        ``s.dayofweek`` even though the date dimension itself works fine
        (Bajaj's suite behaves this way as of 2026-05). Operator still
        sees the breakdown they need without an admin permission ask.
        """
        try:
            data = self._report(
                dimension="variables/dayofweek",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=7,
            )
        except AdobeAnalyticsError as exc:
            logger.info("day_of_week native report failed: %s", exc)
            data = {}
        rows: list[WeekdayRow] = []
        for r in (data.get("rows") or []):
            try:
                n = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                n = 0
            rows.append(WeekdayRow(
                weekday=str(r.get("value") or ""),
                visits=n,
                share_pct=0.0,
            ))
        if rows and any(r.visits > 0 for r in rows):
            total = sum(r.visits for r in rows) or 1
            for r in rows:
                r.share_pct = round(100.0 * r.visits / total, 2)
            return rows

        # Native dimension empty → derive from daily_trend. We already
        # know that dimension works (the Overview chart renders).
        return self._day_of_week_from_daily_trend(lookback_days=lookback_days)

    def _day_of_week_from_daily_trend(
        self, *, lookback_days: int = 30,
    ) -> list[WeekdayRow]:
        """Bucket daily_trend visits by weekday — fallback for suites
        where the native variables/dayofweek dimension is empty."""
        from datetime import datetime

        try:
            daily = self.daily_trend(lookback_days=lookback_days)
        except Exception as exc:  # noqa: BLE001
            logger.info("day_of_week derived: daily_trend failed: %s", exc)
            return []
        if not daily:
            return []

        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday",
                    "Friday", "Saturday", "Sunday"]
        buckets = {w: 0 for w in weekdays}
        for pt in daily:
            try:
                dt = datetime.fromisoformat(str(pt.date))
            except (ValueError, TypeError):
                continue
            buckets[weekdays[dt.weekday()]] += int(pt.visits or 0)
        total = sum(buckets.values()) or 1
        return [
            WeekdayRow(
                weekday=w,
                visits=buckets[w],
                share_pct=round(100.0 * buckets[w] / total, 2),
            )
            for w in weekdays
        ]

    def year_over_year_trend(
        self, *, lookback_days: int = 30,
    ) -> list[DailyPoint]:
        """Daily series for the SAME window one year prior. The frontend
        overlays this on the current ``daily_trend`` for a YoY chart."""
        today = datetime.now(timezone.utc).date()
        # Anchor a year ago, then walk back lookback_days. Adobe's date
        # math wants explicit ISO timestamps.
        end = today.replace(year=today.year - 1).isoformat() + "T00:00:00.000"
        start = (
            (today.replace(year=today.year - 1)) - timedelta(days=lookback_days)
        ).isoformat() + "T00:00:00.000"
        payload = {
            "rsid": self.rsid,
            "globalFilters": [
                {"type": "dateRange", "dateRange": f"{start}/{end}"},
            ],
            "metricContainer": {
                "metrics": [
                    {"columnId": "0", "id": "metrics/pageviews"},
                    {"columnId": "1", "id": "metrics/visits"},
                ],
            },
            "dimension": "variables/daterangeday",
            "settings": {
                "countRepeatInstances": True,
                "limit": lookback_days + 1,
                "page": 0,
                "nonesBehavior": "exclude-nones",
            },
        }
        data = self._post("/reports", payload)
        out: list[DailyPoint] = []
        for r in (data.get("rows") or []):
            value = str(r.get("value") or "")
            iso = _coerce_iso_date(value, r.get("itemId"))
            try:
                pv = int((r.get("data") or [0, 0])[0] or 0)
                vt = int((r.get("data") or [0, 0])[1] or 0)
            except (TypeError, ValueError, IndexError):
                pv, vt = 0, 0
            out.append(DailyPoint(date=iso or value, page_views=pv, visits=vt))
        out.sort(key=lambda d: d.date)
        return out

    def regions(
        self, *, lookback_days: int = 7, limit: int = 30,
    ) -> list[GeoRow]:
        """Top state/region by visits. India-focused — picks up
        Maharashtra / Karnataka / Delhi / etc."""
        return self._dim_with_share(
            "variables/georegion", lookback_days=lookback_days, limit=limit,
        )

    def cities(
        self, *, lookback_days: int = 7, limit: int = 30,
    ) -> list[GeoRow]:
        """Top city by visits."""
        return self._dim_with_share(
            "variables/geocity", lookback_days=lookback_days, limit=limit,
        )

    def languages(
        self, *, lookback_days: int = 7, limit: int = 15,
    ) -> list[LangRow]:
        rows = self._dim_with_share(
            "variables/language", lookback_days=lookback_days, limit=limit,
        )
        return [LangRow(language=r.label, visits=r.visits, share_pct=r.share_pct) for r in rows]

    def browsers(
        self, *, lookback_days: int = 7, limit: int = 15,
    ) -> list[BrowserRow]:
        rows = self._dim_with_share(
            "variables/browser", lookback_days=lookback_days, limit=limit,
        )
        return [BrowserRow(browser=r.label, visits=r.visits, share_pct=r.share_pct) for r in rows]

    def operating_systems(
        self, *, lookback_days: int = 7, limit: int = 15,
    ) -> list[OSRow]:
        rows = self._dim_with_share(
            "variables/operatingsystem", lookback_days=lookback_days, limit=limit,
        )
        return [OSRow(os_name=r.label, visits=r.visits, share_pct=r.share_pct) for r in rows]

    def resolutions(
        self, *, lookback_days: int = 7, limit: int = 15,
    ) -> list[ResolutionRow]:
        rows = self._dim_with_share(
            "variables/monitorresolution", lookback_days=lookback_days, limit=limit,
        )
        return [ResolutionRow(resolution=r.label, visits=r.visits, share_pct=r.share_pct) for r in rows]

    def channel_detail(
        self, *, lookback_days: int = 7, limit: int = 25,
    ) -> list[ChannelRow]:
        """Sub-channel split — e.g. Organic → Google vs Bing."""
        try:
            data = self._report(
                dimension="variables/marketingchanneldetail",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("channel_detail report failed: %s", exc)
            return []
        rows: list[ChannelRow] = []
        for r in (data.get("rows") or []):
            try:
                visits = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                visits = 0
            rows.append(ChannelRow(
                channel=str(r.get("value") or "Unknown"),
                visits=visits,
                share_pct=0.0,
            ))
        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    def referrer_domains(
        self, *, lookback_days: int = 7, limit: int = 25,
    ) -> list[ReferrerDomainRow]:
        try:
            data = self._report(
                dimension="variables/referringdomain",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("referrer_domains report failed: %s", exc)
            return []
        rows: list[ReferrerDomainRow] = []
        for r in (data.get("rows") or []):
            try:
                visits = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                visits = 0
            rows.append(ReferrerDomainRow(
                domain=str(r.get("value") or "Unknown"),
                visits=visits,
                share_pct=0.0,
            ))
        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    def search_engines(
        self, *, lookback_days: int = 7, limit: int = 10,
    ) -> list[SearchEngineRow]:
        try:
            data = self._report(
                dimension="variables/searchengine",
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("search_engines report failed: %s", exc)
            return []
        rows: list[SearchEngineRow] = []
        for r in (data.get("rows") or []):
            try:
                visits = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                visits = 0
            rows.append(SearchEngineRow(
                engine=str(r.get("value") or "Unknown"),
                visits=visits,
                share_pct=0.0,
            ))
        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    def lead_events(
        self, *, lookback_days: int = 30, limit: int = 25,
    ) -> list[LeadEventRow]:
        """Distinct values of the configured lead-hash eVar. We don't
        know the exact custom event ID for "lead submitted" — surface
        the dimension itself so the operator sees which hashes appeared.

        Enabled only when ``ADOBE_LEAD_HASH_EVAR`` env is set; otherwise
        returns []. The env value can be either a bare evar number
        ("evar5") or the full dimension path ("variables/evar5").
        """
        cfg = getattr(settings, "ADOBE_ANALYTICS", None) or {}
        evar = (cfg.get("lead_hash_evar") or "").strip()
        if not evar:
            return []
        if not evar.startswith("variables/"):
            evar = f"variables/{evar}"
        try:
            data = self._report(
                dimension=evar,
                metrics=["metrics/occurrences"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("lead_events report failed: %s", exc)
            return []
        rows: list[LeadEventRow] = []
        for r in (data.get("rows") or []):
            try:
                n = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                n = 0
            rows.append(LeadEventRow(
                hash_value=str(r.get("value") or "")[:64],
                occurrences=n,
            ))
        return rows

    def list_segments(self, *, limit: int = 100) -> list[CatalogueItem]:
        """List segments the operator can apply to any report. Read-only
        view — applying them is a follow-up feature."""
        try:
            params = {"locale": "en_US", "limit": int(limit), "page": 0,
                      "rsids": self.rsid}
            data = self._get("/segments", params=params)
        except AdobeAnalyticsError as exc:
            logger.info("list_segments failed: %s", exc)
            return []
        out: list[CatalogueItem] = []
        for seg in (data.get("content") if isinstance(data, dict) else data) or []:
            out.append(CatalogueItem(
                id=str(seg.get("id") or ""),
                name=str(seg.get("name") or ""),
                description=str(seg.get("description") or "")[:240],
                owner=str((seg.get("owner") or {}).get("name") or seg.get("owner") or ""),
                type=str(seg.get("type") or ""),
                is_calculated=False,
            ))
        return out

    def list_calculated_metrics(self, *, limit: int = 100) -> list[CatalogueItem]:
        """List workspace calculated metrics so the UI can show what
        derived KPIs are already maintained by the analytics team."""
        try:
            params = {"locale": "en_US", "limit": int(limit), "page": 0,
                      "rsids": self.rsid}
            data = self._get("/calculatedmetrics", params=params)
        except AdobeAnalyticsError as exc:
            logger.info("list_calculated_metrics failed: %s", exc)
            return []
        out: list[CatalogueItem] = []
        for cm in (data.get("content") if isinstance(data, dict) else data) or []:
            out.append(CatalogueItem(
                id=str(cm.get("id") or ""),
                name=str(cm.get("name") or ""),
                description=str(cm.get("description") or "")[:240],
                owner=str((cm.get("owner") or {}).get("name") or cm.get("owner") or ""),
                type=str(cm.get("type") or ""),
                is_calculated=True,
            ))
        return out

    def _dim_with_share(
        self,
        dimension: str,
        *,
        lookback_days: int,
        limit: int,
    ) -> list[GeoRow]:
        """Generic helper for "dimension → visits + share_pct" reports.
        Returns GeoRow because the shape is identical to top_countries;
        callers that need a different dataclass map the result."""
        try:
            data = self._report(
                dimension=dimension,
                metrics=["metrics/visits"],
                lookback_days=lookback_days,
                limit=limit,
            )
        except AdobeAnalyticsError as exc:
            logger.info("%s report failed: %s", dimension, exc)
            return []
        rows: list[GeoRow] = []
        for r in (data.get("rows") or []):
            try:
                visits = int((r.get("data") or [0])[0] or 0)
            except (TypeError, ValueError, IndexError):
                visits = 0
            rows.append(GeoRow(
                label=str(r.get("value") or "Unknown"),
                visits=visits,
                share_pct=0.0,
            ))
        total = sum(r.visits for r in rows) or 1
        for r in rows:
            r.share_pct = round(100.0 * r.visits / total, 2)
        return rows

    def top_pages_with_visits(
        self, *, lookback_days: int = 30, limit: int = 100,
    ) -> list[dict]:
        """Top pages with both page-views AND visits — drives the SEO×
        Adobe cross-source join. Returns dicts (not dataclasses) so the
        join layer can mutate them with crawl + GSC enrichment fields
        in-place."""
        data = self._report(
            dimension="variables/page",
            metrics=["metrics/pageviews", "metrics/visits"],
            lookback_days=lookback_days,
            limit=limit,
        )
        out: list[dict] = []
        for r in (data.get("rows") or []):
            d = r.get("data") or []
            try:
                pv = int(d[0] or 0) if len(d) > 0 else 0
                vt = int(d[1] or 0) if len(d) > 1 else 0
            except (TypeError, ValueError, IndexError):
                pv, vt = 0, 0
            out.append({
                "page": str(r.get("value") or ""),
                "page_views": pv,
                "visits": vt,
                "item_id": str(r.get("itemId") or ""),
            })
        return out

    def dashboard(
        self,
        *,
        lookback_days: int | None = None,
        limit: int | None = None,
    ) -> AdobeDashboard:
        """One-shot dashboard payload — every Tier-1/2/3 report in a
        single round trip, each pull cached per-section to
        ``<DATA_DIR>/_adobe_cache/<rsid>/``.

        Failure semantics: if a section's live pull fails AND a cache
        file exists, we return the cached payload tagged "cached".
        If neither path yields data, the section is tagged "missing"
        and renders empty. ``data_freshness`` carries the per-section
        status so the UI can show "live" / "cached 14h ago" banners.

        Cache writes happen on every successful pull — so even when
        the token is alive today, tomorrow's outage still serves
        usable data.
        """
        from . import adobe_cache

        cfg = getattr(settings, "ADOBE_ANALYTICS", None) or {}
        if lookback_days is None:
            lookback_days = int(cfg.get("default_lookback_days", 7))
        if limit is None:
            limit = int(cfg.get("default_top_pages_limit", 25))

        out = AdobeDashboard(
            available=True,
            rsid=self.rsid,
            global_company_id=self.global_company_id,
            lookback_days=lookback_days,
        )

        # Each section is pulled with cache fallback. The first arg is
        # the cache key (lookback embedded so different windows don't
        # clobber each other).
        def _go(key_suffix: str, fetch):
            cache_key = f"{key_suffix}__{lookback_days}d"
            data, status, age = adobe_cache.try_or_cache(
                self.rsid, cache_key, fetch,
                lookback_days=lookback_days, limit=limit,
            )
            out.data_freshness[key_suffix] = status
            if age is not None:
                out.data_age_sec[key_suffix] = age
            return data

        # ── Suite metadata + capability ──────────────────────────────
        rs = _go("report_suite", self.report_suite)
        if isinstance(rs, dict):
            out.report_suite = ReportSuiteInfo(
                rsid=rs.get("rsid", self.rsid),
                name=rs.get("name", ""),
                collection_item_type=rs.get("collection_item_type", ""),
            )

        dims = _go("dimensions", lambda: self.dimensions(limit=500)) or []
        out.dimension_count = len(dims) if isinstance(dims, list) else 0

        mets = _go("metrics", lambda: self.metrics(limit=500)) or []
        out.metric_count = len(mets) if isinstance(mets, list) else 0

        # ── Original Tier-1 ─────────────────────────────────────────
        tp = _go(
            "top_pages",
            lambda: self.top_pages(lookback_days=lookback_days, limit=limit),
        )
        if isinstance(tp, list) and len(tp) == 2:
            # ``try_or_cache`` flattens the live (rows, summary) tuple
            # into a 2-element list; cache hits return the same shape.
            rows, summary = tp
            out.top_pages = [TopPageRow(**r) if isinstance(r, dict) else r for r in (rows or [])]
            out.totals = summary or {}

        trend_days = max(lookback_days, 30)
        dt = _go(
            "daily_trend",
            lambda: self.daily_trend(lookback_days=trend_days),
        ) or []
        out.daily_trend = [DailyPoint(**r) if isinstance(r, dict) else r for r in dt]

        ch = _go(
            "channels",
            lambda: self.marketing_channels(lookback_days=lookback_days, limit=12),
        ) or []
        out.channels = [ChannelRow(**r) if isinstance(r, dict) else r for r in ch]

        ep = _go(
            "entry_pages",
            lambda: self.entry_pages(lookback_days=lookback_days, limit=25),
        ) or []
        out.entry_pages = [EntryPageRow(**r) if isinstance(r, dict) else r for r in ep]

        co = _go(
            "countries",
            lambda: self.top_countries(lookback_days=lookback_days, limit=12),
        ) or []
        out.countries = [GeoRow(**r) if isinstance(r, dict) else r for r in co]

        de = _go(
            "devices",
            lambda: self.device_split(lookback_days=lookback_days, limit=8),
        ) or []
        out.devices = [DeviceRow(**r) if isinstance(r, dict) else r for r in de]

        # ── Tier 1 expansion: audience volume + engagement summary ──
        vs = _go(
            "visitors_summary",
            lambda: self.visitors_summary(lookback_days=lookback_days),
        ) or {}
        out.visitors_summary = vs if isinstance(vs, dict) else {}

        ss = _go(
            "site_sections",
            lambda: self.site_sections(lookback_days=lookback_days, limit=15),
        ) or []
        out.site_sections = [
            SiteSectionRow(**r) if isinstance(r, dict) else r for r in ss
        ]

        ex = _go(
            "exit_pages",
            lambda: self.exit_pages(lookback_days=lookback_days, limit=25),
        ) or []
        out.exit_pages = [ExitPageRow(**r) if isinstance(r, dict) else r for r in ex]

        isr = _go(
            "internal_searches",
            lambda: self.internal_searches(lookback_days=lookback_days, limit=30),
        ) or []
        out.internal_searches = [InternalSearchRow(**r) if isinstance(r, dict) else r for r in isr]

        nf = _go(
            "page_not_found",
            lambda: self.page_not_found(lookback_days=lookback_days, limit=25),
        ) or []
        out.page_not_found = [NotFoundRow(**r) if isinstance(r, dict) else r for r in nf]

        # ── Time profile ────────────────────────────────────────────
        hrs = _go(
            "hours",
            lambda: self.hour_of_day(lookback_days=lookback_days),
        ) or []
        out.hours = [HourRow(**r) if isinstance(r, dict) else r for r in hrs]

        wdays = _go(
            "weekdays",
            lambda: self.day_of_week(lookback_days=max(lookback_days, 30)),
        ) or []
        out.weekdays = [WeekdayRow(**r) if isinstance(r, dict) else r for r in wdays]

        yoy = _go(
            "yoy_daily_trend",
            lambda: self.year_over_year_trend(lookback_days=trend_days),
        ) or []
        out.yoy_daily_trend = [DailyPoint(**r) if isinstance(r, dict) else r for r in yoy]

        # ── Geo depth ───────────────────────────────────────────────
        rg = _go(
            "regions",
            lambda: self.regions(lookback_days=lookback_days, limit=30),
        ) or []
        out.regions = [GeoRow(**r) if isinstance(r, dict) else r for r in rg]

        ct = _go(
            "cities",
            lambda: self.cities(lookback_days=lookback_days, limit=30),
        ) or []
        out.cities = [GeoRow(**r) if isinstance(r, dict) else r for r in ct]

        lng = _go(
            "languages",
            lambda: self.languages(lookback_days=lookback_days, limit=15),
        ) or []
        out.languages = [LangRow(**r) if isinstance(r, dict) else r for r in lng]

        # ── Tech depth ──────────────────────────────────────────────
        br = _go(
            "browsers",
            lambda: self.browsers(lookback_days=lookback_days, limit=15),
        ) or []
        out.browsers = [BrowserRow(**r) if isinstance(r, dict) else r for r in br]

        oss = _go(
            "operating_systems",
            lambda: self.operating_systems(lookback_days=lookback_days, limit=15),
        ) or []
        out.operating_systems = [OSRow(**r) if isinstance(r, dict) else r for r in oss]

        res = _go(
            "resolutions",
            lambda: self.resolutions(lookback_days=lookback_days, limit=15),
        ) or []
        out.resolutions = [ResolutionRow(**r) if isinstance(r, dict) else r for r in res]

        # ── Acquisition depth ───────────────────────────────────────
        chd = _go(
            "channel_detail",
            lambda: self.channel_detail(lookback_days=lookback_days, limit=25),
        ) or []
        out.channel_detail = [ChannelRow(**r) if isinstance(r, dict) else r for r in chd]

        rd = _go(
            "referrer_domains",
            lambda: self.referrer_domains(lookback_days=lookback_days, limit=25),
        ) or []
        out.referrer_domains = [ReferrerDomainRow(**r) if isinstance(r, dict) else r for r in rd]

        se = _go(
            "search_engines",
            lambda: self.search_engines(lookback_days=lookback_days, limit=10),
        ) or []
        out.search_engines = [SearchEngineRow(**r) if isinstance(r, dict) else r for r in se]

        # ── Conversion (lead-hash eVar from settings) ───────────────
        le = _go(
            "lead_events",
            lambda: self.lead_events(lookback_days=max(lookback_days, 30), limit=25),
        ) or []
        out.lead_events = [LeadEventRow(**r) if isinstance(r, dict) else r for r in le]

        # ── Workspace catalogue (segments + calculated metrics) ─────
        sg = _go("segments", lambda: self.list_segments(limit=100)) or []
        out.segments = [CatalogueItem(**r) if isinstance(r, dict) else r for r in sg]

        cm = _go(
            "calculated_metrics",
            lambda: self.list_calculated_metrics(limit=100),
        ) or []
        out.calculated_metrics = [CatalogueItem(**r) if isinstance(r, dict) else r for r in cm]

        # Cache audit — what sections survive on disk regardless of
        # whether they were live this load.
        out.cached_sections_on_disk = adobe_cache.cached_sections(self.rsid)

        return out


# ── helpers ───────────────────────────────────────────────────────────


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[:n] + "…"


def _safe_first(seq) -> float | None:
    try:
        v = seq[0]
        return float(v) if v is not None else None
    except (TypeError, ValueError, IndexError):
        return None


def _coerce_iso_date(value: str, item_id: Any) -> str:
    """Adobe's daterangeday rows carry the date in several shapes:

      * ``value`` like ``"yyyy-mm-dd"`` — perfect, return as-is.
      * ``value`` like ``"May 14, 2026"`` — parse via strptime.
      * ``itemId`` like ``"1240514"`` — last 6 digits are yymmdd; ignore.
      * Anything else — return empty so the caller falls back to ``value``.
    """
    v = (value or "").strip()
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        return v
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def dashboard_payload(
    *,
    lookback_days: int | None = None,
    limit: int | None = None,
) -> dict:
    """Convenience wrapper for the view layer. Returns the dict shape
    the AdobePage frontend consumes, with ``available=False`` when
    credentials are missing."""
    try:
        adapter = AdobeAnalyticsAdapter()
    except AdapterDisabledError as exc:
        return {"available": False, "reason": "not_configured", "error": str(exc)}

    dash = adapter.dashboard(lookback_days=lookback_days, limit=limit)
    body = asdict(dash)
    # Convert nested dataclasses already handled by asdict; ensure
    # report_suite is None vs dict consistent.
    return body


# ── SEO × Adobe cross-source join ─────────────────────────────────────


def _adobe_page_to_url(page: str, domain: str = "bajajlifeinsurance.com") -> str:
    """Adobe's page values are colon-delimited slugs ("term-plan:quote-
    page") rather than full URLs. Convert to a best-effort canonical
    URL by replacing colons with slashes. Empty / "home" pages map to
    the apex. The join key is fuzzy by design — both sides treat the
    URL as a suffix and match on the tail."""
    s = (page or "").strip().strip(":").strip("/")
    if not s or s.lower() in ("home", "homepage", "index"):
        return f"https://www.{domain}/"
    # Replace colons with slashes; collapse repeats.
    path = "/".join(seg for seg in s.replace(":", "/").split("/") if seg)
    return f"https://www.{domain}/{path}"


def seo_adobe_join_payload(
    *, lookback_days: int = 30, limit: int = 100,
) -> dict:
    """Join Adobe top pages with our crawl + GSC data.

    For each top Adobe page (by page-views over ``lookback_days``) the
    payload includes:

      * ``url``               — best-effort canonical URL
      * ``page_views`` / ``visits``  — Adobe over the window
      * ``status_code`` / ``title`` / ``word_count`` — latest crawl row
      * ``has_any_error`` (bool)     — Health Score's error gate
      * ``gsc_clicks`` / ``gsc_impressions`` / ``gsc_position`` — if a
        GSC export exists in the data dir

    The view layer sorts by ``page_views`` desc — the UI lets the user
    re-sort client-side. Pages that don't match a crawl row still
    appear (their crawl_* fields stay None), so this view doubles as
    a "pages with traffic but no crawl entry" detector.
    """
    out: dict = {
        "available": False,
        "reason": "",
        "rows": [],
        "lookback_days": lookback_days,
    }

    try:
        adapter = AdobeAnalyticsAdapter()
    except AdapterDisabledError as exc:
        out["reason"] = "not_configured"
        out["error"] = str(exc)
        return out

    try:
        adobe_rows = adapter.top_pages_with_visits(
            lookback_days=lookback_days, limit=limit,
        )
    except AdobeAnalyticsError as exc:
        out["reason"] = "adobe_failed"
        out["error"] = str(exc)
        return out

    out["available"] = True

    # Lazy import — keep the adapter module importable in environments
    # where Django ORM isn't yet set up (tests, scripts).
    crawl_lookup: dict[str, dict] = {}
    try:
        from apps.crawler.models import CrawlerPageResult, CrawlSnapshot
        # Latest Bajaj snapshot.
        snap = (
            CrawlSnapshot.objects
            .filter(kind=CrawlSnapshot.Kind.BAJAJ,
                    status=CrawlSnapshot.Status.COMPLETE)
            .order_by("-started_at")
            .first()
        )
        if snap is not None:
            for p in CrawlerPageResult.objects.filter(
                snapshot=snap,
            ).only(
                "url", "status_code", "title", "word_count",
                "indexed_status", "from_sitemap",
            ).iterator(chunk_size=500):
                crawl_lookup[_url_tail(p.url)] = {
                    "status_code": p.status_code or "",
                    "title": p.title or "",
                    "word_count": p.word_count or 0,
                    "indexed_status": p.indexed_status or "",
                    "from_sitemap": bool(p.from_sitemap),
                    "url": p.url,
                }
    except Exception as exc:  # noqa: BLE001
        logger.info("adobe join: crawl lookup failed (%s)", exc)

    # GSC enrichment — read web__page.csv (Search Analytics: web · page
    # dimension), which carries clicks/impressions/ctr/position per URL.
    gsc_lookup: dict[str, dict] = _load_gsc_page_csv()

    # Compose join rows.
    rows: list[dict] = []
    for r in adobe_rows:
        url_guess = _adobe_page_to_url(r["page"])
        tail = _url_tail(url_guess)
        crawl = crawl_lookup.get(tail) or {}
        gsc = gsc_lookup.get(tail) or {}
        has_error = bool(crawl) and (crawl.get("status_code") or "").startswith(("4", "5"))
        rows.append({
            "page": r["page"],
            "url": crawl.get("url") or url_guess,
            "page_views": r["page_views"],
            "visits": r["visits"],
            "status_code": crawl.get("status_code") or "",
            "title": crawl.get("title") or "",
            "word_count": crawl.get("word_count") or 0,
            "indexed_status": crawl.get("indexed_status") or "",
            "from_sitemap": crawl.get("from_sitemap") or False,
            "has_any_error": has_error,
            "in_crawl": bool(crawl),
            "gsc_clicks": gsc.get("gsc_clicks"),
            "gsc_impressions": gsc.get("gsc_impressions"),
            "gsc_position": gsc.get("gsc_position"),
        })

    rows.sort(key=lambda r: r["page_views"], reverse=True)
    out["rows"] = rows

    # Top-line summary numbers the UI shows in the KPI strip.
    out["totals"] = {
        "rows": len(rows),
        "in_crawl": sum(1 for r in rows if r["in_crawl"]),
        "with_errors": sum(1 for r in rows if r["has_any_error"]),
        "with_gsc": sum(1 for r in rows if r["gsc_impressions"] is not None),
        "high_impression_no_traffic": sum(
            1 for r in rows
            if (r["gsc_impressions"] or 0) > 1000 and r["visits"] < 50
        ),
    }
    return out


def _load_gsc_page_csv() -> dict[str, dict]:
    """Read backend/data/gsc/{site}/web__page.csv into a tail-keyed
    lookup. Returns an empty dict (silently) when the file doesn't
    exist — the join still works without GSC data."""
    import csv
    from pathlib import Path

    out: dict[str, dict] = {}
    try:
        from django.conf import settings as dj_settings
        base_dir = Path(dj_settings.BASE_DIR) / "data" / "gsc"
        if not base_dir.exists():
            return out
        # Pick the first site directory containing a web__page.csv.
        candidates = list(base_dir.glob("*/web__page.csv"))
        if not candidates:
            return out
        # Newest first so a rotated export wins.
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        path = candidates[0]
        with path.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                url = (row.get("page") or row.get("url") or "").strip()
                if not url:
                    continue
                try:
                    out[_url_tail(url)] = {
                        "gsc_clicks": int(float(row.get("clicks") or 0)),
                        "gsc_impressions": int(
                            float(row.get("impressions") or 0)
                        ),
                        "gsc_position": round(
                            float(row.get("position") or 0.0), 2,
                        ),
                    }
                except (TypeError, ValueError):
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.info("adobe join: gsc page-CSV read failed (%s)", exc)
    return out


def _url_tail(url: str) -> str:
    """Best-effort suffix key — drops scheme + host + trailing slash so
    apex ↔ www variants collapse together. Used as the dictionary key
    for the cross-source join."""
    if not url:
        return ""
    s = str(url).strip().lower()
    for prefix in ("https://", "http://"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    slash = s.find("/")
    s = s[slash:] if slash >= 0 else "/"
    s = s.rstrip("/") or "/"
    return s
