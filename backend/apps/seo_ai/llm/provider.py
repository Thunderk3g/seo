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

        self._client = OpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            http_client=http_client,
        )
        self.model = cfg["model"]
        self._default_max_tokens = cfg["max_tokens"]
        self._default_temperature = cfg["temperature"]

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
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

        # Groq free tier is rate-limited per minute. A 413/429 on a
        # 4k-token prompt almost always means "another concurrent
        # request just ate your budget" — backing off briefly and
        # retrying once typically clears it without bothering the user.
        import time as _time

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                break
            except Exception as exc:  # pragma: no cover - network errors
                msg = str(exc).lower()
                last_exc = exc
                retryable = (
                    "rate_limit" in msg
                    or "tokens per minute" in msg
                    or "429" in msg
                    or "413" in msg
                )
                if retryable and attempt < 2:
                    wait = 30 if "tokens per minute" in msg else 5 * (attempt + 1)
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

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_estimate_cost(self.model, tokens_in, tokens_out),
            model=self.model,
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

        stream = self._client.chat.completions.create(**kwargs)
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
    ) -> LLMResponse:
        return LLMResponse(
            content="{}",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            model=self.model,
            finish_reason="stop",
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
    """Return the configured provider (lazy, cached for the process)."""
    global _singleton
    if _singleton is not None:
        return _singleton
    provider = settings.LLM["provider"].lower()
    if provider == "groq":
        _singleton = GroqProvider()
    elif provider == "stub":
        _singleton = StubProvider()
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER={provider!r}")
    return _singleton
