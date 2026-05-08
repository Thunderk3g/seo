"""Unit tests for :class:`SettingsService`.

Covers the read/write contract that powers the dashboard's
"Crawl configuration" + "Inclusions/exclusions" cards
(spec §5.4.8). All tests hit the ORM via the ``db`` fixture — there is
no view layer here; that's exercised separately once the integration
spec lands in ``views.py``.
"""

from __future__ import annotations

import pytest

from apps.common import constants
from apps.crawler.models import CrawlConfig, Website
from apps.crawler.services.settings_service import SettingsService


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture
def website(db):
    """A bare Website with the auto-created CrawlConfig already wired."""
    site = Website.objects.create(domain="example.test", name="Example")
    CrawlConfig.objects.create(website=site)
    return site


@pytest.fixture
def website_no_config(db):
    """Edge case: a Website whose CrawlConfig was deleted (or never made)."""
    site = Website.objects.create(domain="legacy.test", name="Legacy")
    # Defensive cleanup — ensures no stray config from a fixture chain.
    CrawlConfig.objects.filter(website=site).delete()
    return site


# ─────────────────────────────────────────────────────────────────────────
# get_settings
# ─────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_get_settings_creates_default_config_if_missing(website_no_config):
    """get_settings must self-heal a missing CrawlConfig with model defaults."""
    assert not CrawlConfig.objects.filter(website=website_no_config).exists()

    result = SettingsService.get_settings(website_no_config)

    # Row was materialized.
    assert CrawlConfig.objects.filter(website=website_no_config).exists()

    # Returned dict carries the model defaults.
    assert result["max_depth"] == constants.DEFAULT_MAX_DEPTH
    assert result["max_urls_per_session"] == constants.DEFAULT_MAX_URLS_PER_SESSION
    assert result["concurrency"] == constants.DEFAULT_CONCURRENCY
    assert result["request_delay"] == constants.DEFAULT_REQUEST_DELAY
    assert result["request_timeout"] == constants.DEFAULT_REQUEST_TIMEOUT
    assert result["max_retries"] == constants.DEFAULT_MAX_RETRIES
    assert result["enable_js_rendering"] is False
    assert result["respect_robots_txt"] is True
    assert result["custom_user_agent"] == ""

    # Website-level fields round-trip too.
    assert result["website_id"] == str(website_no_config.id)
    assert result["domain"] == "legacy.test"


@pytest.mark.django_db
def test_get_settings_returns_persisted_values(website):
    """Custom values on disk surface verbatim in the snapshot dict."""
    config = website.crawl_config
    config.max_depth = 12
    config.concurrency = 25
    config.request_delay = 0.5
    config.enable_js_rendering = True
    config.custom_user_agent = "MyBot/1.0"
    config.save()
    website.is_active = False
    website.include_subdomains = True
    website.save()

    result = SettingsService.get_settings(website)

    assert result["max_depth"] == 12
    assert result["concurrency"] == 25
    assert result["request_delay"] == 0.5
    assert result["enable_js_rendering"] is True
    assert result["custom_user_agent"] == "MyBot/1.0"
    assert result["is_active"] is False
    assert result["include_subdomains"] is True


# ─────────────────────────────────────────────────────────────────────────
# update_settings — happy path
# ─────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_update_settings_partial_payload(website):
    """A partial PATCH must only touch the keys it sends."""
    config = website.crawl_config
    config.max_depth = 7
    config.concurrency = 8
    config.request_delay = 1.0
    config.save()

    result = SettingsService.update_settings(website, {"max_depth": 5})

    # Returned dict reflects the change…
    assert result["max_depth"] == 5
    # …and leaves untouched fields alone.
    assert result["concurrency"] == 8
    assert result["request_delay"] == 1.0

    # Persisted state matches: reload from DB to be sure.
    config.refresh_from_db()
    assert config.max_depth == 5
    assert config.concurrency == 8
    assert config.request_delay == 1.0


@pytest.mark.django_db
def test_update_settings_unknown_key_ignored(website):
    """Unknown keys are dropped silently; valid siblings still apply."""
    result = SettingsService.update_settings(
        website, {"max_depth": 5, "foo": "bar", "domain": "evil.test"},
    )

    assert result["max_depth"] == 5
    assert "foo" not in result
    # Domain is read-only — must not have been clobbered.
    assert result["domain"] == "example.test"
    website.refresh_from_db()
    assert website.domain == "example.test"


@pytest.mark.django_db
def test_update_settings_request_delay_float_accepted(website):
    """Float values in range round-trip cleanly."""
    result = SettingsService.update_settings(website, {"request_delay": 1.5})

    assert result["request_delay"] == 1.5
    website.crawl_config.refresh_from_db()
    assert website.crawl_config.request_delay == 1.5


