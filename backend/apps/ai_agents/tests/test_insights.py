"""Unit + integration tests for the Day 5 AI insights surface.

Covers ``InsightsService.get_insights`` across all three branches (stub,
real Anthropic, fallback) and the standalone ``insights_view`` URL hop.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from apps.ai_agents.services import insights_service
from apps.ai_agents.services.insights_service import InsightsService
from apps.crawl_sessions.models import CrawlSession
from apps.crawler.models import Website


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def website(db):
    return Website.objects.create(domain="example.test", name="Example")


@pytest.fixture
def session(db, website):
    return CrawlSession.objects.create(website=website)


@pytest.fixture
def client():
    return APIClient()


def _make_fake_anthropic_class(text: str, *, cache_read: int = 0):
    """Return a class-callable that mimics ``anthropic.Anthropic``.

    Calling the returned class yields a MagicMock client whose
    ``messages.create`` returns a fake message with a single text block and a
    ``usage`` object exposing ``cache_read_input_tokens``.
    """
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

    usage = MagicMock()
    usage.cache_read_input_tokens = cache_read
    usage.cache_creation_input_tokens = 0

    fake_response = MagicMock()
    fake_response.content = [text_block]
    fake_response.usage = usage

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    fake_class = MagicMock(return_value=fake_client)
    return fake_class, fake_client


# ─────────────────────────────────────────────────────────────────────
# Service tests
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_insights_returns_stub_when_no_api_key(monkeypatch, session):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = InsightsService.get_insights(session)

    assert result["available"] is False
    assert result["model"] == "stub"
    assert result["session_id"] == str(session.id)
    assert isinstance(result["summary"], str) and result["summary"]
    assert result["highlights"] == []
    assert result["cached"] is False
    assert "generated_at" in result


@pytest.mark.django_db
def test_insights_calls_anthropic_when_key_present(monkeypatch, session):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

    payload = {
        "summary": "Coverage looks healthy with one canonical mismatch.",
        "highlights": [
            {
                "title": "Canonical mismatch",
                "severity": "warning",
                "body": "One page has a declared canonical that the crawler "
                "rejected. Investigate /products/sale.",
            },
            {
                "title": "No 5xx errors",
                "severity": "info",
                "body": "Server health is clean across the crawl.",
            },
        ],
    }
    fake_class, fake_client = _make_fake_anthropic_class(
        json.dumps(payload), cache_read=0
    )

    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    result = InsightsService.get_insights(session)

    assert result["available"] is True
    assert result["model"] == "claude-sonnet-4-6"
    assert result["cached"] is False
    assert result["summary"] == payload["summary"]
    assert len(result["highlights"]) == 2
    assert result["highlights"][0]["severity"] == "warning"

    # Verify the system block was sent with cache_control on the static prompt.
    fake_client.messages.create.assert_called_once()
    kwargs = fake_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 1024
    assert kwargs["temperature"] == 0.3
    assert isinstance(kwargs["system"], list)
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.django_db
def test_insights_cached_flag_is_false_on_fresh_compute(
    monkeypatch, session
):
    """Spec §4.4: ``cached`` is the row-cache flag, NOT the Anthropic
    prompt-cache flag. Even when ``usage.cache_read_input_tokens > 0``, a
    fresh compute path (regenerate / cache miss) must report
    ``cached=False`` — the prompt-cache signal is intentionally discarded
    so the frontend can rely on ``cached`` to mean "served from
    session.ai_insights without an Anthropic call".
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    payload = {"summary": "All good.", "highlights": []}
    fake_class, _ = _make_fake_anthropic_class(
        json.dumps(payload), cache_read=512
    )
    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    # Empty row-cache → falls through to regenerate, which always emits
    # cached=False regardless of the Anthropic prompt-cache hit.
    result = InsightsService.get_insights(session)

    assert result["cached"] is False


@pytest.mark.django_db
def test_insights_falls_back_on_sdk_error(monkeypatch, session):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

    def _boom(*args, **kwargs):
        raise RuntimeError("SDK exploded")

    fake_module = MagicMock()
    fake_module.Anthropic = _boom
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    result = InsightsService.get_insights(session)

    assert result["model"] == "fallback"
    assert "temporarily unavailable" in result["summary"].lower()
    assert result["available"] is False
    assert result["highlights"] == []


