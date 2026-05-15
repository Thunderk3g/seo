"""Google Gemini visibility probe.

Uses the ``google-generativeai`` SDK. When the model has Google-Search
grounding enabled it returns ``grounding_metadata`` with citation URLs;
we extract those alongside the answer text.
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


class GeminiProbe(AILLMProbeAdapter):
    provider = "google"

    def __init__(self) -> None:
        super().__init__()
        cfg = settings.AI_VISIBILITY
        key = (cfg.get("google_api_key") or "").strip()
        if not key:
            raise AdapterDisabledError("GOOGLE_API_KEY not set")
        try:
            import google.generativeai as genai  # type: ignore
        except ImportError as exc:
            raise AdapterDisabledError(
                "google-generativeai SDK not installed; "
                "pip install google-generativeai"
            ) from exc
        self.model_name = cfg.get("google_model") or "gemini-2.0-flash"
        genai.configure(api_key=key)
        self._genai = genai

    def _probe(self, query: str) -> AIProbeResult:
        prompt = _AI_VISIBILITY_PROMPT.format(query=query)
        model = self._genai.GenerativeModel(self.model_name)
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None) or ""

        # Pull grounding citations when present.
        cited: list[str] = []
        try:
            candidates = getattr(resp, "candidates", None) or []
            for cand in candidates:
                meta = getattr(cand, "grounding_metadata", None)
                if not meta:
                    continue
                for chunk in getattr(meta, "grounding_chunks", None) or []:
                    web = getattr(chunk, "web", None)
                    uri = getattr(web, "uri", None) if web else None
                    if uri:
                        cited.append(uri)
        except Exception as exc:  # noqa: BLE001 - grounding is optional
            logger.debug("gemini grounding extract failed: %s", exc)

        usage = getattr(resp, "usage_metadata", None)
        tokens_in = (
            getattr(usage, "prompt_token_count", 0) if usage else 0
        )
        tokens_out = (
            getattr(usage, "candidates_token_count", 0) if usage else 0
        )
        raw: dict[str, Any]
        try:
            raw = resp.to_dict() if hasattr(resp, "to_dict") else {}
        except Exception:  # noqa: BLE001
            raw = {}
        return AIProbeResult(
            provider=self.provider,
            query=query,
            answer_text=text,
            cited_urls=cited,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            raw=raw,
        )
