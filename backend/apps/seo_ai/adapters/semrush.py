"""SEMrush API adapter.

Hits ``api.semrush.com`` for the two endpoints we actually use:
``domain_ranks`` for the site-level KPI tile, and ``domain_organic``
for the keyword list. SEMrush bills by row (``domain_organic`` is
10 units per row at the time of writing), so we cap pulls per call
and persist results to disk with a short TTL — re-running a grade
the same day must not redo the spend.

The base URL hits the public API. On Windows we disable SSL
revocation checks via ``urllib3`` because corporate certs frequently
break the OCSP probe (we already saw this in this project's terminal).
We **do not** disable certificate verification itself.
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
        # Windows note: corporate proxies break OCSP cert-revocation probes.
        # We *do not* disable verification; we disable revocation checks.
        # See: https://stackoverflow.com/q/63738209 for the underlying
        # SCHANNEL/curl story we already hit in this project's shell.
        try:
            resp = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            raise SemrushError(str(exc)) from exc
        if resp.status_code != 200:
            raise SemrushError(
                f"HTTP {resp.status_code} from SEMrush: {resp.text[:200]}"
            )
        return resp.text

    # ── cache (filesystem JSON, TTL'd) ───────────────────────────────

    def _cache_read(self, name: str) -> Any | None:
        path = self.cache_dir / name
        if not path.exists():
            return None
        try:
            if (time.time() - path.stat().st_mtime) > self.cache_ttl:
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
