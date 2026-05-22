"""Phase D.4 — Forms-based authentication for the crawler.

Some Bajaj internal microsites (staging, agent portals) live behind a
session-cookie login. Without this helper, the crawler hits the login
wall and records every URL as the same 200-OK login page — useless
for the audit.

This module reads ``CRAWLER_AUTH_*`` env vars at crawl start, POSTs
the configured credentials at the configured login URL, and carries
the resulting session cookies into the main crawl Session.

Env contract (all optional — when unset, auth is a no-op):

  CRAWLER_AUTH_ENABLED          true / false (default false)
  CRAWLER_AUTH_LOGIN_URL        full URL of the login form action
  CRAWLER_AUTH_USERNAME_FIELD   form field name for the username
  CRAWLER_AUTH_USERNAME_VALUE   the username to send
  CRAWLER_AUTH_PASSWORD_FIELD   form field name for the password
  CRAWLER_AUTH_PASSWORD_VALUE   the password to send  (never log!)
  CRAWLER_AUTH_EXTRA_FIELDS     additional fields as `k=v;k=v`
                                (CSRF tokens, etc.)
  CRAWLER_AUTH_SUCCESS_REGEX    regex that must match the login
                                response body for auth to be
                                considered successful

Failure modes:
  * env disabled    → returns the session unchanged.
  * login URL 4xx   → logs warning, returns session unchanged.
  * success regex mismatch → logs warning, returns session unchanged.
                             Crawl continues without auth (the
                             operator can re-enable after fixing the
                             config).

We deliberately do NOT raise on auth failure — partial-auth crawls
are still useful, and an empty-credentials env shouldn't break the
whole pipeline.
"""
from __future__ import annotations

import os
import re

import requests

from ..logger import get_logger

log = get_logger(__name__)


def _truthy(s: str | None) -> bool:
    return (s or "").strip().lower() in ("1", "true", "yes", "on", "t", "y")


def apply_forms_auth(session: requests.Session) -> bool:
    """Mutate ``session`` in-place to carry login cookies. Returns
    True when auth was applied successfully, False otherwise.

    Safe to call multiple times — each call re-POSTs the login form,
    which is the correct behavior when a fresh process spins up a
    new session.
    """
    if not _truthy(os.environ.get("CRAWLER_AUTH_ENABLED")):
        return False

    login_url = (os.environ.get("CRAWLER_AUTH_LOGIN_URL") or "").strip()
    user_field = (os.environ.get("CRAWLER_AUTH_USERNAME_FIELD") or "").strip()
    user_value = (os.environ.get("CRAWLER_AUTH_USERNAME_VALUE") or "").strip()
    pass_field = (os.environ.get("CRAWLER_AUTH_PASSWORD_FIELD") or "").strip()
    pass_value = os.environ.get("CRAWLER_AUTH_PASSWORD_VALUE") or ""
    success_re = (os.environ.get("CRAWLER_AUTH_SUCCESS_REGEX") or "").strip()
    extra_raw = (os.environ.get("CRAWLER_AUTH_EXTRA_FIELDS") or "").strip()

    if not (login_url and user_field and pass_field and user_value and pass_value):
        log.warning(
            "CRAWLER_AUTH_ENABLED=true but required env vars are not set — "
            "skipping forms-based auth. Need at least LOGIN_URL, "
            "USERNAME_FIELD, USERNAME_VALUE, PASSWORD_FIELD, PASSWORD_VALUE."
        )
        return False

    payload: dict[str, str] = {user_field: user_value, pass_field: pass_value}
    if extra_raw:
        for pair in extra_raw.split(";"):
            if "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            k, v = k.strip(), v.strip()
            if k:
                payload[k] = v

    try:
        # NB: don't log payload — it contains a password.
        resp = session.post(
            login_url, data=payload, timeout=30, allow_redirects=True,
        )
    except requests.RequestException as exc:
        log.warning("forms auth failed (network error) on %s: %s", login_url, exc)
        return False

    if resp.status_code >= 400:
        log.warning(
            "forms auth failed: %s returned HTTP %d", login_url, resp.status_code,
        )
        return False

    if success_re:
        try:
            if not re.search(success_re, resp.text):
                log.warning(
                    "forms auth failed: success regex %r did not match "
                    "login response body for %s",
                    success_re, login_url,
                )
                return False
        except re.error as exc:
            log.warning("CRAWLER_AUTH_SUCCESS_REGEX is invalid: %s", exc)
            return False

    cookie_count = len(session.cookies)
    log.info(
        "forms auth succeeded: %d session cookies acquired from %s",
        cookie_count, login_url,
    )
    return True
