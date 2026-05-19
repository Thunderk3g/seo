"""PageSpeed Insights adapter — Core Web Vitals for any public URL.

Wraps Google's PSI v5 endpoint, authenticated via a service-account
JSON so the daily quota (25k calls) bills against our Cloud project
instead of the shared anonymous pool that exhausts fast. Quota lands
on whatever project owns the SA (we use ``geoseo-496810``).

PSI is one of Google's "public data" APIs that conventionally uses an
API key — but it also accepts OAuth bearer tokens minted with the
``openid`` + ``userinfo.email`` scope combo. We use the OAuth path
because we already have the SA wired for GSC; one credential serves
both.

Returns a :class:`CWVRecord` for each (url, strategy) pair. Lab data
(Lighthouse run) is always present on a 200; field data (CrUX p75
real-user metrics, 28-day rolling) is only available for URLs that
have enough Chrome user traffic — small pages return no CrUX block,
which is normal not an error.

Failure policy mirrors the SerpAPI adapter: every failure path returns
a :class:`CWVRecord` with ``error`` filled in and empty metric fields.
This adapter NEVER raises out of :meth:`PSIAdapter.fetch` — callers
treat an erroring record as "CWV unavailable for this URL".

Disk-cached for 7 days at ``{SEO_AI.data_dir}/_psi_cache/`` keyed by
SHA1(url|strategy). Re-running the same audit set within a week is
free.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger("seo.ai.adapters.cwv_psi")


_PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
# Empirically the only scope combo PSI accepts from a service account.
# cloud-platform alone returns ACCESS_TOKEN_SCOPE_INSUFFICIENT.
_SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


class AdapterDisabledError(Exception):
    """Raised when the adapter is intentionally inactive (no SA file,
    PSI_ENABLED=false, etc.). Callers should catch and silently skip."""


@dataclass
class CWVRecord:
    """One PSI result for a single (url, strategy) pair.

    Lab metrics come from the synchronous Lighthouse run. Field metrics
    come from CrUX (real Chrome user p75 across a 28-day rolling window)
    and are only populated when CrUX has enough traffic for this URL.
    """

    url: str
    strategy: str           # "mobile" | "desktop"
    fetched_at: str = ""
    cached: bool = False
    latency_ms: int = 0
    error: str = ""

    # ── Lab (Lighthouse) ────────────────────────────────────────────
    performance_score: float | None = None  # 0..1
    lab_lcp_ms: int | None = None
    lab_cls: float | None = None
    lab_fcp_ms: int | None = None
    lab_tbt_ms: int | None = None
    lab_si_ms: int | None = None             # Speed Index
    lab_ttfb_ms: int | None = None

    # ── Field (CrUX p75 real-user) ──────────────────────────────────
    # category values: "FAST" | "AVERAGE" | "SLOW"
    field_lcp_ms: int | None = None
    field_lcp_category: str = ""
    field_cls: float | None = None
    field_cls_category: str = ""
    field_inp_ms: int | None = None
    field_inp_category: str = ""
    field_fcp_ms: int | None = None
    field_fcp_category: str = ""
    field_ttfb_ms: int | None = None
    field_ttfb_category: str = ""
    has_field_data: bool = False

    raw: dict[str, Any] = field(default_factory=dict)  # full PSI JSON for debugging


class PSIAdapter:
    """Synchronous PSI client. Caller passes URLs; we return one
    :class:`CWVRecord` per (url, strategy)."""

    def __init__(self) -> None:
        cfg = getattr(settings, "PSI", {}) or {}
        if not cfg.get("enabled", True):
            raise AdapterDisabledError("PSI_ENABLED=false")
        sa_path = (cfg.get("service_account_json") or "").strip()
        if not sa_path:
            raise AdapterDisabledError("PSI_SERVICE_ACCOUNT_JSON not set")
        if not Path(sa_path).exists():
            raise AdapterDisabledError(
                f"PSI service-account file not found: {sa_path}"
            )
        self._sa_path = sa_path
        self._timeout = int(cfg.get("request_timeout_sec", 120))
        self._cache_ttl = int(cfg.get("cache_ttl_seconds", 7 * 24 * 3600))
        self._ssl_verify = _resolve_psi_ssl_verify(cfg.get("ssl_verify", ""))

        self._cache_dir = Path(settings.SEO_AI["data_dir"]) / "_psi_cache"
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001 - non-fatal
            logger.warning("psi cache dir unwritable: %s", exc)

        # Token cache. google-auth handles refresh, but we hold the
        # creds object across calls so we don't re-read the SA file
        # every request.
        self._creds = None
        self._creds_lock = threading.Lock()

    # ── public ────────────────────────────────────────────────────────

    def fetch(self, url: str, *, strategy: str = "mobile") -> CWVRecord:
        """Return CWV for one (url, strategy). Never raises."""
        strategy = (strategy or "mobile").lower()
        if strategy not in ("mobile", "desktop"):
            return CWVRecord(
                url=url,
                strategy=strategy,
                error=f"invalid strategy: {strategy}",
            )

        cached = self._cache_read(url, strategy)
        if cached is not None:
            cached.cached = True
            return cached

        t0 = time.monotonic()
        try:
            token = self._access_token()
        except Exception as exc:  # noqa: BLE001 - upstream auth issues
            logger.warning("psi auth failed for %s: %s", url, exc)
            return CWVRecord(
                url=url,
                strategy=strategy,
                error=f"auth: {type(exc).__name__}: {exc}"[:300],
            )

        try:
            resp = requests.get(
                _PSI_ENDPOINT,
                params={
                    "url": url,
                    "category": "performance",
                    "strategy": strategy,
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
                verify=self._ssl_verify,
            )
        except requests.RequestException as exc:
            logger.warning("psi network %s/%s: %s", strategy, url, exc)
            return CWVRecord(
                url=url,
                strategy=strategy,
                error=f"network: {type(exc).__name__}: {exc}"[:300],
                latency_ms=int((time.monotonic() - t0) * 1000),
            )

        latency_ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code != 200:
            return CWVRecord(
                url=url,
                strategy=strategy,
                error=f"http {resp.status_code}: {resp.text[:300]}",
                latency_ms=latency_ms,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            return CWVRecord(
                url=url,
                strategy=strategy,
                error=f"json decode: {exc}",
                latency_ms=latency_ms,
            )

        record = _parse_psi(url, strategy, data)
        record.latency_ms = latency_ms
        record.fetched_at = _now_iso()
        self._cache_write(url, strategy, record)
        return record

    # ── auth ─────────────────────────────────────────────────────────

    def _access_token(self) -> str:
        """Mint (or refresh) the OAuth bearer token for PSI.

        Lazy-import google-auth so this module is import-safe even when
        the optional dep isn't installed — the adapter will only break
        at fetch-time, not at module import.
        """
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        with self._creds_lock:
            if self._creds is None:
                self._creds = service_account.Credentials.from_service_account_file(
                    self._sa_path, scopes=_SCOPES
                )
            if not self._creds.valid:
                self._creds.refresh(Request())
            return self._creds.token

    # ── cache ────────────────────────────────────────────────────────

    def _cache_key(self, url: str, strategy: str) -> str:
        return hashlib.sha1(f"{strategy}|{url}".encode("utf-8")).hexdigest()

    def _cache_path(self, url: str, strategy: str) -> Path:
        return self._cache_dir / f"{self._cache_key(url, strategy)}.json"

    def _cache_read(self, url: str, strategy: str) -> CWVRecord | None:
        path = self._cache_path(url, strategy)
        if not path.exists():
            return None
        try:
            if (time.time() - path.stat().st_mtime) > self._cache_ttl:
                return None
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        # Reconstruct dataclass — tolerate extra keys from future schema
        # bumps by filtering to known fields.
        known = set(CWVRecord.__dataclass_fields__.keys())
        return CWVRecord(**{k: v for k, v in data.items() if k in known})

    def _cache_write(self, url: str, strategy: str, record: CWVRecord) -> None:
        path = self._cache_path(url, strategy)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(asdict(record), f, default=str)
        except OSError as exc:  # noqa: BLE001 - cache is best-effort
            logger.warning("psi cache write failed: %s", exc)


# ── parsing helpers ─────────────────────────────────────────────────────


def _parse_psi(url: str, strategy: str, data: dict[str, Any]) -> CWVRecord:
    rec = CWVRecord(url=url, strategy=strategy)

    lh = data.get("lighthouseResult") or {}
    audits = lh.get("audits") or {}
    cats = lh.get("categories") or {}

    perf = (cats.get("performance") or {}).get("score")
    if isinstance(perf, (int, float)):
        rec.performance_score = float(perf)

    rec.lab_lcp_ms = _audit_ms(audits, "largest-contentful-paint")
    rec.lab_cls = _audit_float(audits, "cumulative-layout-shift")
    rec.lab_fcp_ms = _audit_ms(audits, "first-contentful-paint")
    rec.lab_tbt_ms = _audit_ms(audits, "total-blocking-time")
    rec.lab_si_ms = _audit_ms(audits, "speed-index")
    rec.lab_ttfb_ms = _audit_ms(audits, "server-response-time")

    # CrUX field data — present only when the URL has enough Chrome
    # users in the 28-day window. Missing field data is normal for
    # low-traffic pages, not an error.
    field_metrics = (data.get("loadingExperience") or {}).get("metrics") or {}
    if field_metrics:
        rec.has_field_data = True
        rec.field_lcp_ms, rec.field_lcp_category = _crux(
            field_metrics.get("LARGEST_CONTENTFUL_PAINT_MS")
        )
        rec.field_fcp_ms, rec.field_fcp_category = _crux(
            field_metrics.get("FIRST_CONTENTFUL_PAINT_MS")
        )
        rec.field_inp_ms, rec.field_inp_category = _crux(
            field_metrics.get("INTERACTION_TO_NEXT_PAINT")
        )
        rec.field_ttfb_ms, rec.field_ttfb_category = _crux(
            field_metrics.get("EXPERIMENTAL_TIME_TO_FIRST_BYTE")
        )
        # CLS is scaled by 100 in CrUX (so p75=7 means CLS=0.07).
        cls_ms, cls_cat = _crux(field_metrics.get("CUMULATIVE_LAYOUT_SHIFT_SCORE"))
        if cls_ms is not None:
            rec.field_cls = cls_ms / 100.0
        rec.field_cls_category = cls_cat

    # Keep a tiny slice of the raw payload for debugging without
    # ballooning the cache file.
    rec.raw = {
        "fetchTime": lh.get("fetchTime"),
        "userAgent": lh.get("userAgent"),
        "lighthouseVersion": lh.get("lighthouseVersion"),
    }
    return rec


def _audit_ms(audits: dict, key: str) -> int | None:
    """Pull the numericValue (in ms) for a lab audit. PSI returns
    ``numericValue`` as a float in milliseconds for time-based metrics
    and as a unitless number for CLS — callers must use the right
    helper per metric."""
    a = audits.get(key)
    if not isinstance(a, dict):
        return None
    v = a.get("numericValue")
    if isinstance(v, (int, float)):
        return int(round(v))
    return None


def _audit_float(audits: dict, key: str) -> float | None:
    a = audits.get(key)
    if not isinstance(a, dict):
        return None
    v = a.get("numericValue")
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _crux(metric: dict | None) -> tuple[int | None, str]:
    """Extract p75 + category from a CrUX metric block."""
    if not isinstance(metric, dict):
        return None, ""
    p75 = metric.get("percentile")
    cat = metric.get("category") or ""
    if isinstance(p75, (int, float)):
        return int(p75), str(cat)
    return None, str(cat)


def _now_iso() -> str:
    from datetime import datetime, timezone as tz

    return datetime.now(tz.utc).isoformat()


def _resolve_psi_ssl_verify(raw: str) -> bool | str:
    """Same shape as the SEMRUSH / COMPETITOR ssl_verify resolvers:
    "" / unset  → True (default certifi + truststore on Windows)
    "false"     → False (disables verification — corp MITM only)
    "/path/..." → custom CA bundle
    """
    import os.path

    value = (raw or "").strip()
    if not value or value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    if os.path.exists(value):
        return value
    logger.warning(
        "PSI_SSL_VERIFY=%r does not exist on disk — falling back to "
        "default (certifi) verification.",
        value,
    )
    return True
