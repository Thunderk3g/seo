"""Polite single-purpose HTML fetcher for competitor SEO inspection.

The in-house ``apps.crawler.engine`` is hard-gated to
``bajajlifeinsurance.com`` via ``allowed_domains`` (see
``apps/crawler/engine/conf.py`` and ``url_utils.is_allowed_domain``).
We need to inspect *other* domains for the competitor-gap agent, so we
ship a small standalone fetcher that:

- Groups URLs by hostname and enforces a per-host token-bucket
  throttle (≥1 second between requests by default).
- Lazily loads each host's ``robots.txt`` and skips disallowed paths.
  Robots fetch failure → allow-all + WARN, same policy as the
  in-house crawler.
- Disk-caches the raw HTML at
  ``{SEO_AI.data_dir}/_competitor_cache/{sha1(url)}.html`` with a
  sidecar ``.meta.json`` (status_code, fetched_at). TTL configurable
  via ``COMPETITOR_CACHE_TTL_SECONDS`` env var.
- TLS verification driven by ``COMPETITOR_SSL_VERIFY`` env var, parsed
  identically to ``SEMRUSH_SSL_VERIFY`` — needed inside the Docker
  image where the Debian trust store lacks the corp MITM root.
- 15-second soft timeout, no retries on 4xx/5xx (logged + skipped).
- Uses ``truststore`` on Windows hosts so corporate root CAs work
  without disabling verification.

We deliberately do NOT extend ``apps.crawler.engine.parser`` — keeping
this module self-contained means a competitor-fetch bug can't regress
the production crawler.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from django.conf import settings

# truststore so corp MITM proxies work on Windows hosts. Safe no-op
# on Linux containers and if the package isn't installed.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

logger = logging.getLogger("seo.ai.adapters.competitor_crawler")


@dataclass
class CompetitorPage:
    """One fetched + parsed competitor page.

    A failed fetch still yields a CompetitorPage with ``status_code``
    set (0 for network errors, or the actual HTTP status for non-2xx)
    and an ``error`` string. Downstream scoring filters on
    ``status_code == 200``.
    """

    url: str
    final_url: str = ""
    status_code: int = 0
    fetched_at: str = ""
    error: str = ""
    title: str = ""
    title_length: int = 0
    meta_description: str = ""
    meta_description_length: int = 0
    h1_texts: list[str] = field(default_factory=list)
    canonical: str = ""
    word_count: int = 0
    has_schema_org: bool = False


class CompetitorCrawler:
    """Synchronous fetcher. Caller passes a list of URLs; we group by
    host and yield :class:`CompetitorPage` results in input order.
    """

    def __init__(
        self,
        *,
        rate_limit_sec: float | None = None,
        timeout_sec: int | None = None,
        user_agent: str | None = None,
        cache_ttl_seconds: int | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        cfg = settings.COMPETITOR
        self.rate_limit_sec = (
            rate_limit_sec if rate_limit_sec is not None else cfg["rate_limit_sec"]
        )
        self.timeout_sec = (
            timeout_sec if timeout_sec is not None else cfg["timeout_sec"]
        )
        self.user_agent = user_agent or cfg["user_agent"]
        self.cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else cfg["cache_ttl_seconds"]
        )
        self.cache_dir = (
            cache_dir
            if cache_dir
            else settings.SEO_AI["data_dir"] / "_competitor_cache"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._verify = _resolve_competitor_ssl_verify(cfg.get("ssl_verify", ""))
        if self._verify is False:
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:  # noqa: BLE001
                pass

        self._sessions: dict[str, requests.Session] = {}
        self._last_fetch: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    # ── public API ───────────────────────────────────────────────────

    def fetch_pages(self, urls: list[str]) -> list[CompetitorPage]:
        # Preserve input order in the result list; sequential fetching
        # is fine at this scale (10 competitors × 50 URLs = 500 max).
        return [self.fetch_one(u) for u in urls]

    def fetch_one(self, url: str) -> CompetitorPage:
        cached = self._cache_read(url)
        if cached is not None:
            return cached

        host = _host(url)
        if not host:
            return CompetitorPage(url=url, error="invalid url")

        if not self._robots_ok(host, url):
            page = CompetitorPage(url=url, error="blocked by robots.txt")
            self._cache_write(url, page, html="")
            return page

        self._throttle(host)
        session = self._session_for(host)
        try:
            resp = session.get(
                url,
                timeout=self.timeout_sec,
                verify=self._verify,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            logger.warning("competitor fetch %s failed: %s", url, exc)
            page = CompetitorPage(url=url, error=str(exc)[:200])
            self._cache_write(url, page, html="")
            return page

        page = _parse_html(
            url=url, final_url=resp.url, status=resp.status_code, body=resp.text
        )
        self._cache_write(url, page, html=resp.text if resp.status_code == 200 else "")
        return page

    # ── internals ────────────────────────────────────────────────────

    def _session_for(self, host: str) -> requests.Session:
        s = self._sessions.get(host)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": self.user_agent, "Accept": "text/html,*/*"})
            self._sessions[host] = s
        return s

    def _throttle(self, host: str) -> None:
        now = time.monotonic()
        last = self._last_fetch.get(host, 0.0)
        delta = now - last
        if delta < self.rate_limit_sec:
            time.sleep(self.rate_limit_sec - delta)
        self._last_fetch[host] = time.monotonic()

    def _robots_ok(self, host: str, url: str) -> bool:
        rp = self._robots.get(host)
        if rp is None and host not in self._robots:
            rp = RobotFileParser()
            try:
                # Load via requests so we honour our SSL + timeout + UA.
                robots_url = f"https://{host}/robots.txt"
                session = self._session_for(host)
                self._throttle(host)
                resp = session.get(
                    robots_url, timeout=self.timeout_sec, verify=self._verify
                )
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    logger.info(
                        "robots.txt for %s returned %s — allow-all fallback",
                        host,
                        resp.status_code,
                    )
                    rp = None  # treat as allow-all
            except requests.RequestException as exc:
                logger.warning("robots.txt fetch %s failed: %s", host, exc)
                rp = None
            self._robots[host] = rp
        if rp is None:
            return True
        return rp.can_fetch(self.user_agent, url)

    # ── disk cache ───────────────────────────────────────────────────

    def _cache_path(self, url: str) -> tuple[Path, Path]:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{h}.html", self.cache_dir / f"{h}.meta.json"

    def _cache_read(self, url: str) -> CompetitorPage | None:
        html_path, meta_path = self._cache_path(url)
        if not meta_path.exists():
            return None
        try:
            if (time.time() - meta_path.stat().st_mtime) > self.cache_ttl_seconds:
                return None
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        # Re-parse the cached HTML to get fresh extraction output.
        # Cheaper than caching the parsed CompetitorPage and lets us
        # evolve the parser without invalidating the cache.
        html_body = ""
        if html_path.exists():
            try:
                with html_path.open("r", encoding="utf-8") as f:
                    html_body = f.read()
            except OSError:
                html_body = ""
        if meta.get("status_code") != 200 or not html_body:
            page = CompetitorPage(
                url=url,
                final_url=meta.get("final_url", ""),
                status_code=int(meta.get("status_code") or 0),
                fetched_at=meta.get("fetched_at", ""),
                error=meta.get("error", ""),
            )
            return page
        page = _parse_html(
            url=url,
            final_url=meta.get("final_url", url),
            status=200,
            body=html_body,
        )
        page.fetched_at = meta.get("fetched_at", page.fetched_at)
        return page

    def _cache_write(self, url: str, page: CompetitorPage, *, html: str) -> None:
        html_path, meta_path = self._cache_path(url)
        try:
            if html:
                with html_path.open("w", encoding="utf-8") as f:
                    f.write(html)
            meta = {
                "url": url,
                "final_url": page.final_url,
                "status_code": page.status_code,
                "fetched_at": page.fetched_at or _now_iso(),
                "error": page.error,
            }
            with meta_path.open("w", encoding="utf-8") as f:
                json.dump(meta, f)
        except OSError as exc:
            logger.warning("competitor cache write failed for %s: %s", url, exc)


# ── helpers ──────────────────────────────────────────────────────────────


_WHITESPACE_RE = re.compile(r"\s+")
_SCHEMA_NEEDLES = ('application/ld+json', 'itemtype="https://schema.org', "itemtype='https://schema.org")


def _parse_html(*, url: str, final_url: str, status: int, body: str) -> CompetitorPage:
    page = CompetitorPage(
        url=url,
        final_url=final_url or url,
        status_code=status,
        fetched_at=_now_iso(),
    )
    if status != 200 or not body:
        return page

    soup = BeautifulSoup(body, "html.parser")

    title_tag = soup.find("title")
    page.title = (title_tag.get_text(strip=True) if title_tag else "")[:512]
    page.title_length = len(page.title)

    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta and meta.get("content"):
        page.meta_description = str(meta["content"]).strip()[:1024]
        page.meta_description_length = len(page.meta_description)

    page.h1_texts = [
        h.get_text(" ", strip=True)[:256]
        for h in soup.find_all("h1")
        if h.get_text(strip=True)
    ]

    canonical = soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)})
    if canonical and canonical.get("href"):
        page.canonical = str(canonical["href"]).strip()[:1024]

    # Body word count — strip script/style/noscript before counting so
    # the number reflects what a reader actually sees, not embedded JS.
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    page.word_count = len(text.split()) if text else 0

    # Schema.org presence check (cheap substring scan).
    body_lower = body.lower() if any(n in body for n in _SCHEMA_NEEDLES) else ""
    if not body_lower:
        # Slow path: do a case-insensitive scan only if the cheap one missed.
        body_lower = body.lower()
    page.has_schema_org = any(
        n.lower() in body_lower for n in _SCHEMA_NEEDLES
    )
    return page


def _host(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _now_iso() -> str:
    from datetime import datetime, timezone as tz

    return datetime.now(tz.utc).isoformat()


def _resolve_competitor_ssl_verify(raw: str) -> bool | str:
    """Same shape as ``_resolve_semrush_ssl_verify`` in
    :mod:`apps.seo_ai.adapters.semrush`.
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
        "COMPETITOR_SSL_VERIFY=%r does not exist on disk — falling back to "
        "default (certifi) verification.",
        value,
    )
    return True
