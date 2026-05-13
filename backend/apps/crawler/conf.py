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
