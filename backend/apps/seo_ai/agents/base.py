"""Shared agent base.

Every specialist subclasses :class:`Agent`. The base handles three
concerns the specialists shouldn't:

1. **LLM transport.** Pulls the configured provider, prepends the
   agent's system prompt, forwards the validated user payload, and
   normalizes the response.
2. **Schema enforcement.** The LLM is asked to emit JSON; we validate
   that JSON against the agent's output schema before any downstream
   step trusts it. Two retries on schema failure with a tightened
   "fix the JSON to match this schema" repair prompt.
3. **Conversation logging.** Each call is persisted as a
   :class:`SEORunMessage`. The run replay machinery reads these back.

Agents do **not** call each other — they return structured payloads to
the orchestrator. This keeps the call graph one-level deep and the
audit trail readable.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from ..llm import LLMProvider, LLMResponse, get_provider
from ..models import SEORun, SEORunMessage

logger = logging.getLogger("seo.ai.agents")


class AgentError(RuntimeError):
    pass


@dataclass
class AgentResult:
    """Structured return for orchestrator wiring."""

    payload: dict[str, Any]
    cost_usd: float
    tokens_in: int
    tokens_out: int
    step_index: int


@dataclass
class FindingDraft:
    """Detection-only finding produced by the Phase-2 gap-analysis agents.

    Deliberately omits a ``recommendation`` field — these agents only
    *detect* weak points; suggesting fixes is a later phase. The
    orchestrator's persistence step writes these rows into
    :class:`SEORunFinding` with ``recommendation=""``.
    """

    category: str
    severity: str               # "critical" | "warning" | "notice"
    title: str
    description: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    impact: str = "medium"      # "high" | "medium" | "low"
    # ``effort`` is left blank for detection-only agents — costing the
    # fix is a job for the next-phase recommender.
    effort: str = ""


class Agent:
    """Subclasses set ``name``, ``system_prompt``, ``output_schema``."""

    name: str = "base"
    system_prompt: str = "You are a helpful SEO analyst."
    output_schema: dict[str, Any] | None = None

    def __init__(
        self,
        run: SEORun,
        *,
        step_index_start: int,
        provider: LLMProvider | None = None,
    ) -> None:
        self.run = run
        self.step_index = step_index_start
        self.provider = provider or get_provider()

    # ── subclass-facing API ───────────────────────────────────────────

    def call_model(
        self,
        user_payload: dict[str, Any],
        *,
        instruction: str,
        max_repair_attempts: int = 2,
    ) -> AgentResult:
        """Run one prompt → JSON-validated payload loop.

        ``instruction`` is the user-turn text — the per-call analytical
        ask, separate from the agent's stable system prompt. Heavy facts
        ride along as the ``user_payload`` dict, JSON-stringified into
        the same user message — keeps the call shape one-turn so the
        provider's tool-loop machinery isn't needed for the simple case.
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": _build_user_content(instruction, user_payload),
            },
        ]
        attempt = 0
        last_error: Exception | None = None
        total_tokens_in = 0
        total_tokens_out = 0
        total_cost = 0.0

        while attempt <= max_repair_attempts:
            attempt += 1
            t0 = time.time()
            resp: LLMResponse = self.provider.complete(
                messages=messages,
                response_format={"type": "json_object"} if self.output_schema else None,
            )
            self._log_message(
                role="assistant",
                content={"text": resp.content},
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                cost_usd=resp.cost_usd,
            )
            total_tokens_in += resp.tokens_in
            total_tokens_out += resp.tokens_out
            total_cost += resp.cost_usd

            try:
                parsed = _parse_json(resp.content)
            except ValueError as exc:
                last_error = exc
                messages.append({"role": "assistant", "content": resp.content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was not valid JSON. "
                            f"Error: {exc}. Reply ONLY with a single valid "
                            "JSON object matching the schema, no prose."
                        ),
                    }
                )
                continue

            if self.output_schema is not None:
                try:
                    jsonschema.validate(parsed, self.output_schema)
                except jsonschema.ValidationError as exc:
                    last_error = exc
                    messages.append({"role": "assistant", "content": resp.content})
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Your JSON did not pass schema validation. "
                                f"Error: {exc.message}. Path: "
                                f"{list(exc.absolute_path)}. Reply with a "
                                "corrected JSON object."
                            ),
                        }
                    )
                    continue

            logger.info(
                "%s ok after %d attempt(s) in %.2fs (cost $%.4f)",
                self.name,
                attempt,
                time.time() - t0,
                total_cost,
            )
            self.step_index += 1
            return AgentResult(
                payload=parsed,
                cost_usd=total_cost,
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                step_index=self.step_index,
            )

        raise AgentError(
            f"{self.name}: failed to produce valid JSON after "
            f"{max_repair_attempts + 1} attempts: {last_error}"
        )

    # ── conversation logging ──────────────────────────────────────────

    def _log_message(
        self,
        *,
        role: str,
        content: dict[str, Any],
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        to_agent: str = "",
    ) -> None:
        SEORunMessage.objects.create(
            run=self.run,
            step_index=self.step_index,
            from_agent=self.name,
            to_agent=to_agent,
            role=role,
            content=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

    def log_system_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        """Persist a non-LLM step (data fetched, decision taken, etc.)."""
        self._log_message(role="system", content={"event": event, "data": payload or {}})
        self.step_index += 1

    # ── detection-only API ──────────────────────────────────────────────
    #
    # The newer gap-analysis agents (AISearchVisibility, SERPVisibility,
    # TechnicalAudit, etc.) operate in detection mode: they emit a list
    # of weak-point :class:`FindingDraft` entries rather than calling the
    # LLM for narration. Subclasses override :meth:`detect` and (when
    # they cite specific evidence) :meth:`valid_evidence_keys`.

    def detect(self, *, domain: str) -> list[FindingDraft]:
        """Return a list of detection-only findings for the given domain.

        Default implementation is a no-op so legacy specialists can keep
        their JSON-mode ``call_model()`` path without implementing
        ``detect()``. Detection agents override this.
        """
        return []

    def valid_evidence_keys(self) -> set[str]:
        """Return the set of evidence-ref keys this agent legitimately
        cites. The critic consults this when validating findings; an
        empty set is interpreted by the orchestrator as "skip critic
        validation for this agent" (detection-only agents are
        deterministic, so there's nothing to fact-check).
        """
        return set()


# ── helpers ──────────────────────────────────────────────────────────────


def _build_user_content(instruction: str, payload: dict[str, Any]) -> str:
    """Combine the instruction + facts into one user-turn message.

    The facts ride in a fenced JSON block so the model treats them as
    data rather than instructions (mitigates prompt injection from any
    crawled content that ends up in the payload).
    """
    return (
        instruction.strip()
        + "\n\n<facts>\n```json\n"
        + json.dumps(payload, default=str, indent=2)
        + "\n```\n</facts>\n"
        "All claims in your reply MUST cite an evidence_ref drawn from "
        "the facts above. Do not invent URLs, numbers, or sources."
    )


def _parse_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    # Be forgiving: some Groq variants wrap the JSON in ```json``` fences.
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
