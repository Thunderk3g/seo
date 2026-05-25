"""Single source of truth for product + page-type categories.

Both axes are independent (a page can be `term + calculator`).
Products are MULTI-LABEL; page-types are SINGLE-LABEL.

See docs/CONTENT_CLASSIFICATION_PLAN.md §5 for the taxonomy rationale
and the URL-pattern grounding from real Bajaj crawl data.
"""
from __future__ import annotations


# ── Products (multi-label) ────────────────────────────────────────


PRODUCTS: tuple[str, ...] = (
    "term",           # term insurance
    "ulip",           # unit linked
    "endowment",      # savings / guaranteed return
    "retirement",     # pension / annuity
    "child",          # child education / future
    "group",          # group/employer plans
    "wellness",       # health programs, riders
    "tax",            # tax-saving / 80C content
    "nri",            # NRI-targeted (region modifier)
    "general_life",   # broad life-insurance education, not product-specific
)

PRODUCT_LABELS: dict[str, str] = {
    "term": "Term Insurance",
    "ulip": "ULIP",
    "endowment": "Endowment / Savings",
    "retirement": "Retirement / Pension",
    "child": "Child Plans",
    "group": "Group Insurance",
    "wellness": "Wellness / Health Riders",
    "tax": "Tax-Saving / Tax Guides",
    "nri": "NRI",
    "general_life": "General Life Insurance",
}


# ── Page types (single-label, orthogonal to product) ──────────────


PAGE_TYPES: tuple[str, ...] = (
    "home",
    "product_landing",
    "product_detail",
    "calculator",
    "blog_guide",
    "faq_qa",
    "claim_service",
    "branch_locator",
    "legal",
    "corporate",
    "other",
)

PAGE_TYPE_LABELS: dict[str, str] = {
    "home": "Homepage",
    "product_landing": "Product landing",
    "product_detail": "Product detail / variant",
    "calculator": "Calculator",
    "blog_guide": "Blog / Knowledge guide",
    "faq_qa": "FAQ / Q&A",
    "claim_service": "Claim / Customer service",
    "branch_locator": "Branch locator",
    "legal": "Legal / Policy",
    "corporate": "About / Careers / Corporate",
    "other": "Other / Uncategorised",
}


# ── Confidence bands ──────────────────────────────────────────────


CONFIDENCE_CERTAIN = 0.95   # URL + title + JSON-LD all agree
CONFIDENCE_HIGH = 0.85      # URL pattern + title agree
CONFIDENCE_MEDIUM = 0.70    # URL pattern only OR title only (strong)
CONFIDENCE_LOW = 0.60       # Tier 2 / Tier 3 fallback
CONFIDENCE_UNCERTAIN = 0.0  # → tag as `uncertain`, do not auto-label

# Threshold under which we refuse to auto-label.
UNCERTAIN_THRESHOLD = 0.60
