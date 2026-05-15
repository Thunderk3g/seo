"""Shared base for AI-search-visibility probes.

Each provider (OpenAI / Anthropic / Gemini / Perplexity / xAI) implements
:class:`AILLMProbeAdapter` and is responsible for:

  * Validating its env key + SDK availability in ``__init__`` (raise
    :class:`AdapterDisabledError` if either is missing — the agent
    treats that as "this provider is silently unavailable").
  * Implementing :meth:`probe`, returning an :class:`AIProbeResult` even
    on errors. Network / SDK failures must NEVER raise out of
    ``probe`` — wrap them in ``AIProbeResult.error``.

A 7-day disk cache is shared across providers (keyed by provider+query
hash), so re-running the same probe set within a week is free.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger("seo.ai.adapters.ai_visibility")


class AdapterDisabledError(RuntimeError):
    """Raised when an adapter can't operate (missing key, missing SDK).

    The :class:`AISearchVisibilityAgent` catches this and silently drops
    the provider — every other provider still runs.
    """


@dataclass
class AIProbeResult:
    """Outcome of one (provider, query) probe.

    A failed probe still produces an instance with ``error`` filled in
    so the agent can count it as "attempted but failed" rather than
    losing the row. ``mentioned_domains`` is the de-duplicated set of
    bare hostnames pulled out of ``answer_text`` + ``cited_urls``.
    """

    provider: str
    query: str
    answer_text: str = ""
    cited_urls: list[str] = field(default_factory=list)
    mentioned_domains: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str = ""
    cached: bool = False
    raw: dict[str, Any] | None = None


_URL_RE = re.compile(
    r"https?://[^\s\)\]\}<>\"'`]+",
    re.IGNORECASE,
)


def extract_cited_urls(*sources: Any) -> list[str]:
    """Pull all URLs out of a mixed bag of strings / dicts / lists.

    De-duplicates preserving order. Strips trailing punctuation that
    commonly slips into regex matches (periods, commas, etc.).
    """
    out: list[str] = []
    seen: set[str] = set()

    def _push(u: str) -> None:
        u = u.rstrip(".,;:!?)")
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            for m in _URL_RE.findall(node):
                _push(m)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                _walk(v)

    for s in sources:
        _walk(s)
    return out


def domains_from_urls(urls: list[str]) -> list[str]:
    """Bare hostnames (lower-cased, www-stripped) from a URL list."""
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        try:
            host = (urlparse(u).hostname or "").lower()
        except ValueError:
            continue
        if host.startswith("www."):
            host = host[4:]
        if host and host not in seen:
            seen.add(host)
            out.append(host)
    return out


def _resolve_ssl_verify(raw: str) -> bool | str:
    """Map AI_VISIBILITY_SSL_VERIFY env value → httpx ``verify`` arg.

    Mirrors :func:`apps.seo_ai.llm.provider._resolve_ssl_verify`.
    """
    import os.path

    value = (raw or "").strip()
    if not value or value.lower() in ("true", "1", "yes", "on"):
        return True
    if value.lower() in ("false", "0", "no", "off"):
        return False
    if os.path.exists(value):
        return value
    logger.warning(
        "AI_VISIBILITY_SSL_VERIFY=%r does not exist on disk — falling back "
        "to default verification.",
        value,
    )
    return True


class AILLMProbeAdapter(ABC):
    """One probe adapter per LLM provider.

    Subclasses set the ``provider`` class attribute and implement
    :meth:`_probe`. The base class wraps each call with a disk cache
    keyed by ``sha1(provider|model|query)`` and handles result
    normalisation (URL extraction, domain de-dup).
    """

    provider: str = "base"

    def __init__(self) -> None:
        cfg = getattr(settings, "AI_VISIBILITY", {}) or {}
        if not cfg.get("enabled", True):
            raise AdapterDisabledError("AI_VISIBILITY_ENABLED=false")
        self.cache_ttl_seconds = int(cfg.get("cache_ttl_seconds", 7 * 24 * 3600))
        self.request_timeout_sec = int(cfg.get("request_timeout_sec", 30))
        self.ssl_verify = _resolve_ssl_verify(cfg.get("ssl_verify", ""))
        self.cache_dir = (
            Path(settings.SEO_AI["data_dir"]) / "_ai_visibility_cache"
        )
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # noqa: BLE001 - non-fatal
            logger.warning("ai_visibility cache dir unwritable: %s", exc)

    # ── public ────────────────────────────────────────────────────────

    def probe(self, query: str) -> AIProbeResult:
        cached = self._cache_read(query)
        if cached is not None:
            cached.cached = True
            return cached
        t0 = time.monotonic()
        try:
            result = self._probe(query)
        except Exception as exc:  # noqa: BLE001 - never raise out of probe
            logger.warning(
                "%s probe %r failed: %s", self.provider, query[:80], exc
            )
            result = AIProbeResult(
                provider=self.provider,
                query=query,
                error=f"{type(exc).__name__}: {exc}"[:400],
            )
        result.latency_ms = int((time.monotonic() - t0) * 1000)
        # Normalise URL + domain extraction across all providers so the
        # agent can count citations consistently.
        if not result.cited_urls:
            result.cited_urls = extract_cited_urls(
                result.answer_text, result.raw or {}
            )
        result.mentioned_domains = domains_from_urls(result.cited_urls)
        self._cache_write(query, result)
        return result

    # ── subclass hook ─────────────────────────────────────────────────

    @abstractmethod
    def _probe(self, query: str) -> AIProbeResult:
        """Provider-specific probe. Return AIProbeResult; never raise."""

    # ── cache ─────────────────────────────────────────────────────────

    def _cache_key(self, query: str) -> Path:
        model = getattr(self, "model", "default")
        h = hashlib.sha1(
            f"{self.provider}|{model}|{query}".encode("utf-8")
        ).hexdigest()
        return self.cache_dir / f"{h}.json"

    def _cache_read(self, query: str) -> AIProbeResult | None:
        path = self._cache_key(query)
        if not path.exists():
            return None
        try:
            if (time.time() - path.stat().st_mtime) > self.cache_ttl_seconds:
                return None
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return AIProbeResult(**data)

    def _cache_write(self, query: str, result: AIProbeResult) -> None:
        path = self._cache_key(query)
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(asdict(result), f, default=str)
        except OSError as exc:  # noqa: BLE001 - cache is best-effort
            logger.warning("ai_visibility cache write failed: %s", exc)
