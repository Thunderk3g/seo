"""Derive a GSC coverage CSV from data we already have on disk.

The Search Console UI lets you export Coverage as CSV, but most operators
don't do that step. The data we *do* already pull from GSC via OAuth in
``backend/scripts/gsc_pull.py`` is the Search Analytics performance data
(``web__page.csv`` etc.) — every URL that has appeared in search results
in the last 16 months. That is, by definition, an **indexed** URL.

We pair that with a fresh fetch of ``sitemap.xml`` to know which URLs have
been *declared* to Google. From those two sets we can derive a coverage
report that's accurate for the buckets we display in the UI:

    indexed       — present in any GSC *__page*.csv (it performed)
    not_indexed   — in sitemap AND crawler returned 200 AND not performing
    excluded      — in sitemap but crawler returned non-200 (broken sitemap)
                    OR redirected / 4xx / 5xx in our crawl
    unknown       — neither in performance data nor reachable via sitemap

The output is a CSV in the same shape that ``gsc_loader.py`` already
expects (``URL`` + ``Indexing status``), so the rest of the pipeline
needs no changes.

This avoids the URL Inspection API entirely (2,000 calls/day quota +
expensive OAuth dance for every URL). When we eventually want richer
verdicts (e.g. "Duplicate, Google chose different canonical"), we can
selectively call URL Inspection for the ``not_indexed`` subset only.
"""
from __future__ import annotations

import csv
import gzip
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests

from ..conf import settings
from ..logger import get_logger
from . import gsc_loader

log = get_logger(__name__)

GSC_ROOT = settings.data_path / "gsc"
COVERAGE_DIR = GSC_ROOT / "coverage"
DEFAULT_SITEMAP = "https://www.bajajlifeinsurance.com/sitemap.xml"

# Sitemap namespace.
_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


