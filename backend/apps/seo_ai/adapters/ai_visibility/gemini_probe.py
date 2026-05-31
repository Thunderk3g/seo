"""Google Gemini visibility probe (REST, web-grounded).

Uses the Generative Language REST API over httpx instead of the
``google-generativeai`` SDK — the SDK isn't installed in the runtime
image and corp-CA TLS makes a runtime pip install unreliable, whereas
httpx + truststore already work for every other adapter.

Grounding (G2): the request sends ``tools=[{"google_search": {}}]`` so
Gemini answers from live Google Search and returns ``groundingMetadata``
with real citation URLs (not training-data recall). If the model/tier
rejects the tool, we retry once without it so the probe still returns an
answer (flagged as ungrounded by the empty citation list).
"""
from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from .base import AILLMProbeAdapter, AIProbeResult, AdapterDisabledError

logger = logging.getLogger("seo.ai.adapters.ai_visibility.gemini")


_AI_VISIBILITY_PROMPT = (
    "You are answering a real user's search query as if you were a "
    "search assistant. Provide a concise, accurate answer naming any "
    "specific companies, brands, products, or websites you would "
    "recommend. Include source URLs when relevant. If the query is "
    "comparative, name each compared entity explicitly.\n\n"
    "User query: {query}"
)

# Gemini list price per 1M tokens (Nov 2025). Flash is the default.
_GEMINI_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-001": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.0),
}


def _gemini_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = _GEMINI_PRICING.get(model, (0.10, 0.40))
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


class GeminiProbe(AILLMProbeAdapter):
    provider = "google"

    _BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self) -> None:
        super().__init__()
        cfg = settings.AI_VISIBILITY
        key = (cfg.get("google_api_key") or "").strip()
        if not key:
            raise AdapterDisabledError("GOOGLE_API_KEY not set")
        self._key = key
        self.model_name = cfg.get("google_model") or "gemini-2.0-flash"

    def _post(self, body: dict[str, Any]):
        import httpx

        url = f"{self._BASE}/{self.model_name}:generateContent"
        return httpx.post(
            url,
            params={"key": self._key},
            json=body,
            headers={"content-type": "application/json"},
            timeout=float(self.request_timeout_sec),
            verify=self.ssl_verify,
        )

    def _probe(self, query: str) -> AIProbeResult:
        prompt = _AI_VISIBILITY_PROMPT.format(query=query)
        contents = [{"role": "user", "parts": [{"text": prompt}]}]

        # G2: ask for live Google-Search grounding. Retry once without the
        # tool if the tier/model rejects it, so we always get an answer.
        grounded = {"contents": contents, "tools": [{"google_search": {}}]}
        resp = self._post(grounded)
        if resp.status_code != 200:
            logger.info(
                "gemini grounded call %s — retrying ungrounded", resp.status_code,
            )
            resp = self._post({"contents": contents})
        if resp.status_code != 200:
            return AIProbeResult(
                provider=self.provider, query=query,
                error=f"gemini http {resp.status_code}: {resp.text[:300]}",
            )
        data = resp.json()

        text_parts: list[str] = []
        cited: list[str] = []
        for cand in (data.get("candidates") or []):
            content = cand.get("content") or {}
            for part in (content.get("parts") or []):
                if isinstance(part, dict) and part.get("text"):
                    text_parts.append(part["text"])
            meta = cand.get("groundingMetadata") or {}
            for chunk in (meta.get("groundingChunks") or []):
                web = (chunk or {}).get("web") or {}
                uri = web.get("uri")
                if uri:
                    cited.append(uri)
        usage = data.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount") or 0)
        tokens_out = int(usage.get("candidatesTokenCount") or 0)
        return AIProbeResult(
            provider=self.provider,
            query=query,
            answer_text="".join(text_parts),
            cited_urls=cited,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=_gemini_cost(self.model_name, tokens_in, tokens_out),
            raw=data,
        )
