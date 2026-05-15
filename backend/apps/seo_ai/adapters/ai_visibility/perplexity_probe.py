"""Perplexity AI visibility probe.

Direct HTTPS to the Perplexity API (OpenAI-compatible chat-completions
endpoint at ``https://api.perplexity.ai``). No SDK dependency. The
``sonar`` model family returns ``citations`` in the response — those
are the URLs the assistant grounded its answer on, which is exactly
what we want for visibility scoring.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

from .base import AILLMProbeAdapter, AIProbeResult, AdapterDisabledError

logger = logging.getLogger("seo.ai.adapters.ai_visibility.perplexity")


_AI_VISIBILITY_PROMPT = (
    "You are answering a real user's search query as a search "
    "assistant. Provide a concise, accurate answer naming the "
    "specific companies, brands, products, or websites you would "
    "recommend. If the query is comparative, name each compared "
    "entity explicitly.\n\n"
    "User query: {query}"
)


class PerplexityProbe(AILLMProbeAdapter):
    provider = "perplexity"

    def __init__(self) -> None:
        super().__init__()
        cfg = settings.AI_VISIBILITY
        key = (cfg.get("perplexity_api_key") or "").strip()
        if not key:
            raise AdapterDisabledError("PERPLEXITY_API_KEY not set")
        self.model = cfg.get("perplexity_model") or "sonar"
        self._key = key
        self._url = "https://api.perplexity.ai/chat/completions"

    def _probe(self, query: str) -> AIProbeResult:
        prompt = _AI_VISIBILITY_PROMPT.format(query=query)
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            self._url,
            json=body,
            headers=headers,
            timeout=self.request_timeout_sec,
            verify=self.ssl_verify,
        )
        if resp.status_code != 200:
            return AIProbeResult(
                provider=self.provider,
                query=query,
                error=f"http {resp.status_code}: {resp.text[:300]}",
            )
        data = resp.json()
        text = ""
        choices = data.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            text = msg.get("content") or ""
        cited = list(data.get("citations") or [])
        usage = data.get("usage") or {}
        return AIProbeResult(
            provider=self.provider,
            query=query,
            answer_text=text,
            cited_urls=cited,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            raw=data,
        )
