"""LLM provider abstraction.

Currently wired for Groq (OpenAI-API-compatible). The provider is the
single seam between agents and the model — keeping it small means
swapping to a different vendor later (Anthropic, OpenAI direct, a local
model) is a one-file change.

Why Groq + ``openai/gpt-oss-120b``: the 120B open-weight model is large
enough to follow structured-output instructions reliably, and Groq's
LPU-backed inference returns sub-second responses at price points an
order of magnitude below GPT-4-class APIs. That tradeoff is right for
bulk SEO grading work where we run many agents per site.

The :class:`LLMProvider` interface returns a normalized
:class:`LLMResponse` so agent code never has to care which vendor
produced the text. Tool-use is exposed via the OpenAI-style
``tools=[...]`` / ``tool_choice="auto"`` parameters that Groq mirrors.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from django.conf import settings

logger = logging.getLogger("seo.ai.llm")


@dataclass
class StreamChunk:
    """One frame emitted by :meth:`LLMProvider.stream_complete`.

    Three kinds:
      * ``text``      — ``text`` carries the delta to append to the
                         assistant message buffer.
      * ``tool_call`` — emitted once per fully-assembled tool call after
                         the stream finishes. ``tool_call`` is a dict
                         shaped like :attr:`LLMResponse.tool_calls`.
      * ``done``      — terminal frame. Carries the final
                         ``finish_reason`` plus token / cost totals.
    """

    kind: str
    text: str = ""
    tool_call: dict[str, Any] | None = None
    finish_reason: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class LLMResponse:
    """Normalized model response.

    ``content`` is the assistant text (may be empty when ``tool_calls``
    is populated). ``tool_calls`` is a list of OpenAI-style tool-call
    objects: ``[{"id": "...", "name": "...", "arguments": {...}}, ...]``.
    Token counts and cost are best-effort — Groq does not bill per token
    via Anthropic-style headers; cost is estimated from the public price
    list and is meant for budgeting, not invoicing.
    """

    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""
    finish_reason: str = ""
    raw: dict[str, Any] | None = None
    # Populated only by Anthropic web-search turns. ``web_search_results``
    # is a flat list of {url, title, page_age} the server tool returned;
    # ``citations`` is the list of {url, title, cited_text} attached to
    # the assistant's text blocks. Both empty for normal completions.
    web_search_results: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    web_search_count: int = 0


class LLMProvider:
    """Base interface. Subclasses implement :meth:`complete`."""

    name: str = "base"
    model: str = ""

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResponse:  # pragma: no cover - interface
        raise NotImplementedError

    def stream_complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Iterator[StreamChunk]:  # pragma: no cover - interface
        raise NotImplementedError


# ── Groq ────────────────────────────────────────────────────────────────
# Groq publishes prices per million tokens. ``openai/gpt-oss-120b`` is
# $0.15 / 1M input, $0.75 / 1M output (Nov 2025 list price). These get
# stale — keep them in code, not in the prompt, so updates are atomic.
_GROQ_PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.75),
    "openai/gpt-oss-20b": (0.10, 0.50),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    # Models the 413-fallback chain may swap to. Cost stays accurate
    # mid-stream even after a downshift.
    "llama-3.1-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "mixtral-8x7b-32768": (0.24, 0.24),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = _GROQ_PRICING.get(model, (0.0, 0.0))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


class GroqProvider(LLMProvider):
    """OpenAI-API-compatible client pointed at the Groq endpoint.

    The OpenAI Python SDK lets us swap ``base_url`` and reuse all of its
    tool-use and JSON-mode plumbing — saves a separate dependency on the
    ``groq`` SDK and means the same code can target an OpenAI-compatible
    proxy or a self-hosted vLLM endpoint without changes.
    """

    name = "groq"

    def __init__(self) -> None:
        cfg = settings.LLM["groq"]
        if not cfg["api_key"]:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Populate it in .env or disable "
                "LLM-backed agents by setting LLM_PROVIDER=stub."
            )
        # Imported lazily so collection of the module doesn't require the
        # SDK in environments where LLM calls are disabled.
        import httpx
        from openai import OpenAI

        # Windows corporate networks often break certifi's bundle because
        # an MITM proxy injects an intermediate cert that only lives in
        # the OS trust store. ``truststore`` makes Python's TLS stack use
        # the system store, which fixes this without disabling
        # verification. No-op on macOS / Linux.
        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:  # noqa: BLE001 - non-Windows or already injected
            pass

        # Resolve TLS verification. On Linux containers behind a corp
        # MITM proxy, certifi's bundle won't include the intercepting
        # root, so the user can either point at the corp CA (path) or
        # disable verification for dev (LLM_SSL_VERIFY=false).
        verify: bool | str = _resolve_ssl_verify(
            settings.LLM.get("ssl_verify", "")
        )
        if verify is False:
            logger.warning(
                "LLM_SSL_VERIFY=false — TLS certificate verification is "
                "disabled. Acceptable for dev behind a corporate MITM "
                "proxy only. NEVER use in production."
            )
        http_client = httpx.Client(verify=verify, timeout=60.0)

        # Key pool: when GROQ_API_KEYS env carries multiple comma-
        # separated keys (free tier with 7-8 keys is common), we
        # round-robin them and back off the offending key on 429s
        # instead of hammering one budget. ``cfg['api_key']`` stays
        # in use as the bootstrap key for the OpenAI client init;
        # we swap ``self._client.api_key`` per-request inside complete().
        from .key_pool import get_groq_pool

        self._pool = get_groq_pool()  # None when GROQ_API_KEYS unset

        # Store the bound http_client + base_url so we can rebuild the
        # OpenAI client with a fresh key per request without re-creating
        # the underlying httpx connection pool each time.
        self._http_client = http_client
        self._base_url = cfg["base_url"]

        self._client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            http_client=http_client,
        )
        self.model = cfg["model"]
        self._default_max_tokens = cfg["max_tokens"]
        self._default_temperature = cfg["temperature"]
        # 413 ("request too large") fallback chain — primary first,
        # then progressively smaller / higher-TPM models. Pre-cleaned.
        raw_fb = (cfg.get("fallback_models") or "").strip()
        self._fallback_models: list[str] = [
            m.strip() for m in raw_fb.split(",") if m.strip()
        ]

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": (
                temperature if temperature is not None else self._default_temperature
            ),
        }
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        if response_format:
            kwargs["response_format"] = response_format

        # Per-request key acquisition when a pool is configured. Each
        # attempt acquires a fresh key from the pool — if the prior
        # attempt 429-ed, that key is now cooling and we'll get a
        # different one. With N keys the effective TPM is N×ACROSS
        # CALLS — a single request still has to fit one key's TPM
        # bucket. When a single request is too big for the current
        # model's bucket the API returns 413; we downshift to the
        # next model in the fallback chain instead of cooling a key
        # (413 is not a key-state problem).
        import time as _time
        from .key_pool import PoolExhaustedError

        model_chain = [kwargs["model"], *self._fallback_models]
        model_idx = 0

        last_exc: Exception | None = None
        for attempt in range(max(3, len(self._pool) if self._pool else 3)):
            # Acquire-and-bind a key for this attempt.
            current_key: str | None = None
            if self._pool is not None:
                try:
                    current_key = self._pool.acquire()
                except PoolExhaustedError as pex:
                    # Every key cooling. Sleep precisely the time the
                    # pool reports, then try again on next loop iter.
                    sleep_for = max(1.0, min(pex.wait_seconds, 60.0))
                    logger.warning(
                        "groq pool exhausted; sleeping %.1fs", sleep_for,
                    )
                    _time.sleep(sleep_for)
                    continue
                # OpenAI client's api_key is read on every request from
                # the instance attribute — safe to mutate.
                self._client.api_key = current_key

            try:
                resp = self._client.chat.completions.create(**kwargs)
                if self._pool is not None and current_key is not None:
                    self._pool.report_success(current_key)
                break
            except Exception as exc:  # pragma: no cover - network errors
                msg = str(exc).lower()
                last_exc = exc
                # 413 = request too large for this model's TPM bucket.
                # Rotating keys won't help (same bucket per model);
                # swap to the next fallback model and retry.
                is_413 = (
                    "413" in msg
                    or "request too large" in msg
                    or "request_too_large" in msg
                )
                if is_413 and model_idx + 1 < len(model_chain):
                    prev_model = model_chain[model_idx]
                    model_idx += 1
                    next_model = model_chain[model_idx]
                    kwargs["model"] = next_model
                    logger.warning(
                        "groq 413 on %s — downshifting to %s (request too "
                        "large for prior model's TPM bucket)",
                        prev_model,
                        next_model,
                    )
                    # 413 isn't a key problem — don't cool the key.
                    continue
                # 429 / TPM exhausted on the current model. Same model,
                # different key (or backoff if no pool).
                is_429 = (
                    "rate_limit" in msg
                    or "tokens per minute" in msg
                    or "429" in msg
                )
                if is_429 and self._pool is not None and current_key is not None:
                    self._pool.report_429(current_key)
                if is_429 and attempt < (len(self._pool) if self._pool else 2):
                    if self._pool is None:
                        wait = (
                            30 if "tokens per minute" in msg
                            else 5 * (attempt + 1)
                        )
                        logger.warning(
                            "groq retrying after %ss (attempt %d): %s",
                            wait,
                            attempt + 1,
                            exc,
                        )
                        _time.sleep(wait)
                    continue
                logger.error("groq.complete failed: %s", exc)
                raise
        else:
            assert last_exc is not None
            raise last_exc

        choice = resp.choices[0]
        msg = choice.message
        content = msg.content or ""
        raw_tool_calls = getattr(msg, "tool_calls", None) or []
        tool_calls: list[dict[str, Any]] = []
        for tc in raw_tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(
                {"id": tc.id, "name": tc.function.name, "arguments": args}
            )

        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", 0) if usage else 0
        tokens_out = getattr(usage, "completion_tokens", 0) if usage else 0

        # The resolved model reflects both the per-call override and any
        # 413 downshift that happened mid-loop — cost must track that, not
        # the provider default.
        resolved_model = kwargs.get("model") or self.model
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_estimate_cost(resolved_model, tokens_in, tokens_out),
            model=resolved_model,
            finish_reason=getattr(choice, "finish_reason", "") or "",
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )

    def stream_complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Iterator[StreamChunk]:
        """Streaming completion with the same resilience envelope as
        :meth:`complete`:

          * Per-attempt key acquisition from the GroqKeyPool — 429 on
            one key rotates to the next.
          * 413 (request too large) downshifts to the next model in
            ``GROQ_FALLBACK_MODELS``.
          * Up to ``max(3, len(pool))`` total attempts before giving up.

        Important detail for streaming: the OpenAI SDK only raises the
        provider error when you START iterating the stream. That means
        we have to wrap the FIRST chunk fetch in a try/except so a
        rate-limit reply can still be caught and rotated. Once the
        stream has yielded any chunk, we trust it (mid-stream failures
        are rare; treating them as terminal is safer than re-trying
        partial deltas).
        """
        import time as _time
        from .key_pool import PoolExhaustedError

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": (
                temperature if temperature is not None else self._default_temperature
            ),
            "stream": True,
            # include_usage adds a trailing chunk with prompt/completion totals.
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        # Tool calls arrive as a stream of deltas indexed per call. We
        # accumulate per-index until the stream ends, then emit one
        # ``tool_call`` chunk per assembled call with parsed arguments.
        tc_acc: dict[int, dict[str, Any]] = {}
        last_finish_reason = ""
        final_usage: Any = None

        # ── Retry envelope identical to complete() ──────────────────
        model_chain = [kwargs["model"], *self._fallback_models]
        model_idx = 0
        max_attempts = max(3, len(self._pool) if self._pool else 3)
        stream = None
        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            current_key: str | None = None
            if self._pool is not None:
                try:
                    current_key = self._pool.acquire()
                except PoolExhaustedError as pex:
                    sleep_for = max(1.0, min(pex.wait_seconds, 60.0))
                    logger.warning(
                        "groq stream pool exhausted; sleeping %.1fs", sleep_for,
                    )
                    _time.sleep(sleep_for)
                    continue
                self._client.api_key = current_key

            try:
                stream = self._client.chat.completions.create(**kwargs)
                # Force the first chunk to land — OpenAI SDK only raises
                # on iteration, not on .create(). Peek by reading the
                # iterator once, then prepend that chunk back via
                # itertools.chain so the main loop sees the full stream.
                import itertools
                stream_iter = iter(stream)
                first = next(stream_iter)
                stream = itertools.chain([first], stream_iter)
                if self._pool is not None and current_key is not None:
                    self._pool.report_success(current_key)
                break
            except StopIteration:
                # Empty stream — treat as success (no content).
                stream = iter([])
                if self._pool is not None and current_key is not None:
                    self._pool.report_success(current_key)
                break
            except Exception as exc:  # pragma: no cover - network errors
                msg = str(exc).lower()
                last_exc = exc
                is_413 = (
                    "413" in msg
                    or "request too large" in msg
                    or "request_too_large" in msg
                )
                if is_413 and model_idx + 1 < len(model_chain):
                    prev_model = model_chain[model_idx]
                    model_idx += 1
                    next_model = model_chain[model_idx]
                    kwargs["model"] = next_model
                    self.model = next_model  # update for cost estimation
                    logger.warning(
                        "groq stream 413 on %s — downshifting to %s",
                        prev_model, next_model,
                    )
                    continue
                is_429 = (
                    "rate_limit" in msg
                    or "tokens per minute" in msg
                    or "429" in msg
                )
                if is_429 and self._pool is not None and current_key is not None:
                    self._pool.report_429(current_key)
                if is_429 and attempt < max_attempts - 1:
                    if self._pool is None:
                        wait = 30 if "tokens per minute" in msg else 5 * (attempt + 1)
                        logger.warning(
                            "groq stream retrying after %ss (attempt %d): %s",
                            wait, attempt + 1, exc,
                        )
                        _time.sleep(wait)
                    continue
                logger.error("groq.stream_complete failed: %s", exc)
                raise
        else:
            if last_exc is not None:
                raise last_exc

        if stream is None:
            return  # defensive — shouldn't happen

        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                final_usage = usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            text = getattr(delta, "content", None)
            if text:
                yield StreamChunk(kind="text", text=text)

            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0) or 0
                slot = tc_acc.setdefault(
                    idx, {"id": "", "name": "", "args_buf": ""}
                )
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args_buf"] += fn.arguments

            fr = getattr(choice, "finish_reason", None)
            if fr:
                last_finish_reason = fr

        for idx in sorted(tc_acc.keys()):
            slot = tc_acc[idx]
            try:
                args = json.loads(slot["args_buf"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": slot["args_buf"]}
            yield StreamChunk(
                kind="tool_call",
                tool_call={
                    "id": slot["id"],
                    "name": slot["name"],
                    "arguments": args,
                },
            )

        tokens_in = getattr(final_usage, "prompt_tokens", 0) if final_usage else 0
        tokens_out = (
            getattr(final_usage, "completion_tokens", 0) if final_usage else 0
        )
        yield StreamChunk(
            kind="done",
            finish_reason=last_finish_reason,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_estimate_cost(self.model, tokens_in, tokens_out),
        )


# ── Anthropic / Claude ─────────────────────────────────────────────────
# Claude pricing per million tokens (Nov 2025 list). Updated alongside
# the model id so cost estimates stay in sync.
_ANTHROPIC_PRICING: dict[str, tuple[float, float]] = {
    # in / out, USD per 1M tokens
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    # Legacy 3.x — kept so a stale env var doesn't zero out cost.
    "claude-3-5-sonnet-latest": (3.0, 15.0),
    "claude-3-5-haiku-latest": (0.80, 4.0),
}


def _anthropic_estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = _ANTHROPIC_PRICING.get(model, (0.0, 0.0))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


# Web search server tool: $10 per 1,000 searches (Nov 2025 list).
_ANTHROPIC_WEB_SEARCH_PRICE_PER_CALL = 0.01


def _anthropic_cost_from_usage(model: str, usage: dict[str, Any]) -> tuple[float, int, int, int]:
    """Compute USD cost + (total_in, total_out, web_searches) from an
    Anthropic ``usage`` block.

    Anthropic reports ``input_tokens`` EXCLUDING cached tokens; cache
    reads bill at 0.1x and cache writes at 1.25x of the input rate.
    Web-search requests bill per call on top of tokens.
    """
    price_in, price_out = _ANTHROPIC_PRICING.get(model, (0.0, 0.0))
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
    server = usage.get("server_tool_use") or {}
    web_searches = int(server.get("web_search_requests") or 0)

    cost = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
    cost += (cache_creation * price_in * 1.25 + cache_read * price_in * 0.10) / 1_000_000
    cost += web_searches * _ANTHROPIC_WEB_SEARCH_PRICE_PER_CALL
    total_in = input_tokens + cache_read + cache_creation
    return cost, total_in, output_tokens, web_searches


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API client.

    Translates OpenAI-style ``messages`` (system + user + assistant)
    into the Anthropic Messages shape (``system`` param + ``messages``
    list without a system role). JSON-mode requests are honoured by
    appending a strict "respond with ONE JSON object, no prose" line
    to the system prompt — Anthropic doesn't expose response_format=json
    today, but with the system instruction Claude reliably emits valid
    JSON for our writer prompts.

    Tool-use is wired through ``tools=[...]`` with Anthropic's native
    schema; we translate back into the same normalized LLMResponse
    shape Groq uses so callers don't care.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> None:
        cfg = settings.LLM.get("anthropic") or {}
        key = api_key or cfg.get("api_key")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Populate it in .env or set "
                "LLM_PROVIDER back to groq/stub."
            )
        import httpx
        try:
            import truststore
            truststore.inject_into_ssl()
        except Exception:  # noqa: BLE001 — non-Windows or already injected
            pass

        verify: bool | str = _resolve_ssl_verify(
            settings.LLM.get("ssl_verify", "")
        )
        if verify is False:
            logger.warning(
                "LLM_SSL_VERIFY=false on Anthropic — TLS verification off."
            )
        self._http = httpx.Client(verify=verify, timeout=float(timeout or 120.0))
        self._api_key = key
        self._base_url = (cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
        self.model = model or cfg.get("model") or "claude-sonnet-4-6"
        self._default_max_tokens = int(max_tokens or cfg.get("max_tokens") or 6000)
        self._default_temperature = float(cfg.get("temperature") or 0.3)
        # Prompt caching: when on, the (large, static) system block is
        # marked ``cache_control: ephemeral`` so repeat runs read it at
        # 0.1x. Harmless when off or when the system block is below the
        # cacheable minimum (Anthropic just ignores the marker).
        cw_cfg = getattr(settings, "CONTENT_WRITER", None) or {}
        self._cache_system = bool(cw_cfg.get("enable_prompt_cache", True))
        self._web_search_beta = bool(cw_cfg.get("web_search_beta", False))

    @staticmethod
    def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """Pull out system messages → concatenate; return (system, rest)."""
        system_parts: list[str] = []
        rest: list[dict[str, Any]] = []
        for m in messages:
            if m.get("role") == "system":
                content = m.get("content")
                if isinstance(content, str):
                    system_parts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            system_parts.append(part.get("text") or "")
            else:
                rest.append(m)
        return "\n\n".join(p for p in system_parts if p), rest

    def _system_field(self, system: str) -> Any:
        """Return the ``system`` request field, marking it cacheable when
        prompt caching is on. Below Anthropic's cacheable minimum the
        marker is silently ignored, so this is always safe."""
        if not system:
            return None
        if self._cache_system:
            return [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }]
        return system

    def _post(self, body: dict[str, Any], *, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self._http.post(
                f"{self._base_url}/v1/messages",
                json=body,
                headers=headers,
            )
        except Exception as exc:  # pragma: no cover - network errors
            logger.error("anthropic POST network failed: %s", exc)
            raise
        if resp.status_code != 200:
            raise RuntimeError(
                f"anthropic http {resp.status_code}: {resp.text[:500]}"
            )
        return resp.json()

    def _parse(self, data: dict[str, Any], req_model: str) -> LLMResponse:
        """Normalize an Anthropic Messages response into LLMResponse.

        Handles text / tool_use blocks plus the web-search server-tool
        blocks (server_tool_use = the query Claude ran;
        web_search_tool_result = the results) and text-block citations.
        """
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        web_results: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        for block in data.get("content") or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text") or "")
                for c in (block.get("citations") or []):
                    if isinstance(c, dict):
                        citations.append({
                            "url": c.get("url", ""),
                            "title": c.get("title", ""),
                            "cited_text": (c.get("cited_text") or "")[:300],
                        })
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": block.get("input") or {},
                })
            elif btype == "web_search_tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    for r in content:
                        if isinstance(r, dict) and r.get("type") == "web_search_result":
                            web_results.append({
                                "url": r.get("url", ""),
                                "title": r.get("title", ""),
                                "page_age": r.get("page_age", ""),
                            })
        usage = data.get("usage") or {}
        cost, total_in, total_out, web_count = _anthropic_cost_from_usage(req_model, usage)
        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tool_calls,
            tokens_in=total_in,
            tokens_out=total_out,
            cost_usd=cost,
            model=data.get("model") or req_model,
            finish_reason=data.get("stop_reason") or "",
            raw=data,
            web_search_results=web_results,
            citations=citations,
            web_search_count=web_count,
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        req_model = model or self.model
        system, rest = self._split_system(messages)
        # Honour the OpenAI-style "response_format=json_object" by hinting
        # in the system prompt — Anthropic complies very reliably. Append
        # BEFORE wrapping for cache so the cached prefix stays byte-stable.
        if response_format and (response_format.get("type") == "json_object"):
            system = (system + "\n\nRespond with ONE valid JSON object. "
                      "Do not wrap it in markdown. Do not emit any prose "
                      "before or after the JSON.").strip()

        body: dict[str, Any] = {
            "model": req_model,
            "messages": rest,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature if temperature is not None else self._default_temperature,
        }
        sys_field = self._system_field(system)
        if sys_field is not None:
            body["system"] = sys_field

        if tools:
            # OpenAI tool schema → Anthropic tool schema.
            body["tools"] = [
                {
                    "name": t["function"]["name"]
                    if t.get("type") == "function" else t.get("name"),
                    "description": (
                        t["function"].get("description")
                        if t.get("type") == "function"
                        else t.get("description")
                    ) or "",
                    "input_schema": (
                        t["function"].get("parameters")
                        if t.get("type") == "function"
                        else t.get("input_schema")
                    ) or {"type": "object", "properties": {}},
                }
                for t in tools
            ]
            if tool_choice == "auto" or tool_choice is None:
                body["tool_choice"] = {"type": "auto"}
            elif isinstance(tool_choice, dict) and tool_choice.get("type") == "function":
                body["tool_choice"] = {
                    "type": "tool", "name": tool_choice["function"]["name"],
                }

        data = self._post(body)
        return self._parse(data, req_model)

    def complete_with_web_search(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
        max_uses: int = 3,
    ) -> LLMResponse:
        """One agentic call with Anthropic's server-side web_search tool.

        Claude runs the searches server-side during this single request
        and returns the final answer plus ``web_search_tool_result``
        blocks (harvested into ``LLMResponse.web_search_results``) and
        per-search billing in ``usage.server_tool_use``.
        """
        req_model = model or self.model
        system, rest = self._split_system(messages)
        body: dict[str, Any] = {
            "model": req_model,
            "messages": rest,
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature if temperature is not None else self._default_temperature,
            "tools": [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": max(1, int(max_uses)),
            }],
        }
        sys_field = self._system_field(system)
        if sys_field is not None:
            body["system"] = sys_field
        extra = {"anthropic-beta": "web-search-2025-03-05"} if self._web_search_beta else None
        data = self._post(body, extra_headers=extra)
        return self._parse(data, req_model)

    def stream_complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Iterator[StreamChunk]:
        """Non-streaming fallback. Yields one synthetic text chunk + done.

        We rarely stream from the content writer — the rewrite is fetched
        as one JSON object and rendered. If streaming becomes important
        for the chat assistant, wire the Anthropic SSE endpoint here.
        """
        resp = self.complete(
            messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if resp.content:
            yield StreamChunk(kind="text", text=resp.content)
        for tc in resp.tool_calls:
            yield StreamChunk(kind="tool_call", tool_call=tc)
        yield StreamChunk(
            kind="done",
            finish_reason=resp.finish_reason,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            cost_usd=resp.cost_usd,
        )


# ── Stub (no network) ──────────────────────────────────────────────────


class StubProvider(LLMProvider):
    """Deterministic stand-in for tests and offline runs.

    Returns an empty JSON object so JSON-schema agents short-circuit to a
    "no findings" state instead of erroring. Lets the rest of the
    pipeline be exercised without consuming the Groq quota.
    """

    name = "stub"
    model = "stub-0"

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content="{}",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model=model or self.model,
            finish_reason="stop",
        )

    def complete_with_web_search(self, messages, **kwargs) -> LLMResponse:
        return self.complete(messages)

    def stream_complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Iterator[StreamChunk]:
        yield StreamChunk(kind="text", text="(stub provider — no LLM configured)")
        yield StreamChunk(kind="done", finish_reason="stop")


def _resolve_ssl_verify(raw: str) -> bool | str:
    """Map LLM_SSL_VERIFY env value → httpx ``verify`` argument.

    Falsy / empty → ``True`` (use certifi). ``"false" / "0" / "no" / "off"``
    → ``False`` (disable verification). Anything else is treated as a
    filesystem path to a CA bundle; if the path doesn't exist we log a
    warning and fall back to default verification rather than crash.
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
        "LLM_SSL_VERIFY=%r does not exist on disk — falling back to "
        "default (certifi) verification.",
        value,
    )
    return True


