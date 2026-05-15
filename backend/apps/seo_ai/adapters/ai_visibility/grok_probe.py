"""xAI Grok visibility probe.

Direct HTTPS to xAI's OpenAI-compatible chat endpoint at
``https://api.x.ai/v1/chat/completions``. No SDK dependency.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

from .base import AILLMProbeAdapter, AIProbeResult, AdapterDisabledError

logger = logging.getLogger("seo.ai.adapters.ai_visibility.grok")


_AI_VISIBILITY_PROMPT = (
    "You are answering a real user's search query as a search "
    "assistant. Provide a concise, accurate answer naming the "
    "specific companies, brands, products, or websites you would "
    "recommend. List source URLs where you know them. If the query is "
    "comparative, name each compared entity explicitly.\n\n"
    "User query: {query}"
)


class GrokProbe(AILLMProbeAdapter):
    provider = "xai"

    def __init__(self) -> None:
        super().__init__()
        cfg = settings.AI_VISIBILITY
        key = (cfg.get("xai_api_key") or "").strip()
        if not key:
            raise AdapterDisabledError("XAI_API_KEY not set")
        self.model = cfg.get("xai_model") or "grok-2-latest"
        self._key = key
        self._url = "https://api.x.ai/v1/chat/completions"

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
        usage = data.get("usage") or {}
        return AIProbeResult(
            provider=self.provider,
            query=query,
            answer_text=text,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            raw=data,
        )
