"""Synchronous façade over the Scrapy competitor spider.

Mirrors the public API of :class:`CompetitorCrawler` so the six existing
callers (gap pipeline, competitor agent, technical_audit, etc.) keep
working unchanged when ``COMPETITOR_ENGINE=scrapy`` flips on:

  * ``fetch_pages(urls) -> list[CompetitorPage]``
  * ``fetch_one(url) -> CompetitorPage``
  * ``enrich_with_cwv(pages, ...) -> list[CompetitorPage]``

Internals:

  * Groups URLs by host (matches legacy per-host throttle semantics).
  * For each host, spawns ``python manage.py crawl_competitor`` as a
    subprocess with a temp URLs file + temp output file. The subprocess
    boundary keeps Twisted's reactor-singleton constraint contained —
    parent Django/Celery never installs a reactor, multiple
    ``fetch_pages`` calls in one process are safe.
  * Reads the JSONL output and maps every line back to a
    ``CompetitorPage`` (same dataclass the legacy adapter returns).
  * Re-uses the legacy adapter's ``enrich_with_cwv`` verbatim — PSI
    enrichment is an HTTP call, not a crawl.

What this façade does NOT replicate:

  * Disk cache (the Scrapy path persists to Postgres instead — that's
    the durable store now; the legacy disk cache stays for the
    legacy engine path until that's retired).
  * The synchronous retry loop with backoff jitter — Scrapy's
    RetryMiddleware handles that with the same exponential pattern.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from django.conf import settings as django_settings

from .competitor_crawler import (
    CompetitorCrawler,
    CompetitorPage,
)

log = logging.getLogger("apps.seo_ai.adapters.competitor_crawler_scrapy")


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _apex_of(host: str) -> str:
    """Best-effort apex extraction: strip the leading 'www.'. Anything
    fancier (PSL-aware) isn't worth pulling tldextract for; competitor
    rosters use clean apex hosts already."""
    return host[4:] if host.startswith("www.") else host


def _manage_py_path() -> Path:
    """Path to backend/manage.py. Walks up from BASE_DIR until found
    so the façade works whether invoked from manage.py shell, gunicorn,
    or a celery worker."""
    candidate = Path(django_settings.BASE_DIR) / "manage.py"
    if candidate.exists():
        return candidate
    # Walk up one extra level — some deployments put manage.py at the
    # repo root rather than inside backend/.
    parent = Path(django_settings.BASE_DIR).parent / "manage.py"
    if parent.exists():
        return parent
    raise RuntimeError(
        f"manage.py not found near BASE_DIR={django_settings.BASE_DIR}"
    )


class CompetitorCrawlerScrapy(CompetitorCrawler):
    """Scrapy-backed CompetitorCrawler.

    Inherits from CompetitorCrawler so any code that calls
    ``isinstance(x, CompetitorCrawler)`` keeps passing. We override
    only the fetch methods; ``enrich_with_cwv`` and helpers stay on
    the parent class.
    """

    def __init__(
        self,
        *,
        playwright_enabled: bool | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        cfg = django_settings.COMPETITOR
        if playwright_enabled is None:
            playwright_enabled = bool(cfg.get("use_playwright_fallback", False))
        self.playwright_enabled = playwright_enabled

    # ── public API parity ────────────────────────────────────────────

    def fetch_pages(self, urls: list[str]) -> list[CompetitorPage]:
        """Fetch every URL via Scrapy, one subprocess per distinct host
        so each competitor gets its own CrawlSnapshot. Preserves input
        order so callers that pair URL[i] ↔ result[i] keep working."""
        if not urls:
            return []

        # Group URLs by host. Drop URLs whose host is unparsable into a
        # special "" bucket so they still get an error CompetitorPage.
        by_host: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for idx, url in enumerate(urls):
            by_host[_host(url)].append((idx, url))

        results: list[CompetitorPage | None] = [None] * len(urls)

        for host, items in by_host.items():
            if not host:
                for idx, url in items:
                    results[idx] = CompetitorPage(url=url, error="invalid url")
                continue
            domain = _apex_of(host)
            sub_urls = [u for _, u in items]
            sub_index = {u: idx for idx, u in items}
            pages_by_url = self._crawl_one_domain(domain, sub_urls)
            for url, page in pages_by_url.items():
                if url in sub_index:
                    results[sub_index[url]] = page
            # Any URL in the input batch the subprocess didn't return
            # gets a synthetic error page — preserves the no-None
            # contract of the legacy adapter.
            for idx, url in items:
                if results[idx] is None:
                    results[idx] = CompetitorPage(
                        url=url, error="scrapy: no result returned",
                    )

        # Defensive fill for any host that broke before assignment.
        return [
            r if r is not None else CompetitorPage(
                url=urls[i], error="scrapy: missing result",
            )
            for i, r in enumerate(results)
        ]

    def fetch_one(self, url: str) -> CompetitorPage:
        return self.fetch_pages([url])[0]

    def walk_domain(
        self,
        *,
        domain: str,
        seeds: list[str],
        max_depth: int = 2,
        max_pages: int = 0,
    ) -> list[CompetitorPage]:
        """Spider one competitor domain from a set of seeds + link-walk.

        Unlike :meth:`fetch_pages`, this does NOT preserve input order —
        the spider returns pages in the order they were crawled. Use
        when you want "everything reachable from these seeds within
        max_depth" rather than "fetch these specific URLs".

        ``max_pages=0`` means unlimited (only ``max_depth`` and the
        subprocess timeout bound the crawl).
        """
        if not seeds:
            return []
        target = _apex_of((domain or "").lower().lstrip("www."))
        if not target:
            target = _apex_of(_host(seeds[0]))
        pages = self._crawl_one_domain(
            target,
            seeds,
            mode="walk",
            max_depth=max_depth,
            max_pages=max_pages,
        )
        return list(pages.values())

    # ── subprocess orchestration ─────────────────────────────────────

    def _crawl_one_domain(
        self,
        domain: str,
        urls: list[str],
        *,
        mode: str = "urls",
        max_depth: int = 2,
        max_pages: int = 0,
    ) -> dict[str, CompetitorPage]:
        """Spawn one ``crawl_competitor`` subprocess for this domain.
        Returns a dict keyed by URL → CompetitorPage.

        ``mode='walk'`` switches the spider into link-walking mode where
        ``urls`` is the seed list and the spider follows internal links
        up to ``max_depth`` / ``max_pages``.
        """
        if not urls:
            return {}

        manage_py = _manage_py_path()
        tmpdir = Path(tempfile.mkdtemp(prefix=f"comp_{domain[:20]}_"))
        urls_file = tmpdir / "urls.txt"
        out_file = tmpdir / "out.jsonl"
        try:
            urls_file.write_text("\n".join(urls), encoding="utf-8")

            cmd = [
                sys.executable, str(manage_py), "crawl_competitor",
                "--target-domain", domain,
                "--urls-file", str(urls_file),
                "--output-file", str(out_file),
                "--user-agent", self.user_agent,
                "--body-cap", str(self.body_text_max_chars),
                "--mode", mode,
                "--max-depth", str(max_depth),
                "--max-pages", str(max_pages),
            ]
            if self.playwright_enabled:
                cmd.append("--playwright")

            # We inherit the parent's environment so Django settings,
            # DATABASE_URL, etc. propagate naturally. Cap subprocess
            # runtime at the same envelope the legacy adapter uses
            # (timeout_sec × retry_attempts × len(urls)) plus a fixed
            # 60 s of startup slack.
            # Walk mode visits MUCH more than len(urls) — use max_pages
            # as the projected page count, falling back to a large
            # ceiling when unbounded.
            projected_pages = (
                max_pages or 500
                if mode == "walk"
                else len(urls)
            )
            base_timeout = max(
                self.timeout_sec * self.retry_attempts * max(1, projected_pages),
                120,
            )
            total_timeout = min(base_timeout + 60, 60 * 60)  # cap at 1 h

            log.info(
                "competitor scrapy: domain=%s urls=%d timeout=%ds playwright=%s",
                domain, len(urls), total_timeout, self.playwright_enabled,
            )

            try:
                subprocess.run(
                    cmd,
                    cwd=str(manage_py.parent),
                    timeout=total_timeout,
                    check=False,
                    capture_output=True,
                )
            except subprocess.TimeoutExpired:
                log.warning(
                    "competitor scrapy: domain=%s timed out after %ds",
                    domain, total_timeout,
                )
                # Whatever items the subprocess managed to write before
                # the kill are still readable — keep going to harvest
                # them instead of dropping the whole batch.

            return self._read_results(out_file, urls)
        finally:
            # Always remove the temp dir; the durable record is in
            # CrawlerPageResult, not the JSONL.
            shutil.rmtree(tmpdir, ignore_errors=True)

    @property
    def body_text_max_chars(self) -> int:
        cfg = django_settings.COMPETITOR
        return int(cfg.get("body_text_max_chars", 0) or 0)

    def _read_results(
        self, out_file: Path, urls: list[str],
    ) -> dict[str, CompetitorPage]:
        """Parse the JSONL output and map to CompetitorPage objects."""
        pages: dict[str, CompetitorPage] = {}
        if not out_file.exists():
            return pages
        try:
            for line in out_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    log.debug("scrapy output: bad JSON line skipped (%s)", exc)
                    continue
                url = item.get("url") or ""
                if not url:
                    continue
                pages[url] = _item_to_page(item)
        except OSError as exc:
            log.warning("scrapy output: read failed (%s)", exc)
        return pages


def _item_to_page(item: dict) -> CompetitorPage:
    """Map a JSONL item back into a CompetitorPage dataclass.

    Every CompetitorPage field defined in :mod:`competitor_crawler` is
    re-populated; missing keys fall back to dataclass defaults.
    """
    sc = item.get("status_code") or ""
    try:
        status_code = int(sc) if sc and sc != "0" else int(sc or 0)
    except (TypeError, ValueError):
        status_code = 0

    return CompetitorPage(
        url=item.get("url") or "",
        final_url=item.get("final_url") or "",
        status_code=status_code,
        fetched_at=item.get("fetched_at") or "",
        error=item.get("error") or "",
        title=item.get("title") or "",
        title_length=int(item.get("title_length") or 0),
        meta_description=item.get("meta_description") or "",
        meta_description_length=int(item.get("meta_description_length") or 0),
        h1_texts=list(item.get("h1_texts") or []),
        canonical=item.get("canonical") or "",
        word_count=int(item.get("word_count") or 0),
        has_schema_org=bool(item.get("has_schema_org")),
        response_time_ms=int(item.get("response_time_ms") or 0),
        last_modified=item.get("last_modified") or "",
        h2_count=int(item.get("h2_count") or 0),
        h3_count=int(item.get("h3_count") or 0),
        h2_texts=list(item.get("h2_texts") or []),
        internal_link_count=int(item.get("internal_link_count") or 0),
        external_link_count=int(item.get("external_link_count") or 0),
        image_count=int(item.get("image_count") or 0),
        image_alt_pct=float(item.get("image_alt_pct") or 0.0),
        cta_count=int(item.get("cta_count") or 0),
        schema_types=list(item.get("schema_types") or []),
        meta_robots=item.get("meta_robots") or "",
        body_text=item.get("body_text") or "",
        # Structural mirror — Scrapy parity with the legacy adapter.
        headings=list(item.get("headings") or []),
        internal_links=list(item.get("internal_links") or []),
        external_links=list(item.get("external_links") or []),
        images=list(item.get("images") or []),
    )
