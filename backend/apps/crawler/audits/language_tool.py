"""LanguageTool client — grammar + style checker, 40+ languages.

The LanguageTool Docker container (defined in docker-compose.yml as
``languagetool``) exposes a v2 HTTP API at /v2/check. We hit it with
a page's visible body text and get back rich grammar findings:

  * Each finding carries category (TYPOS / GRAMMAR / STYLE / ...),
    rule id, message, and suggested replacements.
  * Multi-language: pass language=en-IN / hi-IN / etc. The server
    auto-detects if you pass language=auto.

Opt-in via CRAWLER_LANGUAGETOOL_URL env. When unset OR the service
is unreachable, the caller transparently falls back to the existing
pyspellchecker-only path (Phase C.4).

We cap the request body at ~20K characters because:
  * LT's free-build server rejects requests > 20K chars.
  * Beyond ~5K we already have plenty of signal per page.

Categories we DROP from the noise set (operator-tunable later):
  * STYLE / REDUNDANCY — too subjective, generates many false positives
    on marketing copy.
  * MISC — catch-all, noise.

What we keep: TYPOS, GRAMMAR, PUNCTUATION, CONFUSED_WORDS, COLLOCATIONS.
"""
from __future__ import annotations

import os
from typing import Any

import requests


# Categories worth surfacing in audit findings. Mirrors SF's defaults.
_KEEP_CATEGORIES = frozenset({
    "TYPOS", "GRAMMAR", "PUNCTUATION", "CONFUSED_WORDS",
    "COLLOCATIONS", "TYPOGRAPHY",
})

# Length cap per request. LT 6.x free-build rejects > 20000 chars.
_MAX_CHARS = 18_000


def _enabled() -> tuple[str, str] | None:
    """Return (url, lang) when LT is configured + reachable, else None."""
    url = (os.environ.get("CRAWLER_LANGUAGETOOL_URL") or "").strip()
    if not url:
        return None
    lang = (os.environ.get("CRAWLER_LANGUAGETOOL_LANG") or "en-US").strip()
    return (url.rstrip("/"), lang)


def grammar_check(text: str, *, language: str | None = None,
                  timeout: float = 12.0) -> dict:
    """Send text to LanguageTool, return a flat findings dict.

    Returns the same shape regardless of whether LT was reached, so
    the caller never has to branch on success/failure:

        {
            "grammar_error_count": int,
            "grammar_errors": [
                {"category": str, "rule": str, "message": str,
                 "context": str, "replacements": [str, ...]},
                ...  (capped at 25)
            ],
            "grammar_categories": {"TYPOS": 5, "GRAMMAR": 2, ...},
            "grammar_lang_detected": str,
            "grammar_tool_used": "languagetool" | "none",
        }
    """
    empty = {
        "grammar_error_count": 0,
        "grammar_errors": [],
        "grammar_categories": {},
        "grammar_lang_detected": "",
        "grammar_tool_used": "none",
    }
    if not text or not text.strip():
        return empty

    cfg = _enabled()
    if cfg is None:
        return empty
    base_url, default_lang = cfg
    lang = language or default_lang

    body_text = text[:_MAX_CHARS]
    try:
        resp = requests.post(
            f"{base_url}/v2/check",
            data={"text": body_text, "language": lang},
            timeout=timeout,
        )
    except (requests.ConnectionError, requests.Timeout):
        return empty

    if resp.status_code != 200:
        return empty

    try:
        payload = resp.json()
    except ValueError:
        return empty

    findings: list[dict] = []
    categories: dict[str, int] = {}
    for m in payload.get("matches", []) or []:
        rule = m.get("rule") or {}
        cat = ((rule.get("category") or {}).get("id") or "").upper()
        if cat and cat not in _KEEP_CATEGORIES:
            continue
        replacements = [
            r.get("value", "") for r in (m.get("replacements") or [])[:3]
        ]
        ctx = m.get("context", {}) or {}
        findings.append({
            "category": cat,
            "rule": rule.get("id", ""),
            "message": (m.get("shortMessage") or m.get("message") or "")[:240],
            "context": (ctx.get("text") or "")[:160],
            "replacements": replacements,
        })
        categories[cat] = categories.get(cat, 0) + 1

    detected = (
        (payload.get("language") or {}).get("detectedLanguage") or {}
    ).get("code", "")

    return {
        "grammar_error_count": len(findings),
        "grammar_errors": findings[:25],
        "grammar_categories": categories,
        "grammar_lang_detected": detected,
        "grammar_tool_used": "languagetool",
    }
