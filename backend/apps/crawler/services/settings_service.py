"""Settings service — read/write the editable subset of a Website's
configuration that powers the dashboard's "Crawl configuration" card.

Settings are 1-to-1 with a :class:`Website` (each Website always has exactly
one :class:`CrawlConfig`). This service keeps the API view thin: the view
parses the query string + request body, then hands a plain ``dict`` payload
here. All validation and the Website/CrawlConfig field-routing live in this
module, so the wire format stays decoupled from the model layout.

The exclusion-paths feature called out in spec §5.4.8 is intentionally NOT
implemented here — it requires a new model field and migration which is out
of scope for the v1 vertical slice. The view layer can omit those keys from
the response; this service neither reads nor writes them.
"""

from __future__ import annotations

from typing import Any, Callable

from django.db import transaction

from apps.crawler.models import CrawlConfig, Website


# ─────────────────────────────────────────────────────────────────────────
# Field routing
# ─────────────────────────────────────────────────────────────────────────
#
# Editable keys live on one of two models. Splitting them up front keeps
# ``update_settings`` linear: validate -> route -> save the model(s) that
# actually changed (so we don't bump ``updated_at`` on a model whose row
# was untouched).
_WEBSITE_FIELDS: frozenset[str] = frozenset({
    "is_active",
    "include_subdomains",
})

_CONFIG_FIELDS: frozenset[str] = frozenset({
    "max_depth",
    "max_urls_per_session",
    "concurrency",
    "request_delay",
    "request_timeout",
    "max_retries",
    "enable_js_rendering",
    "respect_robots_txt",
    "custom_user_agent",
})

# Read-only keys appear in the response dict but are silently dropped from
# any update payload (alongside truly unknown keys). ``domain`` belongs to
# the website-CRUD endpoint, not Settings.
_READ_ONLY_KEYS: frozenset[str] = frozenset({"website_id", "domain"})


# ─────────────────────────────────────────────────────────────────────────
# Validators
# ─────────────────────────────────────────────────────────────────────────
#
# Each validator returns the coerced value or raises ``ValueError`` with a
# message of the form ``"<field>: <reason>"``. The view layer turns that
# into a DRF 400 response. Bool checks come first and use ``isinstance``
# so that the int-check on numeric fields can never accidentally accept
# ``True``/``False`` (Python's ``bool`` subclasses ``int``).

def _validate_bool(field: str, value: Any) -> bool:
    """Strict bool — rejects 0/1/"true" so the API contract stays explicit."""
    if not isinstance(value, bool):
        raise ValueError(
            f"{field}: must be a boolean (got {type(value).__name__})"
        )
    return value


def _validate_int_range(field: str, value: Any, lo: int, hi: int) -> int:
    # Reject bool explicitly — bool is a subclass of int in Python, so a
    # plain ``isinstance(v, int)`` would let ``True`` through as ``1``.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{field}: must be an integer (got {type(value).__name__})"
        )
    if value < lo or value > hi:
        raise ValueError(
            f"{field}: must be between {lo} and {hi} (got {value})"
        )
    return value


def _validate_float_range(field: str, value: Any, lo: float, hi: float) -> float:
    # Accept ints as floats (e.g. ``request_delay=2``) but never bools.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{field}: must be a number (got {type(value).__name__})"
        )
    coerced = float(value)
    if coerced < lo or coerced > hi:
        raise ValueError(
            f"{field}: must be between {lo} and {hi} (got {coerced})"
        )
    return coerced


def _validate_user_agent(field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f"{field}: must be a string (got {type(value).__name__})"
        )
    if len(value) > 500:
        raise ValueError(
            f"{field}: must be at most 500 characters (got {len(value)})"
        )
    return value


# Lookup table: field -> validator. Keeping this here (rather than as
# inline if/elif inside ``update_settings``) makes the ranges easy to
# spot-check against the spec.
_VALIDATORS: dict[str, Callable[[str, Any], Any]] = {
    # CrawlConfig
    "max_depth":            lambda f, v: _validate_int_range(f, v, 0, 50),
    "max_urls_per_session": lambda f, v: _validate_int_range(f, v, 1, 1_000_000),
    "concurrency":          lambda f, v: _validate_int_range(f, v, 1, 100),
    "request_delay":        lambda f, v: _validate_float_range(f, v, 0.0, 60.0),
    "request_timeout":      lambda f, v: _validate_int_range(f, v, 1, 300),
    "max_retries":          lambda f, v: _validate_int_range(f, v, 0, 10),
    "enable_js_rendering":  _validate_bool,
    "respect_robots_txt":   _validate_bool,
    "custom_user_agent":    _validate_user_agent,
    # Website
    "is_active":            _validate_bool,
    "include_subdomains":   _validate_bool,
}


# ─────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────

class SettingsService:
    """Read/write settings for a single Website's CrawlConfig.

    Settings are 1-to-1 with Website (a Website always has exactly one
    CrawlConfig). Reads return a snapshot dict; writes accept a partial
    dict and update only present fields (PATCH semantics).
    """

    @staticmethod
    def get_settings(website: Website) -> dict:
        """Return current settings dict for the website.

        Auto-creates a CrawlConfig row with model defaults if one is
        missing. New websites get a config via WebsiteCreateSerializer,
        but legacy rows or test fixtures may not — so this is defensive.
        """
        config, _ = CrawlConfig.objects.get_or_create(website=website)
        return _to_dict(website, config)

    @staticmethod
    @transaction.atomic
    def update_settings(website: Website, payload: dict) -> dict:
        """Apply partial updates and return the new settings dict.

        Validates each field's range. Raises :class:`ValueError` with the
        field name + reason on bad input — the view layer translates it
        into a 400 response. Unknown keys (and any read-only keys like
        ``domain``) are silently ignored, matching standard PATCH semantics.
        """
        config, _ = CrawlConfig.objects.get_or_create(website=website)

        website_updates: dict[str, Any] = {}
        config_updates: dict[str, Any] = {}

        for key, raw_value in payload.items():
            if key in _READ_ONLY_KEYS or key not in _VALIDATORS:
                # Unknown / read-only keys are dropped per PATCH semantics.
                continue
            value = _VALIDATORS[key](key, raw_value)
            if key in _WEBSITE_FIELDS:
                website_updates[key] = value
            elif key in _CONFIG_FIELDS:
                config_updates[key] = value

        # Save only the model(s) that actually changed — otherwise we'd
        # bump ``updated_at`` on a row no one touched.
        if website_updates:
            for field, value in website_updates.items():
                setattr(website, field, value)
            website.save(update_fields=list(website_updates.keys()))

        if config_updates:
            for field, value in config_updates.items():
                setattr(config, field, value)
            config.save(update_fields=list(config_updates.keys()))

        return _to_dict(website, config)


def _to_dict(website: Website, config: CrawlConfig) -> dict:
    """Project a (Website, CrawlConfig) pair into the API snapshot shape."""
    return {
        "website_id":           str(website.id),
        "domain":               website.domain,
        "is_active":            website.is_active,
        "include_subdomains":   website.include_subdomains,
        "max_depth":            config.max_depth,
        "max_urls_per_session": config.max_urls_per_session,
        "concurrency":          config.concurrency,
        "request_delay":        config.request_delay,
        "request_timeout":      config.request_timeout,
        "max_retries":          config.max_retries,
        "enable_js_rendering":  config.enable_js_rendering,
        "respect_robots_txt":   config.respect_robots_txt,
        "custom_user_agent":    config.custom_user_agent,
    }