_singleton: LLMProvider | None = None


def get_provider() -> LLMProvider:
    """Return the configured provider (lazy, cached for the process).

    Currently shipped:
      * ``groq`` — production-ready, multi-key pool with 429 backoff
      * ``stub`` — offline / test mode

    Deferred (prod-cutover work — tracked separately):
      * ``openai``   → add OpenAIProvider class + config section in
                       settings/base.py LLM dict (uses OPENAI_API_KEY)
      * ``anthropic``→ add AnthropicProvider class + config section
                       (uses ANTHROPIC_API_KEY)

    The OPENAI_API_KEY / ANTHROPIC_API_KEY env vars are already used by
    apps.seo_ai.adapters.ai_visibility.* probes (independent subsystem).

    Apify (Meta Ads ingestion via apps.seo_ai.adapters.apify_meta_ads)
    is NOT an LLM provider — it lives outside this factory.
    """
    global _singleton
    if _singleton is not None:
        return _singleton
    provider = settings.LLM["provider"].lower()
    if provider == "groq":
        _singleton = GroqProvider()
    elif provider == "anthropic":
        _singleton = AnthropicProvider()
    elif provider == "stub":
        _singleton = StubProvider()
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER={provider!r}")
    return _singleton


def get_content_writer_provider() -> LLMProvider:
    """Provider used ONLY by the content_writer package.

    Distinct from the process-wide ``get_provider()`` singleton (which
    stays on Groq for the rest of the app). Builds a FRESH, non-cached
    ``AnthropicProvider`` whose default model is the configured writer
    model — cheap stages (query synthesis, clustering) pass
    ``model=CONTENT_WRITER["cheap_model"]`` per call.

    Falls back to the global provider (or stub) when Anthropic isn't
    configured, so the pipeline degrades instead of hard-crashing.
    """
    cw = getattr(settings, "CONTENT_WRITER", None) or {}
    provider_name = (cw.get("provider") or "anthropic").lower()
    if provider_name == "anthropic":
        key = cw.get("api_key") or (settings.LLM.get("anthropic") or {}).get("api_key")
        if key:
            try:
                return AnthropicProvider(
                    api_key=key,
                    model=cw.get("writer_model"),
                    max_tokens=cw.get("writer_max_tokens"),
                    timeout=cw.get("request_timeout_sec"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "content-writer Anthropic provider init failed (%s); "
                    "falling back to global provider", exc,
                )
    try:
        return get_provider()
    except Exception:  # noqa: BLE001
        return StubProvider()
