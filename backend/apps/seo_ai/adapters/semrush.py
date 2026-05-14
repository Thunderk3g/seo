"""SEMrush API adapter.

Hits ``api.semrush.com`` for the two endpoints we actually use:
``domain_ranks`` for the site-level KPI tile, and ``domain_organic``
for the keyword list. SEMrush bills by row (``domain_organic`` is
10 units per row at the time of writing), so we cap pulls per call
and persist results to disk with a short TTL — re-running a grade
the same day must not redo the spend.

The base URL hits the public API. On Windows corporate networks an
MITM proxy frequently injects an intermediate cert that only lives in
the OS trust store, so ``certifi``'s bundled CAs cannot verify the
connection and ``requests.get`` fails with
``CERTIFICATE_VERIFY_FAILED``. We mitigate this with ``truststore``,
which makes Python's TLS stack use the system store — same fix the
LLM provider already applies. We **do not** disable certificate
verification itself.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from django.conf import settings

# Inject the OS trust store once at module import so all ``requests``
# calls below pick up corporate root CAs without each call having to
# configure SSL itself. Safe no-op on macOS / Linux or if truststore
# isn't installed.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - non-Windows or already injected
    pass

logger = logging.getLogger("seo.ai.adapters.semrush")


@dataclass
class SemrushOverview:
    domain: str
    database: str
    rank: int
    organic_keywords: int
    organic_traffic: int
    organic_cost: int
    adwords_keywords: int
    adwords_traffic: int
    adwords_cost: int


@dataclass
class SemrushKeyword:
    keyword: str
    position: int
    previous_position: int
    search_volume: int
    cpc: float
    competition: float
    traffic_pct: float
    url: str


@dataclass
class SemrushCompetitor:
    """One row from the ``domain_organic_organic`` (Competitors) report."""

    domain: str
    competition_level: float
    common_keywords: int
    organic_keywords: int
    organic_traffic: int


@dataclass
class SemrushTopPage:
    """One row from the ``domain_organic_pages`` report.

    ``traffic_estimate`` is the *absolute* estimated monthly organic
    visits to this URL; ``traffic_pct`` is the same as a percentage of
    the domain total. Either may be 0.0 if SEMrush's model is sparse.
    """

    url: str
    keyword_count: int
    traffic_pct: float
    traffic_estimate: int


class SemrushError(RuntimeError):
    pass


class SemrushAdapter:
    """Thin client. No retries — caller decides what to do on failure."""

    _BASE = "https://api.semrush.com"
    _UNITS_URL = "https://www.semrush.com/users/countapiunits.html"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        database: str | None = None,
        cache_dir: Path | str | None = None,
        cache_ttl_seconds: int = 24 * 3600,
    ) -> None:
        cfg = settings.SEMRUSH
        self.api_key = api_key or cfg["api_key"]
        self.database = database or cfg["database"]
        if not self.api_key:
            raise SemrushError(
                "SEMRUSH_API_KEY not set; disable competitor agent or "
                "configure the key."
            )
        self.cache_dir = (
            Path(cache_dir)
            if cache_dir
            else (settings.SEO_AI["data_dir"] / "_semrush_cache")
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = cache_ttl_seconds

    # ── public API ────────────────────────────────────────────────────

    def units_remaining(self) -> int:
        body = self._http_get(self._UNITS_URL).strip()
        try:
            return int(body)
        except ValueError as exc:
            raise SemrushError(f"unexpected units response: {body!r}") from exc

    def domain_overview(self, domain: str) -> SemrushOverview:
        """Fetch ``domain_ranks`` (10 units)."""
        cached = self._cache_read(f"overview__{domain}__{self.database}.json")
        if cached:
            return SemrushOverview(**cached)
        rows = self._call(
            "domain_ranks",
            domain=domain,
            export_columns="Db,Dn,Rk,Or,Ot,Oc,Ad,At,Ac",
        )
        if not rows:
            raise SemrushError(f"no rows returned for {domain}")
        r = rows[0]
        overview = SemrushOverview(
            domain=domain,
            database=r.get("Database", self.database),
            rank=_int(r.get("Rank")),
            organic_keywords=_int(r.get("Organic Keywords")),
            organic_traffic=_int(r.get("Organic Traffic")),
            organic_cost=_int(r.get("Organic Cost")),
            adwords_keywords=_int(r.get("Adwords Keywords")),
            adwords_traffic=_int(r.get("Adwords Traffic")),
            adwords_cost=_int(r.get("Adwords Cost")),
        )
        self._cache_write(
            f"overview__{domain}__{self.database}.json", overview.__dict__
        )
        return overview

    def organic_keywords(
        self,
        domain: str,
        *,
        limit: int | None = None,
        sort: str = "tr_desc",
    ) -> list[SemrushKeyword]:
        """Fetch top organic keywords (10 units per row)."""
        limit = limit or settings.SEMRUSH["default_limit"]
        cached = self._cache_read(
            f"organic__{domain}__{self.database}__{limit}__{sort}.json"
        )
        if cached:
            return [SemrushKeyword(**row) for row in cached]
        rows = self._call(
            "domain_organic",
            domain=domain,
            display_limit=str(limit),
            display_sort=sort,
            export_columns="Ph,Po,Pp,Nq,Cp,Co,Tr,Ur",
        )
        keywords = [
            SemrushKeyword(
                keyword=r.get("Keyword", ""),
                position=_int(r.get("Position")),
                previous_position=_int(r.get("Previous Position")),
                search_volume=_int(r.get("Search Volume")),
                cpc=_float(r.get("CPC")),
                competition=_float(r.get("Competition")),
                traffic_pct=_float(r.get("Traffic (%)")),
                url=r.get("Url", ""),
            )
            for r in rows
        ]
        self._cache_write(
            f"organic__{domain}__{self.database}__{limit}__{sort}.json",
            [k.__dict__ for k in keywords],
        )
        return keywords

    def organic_competitors(
        self,
        domain: str,
        *,
        limit: int = 10,
    ) -> list[SemrushCompetitor]:
        """Top organic competitors for ``domain`` — domains that rank
        for the same keywords (40 units, regardless of ``limit``).

        Column codes: ``Dn,Cr,Np,Or,Ot`` — Domain, Competition Level,
        Common Keywords, Organic Keywords, Organic Traffic. Sorted by
        competition level descending so the most relevant rivals come
        first.
        """
        ttl_key = settings.SEMRUSH.get("competitor_cache_ttl") or self.cache_ttl
        cache_name = f"competitors__{domain}__{self.database}__{limit}.json"
        cached = self._cache_read(cache_name, ttl_seconds=ttl_key)
        if cached:
            return [SemrushCompetitor(**row) for row in cached]
        rows = self._call(
            "domain_organic_organic",
            domain=domain,
            display_limit=str(limit),
            display_sort="cr_desc",
            export_columns="Dn,Cr,Np,Or,Ot",
        )
        competitors = [
            SemrushCompetitor(
                domain=r.get("Domain", ""),
                competition_level=_float(r.get("Competitor Relevance") or r.get("Competition Level")),
                common_keywords=_int(r.get("Common Keywords")),
                organic_keywords=_int(r.get("Organic Keywords")),
                organic_traffic=_int(r.get("Organic Traffic")),
            )
            for r in rows
            if r.get("Domain")
        ]
        self._cache_write(cache_name, [c.__dict__ for c in competitors])
        return competitors

    def top_pages(
        self,
        domain: str,
        *,
        limit: int = 50,
    ) -> list[SemrushTopPage]:
        """Top organic landing pages on ``domain``.

        Tries the dedicated ``domain_organic_pages`` report first; on
        API tiers where that endpoint is unavailable (SEMrush returns
        ``HTTP 400 query type not found``) we fall back to aggregating
        from the keyword list — pulling :meth:`organic_keywords` and
        grouping rows by URL. The fallback is free in units because
        the keywords are pulled anyway by the competitor agent for the
        keyword-gap dimension.
        """
        ttl_key = settings.SEMRUSH.get("competitor_cache_ttl") or self.cache_ttl
        cache_name = f"top_pages__{domain}__{self.database}__{limit}.json"
        cached = self._cache_read(cache_name, ttl_seconds=ttl_key)
        if cached:
            return [SemrushTopPage(**row) for row in cached]

        pages: list[SemrushTopPage] = []
        try:
            rows = self._call(
                "domain_organic_pages",
                domain=domain,
                display_limit=str(limit),
                display_sort="tr_desc",
                export_columns="Ur,Pc,Tg,Tr",
            )
            pages = [
                SemrushTopPage(
                    url=r.get("URL") or r.get("Url", ""),
                    keyword_count=_int(
                        r.get("Number of Keywords") or r.get("Page Keywords")
                    ),
                    traffic_estimate=_int(r.get("Traffic")),
                    traffic_pct=_float(r.get("Traffic (%)")),
                )
                for r in rows
                if (r.get("URL") or r.get("Url"))
            ]
        except SemrushError as exc:
            # "query type not found" → endpoint not on this API tier.
            # Any other error → re-raise so callers surface it.
            msg = str(exc).lower()
            if "query type" not in msg and "not found" not in msg:
                raise
            logger.info(
                "domain_organic_pages unavailable for %s — falling back to "
                "URL aggregation from organic_keywords. (%s)",
                domain,
                exc,
            )
            kw_limit = max(limit * 5, 200)
            keywords = self.organic_keywords(domain, limit=kw_limit)
            agg: dict[str, dict[str, float]] = {}
            for k in keywords:
                if not k.url:
                    continue
                bucket = agg.setdefault(
                    k.url,
                    {"keyword_count": 0, "traffic_pct": 0.0, "traffic_estimate": 0.0},
                )
                bucket["keyword_count"] += 1
                bucket["traffic_pct"] += k.traffic_pct
            # Sort by aggregated traffic-share % desc, take top N.
            ordered = sorted(
                agg.items(), key=lambda kv: kv[1]["traffic_pct"], reverse=True
            )[:limit]
            pages = [
                SemrushTopPage(
                    url=url,
                    keyword_count=int(b["keyword_count"]),
                    traffic_pct=round(b["traffic_pct"], 2),
                    traffic_estimate=0,
                )
                for url, b in ordered
            ]
        self._cache_write(cache_name, [p.__dict__ for p in pages])
        return pages

    # ── low-level ─────────────────────────────────────────────────────

    def _call(self, type_: str, **params: str) -> list[dict[str, str]]:
        url = self._BASE + "/?" + _encode(
            {
                "type": type_,
                "key": self.api_key,
                "database": self.database,
                **params,
            }
        )
        body = self._http_get(url)
        # SEMrush returns ``ERROR ###`` plaintext on failure.
        if body.startswith("ERROR"):
            raise SemrushError(body.strip())
        return _parse_semrush_csv(body)

    def _http_get(self, url: str) -> str:
        # TLS verification handling mirrors the LLM provider: behind a
        # corporate MITM proxy where certifi's bundle can't verify the
        # injected intermediate cert, the operator sets
        # SEMRUSH_SSL_VERIFY=false (dev) or points it at a CA bundle.
        # Inside the Linux Docker image neither truststore nor the
        # bundled Debian roots see the corp CA, so this is the only
        # working escape hatch short of mounting a CA into the container.
        verify = _resolve_semrush_ssl_verify(settings.SEMRUSH.get("ssl_verify", ""))
        if verify is False:
            # Quiet the urllib3 InsecureRequestWarning that floods the
            # logs once per call when verification is off.
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:  # noqa: BLE001
                pass
        try:
            resp = requests.get(url, timeout=30, verify=verify)
        except requests.RequestException as exc:
            raise SemrushError(str(exc)) from exc
        if resp.status_code != 200:
            raise SemrushError(
                f"HTTP {resp.status_code} from SEMrush: {resp.text[:200]}"
            )
        return resp.text

    # ── cache (filesystem JSON, TTL'd) ───────────────────────────────

    def _cache_read(self, name: str, *, ttl_seconds: int | None = None) -> Any | None:
        path = self.cache_dir / name
        if not path.exists():
            return None
        ttl = ttl_seconds if ttl_seconds is not None else self.cache_ttl
        try:
            if (time.time() - path.stat().st_mtime) > ttl:
                return None
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _cache_write(self, name: str, payload: Any) -> None:
        path = self.cache_dir / name
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, default=str)
        except OSError as exc:
            logger.warning("semrush cache write failed: %s", exc)


# ── helpers ──────────────────────────────────────────────────────────────


def _encode(params: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return urlencode({k: v for k, v in params.items() if v is not None})


def _resolve_semrush_ssl_verify(raw: str) -> bool | str:
    """Map SEMRUSH_SSL_VERIFY env value → requests ``verify`` argument.

    Empty / "true" → True (use certifi). "false"/"0"/"no"/"off" → False
    (disable verification; dev-only escape hatch for corp MITM proxies,
    same pattern as LLM_SSL_VERIFY). Anything else is treated as a path
    to a CA bundle file; non-existent paths fall back to True with a
    log warning rather than crashing the API call.
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
        "SEMRUSH_SSL_VERIFY=%r does not exist on disk — falling back to "
        "default (certifi) verification.",
        value,
    )
    return True


def _parse_semrush_csv(body: str) -> list[dict[str, str]]:
    """SEMrush ships ``;``-separated headers + rows."""
    body = body.strip()
    if not body:
        return []
    reader = csv.reader(io.StringIO(body), delimiter=";")
    header = next(reader, None)
    if not header:
        return []
    return [dict(zip(header, row)) for row in reader]


def _int(raw: object) -> int:
    try:
        return int(float(str(raw)))
    except (TypeError, ValueError):
        return 0


def _float(raw: object) -> float:
    try:
        return float(str(raw))
    except (TypeError, ValueError):
        return 0.0
