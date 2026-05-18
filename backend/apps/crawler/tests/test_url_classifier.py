"""Unit tests for url_classifier.classify().

The classifier drives every report filter, so we cover every Bajaj URL
pattern the live data actually contains.
"""
from __future__ import annotations

import pytest

from apps.crawler.storage.url_classifier import CATEGORY_DEFS, classify


# (url, expected subdomain, expected category_key)
CASES = [
    # ── www: term insurance ──────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/term-insurance-plans.html",
     "www", "product_term"),
    ("https://www.bajajlifeinsurance.com/term-insurance-plans/1-crore-term-insurance.html",
     "www", "product_term"),
    ("https://www.bajajlifeinsurance.com/term-insurance-plans/super-woman-term-plan.html",
     "www", "product_term"),
    ("https://www.bajajlifeinsurance.com/term-insurance-plans/saral-jeevan-bima.html",
     "www", "product_term"),
    ("https://www.bajajlifeinsurance.com/term-insurance-plans/claim-settlement-ratio.html",
     "www", "support_legal"),
    # ── www: ULIP ────────────────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/ulip-plans.html",
     "www", "product_ulip"),
    ("https://www.bajajlifeinsurance.com/ulip-plans/fortune-gain.html",
     "www", "product_ulip"),
    # ── www: other products ──────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/endowment-plans.html",
     "www", "product_other"),
    ("https://www.bajajlifeinsurance.com/savings-plans/young-achiever-plan.html",
     "www", "product_other"),
    ("https://www.bajajlifeinsurance.com/retirement-pension-plans.html",
     "www", "product_other"),
    ("https://www.bajajlifeinsurance.com/investment-insurance-plans.html",
     "www", "product_other"),
    ("https://www.bajajlifeinsurance.com/life-insurance-plans/whole-life-insurance.html",
     "www", "product_other"),
    ("https://www.bajajlifeinsurance.com/group-insurance-plans/group-term-life-insurance-plan.html",
     "www", "product_other"),
    # ── www: NRI / geographic ────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/nri-term-insurance.html",
     "www", "nri"),
    ("https://www.bajajlifeinsurance.com/us/nri-term-insurance.html",
     "www", "nri"),
    ("https://www.bajajlifeinsurance.com/uk/nri-life-insurance.html",
     "www", "nri"),
    ("https://www.bajajlifeinsurance.com/qa/nri-investment-plans.html",
     "www", "nri"),
    ("https://www.bajajlifeinsurance.com/ae/nri-investment-plans.html",
     "www", "nri"),
    # ── www: knowledge hub ───────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/life-insurance-guide.html",
     "www", "knowledge"),
    ("https://www.bajajlifeinsurance.com/life-insurance-guide/term/term-insurance-tax-benefits.html",
     "www", "knowledge"),
    ("https://www.bajajlifeinsurance.com/life-insurance-guide/ulip/what-is-ulip.html",
     "www", "knowledge"),
    # ── www: calculators ─────────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/life-insurance-calculator/sip-calculator.html",
     "www", "calculators"),
    ("https://www.bajajlifeinsurance.com/life-goal-calculator.html",
     "www", "calculators"),
    # ── www: support / legal ─────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/customer-services.html",
     "www", "support_legal"),
    ("https://www.bajajlifeinsurance.com/contact-us.html",
     "www", "support_legal"),
    ("https://www.bajajlifeinsurance.com/about-us.html",
     "www", "support_legal"),
    ("https://www.bajajlifeinsurance.com/privacy-policy.html",
     "www", "support_legal"),
    ("https://www.bajajlifeinsurance.com/testimonials.html",
     "www", "support_legal"),
    # ── www: wellness ────────────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/diabetes-care-program/strength-training-for-diabetes-control.html",
     "www", "wellness"),
    # ── www: funds ───────────────────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/funds/opportunity-fund.html",
     "www", "funds"),
    # ── www: other / unclassified ────────────────────────────────────────
    ("https://www.bajajlifeinsurance.com/", "www", "other"),
    ("https://www.bajajlifeinsurance.com/some-random-page.html", "www", "other"),
    # ── branch subdomain ─────────────────────────────────────────────────
    ("https://branch.bajajlifeinsurance.com/storepages/bajaj-life-insurance-noida-life-insurance-noida-sector-4-noida-162896",
     "branch", "branch"),
    ("https://branch.bajajlifeinsurance.com/location/chandigarh",
     "branch", "branch"),
    ("https://branch.bajajlifeinsurance.com/?search=NH-39%2C+Garhwa%2C+822114",
     "branch", "branch"),
    ("https://branch.bajajlifeinsurance.com/downloadqrcode/MTE5NTQx/MTYyODM1",
     "branch", "branch"),
    # ── investmentcorner subdomain ───────────────────────────────────────
    ("https://investmentcorner.bajajlifeinsurance.com/cnbc-tv18-mr-sampath-reddy-chief-investment-officer-bajaj-allianz-life/index.php",
     "investmentcorner", "investmentcorner"),
    ("https://investmentcorner.bajajlifeinsurance.com/why-nomination-is-vital-in-life-insurance",
     "investmentcorner", "investmentcorner"),
    # ── investmentcorner WP-JSON noise ───────────────────────────────────
    ("https://investmentcorner.bajajlifeinsurance.com/wp-json/oembed/1.0/embed?url=https%3A%2F%2Finvestmentcorner.bajajlifeinsurance.com%2F10-key-takeaways-for-investors%2F&format=xml",
     "investmentcorner", "investmentcorner_api"),
    # ── external / unknown ───────────────────────────────────────────────
    ("https://example.com/", "external", "unknown"),
    ("", "external", "unknown"),
]


@pytest.mark.parametrize("url,sub,cat", CASES)
def test_classify(url, sub, cat):
    result = classify(url)
    assert result["subdomain"] == sub, f"{url} -> {result}"
    assert result["category_key"] == cat, f"{url} -> {result}"
    assert result["category_label"], "label must be non-empty"


def test_classify_handles_garbage_input():
    assert classify(None)["category_key"] == "unknown"  # type: ignore[arg-type]
    assert classify(123)["category_key"] == "unknown"   # type: ignore[arg-type]
    assert classify("not a url")["category_key"] == "unknown"


def test_category_defs_keys_unique():
    keys = [c["key"] for c in CATEGORY_DEFS]
    assert len(keys) == len(set(keys)), "CATEGORY_DEFS has duplicate keys"


def test_every_returned_category_is_in_defs():
    defined = {c["key"] for c in CATEGORY_DEFS}
    for url, _sub, expected_cat in CASES:
        result = classify(url)
        assert result["category_key"] in defined, (
            f"classify({url!r}) returned undefined category {result['category_key']!r}"
        )
