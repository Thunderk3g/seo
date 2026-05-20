"""IndexNow adapter — Bing + Yandex protocol for instant URL submission.

IndexNow lets a site notify search engines the moment a URL is
created/updated/deleted, replacing the slow "wait for a crawl"
cycle. One ping reaches Bing, Yandex, Naver, Seznam, and (per the
protocol agreement) ChatGPT/Microsoft Copilot's grounding index.

Bajaj-specific guard rails:
  * URLs MUST start with one of ``ALLOWED_PREFIXES`` so a staging /
    UAT environment can never accidentally ping production search
    engines. The operator changes this list when adding/removing
    domains.
  * The IndexNow key file must be reachable at
    ``https://www.bajajlifeinsurance.com/<key>.txt`` returning the
    raw key — Bing fetches this once to authenticate the host
    before honouring pings.
  * Empty / dry-run mode if ``INDEXNOW_KEY`` env var is unset, so
    the endpoint stays callable in dev without surprises.

Spec: https://www.indexnow.org/documentation
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import requests


ALLOWED_PREFIXES: tuple[str, ...] = (
    "https://www.bajajlifeinsurance.com/",
    "https://bajajlifeinsurance.com/",
    "https://branch.bajajlifeinsurance.com/",
)


_INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"


def _filter_allowed(urls: list[str]) -> tuple[list[str], list[str]]:
    allowed: list[str] = []
    rejected: list[str] = []
    for u in urls:
        u = (u or "").strip()
        if not u:
            continue
        if any(u.startswith(p) for p in ALLOWED_PREFIXES):
            allowed.append(u)
        else:
            rejected.append(u)
    return allowed, rejected


def ping_urls(urls: list[str]) -> dict[str, Any]:
    """Submit a batch of URLs to IndexNow.

    Returns a dict with keys:
      - ok               (bool)
      - submitted        (count of URLs actually sent)
      - rejected         (URLs blocked by the allow-list)
      - rejected_count   (int)
      - status_code      (HTTP code from IndexNow; 200/202 means OK)
      - response_body    (raw response, useful when status != 200)
      - dry_run          (true when INDEXNOW_KEY is unset — nothing sent)
    """
    allowed, rejected = _filter_allowed(urls or [])
    if not allowed:
        return {
            "ok": False,
            "error": "no URLs after allow-list filter",
            "submitted": 0,
            "rejected": rejected,
            "rejected_count": len(rejected),
        }

    # Derive the canonical host from the first URL so the IndexNow
    # signature ties to a single domain per submission (the protocol
    # rejects mixed-host batches with HTTP 422).
    host = urlparse(allowed[0]).netloc
    same_host = [u for u in allowed if urlparse(u).netloc == host]
    cross_host = [u for u in allowed if urlparse(u).netloc != host]
    if cross_host:
        rejected.extend(cross_host)

    key = os.environ.get("INDEXNOW_KEY", "").strip()
    key_location = os.environ.get(
        "INDEXNOW_KEY_LOCATION",
        f"https://{host}/{key}.txt" if key else "",
    )

    if not key:
        return {
            "ok": True,
            "dry_run": True,
            "note": (
                "INDEXNOW_KEY env var not set — nothing sent. "
                "Configure INDEXNOW_KEY (and host the key file at "
                f"https://{host}/<key>.txt) to enable real pings."
            ),
            "submitted": 0,
            "would_submit": len(same_host),
            "would_submit_sample": same_host[:5],
            "rejected": rejected,
            "rejected_count": len(rejected),
        }

    payload = {
        "host": host,
        "key": key,
        "keyLocation": key_location,
        "urlList": same_host,
    }
    try:
        resp = requests.post(
            _INDEXNOW_ENDPOINT,
            json=payload,
            timeout=15,
            headers={
                "User-Agent": "BajajSEOBot/1.0 IndexNow-Pinger",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": f"network: {type(exc).__name__}: {exc}",
            "submitted": 0,
            "rejected": rejected,
            "rejected_count": len(rejected),
        }

    return {
        "ok": resp.status_code in (200, 202),
        "submitted": len(same_host),
        "status_code": resp.status_code,
        "response_body": (resp.text or "")[:500],
        "host": host,
        "rejected": rejected,
        "rejected_count": len(rejected),
    }
