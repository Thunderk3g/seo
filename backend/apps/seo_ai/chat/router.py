"""Per-turn chat router.

Takes a full client-supplied message history, prepends the system
prompt, runs a streaming completion against the configured LLM
provider, dispatches tool calls, and yields Server-Sent Events back to
the caller.

Wire shape (one turn):

    user message
        ↓
    [stream tokens] → SSE: event=token data={"text":"..."}
    [tool_calls assembled]
        ↓ for each call:
           - run handler synchronously
           - SSE: event=tool_call data={"name":..., "args":..., "result":...}
           - if call was emit_card, also SSE: event=card data={...payload}
        ↓
    [feed tool results back into messages, loop]
        ↓ when finish_reason == "stop":
    SSE: event=done data={"tokens_in":N, "tokens_out":N, "cost_usd":F}

Bounded at ``MAX_TOOL_ROUNDS`` to defang a runaway model.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from ..llm import StreamChunk, get_provider
from .system_prompt import SYSTEM_PROMPT
from .tools import TOOL_HANDLERS, TOOL_SCHEMAS

logger = logging.getLogger("seo.ai.chat.router")

MAX_TOOL_ROUNDS = 5


def _sse(event: str, data: dict[str, Any]) -> str:
    """Encode one SSE frame. Newline-terminated per the spec."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


class ChatRouter:
    """Stateless per-turn handler. New instance per request."""

    def __init__(self, *, domain: str = "bajajlifeinsurance.com") -> None:
        self.domain = domain
        self.provider = get_provider()
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_cost = 0.0

    # ── public SSE entrypoint ─────────────────────────────────────────

    def handle_sse(self, messages: list[dict[str, Any]]) -> Iterator[str]:
        """Yield SSE-formatted strings. Wraps :meth:`handle` for views."""
        try:
            for event_name, data in self.handle(messages):
                yield _sse(event_name, data)
        except Exception as exc:  # noqa: BLE001 - surface to client
            logger.exception("chat router crashed")
            yield _sse(
                "error",
                {"message": f"{type(exc).__name__}: {exc}"[:300]},
            )

    # ── per-turn loop ────────────────────────────────────────────────

    def handle(
        self, messages: list[dict[str, Any]]
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        # Defensive: trim runaway client-side histories to the last 30
        # turns. Each turn carries facts blocks (tool results) which can
        # be sizable.
        client_messages = self._sanitize(messages)[-30:]
        # Inject domain context as a final system note so the model has
        # the active domain without the user having to repeat it.
        domain_hint = {
            "role": "system",
            "content": (
                f"Active domain: {self.domain}. Treat questions without "
                "an explicit domain as being about this site."
            ),
        }
        convo: list[dict[str, Any]] = (
            [{"role": "system", "content": SYSTEM_PROMPT}, domain_hint]
            + client_messages
        )

        for _round in range(MAX_TOOL_ROUNDS):
            assistant_text_buf: list[str] = []
            assistant_tool_calls: list[dict[str, Any]] = []
            finish_reason = ""

            for chunk in self.provider.stream_complete(
                convo,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            ):
                if chunk.kind == "text":
                    assistant_text_buf.append(chunk.text)
                    yield "token", {"text": chunk.text}
                elif chunk.kind == "tool_call" and chunk.tool_call:
                    assistant_tool_calls.append(chunk.tool_call)
                elif chunk.kind == "done":
                    finish_reason = chunk.finish_reason
                    self.total_tokens_in += chunk.tokens_in
                    self.total_tokens_out += chunk.tokens_out
                    self.total_cost += chunk.cost_usd

            # Record what the assistant just said into the running
            # conversation so the next round (if any) sees it.
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(assistant_text_buf) or None,
            }
            if assistant_tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("arguments") or {}),
                        },
                    }
                    for tc in assistant_tool_calls
                ]
            convo.append(assistant_msg)

            # No tool calls → we're done.
            if not assistant_tool_calls:
                break

            # Dispatch each tool call sequentially. Emit a tool_call SSE
            # event with the result, plus a card event for emit_card.
            for tc in assistant_tool_calls:
                name = tc.get("name") or ""
                args = tc.get("arguments") or {}
                handler = TOOL_HANDLERS.get(name)
                if handler is None:
                    result = {"ok": False, "error": f"unknown tool: {name}"}
                else:
                    try:
                        result = handler(**args)
                    except TypeError as exc:
                        # Bad argument names from the model — surface as
                        # a tool-side error rather than 500ing the SSE.
                        result = {
                            "ok": False,
                            "error": f"bad arguments: {exc}",
                        }

                yield "tool_call", {
                    "id": tc.get("id", ""),
                    "name": name,
                    "args": args,
                    "result": result,
                }

                if name == "emit_card" and isinstance(args, dict):
                    yield "card", {
                        "card_type": args.get("card_type", ""),
                        "payload": args.get("payload") or {},
                    }

                # Feed the result back as a tool message for the next
                # round. JSON-stringify per the OpenAI tool protocol.
                convo.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": json.dumps(result, default=str),
                    }
                )

            if finish_reason == "stop":
                # Model produced a final answer alongside tool calls —
                # unusual but possible. Don't loop again.
                break
        else:
            # Hit the round cap without natural termination.
            yield "token", {
                "text": (
                    "\n\n_(Reached the tool-call depth limit — answering "
                    "with the data gathered so far.)_"
                ),
            }

        yield "done", {
            "tokens_in": self.total_tokens_in,
            "tokens_out": self.total_tokens_out,
            "cost_usd": round(self.total_cost, 6),
        }

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _sanitize(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop any client-supplied system messages and any role we
        don't expect, then strip extra keys so we send the provider a
        clean OpenAI-shaped history.
        """
        allowed_roles = {"user", "assistant", "tool"}
        out: list[dict[str, Any]] = []
        for m in messages or []:
            if not isinstance(m, dict):
                continue
            role = m.get("role")
            if role not in allowed_roles:
                continue
            entry: dict[str, Any] = {"role": role, "content": m.get("content") or ""}
            if role == "tool" and m.get("tool_call_id"):
                entry["tool_call_id"] = m["tool_call_id"]
            if role == "assistant" and m.get("tool_calls"):
                entry["tool_calls"] = m["tool_calls"]
            out.append(entry)
        return out
