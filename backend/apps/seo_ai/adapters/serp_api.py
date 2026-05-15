"""SerpAPI adapter for traditional-SERP visibility probing.

We call SerpAPI's REST endpoint at https://serpapi.com/search.json and
normalise the response into a :class:`SerpResult` regardless of engine.
Disk-cached 7 days at ``{SEO_AI.data_dir}/_serp_cache/`` so re-running
the same probe set within a week is free.

This module is intentionally narrow — we do NOT depend on the official
``serpapi`` SDK so that missing the package never breaks the import
graph. All HTTP is plain ``requests``.

A failed call (network error, non-200, JSON decode error) returns a
:class:`SerpResult` with ``error`` filled in and empty data lists — it
NEVER raises out of :meth:`SerpAPIAdapter.search`. The detection agent
treats an erroring engine the same as "no data".
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings

from .ai_visibility.base import AdapterDisabledError, _resolve_ssl_verify

logger = logging.getLogger("seo.ai.adapters.serp_api")


@dataclass
class OrganicRow:
    position: int
    title: str
    url: str
    domain: str
    snippet: str


@dataclass
class SerpResult:
    query: str
    engine: str
    organic: list[OrganicRow] = field(default_factory=list)
    featured_snippet: dict[str, Any] | None = None
    people_also_ask: list[str] = field(default_factory=list)
    ai_overview: dict[str, Any] | None = None
    related_searches: list[str] = field(default_factory=list)
    error: str = ""
    cached: bool = False
    latency_ms: int = 0


_SERPAPI_ENGINE_MAP = {
    "google": "google",
    "bing": "bing",
    "duckduckgo": "duckduckgo",
}


def _bare_host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


class SerpAPIAdapter:
    """One adapter for all three SerpAPI engines. Stateless per call."""

    def __init__(self) -> None:
        cfg = getattr(settings, "SERP_API", {}) or {}
        if not cfg.get("enabled", True):
            raise AdapterDisabledError("SERP_API_ENABLED=false")
        provider = (cfg.get("provider") or "serpapi").lower()
        if provider != "serpapi":
            # Future: DataForSEO / Zenserp. For now we only implement
            # SerpAPI; refuse to silently misroute requests.
            raise AdapterDisabledError(
                f"SERP_API_PROVIDER={provider!r} not implemented yet"
            )
        key = (cfg.get("api_key") or "").strip()
        if not key:
            raise AdapterDisabledError("SERPAPI_API_KEY not set")
        self._key = key
        self._country = cfg.get("country") or "in"
        self._language = cfg.get("language") or "en"
        self._timeout = int(cfg.get("request_timeout_sec", 30))
        self._ssl_verify = _resolve_ssl_verify(cfg.get("ssl_verify", ""))
        self._cache_ttl = int(cfg.get("cache_ttl_seconds", 7 * 24 * 3600))
        self._cache_dir = (
            Path(settings.SEO_AI["data_dir"]) / "_serp_cache"
        )
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001 - non-fatal
            logger.warning("serp cache dir unwritable: %s", exc)

    # ── public ────────────────────────────────────────────────────────

    def search(self, query: str, *, engine: str = "google") -> SerpResult:
        engine_key = (engine or "google").lower()
        if engine_key not in _SERPAPI_ENGINE_MAP:
            return SerpResult(
                query=query,
                engine=engine_key,
                error=f"unsupported engine: {engine_key}",
            )
        cached = self._cache_read(query, engine_key)
        if cached is not None:
            cached.cached = True
            return cached
        t0 = time.monotonic()
        result = self._fetch(query, engine_key)
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        self._cache_write(query, engine_key, result)
        return result

    # ── network ───────────────────────────────────────────────────────

    def _fetch(self, query: str, engine: str) -> SerpResult:
        params: dict[str, Any] = {
            "engine": _SERPAPI_ENGINE_MAP[engine],
            "q": query,
            "api_key": self._key,
        }
        # Google + Bing accept ``gl`` and ``hl``; DuckDuckGo doesn't —
        # but SerpAPI ignores unknown params rather than 400-ing, so we
        # set them uniformly.
        params["gl"] = self._country
        params["hl"] = self._language
        try:
            resp = requests.get(
                "https://serpapi.com/search.json",
                params=params,
                timeout=self._timeout,
                verify=self._ssl_verify,
            )
        except requests.RequestException as exc:
            logger.warning("serpapi network %s/%r: %s", engine, query[:80], exc)
            return SerpResult(
                query=query,
                engine=engine,
                error=f"network: {type(exc).__name__}: {exc}"[:300],
            )
        if resp.status_code != 200:
            return SerpResult(
                query=query,
                engine=engine,
                error=f"http {resp.status_code}: {resp.text[:300]}",
            )
        try:
            data = resp.json()
        except ValueError as exc:
            return SerpResult(
                query=query, engine=engine, error=f"json decode: {exc}"
            )
        return self._normalise(query, engine, data)

    # ── normalisation ─────────────────────────────────────────────────

    def _normalise(
        self, query: str, engine: str, data: dict[str, Any]
    ) -> SerpResult:
        organic: list[OrganicRow] = []
        for i, row in enumerate(data.get("organic_results") or []):
            url = (row.get("link") or "").strip()
            organic.append(
                OrganicRow(
                    position=int(row.get("position") or (i + 1)),
                    title=(row.get("title") or "")[:300],
                    url=url,
                    domain=_bare_host(url),
                    snippet=(row.get("snippet") or "")[:600],
                )
            )

        fs = data.get("answer_box") or data.get("featured_snippet")
        featured = None
        if isinstance(fs, dict) and (fs.get("link") or fs.get("title")):
            featured = {
                "title": (fs.get("title") or "")[:300],
                "url": (fs.get("link") or "").strip(),
                "domain": _bare_host(fs.get("link") or ""),
                "snippet": (fs.get("snippet") or fs.get("answer") or "")[:600],
            }

        paa: list[str] = []
        for q in data.get("related_questions") or []:
            q_text = q.get("question") if isinstance(q, dict) else None
            if q_text:
                paa.append(str(q_text)[:300])

        ai_overview = None
        ai_raw = data.get("ai_overview")
        if isinstance(ai_raw, dict):
            cites = []
            for r in ai_raw.get("references") or []:
                if not isinstance(r, dict):
                    continue
                url = (r.get("link") or "").strip()
                if url:
                    cites.append(
                        {
                            "title": (r.get("title") or "")[:300],
                            "url": url,
                            "domain": _bare_host(url),
                        }
                    )
            ai_overview = {
                "text_blocks": [
                    b.get("snippet") or b.get("text") or ""
                    for b in (ai_raw.get("text_blocks") or [])
                    if isinstance(b, dict)
                ][:10],
                "citations": cites,
            }

        related: list[str] = []
        for r in data.get("related_searches") or []:
            text = r.get("query") if isinstance(r, dict) else None
            if text:
                related.append(str(text)[:200])

        return SerpResult(
            query=query,
            engine=engine,
            organic=organic[:20],
            featured_snippet=featured,
            people_also_ask=paa[:10],
            ai_overview=ai_overview,
            related_searches=related[:10],
        )

    # ── cache ─────────────────────────────────────────────────────────

    def _cache_path(self, query: str, engine: str) -> Path:
        h = hashlib.sha1(
            f"{engine}|{self._country}|{self._language}|{query}".encode("utf-8")
        ).hexdigest()
        return self._cache_dir / f"{h}.json"

    def _cache_read(self, query: str, engine: str) -> SerpResult | None:
        path = self._cache_path(query, engine)
        if not path.exists():
            return None
        try:
            if (time.time() - path.stat().st_mtime) > self._cache_ttl:
                return None
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        # Reconstruct OrganicRow dataclass instances.
        rows = [
            OrganicRow(**row) for row in (data.get("organic") or [])
        ]
        result = SerpResult(
            query=data.get("query") or query,
            engine=data.get("engine") or engine,
            organic=rows,
            featured_snippet=data.get("featured_snippet"),
            people_also_ask=list(data.get("people_also_ask") or []),
            ai_overview=data.get("ai_overview"),
            related_searches=list(data.get("related_searches") or []),
            error=data.get("error") or "",
            latency_ms=int(data.get("latency_ms") or 0),
        )
        return result

    def _cache_write(
        self, query: str, engine: str, result: SerpResult
    ) -> None:
        path = self._cache_path(query, engine)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(asdict(result), f, default=str)
        except OSError as exc:  # noqa: BLE001 - cache is best-effort
            logger.warning("serp cache write failed: %s", exc)
