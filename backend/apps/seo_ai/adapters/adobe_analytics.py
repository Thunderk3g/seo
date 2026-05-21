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
class AdobeDashboard:
    """End-to-end dashboard payload — what the UI needs in one round trip."""
    available: bool
    rsid: str
    global_company_id: str
    lookback_days: int
    report_suite: ReportSuiteInfo | None = None
    totals: dict = field(default_factory=dict)
    top_pages: list[TopPageRow] = field(default_factory=list)
    dimension_count: int = 0
    metric_count: int = 0
    error: str = ""


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
        if resp.status_code != 200:
            raise AdobeAnalyticsError(
                f"POST {path} → HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=_truncate(resp.text, 500),
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

    def top_pages(
        self,
        *,
        lookback_days: int = 7,
        limit: int = 25,
    ) -> tuple[list[TopPageRow], dict]:
        """Top N pages by page-views over the trailing window. Returns
        (rows, summary) where summary carries totals + min/max."""
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=lookback_days)).isoformat() + "T00:00:00.000"
        end = today.isoformat() + "T00:00:00.000"
        payload = {
            "rsid": self.rsid,
            "globalFilters": [
                {"type": "dateRange", "dateRange": f"{start}/{end}"},
            ],
            "metricContainer": {
                "metrics": [{"columnId": "0", "id": "metrics/pageviews"}],
            },
            "dimension": "variables/page",
            "settings": {
                "countRepeatInstances": True,
                "limit": int(limit),
                "page": 0,
                "nonesBehavior": "exclude-nones",
            },
            "statistics": {"functions": ["col-max", "col-min"]},
        }
        data = self._post("/reports", payload)
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

    def dashboard(
        self,
        *,
        lookback_days: int | None = None,
        limit: int | None = None,
    ) -> AdobeDashboard:
        """One-shot dashboard payload — everything the AdobePage UI
        renders. Catches per-call errors so a partial outage still
        returns a usable response (rather than 500-ing the whole page).
        """
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

        try:
            out.report_suite = self.report_suite()
        except AdobeAnalyticsError as exc:
            logger.info("adobe report_suite failed: %s", exc)

        try:
            dims = self.dimensions(limit=500)
            out.dimension_count = len(dims)
        except AdobeAnalyticsError as exc:
            logger.info("adobe dimensions failed: %s", exc)

        try:
            mets = self.metrics(limit=500)
            out.metric_count = len(mets)
        except AdobeAnalyticsError as exc:
            logger.info("adobe metrics failed: %s", exc)

        try:
            rows, summary = self.top_pages(
                lookback_days=lookback_days, limit=limit,
            )
            out.top_pages = rows
            out.totals = summary
        except AdobeAnalyticsError as exc:
            logger.warning("adobe top_pages failed: %s", exc)
            out.error = str(exc)

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
