"""URL classifier — assign each crawled URL a subdomain + page-type category.

Used by ``csv_writer.append()`` to enrich every row written to disk, and by
``repository.read_csv()`` to filter on the same dimensions. Pure function, no
I/O; regexes are compiled once at import.

Taxonomy:
    subdomain    -> www | branch | investmentcorner | external
    page_type    -> within www only; "n_a" elsewhere
    category_key -> a flat key combining subdomain + page-type, used as the
                    primary filter key in the API. Examples:
                        "product_term", "knowledge", "calculators",
                        "branch", "investmentcorner",
                        "investmentcorner_api"
    category_label -> human-readable display string for the UI.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


# ── Subdomain markers ──────────────────────────────────────────────────────
_HOST_WWW = ("www.bajajlifeinsurance.com", "bajajlifeinsurance.com")
_HOST_BRANCH_PREFIX = "branch."
_HOST_INVCORNER_PREFIX = "investmentcorner."


# ── Page-type regexes (within www). First match wins. ─────────────────────
_RE_NRI_GEO = re.compile(r"^/(us|uk|qa|sg|ae|om|kw|bh|ca|au)(/|$)", re.I)
_RE_NRI_PATH = re.compile(r"\bnri[-_]", re.I)
_RE_CALCULATOR = re.compile(r"(calculator|life-goal)", re.I)
_RE_KNOWLEDGE = re.compile(r"(life-insurance-guide|/blog(/|$)|/articles(/|$))", re.I)
_RE_WELLNESS = re.compile(r"(diabetes-care-program|wellness)", re.I)
_RE_FUNDS = re.compile(r"/funds/", re.I)
_RE_SUPPORT_LEGAL = re.compile(
    r"(customer-services|contact-us|about-us|privacy-policy|terms|"
    r"disclaimer|testimonials|sitemap|career|faq|grievance|claim)",
    re.I,
)
_RE_PRODUCT_TERM = re.compile(r"(term-insurance|term-plan)", re.I)
_RE_PRODUCT_ULIP = re.compile(r"ulip", re.I)
_RE_PRODUCT_OTHER = re.compile(
    r"(savings-plans|endowment|investment-insurance|whole-life|"
    r"retirement|pension|child-insurance|group-insurance|life-insurance-plans)",
    re.I,
)

_RE_WPJSON = re.compile(r"/wp-json/", re.I)


# ── Category metadata. Single source of truth for UI / Excel. ─────────────
CATEGORY_DEFS: list[dict] = [
    # subdomain: www
    {"key": "product_term",       "subdomain": "www", "label": "Product · Term",        "icon": "shield"},
    {"key": "product_ulip",       "subdomain": "www", "label": "Product · ULIP",        "icon": "trending_up"},
    {"key": "product_other",      "subdomain": "www", "label": "Product · Other",       "icon": "savings"},
    {"key": "knowledge",          "subdomain": "www", "label": "Knowledge / Guides",    "icon": "menu_book"},
    {"key": "calculators",        "subdomain": "www", "label": "Calculators & Tools",   "icon": "calculate"},
    {"key": "support_legal",      "subdomain": "www", "label": "Support / Legal",       "icon": "support_agent"},
    {"key": "nri",                "subdomain": "www", "label": "NRI / Geo",             "icon": "public"},
    {"key": "wellness",           "subdomain": "www", "label": "Wellness",              "icon": "favorite"},
    {"key": "funds",              "subdomain": "www", "label": "Funds / NAV",           "icon": "account_balance"},
    {"key": "other",              "subdomain": "www", "label": "Other / Unclassified",  "icon": "more_horiz"},
    # subdomain: branch
    {"key": "branch",             "subdomain": "branch",            "label": "Branch Locator",                  "icon": "store"},
    # subdomain: investmentcorner
    {"key": "investmentcorner",     "subdomain": "investmentcorner", "label": "Investment Corner (Blog)",          "icon": "article"},
    {"key": "investmentcorner_api", "subdomain": "investmentcorner", "label": "InvestmentCorner · WP-JSON noise",  "icon": "bug_report"},
    # fallback
    {"key": "unknown",            "subdomain": "external",          "label": "Unknown",                         "icon": "help_outline"},
]

_LABEL_BY_KEY: dict[str, str] = {c["key"]: c["label"] for c in CATEGORY_DEFS}


# ── Public API ─────────────────────────────────────────────────────────────
def classify(url: str) -> dict:
    """Map a URL to ``{subdomain, page_type, category_key, category_label}``.

    Empty / malformed URLs fall back to the ``unknown`` category so callers
    never see a KeyError downstream.
    """
    if not url or not isinstance(url, str):
        return _result("external", "unknown", "unknown")

    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return _result("external", "unknown", "unknown")

    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"

    # 1. Branch subdomain — single bucket, page_type matches subdomain.
    if host.startswith(_HOST_BRANCH_PREFIX):
        return _result("branch", "branch", "branch")

    # 2. InvestmentCorner WP-JSON endpoints — a distinct noise bucket.
    if host.startswith(_HOST_INVCORNER_PREFIX):
        if _RE_WPJSON.search(path):
            return _result("investmentcorner", "wp_json", "investmentcorner_api")
        return _result("investmentcorner", "blog", "investmentcorner")

    # 3. Main site (www).
    if host in _HOST_WWW:
        return _result("www", *_www_page_type(path))

    # 4. Defensive fallback — shouldn't happen given allowed-domains, but
    # keeps the pipeline alive if the crawler is reconfigured.
    return _result("external", "unknown", "unknown")


# ── Internals ──────────────────────────────────────────────────────────────
def _www_page_type(path: str) -> tuple[str, str]:
    """First-match-wins routing inside the www subdomain. Returns (page_type, category_key)."""
    if _RE_NRI_GEO.search(path) or _RE_NRI_PATH.search(path):
        return ("nri", "nri")
    if _RE_CALCULATOR.search(path):
        return ("calculators", "calculators")
    if _RE_KNOWLEDGE.search(path):
        return ("knowledge", "knowledge")
    if _RE_WELLNESS.search(path):
        return ("wellness", "wellness")
    if _RE_FUNDS.search(path):
        return ("funds", "funds")
    if _RE_SUPPORT_LEGAL.search(path):
        return ("support_legal", "support_legal")
    if _RE_PRODUCT_TERM.search(path):
        return ("product", "product_term")
    if _RE_PRODUCT_ULIP.search(path):
        return ("product", "product_ulip")
    if _RE_PRODUCT_OTHER.search(path):
        return ("product", "product_other")
    return ("other", "other")


def _result(subdomain: str, page_type: str, category_key: str) -> dict:
    return {
        "subdomain": subdomain,
        "page_type": page_type,
        "category_key": category_key,
        "category_label": _LABEL_BY_KEY.get(category_key, category_key),
    }
