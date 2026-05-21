"""Apify Meta Ad Library adapter — competitor ad intelligence.

The Bajaj corporate Cisco WSA filter blocks ``graph.facebook.com`` at
the URL-category layer (social-media), so the official Meta Graph API
(``/ads_archive`` endpoint) can't be called directly from the
container/host. Apify's "Facebook Ad Library Scraper" actor
(``curious_coder/facebook-ads-library-scraper``) scrapes the public
Ad Library from Apify's own infrastructure and returns the JSON via
``api.apify.com`` — the same vendor pattern we already use for SEMrush
and PSI.

Auth: a single Apify personal-API token (Bearer header).

Cost: ~$0.75 per 1000 ads. Default config pulls 25 ads per competitor
for 8 competitors = ~200 ads = ~$0.15 per refresh. The 24-hour disk
cache means a typical day costs at most $0.15.

Public surface:

    ApifyMetaAdsAdapter().dashboard(competitors=[...])
        → returns a dict with per-competitor ad lists + aggregates.

The view layer hands the dict back to the React page verbatim.

Errors degrade gracefully — a failed actor call returns
``available=True, error="..."`` with empty rows so the UI still
renders the page chrome instead of 500-ing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
from django.conf import settings

# Corp MITM TLS — same pattern as the rest of the adapters.
try:
    import truststore  # noqa: F401
    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

logger = logging.getLogger("apps.seo_ai.adapters.apify_meta_ads")


# ── exceptions ───────────────────────────────────────────────────────


class AdapterDisabledError(RuntimeError):
    """Raised at init when no APIFY_API_TOKEN is configured."""


class ApifyMetaAdsError(RuntimeError):
    """Apify API failure — network / actor error / non-JSON response."""

    def __init__(self, message: str, *, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ── dataclasses ──────────────────────────────────────────────────────


@dataclass
class MetaAdCard:
    """One creative card inside an ad — most ads have 1, carousels have N."""
    title: str = ""
    body: str = ""
    link_url: str = ""
    cta_text: str = ""
    image_url: str = ""
    video_url: str = ""


@dataclass
class MetaAd:
    """One Meta Ad Library row, flattened to a small UI-friendly shape."""
    ad_archive_id: str
    page_name: str
    page_id: str
    page_profile_url: str
    page_profile_picture_url: str
    start_date_iso: str
    end_date_iso: str
    is_active: bool
    publisher_platforms: list[str]
    languages: list[str]
    categories: list[str]
    cta_text: str
    primary_link_url: str
    cards: list[MetaAdCard] = field(default_factory=list)
    raw_caption: str = ""


@dataclass
class CompetitorAdsSummary:
    """Per-competitor aggregate — what we show in the dashboard."""
    competitor: str
    total_ads: int
    active_ads: int
    page_name: str = ""
    page_id: str = ""
    page_profile_picture_url: str = ""
    top_landing_domains: list[dict] = field(default_factory=list)   # [{domain, count}]
    top_landing_paths: list[dict] = field(default_factory=list)     # [{path, count}]
    top_ctas: list[dict] = field(default_factory=list)              # [{cta, count}]
    publisher_platforms: list[dict] = field(default_factory=list)   # [{platform, count}]
    common_themes: list[dict] = field(default_factory=list)         # [{theme, count}]
    new_ads_last_7d: int = 0
    ads: list[MetaAd] = field(default_factory=list)
    error: str = ""


@dataclass
class MetaAdsDashboard:
    """End-to-end dashboard payload."""
    available: bool
    country: str
    refreshed_at: str
    cost_estimate_usd: float = 0.0
    total_ads_fetched: int = 0
    competitors_processed: int = 0
    competitors: list[CompetitorAdsSummary] = field(default_factory=list)
    error: str = ""


# ── helpers ──────────────────────────────────────────────────────────


def _resolve_ssl_verify(raw: str) -> bool | str:
    value = (raw or "").strip()
    if not value or value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    if os.path.exists(value):
        return value
    return True


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "unknown"


def _epoch_to_iso(epoch: Any) -> str:
    """Convert a Unix epoch number (seconds) to ISO date. Empty if invalid."""
    try:
        n = int(epoch)
        if n <= 0:
            return ""
        from datetime import datetime, timezone
        return datetime.fromtimestamp(n, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


_THEME_KEYWORDS = [
    ("Tax saving", re.compile(r"\b(tax\s+sav|80c|sec(?:tion)?\s*80)\b", re.I)),
    ("Premium calculator", re.compile(r"\b(premium\s+calc|calculate\s+premium)\b", re.I)),
    ("Family protection", re.compile(r"\b(family|loved\s+ones|protect\s+your)\b", re.I)),
    ("Retirement / pension", re.compile(r"\b(retire|pension|lifelong\s+income)\b", re.I)),
    ("Child plan", re.compile(r"\b(child|kid'?s?\s+future|education\s+plan)\b", re.I)),
    ("Term insurance", re.compile(r"\bterm\s+(?:insurance|plan|cover)\b", re.I)),
    ("ULIP / investment", re.compile(r"\b(ulip|investment\s+plan|wealth)\b", re.I)),
    ("Critical illness", re.compile(r"\b(critical\s+illness|cancer|heart)\b", re.I)),
    ("Guaranteed return", re.compile(r"\b(guaranteed\s+(?:return|income))\b", re.I)),
    ("Health / hospitalisation", re.compile(r"\b(health\s+cover|hospital|medical)\b", re.I)),
]


def _classify_themes(text: str) -> list[str]:
    if not text:
        return []
    hits: list[str] = []
    for label, rx in _THEME_KEYWORDS:
        if rx.search(text):
            hits.append(label)
    return hits


def _ad_library_url(query: str, country: str = "IN") -> str:
    """Build the public Ad Library search URL the scraper actor consumes."""
    return (
        "https://www.facebook.com/ads/library/"
        f"?active_status=active&ad_type=all&country={country}"
        f"&q={quote(query)}&search_type=keyword_unordered"
    )


# ── adapter ──────────────────────────────────────────────────────────


class ApifyMetaAdsAdapter:
    """Pull Meta Ad Library data via Apify's actor."""

    def __init__(self) -> None:
        cfg = getattr(settings, "APIFY", None) or {}
        if not cfg.get("enabled") or not cfg.get("api_token"):
            raise AdapterDisabledError(
                "Apify adapter disabled — set APIFY_API_TOKEN in .env."
            )
        self.token: str = cfg["api_token"]
        self.actor: str = cfg.get(
            "meta_ads_actor", "curious_coder~facebook-ads-library-scraper",
        )
        self.default_competitors: list[str] = list(
            cfg.get("default_meta_ads_competitors") or []
        )
        self.default_country: str = cfg.get("default_country", "IN")
        self.default_count: int = max(
            10, int(cfg.get("default_count_per_competitor", 25)),
        )
        self.cache_ttl: int = int(cfg.get("cache_ttl_seconds", 24 * 3600))
        self.verify = _resolve_ssl_verify(cfg.get("ssl_verify", "false"))
        if self.verify is False:
            try:
                import urllib3
                urllib3.disable_warnings(
                    urllib3.exceptions.InsecureRequestWarning
                )
            except Exception:  # noqa: BLE001
                pass

        # Disk cache — one JSON per (competitor, country, count) so a
        # repeated dashboard render doesn't burn Apify credit.
        from django.conf import settings as dj_settings
        self.cache_dir = (
            Path(dj_settings.BASE_DIR) / "data" / "meta_ads_cache"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────

    def fetch_for_competitor(
        self,
        competitor: str,
        *,
        country: str | None = None,
        count: int | None = None,
        force_refresh: bool = False,
    ) -> list[dict]:
        """Pull raw ad records for one competitor. Returns the list of
        raw Apify items (dicts) — caller decides how to slim them. Uses
        the disk cache by default; pass ``force_refresh=True`` to
        bypass."""
        country = country or self.default_country
        count = max(10, int(count or self.default_count))

        cached = self._cache_read(competitor, country, count)
        if cached is not None and not force_refresh:
            logger.info(
                "apify meta-ads: cache hit for %r (%d records)",
                competitor, len(cached),
            )
            return cached

        url = (
            f"https://api.apify.com/v2/acts/{self.actor}/"
            "run-sync-get-dataset-items"
        )
        payload = {
            "urls": [{"url": _ad_library_url(competitor, country)}],
            "count": count,
        }
        logger.info(
            "apify meta-ads: running actor for %r country=%s count=%d",
            competitor, country, count,
        )
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300,
                verify=self.verify,
            )
        except requests.RequestException as exc:
            raise ApifyMetaAdsError(
                f"Apify call network failure: {exc}",
            ) from exc

        if resp.status_code not in (200, 201):
            raise ApifyMetaAdsError(
                f"Apify actor returned HTTP {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text[:600],
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise ApifyMetaAdsError(
                "Apify response was not valid JSON",
                status_code=resp.status_code,
                body=resp.text[:600],
            ) from exc

        if not isinstance(data, list):
            raise ApifyMetaAdsError(
                f"Apify response is not a list (got {type(data).__name__})",
            )

        # Some runs return a single {"error": "..."} item to signal a
        # validation failure (e.g. count below 10). Surface as error.
        if len(data) == 1 and isinstance(data[0], dict) and "error" in data[0] and "ad_archive_id" not in data[0]:
            raise ApifyMetaAdsError(
                f"Apify actor refused input: {data[0].get('error')}",
            )

        self._cache_write(competitor, country, count, data)
        return data

    def dashboard(
        self,
        *,
        competitors: list[str] | None = None,
        country: str | None = None,
        count: int | None = None,
        force_refresh: bool = False,
    ) -> MetaAdsDashboard:
        """Pull ads for every competitor + assemble dashboard payload."""
        from datetime import datetime, timezone, timedelta

        competitors = competitors or self.default_competitors
        country = country or self.default_country
        count = max(10, int(count or self.default_count))
        if not competitors:
            return MetaAdsDashboard(
                available=False, country=country, refreshed_at="",
                error="No competitors configured (set APIFY_META_ADS_COMPETITORS).",
            )

        dash = MetaAdsDashboard(
            available=True,
            country=country,
            refreshed_at=datetime.now(timezone.utc).isoformat(),
        )

        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date()
        total_records = 0

        for comp in competitors:
            try:
                raw = self.fetch_for_competitor(
                    comp, country=country, count=count,
                    force_refresh=force_refresh,
                )
            except ApifyMetaAdsError as exc:
                logger.warning("meta-ads: %s failed: %s", comp, exc)
                dash.competitors.append(CompetitorAdsSummary(
                    competitor=comp, total_ads=0, active_ads=0,
                    error=str(exc),
                ))
                continue

            ads = [self._normalize_ad(r) for r in raw if isinstance(r, dict) and r.get("ad_archive_id")]
            total_records += len(ads)

            summary = CompetitorAdsSummary(
                competitor=comp,
                total_ads=len(ads),
                active_ads=sum(1 for a in ads if a.is_active),
                ads=ads,
            )
            if ads:
                first = ads[0]
                summary.page_name = first.page_name
                summary.page_id = first.page_id
                summary.page_profile_picture_url = first.page_profile_picture_url

            # Aggregates
            domain_counter: Counter[str] = Counter()
            path_counter: Counter[str] = Counter()
            cta_counter: Counter[str] = Counter()
            platform_counter: Counter[str] = Counter()
            theme_counter: Counter[str] = Counter()
            new_count = 0

            for ad in ads:
                if ad.start_date_iso:
                    try:
                        from datetime import date as _date
                        if _date.fromisoformat(ad.start_date_iso) >= seven_days_ago:
                            new_count += 1
                    except (TypeError, ValueError):
                        pass
                if ad.primary_link_url:
                    try:
                        p = urlparse(ad.primary_link_url)
                        if p.netloc:
                            domain_counter[p.netloc.lower().lstrip("www.")] += 1
                        if p.path and p.path not in ("/", ""):
                            path_counter[p.path] += 1
                    except ValueError:
                        pass
                if ad.cta_text:
                    cta_counter[ad.cta_text] += 1
                for pf in ad.publisher_platforms:
                    platform_counter[pf] += 1
                blob = " ".join(
                    [ad.raw_caption or ""]
                    + [c.title or "" for c in ad.cards]
                    + [c.body or "" for c in ad.cards]
                )
                for theme in _classify_themes(blob):
                    theme_counter[theme] += 1

            summary.top_landing_domains = [
                {"domain": k, "count": v} for k, v in domain_counter.most_common(8)
            ]
            summary.top_landing_paths = [
                {"path": k, "count": v} for k, v in path_counter.most_common(8)
            ]
            summary.top_ctas = [
                {"cta": k, "count": v} for k, v in cta_counter.most_common(6)
            ]
            summary.publisher_platforms = [
                {"platform": k, "count": v} for k, v in platform_counter.most_common(6)
            ]
            summary.common_themes = [
                {"theme": k, "count": v} for k, v in theme_counter.most_common(8)
            ]
            summary.new_ads_last_7d = new_count

            dash.competitors.append(summary)

        dash.total_ads_fetched = total_records
        dash.competitors_processed = sum(1 for c in dash.competitors if c.total_ads > 0)
        # Apify pricing: $0.75 per 1000 results.
        dash.cost_estimate_usd = round(total_records * 0.00075, 4)
        return dash

    # ── normalisation ─────────────────────────────────────────────────

    def _normalize_ad(self, raw: dict) -> MetaAd:
        """Flatten Apify's raw Ad Library item to the slim MetaAd dataclass.

        Apify mirrors Facebook's nested ``snapshot.cards[*]`` schema —
        we extract the bits the dashboard cares about and ignore the
        rest (audio_node, fev_info, regional_regulation_data, etc.).
        """
        snap = raw.get("snapshot") or {}
        cards_raw = snap.get("cards") or []
        cards: list[MetaAdCard] = []
        for c in cards_raw:
            if not isinstance(c, dict):
                continue
            cards.append(MetaAdCard(
                title=(c.get("title") or "")[:512],
                body=(c.get("body") or "")[:2048],
                link_url=(c.get("link_url") or "")[:2048],
                cta_text=(c.get("cta_text") or "")[:64],
                image_url=(
                    c.get("image_url")
                    or c.get("original_image_url")
                    or c.get("resized_image_url")
                    or ""
                )[:2048],
                video_url=(
                    c.get("video_hd_url")
                    or c.get("video_sd_url")
                    or ""
                )[:2048],
            ))

        # Fallback to top-level snapshot fields when card list is empty.
        if not cards:
            cards.append(MetaAdCard(
                title=(snap.get("title") or "")[:512],
                body=(snap.get("body", {}) or {}).get("text", "")[:2048] if isinstance(snap.get("body"), dict) else (snap.get("body") or "")[:2048],
                link_url=(snap.get("link_url") or "")[:2048],
                cta_text=(snap.get("cta_text") or "")[:64],
                image_url=(
                    snap.get("image_url")
                    or (snap.get("images") or [{}])[0].get("original_image_url", "")
                )[:2048],
                video_url="",
            ))

        primary_link = next(
            (c.link_url for c in cards if c.link_url and "fb.me" not in c.link_url),
            cards[0].link_url if cards else "",
        )
        cta_text = next((c.cta_text for c in cards if c.cta_text), snap.get("cta_text") or "")

        return MetaAd(
            ad_archive_id=str(raw.get("ad_archive_id") or ""),
            page_name=str(raw.get("page_name") or snap.get("page_name") or ""),
            page_id=str(raw.get("page_id") or snap.get("page_id") or ""),
            page_profile_url=str(snap.get("page_profile_uri") or ""),
            page_profile_picture_url=str(snap.get("page_profile_picture_url") or ""),
            start_date_iso=_epoch_to_iso(raw.get("start_date")),
            end_date_iso=_epoch_to_iso(raw.get("end_date")),
            is_active=bool(raw.get("is_active")),
            publisher_platforms=[
                str(p) for p in (raw.get("publisher_platform") or [])
            ][:8],
            languages=[
                str(lng) for lng in (snap.get("languages") or [])
            ][:6],
            categories=[
                str(c) for c in (raw.get("categories") or [])
            ][:6],
            cta_text=str(cta_text or "")[:64],
            primary_link_url=str(primary_link or "")[:2048],
            cards=cards,
            raw_caption=str(snap.get("caption") or "")[:256],
        )

    # ── disk cache ────────────────────────────────────────────────────

    def _cache_path(self, competitor: str, country: str, count: int) -> Path:
        key = hashlib.sha1(
            f"{_slugify(competitor)}|{country}|{count}".encode("utf-8")
        ).hexdigest()[:16]
        return self.cache_dir / f"{_slugify(competitor)}_{country}_{count}_{key}.json"

    def _cache_read(self, competitor: str, country: str, count: int) -> list[dict] | None:
        path = self._cache_path(competitor, country, count)
        if not path.exists():
            return None
        try:
            mtime = path.stat().st_mtime
            if (time.time() - mtime) > self.cache_ttl:
                return None
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.info("meta-ads cache read failed for %s: %s", competitor, exc)
        return None

    def _cache_write(
        self, competitor: str, country: str, count: int, data: list,
    ) -> None:
        path = self._cache_path(competitor, country, count)
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            tmp.replace(path)
        except OSError as exc:
            logger.warning("meta-ads cache write failed for %s: %s", competitor, exc)


# ── view helper ──────────────────────────────────────────────────────


def dashboard_payload(
    *,
    competitors: list[str] | None = None,
    country: str | None = None,
    count: int | None = None,
    force_refresh: bool = False,
) -> dict:
    """View-layer convenience — returns the dict the React page consumes."""
    try:
        adapter = ApifyMetaAdsAdapter()
    except AdapterDisabledError as exc:
        return {
            "available": False,
            "reason": "not_configured",
            "error": str(exc),
        }
    dash = adapter.dashboard(
        competitors=competitors, country=country, count=count,
        force_refresh=force_refresh,
    )
    return asdict(dash)
