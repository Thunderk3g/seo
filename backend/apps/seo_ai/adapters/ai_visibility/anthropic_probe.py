"""Anthropic Claude visibility probe.

Uses the Messages API. Claude doesn't natively browse the web in the
standalone API call (Anthropic exposes a web-search beta only on
specific tiers), so this probe captures the model's intrinsic
knowledge — useful for "is the brand recognised?" checks even without
live citations.
"""
from __future__ import annotations

import logging

from django.conf import settings

from .base import AILLMProbeAdapter, AIProbeResult, AdapterDisabledError

logger = logging.getLogger("seo.ai.adapters.ai_visibility.anthropic")


_AI_VISIBILITY_PROMPT = (
    "You are answering a real user's search query. Provide a concise, "
    "accurate answer naming the specific companies, brands, products, "
    "or websites you would recommend. Include source URLs where you "
    "know them. If the query is comparative, name each compared entity "
    "explicitly.\n\n"
    "User query: {query}"
)


class AnthropicProbe(AILLMProbeAdapter):
    provider = "anthropic"

    def __init__(self) -> None:
        super().__init__()
        cfg = settings.AI_VISIBILITY
        key = (cfg.get("anthropic_api_key") or "").strip()
        if not key:
            raise AdapterDisabledError("ANTHROPIC_API_KEY not set")
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise AdapterDisabledError(
                "anthropic SDK not installed; pip install anthropic"
            ) from exc
        import httpx

        self.model = cfg.get("anthropic_model") or "claude-3-5-haiku-latest"
        self._client = anthropic.Anthropic(
            api_key=key,
            http_client=httpx.Client(
                verify=self.ssl_verify, timeout=self.request_timeout_sec
            ),
        )

    def _probe(self, query: str) -> AIProbeResult:
        prompt = _AI_VISIBILITY_PROMPT.format(query=query)
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        # Concatenate all text blocks. Skip non-text blocks (tool_use,
        # thinking, etc.) so we only score on what a user would read.
        parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", "") or "")
        text = "".join(parts)
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