@pytest.mark.django_db
def test_update_settings_website_field_changes(website):
    """is_active / include_subdomains route to Website, not CrawlConfig."""
    assert website.is_active is True
    assert website.include_subdomains is False

    SettingsService.update_settings(website, {"is_active": False})
    website.refresh_from_db()
    assert website.is_active is False

    SettingsService.update_settings(website, {"include_subdomains": True})
    website.refresh_from_db()
    assert website.include_subdomains is True


# ─────────────────────────────────────────────────────────────────────────
# update_settings — validation failures
# ─────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_update_settings_max_depth_out_of_range_high(website):
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(website, {"max_depth": 100})
    assert "max_depth" in str(exc.value)


@pytest.mark.django_db
def test_update_settings_max_depth_out_of_range_low(website):
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(website, {"max_depth": -1})
    assert "max_depth" in str(exc.value)


@pytest.mark.django_db
def test_update_settings_concurrency_zero_rejected(website):
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(website, {"concurrency": 0})
    assert "concurrency" in str(exc.value)


@pytest.mark.django_db
def test_update_settings_request_delay_too_high(website):
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(website, {"request_delay": 100})
    assert "request_delay" in str(exc.value)


@pytest.mark.django_db
def test_update_settings_user_agent_too_long(website):
    long_ua = "x" * 501
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(website, {"custom_user_agent": long_ua})
    assert "custom_user_agent" in str(exc.value)


@pytest.mark.django_db
def test_update_settings_boolean_with_int_rejected(website):
    """Strict bool check — ``1`` must not be coerced to ``True``."""
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(website, {"enable_js_rendering": 1})
    assert "enable_js_rendering" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────
# excluded_paths / excluded_params — JSON list validators
# ─────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_excluded_paths_default_is_empty_list(website):
    """Fresh CrawlConfig surfaces empty lists — never None."""
    result = SettingsService.get_settings(website)
    assert result["excluded_paths"] == []
    assert result["excluded_params"] == []


@pytest.mark.django_db
def test_update_excluded_paths_round_trip(website):
    """Set then re-read — the persisted list comes back verbatim."""
    payload = {"excluded_paths": ["/admin", "/private"]}
    result = SettingsService.update_settings(website, payload)
    assert result["excluded_paths"] == ["/admin", "/private"]

    # Fresh fetch from DB — confirms it actually persisted, not just
    # echoed from the input dict.
    website.crawl_config.refresh_from_db()
    assert website.crawl_config.excluded_paths == ["/admin", "/private"]
    refetched = SettingsService.get_settings(website)
    assert refetched["excluded_paths"] == ["/admin", "/private"]


@pytest.mark.django_db
def test_update_excluded_params_round_trip(website):
    payload = {"excluded_params": ["utm_source", "fbclid", "gclid"]}
    result = SettingsService.update_settings(website, payload)
    assert result["excluded_params"] == ["utm_source", "fbclid", "gclid"]

    website.crawl_config.refresh_from_db()
    assert website.crawl_config.excluded_params == [
        "utm_source", "fbclid", "gclid",
    ]


@pytest.mark.django_db
def test_update_excluded_paths_empty_list_clears(website):
    """Sending [] must clear an existing list (not be misread as 'unset')."""
    SettingsService.update_settings(website, {"excluded_paths": ["/admin"]})
    result = SettingsService.update_settings(website, {"excluded_paths": []})
    assert result["excluded_paths"] == []
    website.crawl_config.refresh_from_db()
    assert website.crawl_config.excluded_paths == []


@pytest.mark.django_db
def test_update_excluded_paths_non_list_rejected(website):
    """A bare string is a common client mistake — must 400, not coerce."""
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(website, {"excluded_paths": "/admin"})
    assert "excluded_paths" in str(exc.value)


@pytest.mark.django_db
def test_update_excluded_paths_non_string_entry_rejected(website):
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(
            website, {"excluded_paths": ["/admin", 42]},
        )
    assert "excluded_paths" in str(exc.value)


@pytest.mark.django_db
def test_update_excluded_paths_empty_entry_rejected(website):
    """Empty strings are usually whitespace bugs from the client — reject."""
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(
            website, {"excluded_paths": ["/admin", ""]},
        )
    assert "excluded_paths" in str(exc.value)


@pytest.mark.django_db
def test_update_excluded_paths_entry_too_long_rejected(website):
    too_long = "/" + ("x" * 200)  # 201 chars total, over the 200 cap.
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(
            website, {"excluded_paths": [too_long]},
        )
    assert "excluded_paths" in str(exc.value)


@pytest.mark.django_db
def test_update_excluded_paths_too_many_entries_rejected(website):
    too_many = [f"/p{i}" for i in range(101)]  # 101 > 100 cap.
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(
            website, {"excluded_paths": too_many},
        )
    assert "excluded_paths" in str(exc.value)


@pytest.mark.django_db
def test_update_excluded_params_validation_shares_rules(website):
    """The same validator covers both fields; spot-check excluded_params."""
    with pytest.raises(ValueError) as exc:
        SettingsService.update_settings(
            website, {"excluded_params": [None]},
        )
    assert "excluded_params" in str(exc.value)
