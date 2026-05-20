"""Crawler configuration — Django-settings backed.

Drop-in replacement for ``crawler-engine/app/core/config.py``. Values come
from ``django.conf.settings`` (which itself reads ``backend/.env`` via
``python-dotenv`` if loaded) and fall back to the same defaults the
pydantic-settings version used.

Accessed via ``apps.crawler.conf.settings`` so existing call sites that
were written against the old ``from ..core.config import settings`` shape
continue to work after import paths are rewritten.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from django.conf import settings as dj_settings

BACKEND_ROOT: Path = Path(dj_settings.BASE_DIR)
PROJECT_ROOT: Path = BACKEND_ROOT.parent


def _env_str(key: str, default: str) -> str:
    raw = os.environ.get(f"CRAWLER_{key}")
    if raw is None:
        raw = getattr(dj_settings, f"CRAWLER_{key}", None)
    return default if raw is None else str(raw)


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env_str(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env_str(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = _env_str(key, "true" if default else "false").strip().lower()
    return raw in ("1", "true", "yes", "on", "y", "t")


def _env_csv(key: str, default: List[str]) -> List[str]:
    raw = _env_str(key, "")
    if not raw:
        return list(default)
    return [s.strip() for s in raw.split(",") if s.strip()]


@dataclass
class CrawlerSettings:
    """Runtime crawler configuration. Mirrors crawler-engine pydantic Settings.

    Field defaults match crawler-engine/.env.example so behaviour is identical
    on first boot. Override any field via env vars prefixed ``CRAWLER_`` or
    Django settings attributes of the same name.
    """

    # ── Crawler ──────────────────────────────────────────────
    seed_url: str = field(
        default_factory=lambda: _env_str(
            "SEED_URL", "https://www.bajajlifeinsurance.com/",
        )
    )
    allowed_domains: List[str] = field(
        default_factory=lambda: _env_csv(
            "ALLOWED_DOMAINS",
            ["bajajlifeinsurance.com", "www.bajajlifeinsurance.com"],
        )
    )
    user_agent: str = field(
        default_factory=lambda: _env_str(
            "USER_AGENT",
            "Mozilla/5.0 (compatible; BajajCrawler/2.0; "
            "+https://www.bajajlifeinsurance.com/)",
        )
    )
    request_timeout: int = field(default_factory=lambda: _env_int("REQUEST_TIMEOUT", 30))
    max_workers: int = field(default_factory=lambda: _env_int("MAX_WORKERS", 12))
    per_worker_delay: float = field(
        default_factory=lambda: _env_float("PER_WORKER_DELAY", 0.2)
    )
    checkpoint_every: int = field(
        default_factory=lambda: _env_int("CHECKPOINT_EVERY", 500)
    )
    respect_robots: bool = field(
        default_factory=lambda: _env_bool("RESPECT_ROBOTS", True)
    )

    # ── TLS / response-size guards ───────────────────────────
    # ssl_verify accepts: "" / "true" → True (default certifi+truststore)
    #                     "false"     → disable (only for corp MITM proxies)
    #                     "/path/to/ca.pem" → custom CA bundle
    # Mirrors SEMRUSH_SSL_VERIFY / COMPETITOR_SSL_VERIFY semantics.
    ssl_verify: str = field(
        default_factory=lambda: _env_str("SSL_VERIFY", "true")
    )
    # Hard ceiling on HTML body bytes per page. **0 = unlimited
    # (default).** The in-house crawler only hits our own domain, so
    # no defensive cap is needed — every page must be captured no
    # matter the size. Set CRAWLER_MAX_BODY_BYTES to a positive
    # integer (e.g., 104857600 for 100 MB) if you ever want a safety
    # net for crawling third-party domains. The competitor crawler
    # has its own COMPETITOR_MAX_BODY_BYTES knob and uses a 5 MB
    # default because untrusted hosts can serve pathological responses.
    max_body_bytes: int = field(
        default_factory=lambda: _env_int("MAX_BODY_BYTES", 0)
    )
    # In-memory state caps. Crawler streams to CSV anyway; the in-process
    # lists were originally for "recent activity" UI. Past this many
    # entries we drop the oldest. 0 = unbounded (legacy behaviour).
    results_buffer_cap: int = field(
        default_factory=lambda: _env_int("RESULTS_BUFFER_CAP", 2000)
    )

    # ── Full-site crawl: completeness & resilience ───────────
    max_depth: int = field(default_factory=lambda: _env_int("MAX_DEPTH", 0))
    max_pages: int = field(default_factory=lambda: _env_int("MAX_PAGES", 0))
    max_retries: int = field(default_factory=lambda: _env_int("MAX_RETRIES", 4))
    retry_backoff_base: float = field(
        default_factory=lambda: _env_float("RETRY_BACKOFF_BASE", 1.5)
    )
    retry_backoff_cap: float = field(
        default_factory=lambda: _env_float("RETRY_BACKOFF_CAP", 45.0)
    )
    respect_crawl_delay: bool = field(
        default_factory=lambda: _env_bool("RESPECT_CRAWL_DELAY", True)
    )
    extra_request_delay: float = field(
        default_factory=lambda: _env_float("EXTRA_REQUEST_DELAY", 0.0)
    )
    resume: bool = field(default_factory=lambda: _env_bool("RESUME", True))
    max_url_length: int = field(
        default_factory=lambda: _env_int("MAX_URL_LENGTH", 2048)
    )
    max_query_params: int = field(
        default_factory=lambda: _env_int("MAX_QUERY_PARAMS", 16)
    )
    max_path_segments: int = field(
        default_factory=lambda: _env_int("MAX_PATH_SEGMENTS", 30)
    )
    sitemap_max_depth: int = field(
        default_factory=lambda: _env_int("SITEMAP_MAX_DEPTH", 6)
    )

    # ── Phase-2 console capture (Playwright) ──────────────────────────
    # After the static crawl finishes, optionally launch headless
    # Chromium on a subset of www HTTP-200 pages to capture real JS
    # errors. Adds ~3 sec/URL — at limit=200 that's ~10 minutes after
    # the regular crawl. Set CRAWLER_CAPTURE_CONSOLE_AFTER_CRAWL=false
    # in .env to skip the phase entirely.
    capture_console_after_crawl: bool = field(
        default_factory=lambda: _env_bool("CAPTURE_CONSOLE_AFTER_CRAWL", True)
    )
    console_capture_limit: int = field(
        default_factory=lambda: _env_int("CONSOLE_CAPTURE_LIMIT", 200)
    )

    # ── Phase-3 PSI / Core Web Vitals capture ────────────────────────
    # After the console phase, hit Google's PSI API on a subset of www
    # HTTP-200 pages to capture LCP / CLS / INP / FCP / TBT / TTFB
    # (lab + CrUX field). Slow: ~1-3s/URL on mobile, 30-40s on desktop.
    # With limit=100 + both strategies expect ~10-40 min after the
    # console phase. Skip with CRAWLER_CAPTURE_PSI_AFTER_CRAWL=false.
    capture_psi_after_crawl: bool = field(
        default_factory=lambda: _env_bool("CAPTURE_PSI_AFTER_CRAWL", True)
    )
    psi_capture_limit: int = field(
        default_factory=lambda: _env_int("PSI_CAPTURE_LIMIT", 100)
    )

    # ── Data dirs ────────────────────────────────────────────
    data_dir: str = field(default_factory=lambda: _env_str("DATA_DIR", ""))
    reports_dir: str = field(default_factory=lambda: _env_str("REPORTS_DIR", ""))

    # ── Log level ────────────────────────────────────────────
    log_level: str = field(default_factory=lambda: _env_str("LOG_LEVEL", "INFO"))

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir) if self.data_dir else BACKEND_ROOT / "data"

    @property
    def reports_path(self) -> Path:
        return Path(self.reports_dir) if self.reports_dir else BACKEND_ROOT / "reports"

    @property
    def legacy_data_path(self) -> Path:
        """Pre-existing crawl outputs to seed from on first boot (optional)."""
        return PROJECT_ROOT.parent / "data_complete"


_singleton: CrawlerSettings | None = None


def _load() -> CrawlerSettings:
    global _singleton
    if _singleton is None:
        _singleton = CrawlerSettings()
        os.makedirs(_singleton.data_path, exist_ok=True)
        os.makedirs(_singleton.reports_path, exist_ok=True)
    return _singleton


settings = _load()
