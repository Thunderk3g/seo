"""Seed query lists for the AI-visibility + SERP-visibility detection
agents. Single module exposing :func:`load_queries` so callers don't
care about bucket layout.
"""
from .seed_queries import (
    BRAND_COMPARISON,
    COMMERCIAL,
    CONVERSATIONAL,
    INFORMATIONAL,
    LONG_TAIL,
    PRIMARY,
    load_queries,
)

__all__ = [
    "PRIMARY",
    "COMMERCIAL",
    "INFORMATIONAL",
    "BRAND_COMPARISON",
    "LONG_TAIL",
    "CONVERSATIONAL",
    "load_queries",
]
