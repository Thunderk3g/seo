"""Tests for GET /api/v1/system/metrics/ — Spec §4.2 system signals.

Covers the four contractual guarantees of the endpoint:

  1. Healthy path returns the documented payload shape (200 + four
     top-level keys with the right types).
  2. A flaky / unreachable Redis must not 500 — sub-collector returns
     ``connected=False`` and ``queue_depth=0``.
  3. A missing Celery control-plane (no workers attached) must not 500 —
     sub-collector returns zeros across all three Celery counters.
  4. The ``host`` block is always populated with the documented keys
     (psutil is a hard dependency in base.txt).

Mirrors the pytest + APIClient conventions already used in
``apps/crawler/tests/test_session_views.py``.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.crawler import views_system_metrics


URL = "/api/v1/system/metrics/"


@pytest.fixture
def client():
    return APIClient()


# ─────────────────────────────────────────────────────────────
# 1. Healthy-path shape
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_endpoint_returns_payload_shape(client):
    """200 + the four top-level keys, each with the right primitive type."""
    resp = client.get(URL)

    assert resp.status_code == 200, resp.content
    body = resp.data
    assert set(body.keys()) >= {"host", "redis", "celery", "captured_at"}

    assert isinstance(body["host"], dict)
    assert isinstance(body["redis"], dict)
    assert isinstance(body["celery"], dict)
    assert isinstance(body["captured_at"], str)


# ─────────────────────────────────────────────────────────────
# 2. Redis disconnected → safe zeros, still 200
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_redis_disconnected_returns_safe_zeros(client, monkeypatch):
    """Patch ``redis_lib.from_url`` inside the view module to raise.

    The except-branch must zero out the redis block and still return 200
    so the dashboard renders even if the broker is down.
    """
    def boom(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(views_system_metrics.redis_lib, "from_url", boom)

    resp = client.get(URL)

    assert resp.status_code == 200, resp.content
    redis_block = resp.data["redis"]
    assert redis_block["connected"] is False
    assert redis_block["queue_depth"] == 0


# ─────────────────────────────────────────────────────────────
# 3. Celery inspect unavailable → all zeros, still 200
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_celery_inspect_unavailable_returns_zeros(client, monkeypatch):
    """Patch ``current_app.control.inspect`` to raise.

    Mirrors the no-worker production case — the inspect call returns
    None or raises, and our collector must degrade to zeros.
    """
    from celery import current_app

    def broken_inspect(*args, **kwargs):
        raise RuntimeError("no broker reachable")

    monkeypatch.setattr(current_app.control, "inspect", broken_inspect)

    resp = client.get(URL)

    assert resp.status_code == 200, resp.content
    celery_block = resp.data["celery"]
    assert celery_block["active_tasks"] == 0
    assert celery_block["scheduled_tasks"] == 0
    assert celery_block["workers_online"] == 0


# ─────────────────────────────────────────────────────────────
# 4. Host metrics keys
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_host_metrics_keys_present(client):
    """All five documented host keys are present with numeric values."""
    resp = client.get(URL)

    assert resp.status_code == 200, resp.content
    host = resp.data["host"]
    expected = {
        "cpu_percent",
        "memory_percent",
        "memory_used_mb",
        "memory_total_mb",
        "thread_count",
    }
    assert set(host.keys()) == expected
    # cpu/memory percent are floats (psutil returns float); used/total/threads ints.
    assert isinstance(host["cpu_percent"], (int, float))
    assert isinstance(host["memory_percent"], (int, float))
    assert isinstance(host["memory_used_mb"], int)
    assert isinstance(host["memory_total_mb"], int)
    assert isinstance(host["thread_count"], int)
    assert host["memory_total_mb"] > 0
    assert host["thread_count"] > 0