# ── Performance pages (= indexed) ──────────────────────────────────────────
def collect_indexed_urls() -> set[str]:
    """Union of every URL that has appeared in any GSC *__page*.csv.

    Performance data only contains URLs that produced impressions or
    clicks. Any URL Google has indexed in the past 16 months will be in
    here. The flip side: a URL with 0 impressions could still be indexed,
    but for our purposes "indexed-and-relevant" is exactly what we want.
    """
    out: set[str] = set()
    if not GSC_ROOT.exists():
        return out
    for site_dir in GSC_ROOT.iterdir():
        if not site_dir.is_dir() or site_dir.name == "coverage":
            continue
        for csv_path in site_dir.glob("*__page*.csv"):
            try:
                with open(csv_path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    if not reader.fieldnames or "page" not in reader.fieldnames:
                        continue
                    for row in reader:
                        page = (row.get("page") or "").strip()
                        if page:
                            out.add(gsc_loader.normalize_url(page))
            except OSError as exc:
                log.warning("gsc_coverage_builder: read %s failed: %s",
                            csv_path, exc)
    return out


# ── Sitemap discovery ──────────────────────────────────────────────────────
def fetch_sitemap_urls(seed: str = DEFAULT_SITEMAP,
                      timeout: float = 15.0,
                      max_urls: int = 100_000) -> list[str]:
    """Recursively expand a sitemap URL into the list of contained pages.

    Handles ``<sitemapindex>`` (nested sitemaps) and gzipped sitemaps.
    Stops at ``max_urls`` to avoid runaway fetches on broken servers.
    """
    seen: set[str] = set()
    urls: list[str] = []
    stack: list[str] = [seed]
    seen.add(seed)
    while stack and len(urls) < max_urls:
        target = stack.pop()
        try:
            data = _fetch_xml(target, timeout)
        except Exception as exc:  # noqa: BLE001
            log.warning("gsc_coverage_builder: sitemap %s failed: %s",
                        target, exc)
            continue
        if data is None:
            continue
        kind, items = _parse_sitemap(data)
        if kind == "index":
            for sm in items:
                if sm not in seen:
                    seen.add(sm)
                    stack.append(sm)
        else:
            for u in items:
                if len(urls) >= max_urls:
                    break
                urls.append(u)
    return urls


def _fetch_xml(url: str, timeout: float) -> bytes | None:
    headers = {"User-Agent": "BajajLife-Crawler/1.0 (+coverage builder)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    content = resp.content
    if url.endswith(".gz") or resp.headers.get("Content-Type", "").endswith("gzip"):
        try:
            content = gzip.decompress(content)
        except OSError:
            pass
    return content


def _parse_sitemap(data: bytes) -> tuple[str, list[str]]:
    """Return ('index', sitemap_urls) or ('urlset', page_urls)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        log.warning("gsc_coverage_builder: sitemap parse error: %s", exc)
        return ("urlset", [])
    tag = re.sub(r"^\{[^}]+\}", "", root.tag)
    if tag == "sitemapindex":
        sm_urls = [
            (el.text or "").strip()
            for el in root.findall(".//sm:sitemap/sm:loc", _NS)
            if el is not None and el.text
        ]
        return ("index", [u for u in sm_urls if u])
    page_urls = [
        (el.text or "").strip()
        for el in root.findall(".//sm:url/sm:loc", _NS)
        if el is not None and el.text
    ]
    return ("urlset", [u for u in page_urls if u])


# ── Coverage build ─────────────────────────────────────────────────────────
def build_coverage(
    *,
    sitemap_seed: str = DEFAULT_SITEMAP,
    crawler_results_csv: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    """Derive coverage from performance + sitemap + (optional) crawler results.

    Returns a summary dict for the management command + UI feedback. Writes
    a fresh ``coverage_derived_YYYY-MM-DD.csv`` into ``COVERAGE_DIR``; the
    in-memory cache is invalidated so the next ``gsc_loader.status_for()``
    call picks it up.
    """
    indexed = collect_indexed_urls()
    sitemap_urls = [gsc_loader.normalize_url(u) for u in fetch_sitemap_urls(sitemap_seed)]
    sitemap_set = set(sitemap_urls)
    crawler_status = _crawler_status_map(crawler_results_csv) if crawler_results_csv or _default_crawler_csv().exists() else {}

    out_dir = output_dir or COVERAGE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = out_dir / f"coverage_derived_{today}.csv"

    counts = {"indexed": 0, "not_indexed": 0, "excluded": 0, "unknown": 0}
    universe = set(indexed) | sitemap_set | set(crawler_status.keys())
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["URL", "Indexing status", "Last crawled"])
        for url in sorted(universe):
            status = _derive_status(url, indexed, sitemap_set, crawler_status)
            counts[_bucket_of(status)] += 1
            w.writerow([_humanise(url), status, ""])

    gsc_loader.invalidate_cache()
    # The coverage file is now on disk; immediately rewrite the
    # ``indexed_status`` column on every crawler CSV so the Reports UI
    # picks up the new state on the next render.
    indexed_status_backfill = backfill_indexed_status()

    log.info("gsc_coverage_builder: wrote %s (%s rows)", out_path.name, sum(counts.values()))
    return {
        "output": str(out_path),
        "indexed": counts["indexed"],
        "not_indexed": counts["not_indexed"],
        "excluded": counts["excluded"],
        "unknown": counts["unknown"],
        "indexed_urls_seen": len(indexed),
        "sitemap_urls_seen": len(sitemap_set),
        "crawler_urls_seen": len(crawler_status),
        "indexed_status_backfill": indexed_status_backfill,
    }


def _derive_status(url: str,
                   indexed: set[str],
                   sitemap_set: set[str],
                   crawler_status: dict[str, str]) -> str:
    """Map (indexed?, in_sitemap?, crawler_status_code?) -> GSC-style status.

    Important: we can confidently emit `indexed` (impressions exist) and
    `excluded` (crawler proved the URL is broken). For URLs without a GSC
    performance signal we deliberately emit a NEUTRAL status so the UI
    doesn't mislabel low-traffic indexed pages as "not indexed". A real
    not_indexed verdict only comes from URL Inspection API (see
    ``upgrade_with_url_inspection`` below) or a manual Coverage export.
    """
    if url in indexed:
        if url in sitemap_set:
            return "Submitted and indexed"
        return "Indexed, not submitted in sitemap"
    code = crawler_status.get(url)
    if code == "404":
        return "Not found (404)"
    if code and code.startswith(("4", "5")):
        return "URL is not on Google"
    # No performance signal — we honestly don't know. Don't claim
    # "not_indexed". Keep it unknown so the UI shows the right hedge.
    # (gsc_loader._STATUS_MAP turns this into the `unknown` bucket.)
    return "No GSC signal"


def _bucket_of(status: str) -> str:
    mapped = gsc_loader._STATUS_MAP.get(status.lower(), "unknown")
    return mapped if mapped != "unknown" else "unknown"


def _default_crawler_csv() -> Path:
    return settings.data_path / "crawl_results.csv"


def _crawler_status_map(path: Path | None) -> dict[str, str]:
    """Read status_code per URL from crawl_results.csv (normalised key)."""
    p = path or _default_crawler_csv()
    out: dict[str, str] = {}
    if not p.exists():
        return out
    try:
        with open(p, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                u = (row.get("url") or "").strip()
                if not u:
                    continue
                out[gsc_loader.normalize_url(u)] = (row.get("status_code") or "").strip()
    except OSError as exc:
        log.warning("gsc_coverage_builder: cannot read %s: %s", p, exc)
    return out


def _humanise(normalised: str) -> str:
    """Restore the trailing slash on roots so the CSV reads more naturally."""
    return normalised


# ── Backfills on existing CSVs ─────────────────────────────────────────────
_BACKFILL_FILES = (
    "crawl_results.csv",
    "crawl_errors.csv",
    "crawl_404_errors.csv",
    "crawl_errors_httperror.csv",
    "crawl_errors_connectionerror.csv",
    "crawl_errors_chunkedencodingerror.csv",
    "crawl_console_log.csv",
    "crawl_discovered.csv",
)


def backfill_from_sitemap(sitemap_seed: str = DEFAULT_SITEMAP,
                         data_dir: Path | None = None) -> dict:
    """Update the ``from_sitemap`` column on every crawler CSV based on the
    current live sitemap. Existing ``from_sitemap`` values are overwritten
    (this is the whole point — historic rows say ``unknown``).
    """
    data_dir = data_dir or settings.data_path
    sitemap_urls = {gsc_loader.normalize_url(u) for u in fetch_sitemap_urls(sitemap_seed)}
    if not sitemap_urls:
        return {"sitemap_urls": 0, "files": {}}

    summary: dict[str, dict] = {}
    for name in _BACKFILL_FILES:
        p = data_dir / name
        if not p.exists() or p.stat().st_size == 0:
            summary[name] = {"status": "missing", "updated": 0}
            continue
        summary[name] = _rewrite_column(
            p,
            column="from_sitemap",
            value_fn=lambda key: "1" if key and key in sitemap_urls else "0",
        )
    return {"sitemap_urls": len(sitemap_urls), "files": summary}


def backfill_indexed_status(data_dir: Path | None = None) -> dict:
    """Update the ``indexed_status`` column on every crawler CSV from the
    latest GSC coverage map. Called right after ``build_coverage()`` so
    crawler rows reflect the freshly derived indexing state.
    """
    data_dir = data_dir or settings.data_path
    gsc_loader.invalidate_cache()
    cov = gsc_loader.load_coverage_map()
    if not cov:
        return {"coverage_urls": 0, "files": {}}

    summary: dict[str, dict] = {}
    for name in _BACKFILL_FILES:
        p = data_dir / name
        if not p.exists() or p.stat().st_size == 0:
            summary[name] = {"status": "missing", "updated": 0}
            continue
        summary[name] = _rewrite_column(
            p,
            column="indexed_status",
            value_fn=lambda key: cov.get(key, "unknown"),
        )
    return {"coverage_urls": len(cov), "files": summary}


def _rewrite_column(path: Path, *, column: str, value_fn) -> dict:
    """Stream-rewrite ``path`` updating one column. Used by both backfills."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    updated = 0
    try:
        with open(path, "r", encoding="utf-8", newline="") as src, \
             open(tmp, "w", encoding="utf-8", newline="") as dst:
            reader = csv.DictReader(src)
            fieldnames = reader.fieldnames or []
            if column not in fieldnames:
                # Older file pre-dating the enrichment migration — leave it.
                return {"status": "skipped", "updated": 0}
            writer = csv.DictWriter(dst, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                u = (row.get("url") or "").strip()
                key = gsc_loader.normalize_url(u) if u else ""
                want = value_fn(key)
                if row.get(column) != want:
                    row[column] = want
                    updated += 1
                writer.writerow(row)
        tmp.replace(path)
        return {"status": "ok", "updated": updated}
    except Exception as exc:  # noqa: BLE001
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return {"status": "error", "updated": updated, "detail": str(exc)}


# ── URL Inspection API upgrade ─────────────────────────────────────────────
#
# Quota: ~2,000 inspections / day per property. The puller persists progress
# so it can resume the next day. Use this to convert the "unknown" rows
# (no GSC performance signal) into definitive indexed / not_indexed /
# excluded verdicts straight from Google.
def upgrade_with_url_inspection(
    site_url: str = "https://www.bajajlifeinsurance.com/",
    *,
    max_urls: int = 1900,           # leave headroom on the 2000/day quota
    only_unknown: bool = True,
    sleep_between: float = 0.4,     # rate-limit politely
) -> dict:
    """Call URL Inspection API for URLs whose status is `unknown` and
    rewrite the coverage CSV + crawler indexed_status with real verdicts.

    Requires OAuth credentials already in ``backend/data/gsc/`` (i.e. the
    user has run ``python backend/scripts/gsc_pull.py`` at least once).
    Falls back gracefully if the Google client libs aren't installed.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return {"ok": False, "error": "google-api-python-client not installed"}

    import time
    token = settings.data_path / "gsc" / "token.json"
    if not token.exists():
        return {"ok": False,
                "error": "No GSC OAuth token. Run backend/scripts/gsc_pull.py first."}

    scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
    creds = Credentials.from_authorized_user_file(str(token), scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    # Pick the URLs to inspect.
    cov = gsc_loader.load_coverage_map()
    targets: list[str] = []
    if only_unknown:
        # Look at crawler URLs that currently resolve to unknown.
        crawler_status = _crawler_status_map(None)
        for url, code in crawler_status.items():
            if cov.get(url, "unknown") == "unknown":
                targets.append(url)
    targets = targets[:max_urls]
    if not targets:
        return {"ok": True, "inspected": 0, "msg": "No unknown URLs to inspect."}

    # Inspect + collect.
    updates: dict[str, str] = {}
    successes = errors = 0
    for i, url in enumerate(targets):
        try:
            resp = svc.urlInspection().index().inspect(body={
                "inspectionUrl": url,
                "siteUrl": site_url,
            }).execute()
            state = (resp.get("inspectionResult", {})
                          .get("indexStatusResult", {})
                          .get("coverageState", "")
                          .strip())
            if state:
                updates[url] = state
                successes += 1
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status == 429:
                # quota hit — stop early
                log.warning("upgrade_with_url_inspection: 429 quota — stopping")
                break
            errors += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("upgrade_with_url_inspection: %s failed: %s", url, exc)
            errors += 1
        if sleep_between:
            time.sleep(sleep_between)

    # Merge updates into the coverage CSV and rewrite crawler indexed_status.
    merged = _merge_into_coverage(updates)
    backfill = backfill_indexed_status()
    return {
        "ok": True,
        "inspected": successes,
        "errors": errors,
        "remaining": max(0, len([u for u in targets if u not in updates])),
        "merged_into_coverage": merged,
        "backfill": backfill,
    }


def _merge_into_coverage(updates: dict[str, str]) -> int:
    """Append URL Inspection verdicts to the latest coverage CSV (or write a
    fresh one if none exists). Returns the number of rows updated/added.
    """
    if not updates:
        return 0
    COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    # Read latest coverage so we can union without losing prior rows.
    cov_path = None
    candidates = sorted(COVERAGE_DIR.glob("coverage_*.csv"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    cov_path = candidates[0] if candidates else None
    rows: dict[str, str] = {}
    if cov_path:
        with open(cov_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                u = (r.get("URL") or r.get("url") or "").strip()
                s = (r.get("Indexing status") or r.get("status") or "").strip()
                if u:
                    rows[gsc_loader.normalize_url(u)] = s
    for url, status in updates.items():
        rows[url] = status
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = COVERAGE_DIR / f"coverage_inspection_{today}.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["URL", "Indexing status", "Last crawled"])
        for url, status in sorted(rows.items()):
            w.writerow([url, status, ""])
    gsc_loader.invalidate_cache()
    return len(updates)


# ── Convenience for CLI / debugger ─────────────────────────────────────────
def format_summary(summary: dict) -> str:
    out = []
    if "output" in summary:
        out.append(f"Output: {summary['output']}")
        out.append(f"  indexed     = {summary['indexed']:>6}")
        out.append(f"  not_indexed = {summary['not_indexed']:>6}")
        out.append(f"  excluded    = {summary['excluded']:>6}")
        out.append(f"  unknown     = {summary['unknown']:>6}")
        out.append(f"  (from {summary['indexed_urls_seen']} performance URLs, "
                   f"{summary['sitemap_urls_seen']} sitemap URLs, "
                   f"{summary['crawler_urls_seen']} crawled URLs)")
    if "files" in summary:
        out.append("")
        out.append(f"Sitemap backfill ({summary['sitemap_urls']} sitemap URLs):")
        for name, info in summary["files"].items():
            out.append(f"  {name:<42} {info['status']:<8} updated={info.get('updated', 0)}")
    return "\n".join(out)
