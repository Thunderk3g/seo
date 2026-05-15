"""Default seed queries for AI-visibility + SERP-visibility probes.

Edit the lists below to tune what we probe LLMs and search engines for.
Six buckets so the agents can balance breadth (covers many intents)
against per-bucket caps when ``max_queries`` is small.

Bucket guidance (life-insurance vertical for bajajlifeinsurance.com):

* ``PRIMARY``           — head terms ("term insurance", "ULIP plan").
* ``COMMERCIAL``        — buyer-intent qualifiers ("best", "compare", "buy").
* ``INFORMATIONAL``     — explainer queries ("what is", "how to").
* ``BRAND_COMPARISON``  — Bajaj vs. each rival.
* ``LONG_TAIL``         — multi-word, niche queries.
* ``CONVERSATIONAL``    — ChatGPT-style natural-language asks.

Adding 5-10 to any bucket is fine — both probe agents cap at
``settings.AI_VISIBILITY['max_queries']`` / ``settings.SERP_API['max_queries']``
total to control cost.
"""
from __future__ import annotations

PRIMARY: list[str] = [
    "term insurance",
    "life insurance",
    "ULIP plan",
    "endowment policy",
    "retirement plan",
    "pension plan",
    "child education plan",
    "money back policy",
]

COMMERCIAL: list[str] = [
    "best term insurance in India",
    "best life insurance company in India 2026",
    "best ULIP plan for long term",
    "compare term insurance plans India",
    "buy term insurance online India",
    "best retirement plan India",
    "lowest premium term insurance",
]

INFORMATIONAL: list[str] = [
    "what is term insurance",
    "what is ULIP",
    "how to claim life insurance",
    "term insurance vs whole life insurance",
    "tax benefits on life insurance section 80C",
    "what is claim settlement ratio",
    "how to calculate life insurance cover",
]

BRAND_COMPARISON: list[str] = [
    "Bajaj Allianz Life vs HDFC Life",
    "Bajaj Allianz Life vs ICICI Prudential Life",
    "Bajaj Allianz Life vs LIC",
    "Bajaj Allianz Life vs Max Life",
    "Bajaj Allianz Life vs SBI Life",
    "Bajaj Allianz Life term insurance review",
]

LONG_TAIL: list[str] = [
    "term insurance for NRI with Indian income",
    "term insurance for women housewives",
    "term insurance with return of premium",
    "ULIP for child higher education planning",
    "pension plan for self employed India",
    "best critical illness rider in term insurance",
    "term insurance for smokers in India",
]

CONVERSATIONAL: list[str] = [
    "I am 32 and earn 12 lakh — which term insurance plan should I buy?",
    "How much life insurance cover do I need for a family of four?",
    "Is ULIP better than mutual fund for tax saving?",
    "What happens to my term insurance if I become an NRI?",
    "Which Indian life insurer has the fastest claim settlement?",
]


def load_queries(*, max_per_bucket: int | None = None) -> list[str]:
    """Flatten the six buckets into one de-duplicated list.

    ``max_per_bucket`` truncates each bucket before flattening so a
    cost-constrained probe can sample broadly without paying for every
    bucket's full list. Order is preserved (PRIMARY first, etc.) so
    head-term queries are tried first when a global cap kicks in
    downstream.
    """
    seen: set[str] = set()
    out: list[str] = []
    for bucket in (
        PRIMARY,
        COMMERCIAL,
        INFORMATIONAL,
        BRAND_COMPARISON,
        LONG_TAIL,
        CONVERSATIONAL,
    ):
        items = bucket[:max_per_bucket] if max_per_bucket else bucket
        for q in items:
            normalized = q.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized)
    return out