@pytest.mark.django_db
def test_insights_handles_malformed_json_reply(monkeypatch, session):
    """Non-JSON model reply → summary uses raw text, highlights=[]."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    fake_class, _ = _make_fake_anthropic_class(
        "this is not json at all"
    )
    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    result = InsightsService.get_insights(session)

    assert result["available"] is True
    assert result["summary"] == "this is not json at all"
    assert result["highlights"] == []


@pytest.mark.django_db
def test_insights_respects_anthropic_model_env_override(monkeypatch, session):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-7")
    fake_class, fake_client = _make_fake_anthropic_class(
        json.dumps({"summary": "x", "highlights": []})
    )
    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    result = InsightsService.get_insights(session)

    assert result["model"] == "claude-opus-4-7"
    assert fake_client.messages.create.call_args.kwargs["model"] == (
        "claude-opus-4-7"
    )


# ─────────────────────────────────────────────────────────────────────
# Endpoint tests
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_insights_endpoint_404_for_unknown_session(client):
    resp = client.get(f"/api/v1/sessions/{uuid4()}/insights/")
    assert resp.status_code == 404
    assert "detail" in resp.data


@pytest.mark.django_db
def test_insights_endpoint_returns_payload(monkeypatch, client, session):
    """Endpoint returns whatever the service produces, with full shape."""
    fake_payload = {
        "available": False,
        "session_id": str(session.id),
        "summary": "Mocked summary.",
        "highlights": [],
        "model": "stub",
        "cached": False,
        "generated_at": "2026-05-08T00:00:00+00:00",
    }
    monkeypatch.setattr(
        insights_service.InsightsService,
        "get_insights",
        staticmethod(lambda s: fake_payload),
    )

    resp = client.get(f"/api/v1/sessions/{session.id}/insights/")

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert set(body.keys()) == {
        "available",
        "session_id",
        "summary",
        "highlights",
        "model",
        "cached",
        "generated_at",
    }
    assert body == fake_payload


# ─────────────────────────────────────────────────────────────────────
# Cache-aware behaviour (spec §4.3, §4.4, §6 step 5)
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_get_insights_returns_cached_when_present(monkeypatch, session):
    """Pre-populated session.ai_insights → no SDK call, cached=True."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

    # Anthropic class that would explode if invoked — proves we don't call it.
    fake_class, fake_client = _make_fake_anthropic_class(
        json.dumps({"summary": "should not run", "highlights": []})
    )
    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    # Seed the cache directly.
    from django.utils import timezone as _tz
    session.ai_insights = {
        "available": True,
        "session_id": str(session.id),
        "summary": "Cached summary from prior crawl.",
        "highlights": [
            {"title": "Old finding", "severity": "info", "body": "Cached body."}
        ],
        "model": "claude-sonnet-4-6",
        "cached": False,  # gets overridden to True on read
        "generated_at": "2026-05-01T00:00:00+00:00",
    }
    session.ai_insights_generated_at = _tz.now()
    session.ai_insights_model = "claude-sonnet-4-6"
    session.save(update_fields=[
        "ai_insights", "ai_insights_generated_at", "ai_insights_model",
    ])

    result = InsightsService.get_insights(session)

    assert result["cached"] is True
    assert result["summary"] == "Cached summary from prior crawl."
    assert result["model"] == "claude-sonnet-4-6"
    assert fake_client.messages.create.call_count == 0


@pytest.mark.django_db
def test_get_insights_falls_back_to_regenerate_when_cache_empty(
    monkeypatch, session
):
    """Empty cache → SDK is called and the payload is persisted to the row."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

    payload = {"summary": "Fresh compute.", "highlights": []}
    fake_class, fake_client = _make_fake_anthropic_class(json.dumps(payload))
    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    assert session.ai_insights is None  # baseline

    result = InsightsService.get_insights(session)

    assert result["cached"] is False
    assert result["summary"] == "Fresh compute."
    assert fake_client.messages.create.call_count == 1

    session.refresh_from_db()
    assert session.ai_insights is not None
    assert session.ai_insights["summary"] == "Fresh compute."
    assert session.ai_insights_generated_at is not None
    assert session.ai_insights_model == "claude-sonnet-4-6"


@pytest.mark.django_db
def test_regenerate_writes_to_session(monkeypatch, session):
    """regenerate(session) persists payload + timestamp + model on the row."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-7")
    fake_class, _ = _make_fake_anthropic_class(
        json.dumps({"summary": "Regen result.", "highlights": []})
    )
    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    from django.utils import timezone as _tz
    before = _tz.now()
    result = InsightsService.regenerate(session)

    assert result["cached"] is False
    assert result["summary"] == "Regen result."

    session.refresh_from_db()
    assert session.ai_insights is not None
    assert session.ai_insights["summary"] == "Regen result."
    assert session.ai_insights_generated_at is not None
    assert session.ai_insights_generated_at >= before
    assert session.ai_insights_model == "claude-opus-4-7"


@pytest.mark.django_db
def test_post_endpoint_regenerates(monkeypatch, client, session):
    """POST → fresh compute, cached payload updated."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    fake_class, fake_client = _make_fake_anthropic_class(
        json.dumps({"summary": "POST regen.", "highlights": []})
    )
    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    resp = client.post(f"/api/v1/sessions/{session.id}/insights/")

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["summary"] == "POST regen."
    assert body["cached"] is False
    assert fake_client.messages.create.call_count == 1

    session.refresh_from_db()
    assert session.ai_insights is not None
    assert session.ai_insights["summary"] == "POST regen."


@pytest.mark.django_db
def test_get_endpoint_returns_cached_after_post(monkeypatch, client, session):
    """POST then GET → second call hits the row cache (cached=True)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    fake_class, fake_client = _make_fake_anthropic_class(
        json.dumps({"summary": "First-pass.", "highlights": []})
    )
    fake_module = MagicMock()
    fake_module.Anthropic = fake_class
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake_module)

    # Prime the cache via POST.
    post_resp = client.post(f"/api/v1/sessions/{session.id}/insights/")
    assert post_resp.status_code == 200
    assert post_resp.json()["cached"] is False
    assert fake_client.messages.create.call_count == 1

    # Subsequent GET must NOT issue a second Anthropic call.
    get_resp = client.get(f"/api/v1/sessions/{session.id}/insights/")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["cached"] is True
    assert body["summary"] == "First-pass."
    assert fake_client.messages.create.call_count == 1  # unchanged
