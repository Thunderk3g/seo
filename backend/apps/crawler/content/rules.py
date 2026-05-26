"""Tier 1 — Rule-based content classification.

Pure-Python, deterministic, zero external deps. Looks at URL,
title, meta description, H1, and JSON-LD types — all already on
the result row from Phases A-D.

Each `_score_*` function returns a float in [0, 1] for how strongly
that signal indicates the candidate label. We sum signals to a
final confidence; pages can carry multiple product labels.

Public entry: ``classify_tier1(row) → ClassificationResult``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .taxonomy import (
    PRODUCTS, PAGE_TYPES,
    CONFIDENCE_CERTAIN, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM,
    UNCERTAIN_THRESHOLD,
)


# ── Result shape ──────────────────────────────────────────────────


@dataclass
class ClassificationResult:
    """Per-page classification output. ``products`` is multi-label."""
    products: list[tuple[str, float]] = field(default_factory=list)  # [(label, conf)]
    page_type: tuple[str, float] = ("other", 0.0)
    tier: int = 1                  # which tier produced this result
    signals: list[str] = field(default_factory=list)  # human-readable signal trace

    @property
    def primary_product(self) -> str | None:
        if not self.products:
            return None
        return max(self.products, key=lambda x: x[1])[0]

    @property
    def is_uncertain(self) -> bool:
        if self.page_type[1] < UNCERTAIN_THRESHOLD:
            return True
        if self.products and max(p[1] for p in self.products) < UNCERTAIN_THRESHOLD:
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "products": [
                {"label": p, "confidence": round(c, 3)}
                for p, c in sorted(self.products, key=lambda x: -x[1])
            ],
            "page_type": self.page_type[0],
            "page_type_confidence": round(self.page_type[1], 3),
            "tier": self.tier,
            "uncertain": self.is_uncertain,
            "signals": self.signals,
        }


# ── Helpers ───────────────────────────────────────────────────────


def _path(url: str) -> str:
    try:
        return urlparse(url or "").path.lower()
    except Exception:  # noqa: BLE001
        return ""


def _row_text(row: dict) -> str:
    """Lower-cased concatenation of title + meta + H1 — the searchable
    text the classifier inspects beyond URL."""
    parts = [
        row.get("title", "") or "",
        row.get("meta_description", "") or "",
    ]
    return " ".join(p for p in parts if p).lower()


def _row_jsonld_types(row: dict) -> list[str]:
    raw = row.get("jsonld_types")
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if t]
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
        return [str(t).strip() for t in parsed if t] if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


# ── Product taggers (multi-label) ─────────────────────────────────


# Each tagger: (label, list of (signal_name, score_fn -> float | bool, weight))
# Final confidence per product = sum(weight × score), capped at 0.99.
# Pages can fire multiple taggers → multi-label output.

# Heavy weight: URL is the strongest signal we have for insurance.
W_URL_STRONG = 0.55
W_URL_HINT = 0.25
W_TITLE = 0.25
W_META = 0.10
W_JSONLD = 0.15


_PRODUCT_RULES: dict[str, list[tuple[str, str, float]]] = {
    # label : [(signal_name, regex, weight), ...]
    # Note: URL patterns alone need to exceed UNCERTAIN_THRESHOLD (0.60)
    # so a single URL hit qualifies — we use 0.65 for definitive paths.
    #
    # Each product carries TWO families of URL patterns:
    #   * ``url:*-bajaj``     — Bajaj-specific paths (highest precision)
    #   * ``url:*-generic``   — insurer-agnostic paths that catch the
    #     same product on ICICI / HDFC / Max / Tata AIA / SBI / Kotak
    #     etc. Lower weight (0.65) so Bajaj-specific patterns still win
    #     when both fire, but enough to classify competitor pages.
    "term": [
        ("url:term-plans",   r"/term-insurance-plans?(?:\.|/|$)", 0.70),
        ("url:nri-term",     r"/nri-term-", 0.70),
        ("url:term-html",    r"/term-insurance-plans?\.html(?:$|\?)", 0.70),
        ("url:guide-term",   r"/life-insurance-guide/term/", 0.65),
        # Generic insurer-agnostic catchers — ICICI uses
        # /insurance-plans/term-insurance/, HDFC uses /term-insurance/,
        # Max uses /life-insurance-plans/term-plan/, Tata AIA uses
        # /life-insurance/term-insurance-plans/, SBI uses /smart-shield/.
        ("url:term-generic",  r"/term[-_]?insurance(?:[-_/]plan)?", 0.65),
        ("url:iprotect",      r"/iprotect", 0.65),
        ("url:click2protect", r"/click[-_]?2[-_]?protect", 0.65),
        ("title:term",        r"\bterm insurance\b", W_TITLE),
        ("title:crore",       r"₹[\d,]+\s*crore\s*term", 0.15),
    ],
    "ulip": [
        ("url:ulip",          r"/ulip-plans?(?:\.|/|$)", 0.70),
        ("url:guide-ulip",    r"/life-insurance-guide/ulip/", 0.65),
        ("url:funds",         r"/funds/", 0.65),
        # Generic — most insurers use /ulip/ or /unit-linked/.
        ("url:ulip-generic",  r"/ulip(?:[-_/]plan)?", 0.65),
        ("url:unit-linked",   r"/unit[-_]?linked", 0.65),
        ("title:ulip",        r"\bulip\b", W_TITLE),
        ("title:linked",      r"\b(unit[- ]linked|investment plan|fund)\b", W_TITLE),
    ],
    "endowment": [
        ("url:endow",         r"/endowment-plans?(?:\.|/|$)", 0.70),
        ("url:savings",       r"/savings-plans?(?:\.|/|$)", 0.70),
        ("url:guide-invest",  r"/life-insurance-guide/investments/", 0.65),
        ("url:guar",          r"/guaranteed-", 0.35),
        # Generic — endowment + savings + guaranteed-income.
        ("url:endow-generic", r"/(endowment|saving[s]?[-_]?plan|guaranteed[-_]?(?:income|return|saving|wealth))", 0.65),
        ("title:endow",       r"\b(endowment|savings plan|guaranteed return|smart wealth|solvency)\b", W_TITLE),
    ],
    "retirement": [
        ("url:pension",       r"/(retirement|pension)-?(plan|pension-plan)s?", 0.70),
        ("url:guide-ret",     r"/life-insurance-guide/retirement/", 0.65),
        ("url:pension-fund",  r"/funds/[a-z0-9-]*pension[a-z0-9-]*", 0.65),
        # Generic — annuity + pension + retirement variations.
        ("url:retire-generic", r"/(retirement|pension|annuity|immediate[-_]annuity|deferred[-_]annuity)", 0.65),
        ("title:retire",      r"\b(pension|retirement|annuity|viklang|family pension)\b", W_TITLE),
    ],
    "child": [
        ("url:child",         r"/child-plans?(?:\.|/|$)", 0.70),
        ("url:guide-child",   r"/life-insurance-guide/child/", 0.65),
        # Generic — child + education + young-star variants.
        ("url:child-generic", r"/(child|education|young[-_]?star|future[-_]?genius)", 0.65),
        ("title:child",       r"\b(child plan|education plan|child future)\b", W_TITLE),
    ],
    "group": [
        ("url:group",         r"/group-insurance-plans?(?:\.|/|$)", 0.70),
        ("url:group-generic", r"/group[-_]?(insurance|term|secure|gratuity|leave[-_]?encash|superannuation)", 0.65),
        ("title:group",       r"\b(group insurance|employer-employee|group secure)\b", W_TITLE),
    ],
    "wellness": [
        ("url:diabetes",      r"/diabetes-care-program", 0.70),
        ("url:wellness",      r"/wellness", 0.70),
        ("url:rider",         r"/(health|critical-illness)-rider", 0.70),
        # Generic — health + critical-illness add-ons.
        ("url:health-generic", r"/(health[-_]?(plan|insurance)|critical[-_]illness)", 0.65),
        ("title:wellness",    r"\b(diabetes|wellness|health rider)\b", W_TITLE),
    ],
    "tax": [
        ("url:tax-guide",     r"/life-insurance-guide/tax/", 0.70),
        ("url:tax-save",      r"/tax-saving", 0.70),
        ("url:tax-generic",   r"/(tax[-_]?(saving|benefit|deduction)|section[-_]?80c)", 0.65),
        ("title:tax",         r"\b(tax[- ]saving|section 80c|itr|deduction)\b", W_TITLE),
    ],
    "nri": [
        ("url:us",            r"^/us/", 0.65),
        ("url:hi",            r"^/hi/", 0.25),
        ("url:nri",           r"/nri-", 0.65),
        ("url:nri-generic",   r"/(nri|non[-_]?resident|overseas[-_]?(indian|customer))", 0.65),
        ("title:nri",         r"\b(nri|non-resident|abroad|overseas)\b", W_TITLE),
    ],
    "general_life": [
        ("url:guide-life",    r"/life-insurance-guide/life/", 0.65),
    ],
}


# ── Page-type tagger (single-label, highest score wins) ───────────


_PAGE_TYPE_RULES: list[tuple[str, str, float]] = [
    # (page_type, regex_against_url_path, score)
    # Order matters: most specific first.
    ("home",             r"^/?$", CONFIDENCE_CERTAIN),
    ("calculator",       r"-calculator(\.html)?(/|$)", CONFIDENCE_CERTAIN),
    ("calculator",       r"/(life-insurance-calculator|financial-fitness|life-goal-calculator)", CONFIDENCE_CERTAIN),
    ("faq_qa",           r"^/qa/", CONFIDENCE_CERTAIN),
    ("faq_qa",           r"/faqs?(\.|/|$)", CONFIDENCE_CERTAIN),
    ("blog_guide",       r"^/life-insurance-guide/", CONFIDENCE_CERTAIN),
    ("legal",            r"/(privacy-policy|terms-and-conditions|disclaimer|cookie-policy)", CONFIDENCE_CERTAIN),
    ("corporate",        r"/(about-us|careers?|leadership|testimonials)", CONFIDENCE_CERTAIN),
    ("branch_locator",   r"^/branch", CONFIDENCE_CERTAIN),
    ("claim_service",    r"/(claim|customer-service|grievance)", CONFIDENCE_CERTAIN),
    # Product landing — bare /xxx-plans/ or /xxx-plans.html with NO further segments
    ("product_landing",  r"^/[a-z-]+-plans?\.html$", CONFIDENCE_HIGH),
    ("product_landing",  r"^/[a-z-]+-(plans?|insurance)/?$", CONFIDENCE_HIGH),
    # Product detail — variant inside a product-plans section
    ("product_detail",   r"^/[a-z-]+-plans?/[a-z0-9-]+", CONFIDENCE_HIGH),
    # /funds/* — ULIP fund detail pages
    ("product_detail",   r"^/funds/", CONFIDENCE_HIGH),
]


# JSON-LD type → page_type boosters (additive evidence, not authoritative)
_JSONLD_BOOSTS: dict[str, str] = {
    "FAQPage":      "faq_qa",
    "Question":     "faq_qa",
    "Product":      "product_landing",
    "Article":      "blog_guide",
    "NewsArticle":  "blog_guide",
    "BlogPosting":  "blog_guide",
    "WebPage":      "",   # uninformative
}


def _score_products(row: dict) -> list[tuple[str, float, list[str]]]:
    """Return list of (label, confidence, signal_trace) for every product
    whose accumulated score >= UNCERTAIN_THRESHOLD."""
    path = _path(row.get("url", ""))
    text = _row_text(row)
    jsonld = _row_jsonld_types(row)

    results: list[tuple[str, float, list[str]]] = []
    for product, rules in _PRODUCT_RULES.items():
        score = 0.0
        signals: list[str] = []
        for signal_name, pattern, weight in rules:
            target = path if signal_name.startswith("url:") else text
            if re.search(pattern, target, re.IGNORECASE):
                score += weight
                signals.append(signal_name)

        # JSON-LD bonus — product-page JSON-LD lifts product confidence
        if score > 0 and ("Product" in jsonld or "FinancialProduct" in jsonld):
            score += W_JSONLD
            signals.append("jsonld:Product")

        score = min(score, 0.99)
        if score >= UNCERTAIN_THRESHOLD:
            results.append((product, score, signals))

    return results


def _score_page_type(row: dict) -> tuple[str, float, list[str]]:
    """Return (page_type, confidence, signal_trace). Single best match."""
    path = _path(row.get("url", ""))
    jsonld = _row_jsonld_types(row)
    title = (row.get("title") or "").lower()

    best: tuple[str, float, list[str]] = ("other", 0.0, [])
    for page_type, pattern, score in _PAGE_TYPE_RULES:
        if re.search(pattern, path):
            if score > best[1]:
                best = (page_type, score, [f"url:{pattern}"])

    # JSON-LD boost — promotes confidence when URL was ambiguous
    for ld_type, suggested_pt in _JSONLD_BOOSTS.items():
        if not suggested_pt:
            continue
        if ld_type in jsonld:
            if best[0] == suggested_pt:
                # Reinforces existing label — bump to certain
                best = (best[0], max(best[1], CONFIDENCE_CERTAIN), best[2] + [f"jsonld:{ld_type}"])
            elif best[1] < CONFIDENCE_MEDIUM:
                # Overrides weak URL signal
                best = (suggested_pt, CONFIDENCE_HIGH, [f"jsonld:{ld_type}"])

    # Calculator hint via form presence (some calculator URLs don't have "calculator" in path)
    if best[0] == "other" and (
        "calculator" in title or "calculate your" in title
    ):
        best = ("calculator", CONFIDENCE_MEDIUM, ["title:calculator"])

    return best


def classify_tier1(row: dict) -> ClassificationResult:
    """Tier 1 classifier. Returns ClassificationResult; the caller
    decides whether to escalate to Tier 2/3 based on
    ``result.is_uncertain``.
    """
    product_hits = _score_products(row)
    page_type, pt_conf, pt_signals = _score_page_type(row)

    result = ClassificationResult(
        products=[(p, c) for p, c, _ in product_hits],
        page_type=(page_type, pt_conf),
        tier=1,
        signals=[s for _, _, sigs in product_hits for s in sigs] + pt_signals,
    )
    return result
