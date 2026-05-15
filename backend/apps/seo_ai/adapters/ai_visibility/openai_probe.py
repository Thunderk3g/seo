"""OpenAI ChatGPT visibility probe.

Uses the OpenAI Responses API with the ``web_search_preview`` tool so
the model returns live citations. Falls back to plain chat-completion
if the SDK or tool isn't available. Both modes pass through the same
:class:`AIProbeResult` shape.
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from .base import AILLMProbeAdapter, AIProbeResult, AdapterDisabledError

logger = logging.getLogger("seo.ai.adapters.ai_visibility.openai")


_AI_VISIBILITY_PROMPT = (
    "You are answering a real user's search query as if you were a "
    "search assistant. Provide a concise, accurate answer naming any "
    "specific companies, brands, products, or websites you would "
    "recommend. List source URLs when relevant. If the query is "
    "comparative, name each compared entity explicitly.\n\n"
    "User query: {query}"
)


class OpenAIProbe(AILLMProbeAdapter):
    provider = "openai"

    def __init__(self) -> None:
        super().__init__()
        cfg = settings.AI_VISIBILITY
        key = (cfg.get("openai_api_key") or "").strip()
        if not key:
            raise AdapterDisabledError("OPENAI_API_KEY not set")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise AdapterDisabledError(
                "openai SDK not installed; pip install openai"
            ) from exc
        import httpx

        self.model = cfg.get("openai_model") or "gpt-4o-mini"
        self._client = OpenAI(
            api_key=key,
            http_client=httpx.Client(
                verify=self.ssl_verify, timeout=self.request_timeout_sec
            ),
        )

    def _probe(self, query: str) -> AIProbeResult:
        prompt = _AI_VISIBILITY_PROMPT.format(query=query)
        # Try the Responses API with web search first; fall back to
        # chat completions if the account / model doesn't expose it.
        try:
            resp = self._client.responses.create(
                model=self.model,
                input=prompt,
                tools=[{"type": "web_search_preview"}],
            )
            text = getattr(resp, "output_text", "") or ""
            usage = getattr(resp, "usage", None)
            tokens_in = getattr(usage, "input_tokens", 0) if usage else 0
            tokens_out = getattr(usage, "output_tokens", 0) if usage else 0
            return AIProbeResult(
                provider=self.provider,
                query=query,
                answer_text=text,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
            )
        except Exception as exc:  # noqa: BLE001 - fall through
            logger.info(
                "openai responses API failed; falling back to chat: %s", exc
            )

        # Plain chat-completions fallback. Doesn't browse — citations
        # come purely from the model's training data, which is still
        # informative for "is this brand known?" checks.
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        choice = resp.choices[0]
        text = (choice.message.content or "") if choice.message else ""
        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", 0) if usage else 0
        tokens_out = getattr(usage, "completion_tokens", 0) if usage else 0
        return AIProbeResult(
            provider=self.provider,
            query=query,
            answer_text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            raw=resp.model_dump() if hasattr(resp, "model_dump") else None,
        )
