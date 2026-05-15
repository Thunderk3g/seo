"""AI-visibility probe registry.

The :class:`AISearchVisibilityAgent` walks the ``PROVIDER_REGISTRY`` to
discover which providers are wired up at runtime. Each adapter class
self-gates inside its ``__init__`` — if env keys or SDK packages are
missing it raises :class:`AdapterDisabledError`, which the agent
catches to skip that provider while running the others.
"""
from .anthropic_probe import AnthropicProbe
from .base import AdapterDisabledError, AILLMProbeAdapter, AIProbeResult
from .gemini_probe import GeminiProbe
from .grok_probe import GrokProbe
from .openai_probe import OpenAIProbe
from .perplexity_probe import PerplexityProbe

PROVIDER_REGISTRY: list[type[AILLMProbeAdapter]] = [
    OpenAIProbe,
    AnthropicProbe,
    GeminiProbe,
    PerplexityProbe,
    GrokProbe,
]

__all__ = [
    "AILLMProbeAdapter",
    "AIProbeResult",
    "AdapterDisabledError",
    "PROVIDER_REGISTRY",
    "OpenAIProbe",
    "AnthropicProbe",
    "GeminiProbe",
    "PerplexityProbe",
    "GrokProbe",
]
