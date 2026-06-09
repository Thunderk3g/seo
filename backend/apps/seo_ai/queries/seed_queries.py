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

2026-06-10 expansion: ~100 queries covering EVERY product line on
bajajlifeinsurance.com (term, ULIP/investment, savings/endowment,
guaranteed income, retirement/pension/annuity, child, NRI, group,
health/riders, funds/NAV, calculators, tax, claims) so a no-LLM
pipeline run still probes the full product surface. The gap pipeline
falls back to this file verbatim when no LLM provider is configured.
"""
from __future__ import annotations

PRIMARY: list[str] = [
    "term insurance",
    "life insurance",
    "ULIP plan",
    "endowment policy",
    "guaranteed income plan",
    "guaranteed return investment plan",
    "retirement plan",
    "pension plan",
    "annuity plan",
    "child education plan",
    "child investment plan",
    "money back policy",
    "savings plan with life cover",
    "whole life insurance",
    "investment plan with insurance",
    "NRI life insurance",
    "group life insurance",
    "term insurance with return of premium",
]

COMMERCIAL: list[str] = [
    "best term insurance in India",
    "best term insurance plan 2026",
    "best life insurance company in India 2026",
    "best ULIP plan for long term",
    "best ULIP plan 2026",
    "compare term insurance plans India",
    "buy term insurance online India",
    "best retirement plan India",
    "best pension plan in India 2026",
    "best annuity plan for senior citizens India",
    "best guaranteed income plan India",
    "best child education plan India",
    "best investment plan for 5 years India",
    "best investment plan for 10 years India",
    "best savings plan in India",
    "best money back policy India",
    "lowest premium term insurance",
    "1 crore term insurance premium",
    "2 crore term insurance plan",
    "best term plan for self employed",
    "best life insurance plan for NRI",
    "best tax saving investment under 80C",
    "term insurance offers online discount",
]

INFORMATIONAL: list[str] = [
    "what is term insurance",
    "what is ULIP",
    "what is endowment plan",
    "what is annuity",
    "what is guaranteed income plan",
    "what is a money back policy",
    "what is rider in insurance",
    "what is claim settlement ratio",
    "what is surrender value of life insurance",
    "what is sum assured in life insurance",
    "how to claim life insurance",
    "how to choose term insurance cover amount",
    "how to calculate life insurance cover",
    "how does ULIP work",
    "how is term insurance premium calculated",
    "term insurance vs whole life insurance",
    "term insurance vs life insurance difference",
    "ULIP vs mutual fund which is better",
    "ULIP vs ELSS for tax saving",
    "endowment vs ULIP difference",
    "annuity vs pension plan difference",
    "NPS vs pension plan from insurance company",
    "tax benefits on life insurance section 80C",
    "section 10(10D) exemption on maturity amount",
    "is ULIP maturity amount taxable",
    "life insurance premium calculator how it works",
    "what is human life value HLV",
    "fund NAV meaning in ULIP",
    "how to switch funds in ULIP",
    "grace period in life insurance policy",
    "can I have two term insurance policies",
]

BRAND_COMPARISON: list[str] = [
    # Brand was renamed from "Bajaj Allianz Life" to "Bajaj Life Insurance".
    # Queries use the new name; legacy-name long-tail searches are tracked
    # separately by the brand_mentions adapter (apps/seo_ai/adapters/
    # brand_mentions/) which keys off brand_tokens_old in settings.
    "Bajaj Life Insurance vs HDFC Life",
    "Bajaj Life Insurance vs ICICI Prudential Life",
    "Bajaj Life Insurance vs LIC",
    "Bajaj Life Insurance vs Max Life",
    "Bajaj Life Insurance vs SBI Life",
    "Bajaj Life Insurance vs Tata AIA",
    "Bajaj Life Insurance term insurance review",
    "Bajaj Life Insurance claim settlement ratio",
    "Bajaj Life Insurance ULIP review",
    "Bajaj Life eTouch term plan review",
    "is Bajaj Life Insurance good for term insurance",
    "HDFC Click 2 Protect vs Bajaj eTouch",
    "LIC term plan vs private insurer term plan",
]

LONG_TAIL: list[str] = [
    "term insurance for NRI with Indian income",
    "term insurance for NRI living in UAE",
    "term insurance for women housewives",
    "term insurance for housewife without income proof",
    "term insurance with return of premium worth it",
    "term insurance for smokers in India",
    "term insurance for diabetics in India",
    "term insurance after age 50 in India",
    "best critical illness rider in term insurance",
    "accidental death benefit rider worth it",
    "waiver of premium rider meaning",
    "ULIP for child higher education planning",
    "ULIP with lowest charges in India",
    "guaranteed income plan with monthly payout",
    "pension plan for self employed India",
    "immediate annuity plan for retired parents",
    "deferred annuity vs immediate annuity which is better",
    "retirement corpus needed at 60 in India",
    "child plan with premium waiver on parent death",
    "single premium investment plan with life cover",
    "life insurance for home loan protection",
    "group term life insurance for employees India",
    "term plan medical test requirements India",
    "life insurance maturity claim process documents",
]

CONVERSATIONAL: list[str] = [
    "I am 32 and earn 12 lakh — which term insurance plan should I buy?",
    "How much life insurance cover do I need for a family of four?",
    "Is ULIP better than mutual fund for tax saving?",
    "What happens to my term insurance if I become an NRI?",
    "Which Indian life insurer has the fastest claim settlement?",
    "Should I buy term insurance with return of premium or invest the difference?",
    "I want 1 crore cover at age 40 — how much premium will I pay?",
    "Which is the safest investment plan for my child's education in India?",
    "How do I plan a monthly pension of 50000 rupees after retirement?",
    "Can I pay term insurance premium yearly and get a discount?",
    "What riders should I add to my term insurance policy?",
    "Is it too late to buy term insurance at 45?",
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
