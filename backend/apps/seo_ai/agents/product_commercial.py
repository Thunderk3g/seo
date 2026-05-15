"""ProductCommercialAgent — detection-only.

Commercial / product-page comparison and AI-agent buyability checks
inspired by SKILL.md §"Machine-Readable Files for AI Agents":

  * /pricing page present?
  * /pricing.md (machine-readable for AI agents)?
  * /llms.txt?
  * Product / Offer schema presence on product pages.
  * Calculator / tool page count.
  * Comparison page count.
  * CTA element count on top-of-funnel pages.

Detection only.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import requests

from ..adapters.competitor_crawler import CompetitorCrawler
from ..adapters.sitemap_aem import SitemapAEMAdapter
from .base import Agent, FindingDraft

logger = logging.getLogger("seo.ai.agents.product_commercial")


def _bare(domain: str) -> str:
    return re.sub(r"^www\d?\.", "", (domain or "").lower()).split("/")[0]


def _head(url: str, timeout: int = 8) -> int:
    """Return HTTP status code for a HEAD request; 0 on network error."""
    try:
        resp = requests.head(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; bajaj-seo-audit)"},
        )
        return resp.status_code
    except requests.RequestException:
        return 0


class ProductCommercialAgent(Agent):
    name = "product_commercial"
    system_prompt = "Detection-only agent."

    def detect(self, *, domain: str) -> list[FindingDraft]:
        focus = _bare(domain)
        out: list[FindingDraft] = []

        # ── machine-readable files (SKILL.md) ───────────────────────
        pricing_md_status = _head(f"https://{focus}/pricing.md")
        llms_txt_status = _head(f"https://{focus}/llms.txt")
        pricing_html_status = _head(f"https://{focus}/pricing")

        self.log_system_event(
            "product_commercial.machine_files",
            {
                "pricing_md_status": pricing_md_status,
                "llms_txt_status": llms_txt_status,
                "pricing_html_status": pricing_html_status,
            },
        )
        if pricing_md_status != 200:
            out.append(
                FindingDraft(
                    category="product_commercial_pricing_md",
                    severity="notice",
                    title="No /pricing.md machine-readable pricing file",
                    description=(
                        "AI agents evaluating products on behalf of "
                        "buyers prefer parseable Markdown over JS-"
                        "rendered HTML or 'contact sales' walls. "
                        "/pricing.md returned status "
                        f"{pricing_md_status} (expected 200)."
                    ),
                    evidence_refs=[
                        f"product_commercial:pricing_md_status={pricing_md_status}"
                    ],
                    impact="medium",
                )
            )
        if llms_txt_status != 200:
            out.append(
                FindingDraft(
                    category="product_commercial_llms_txt",
                    severity="notice",
                    title="No /llms.txt context file",
                    description=(
                        "llms.txt gives AI systems a quick canonical "
                        "summary of the site and links to key pages "
                        "(per llmstxt.org). Status returned: "
                        f"{llms_txt_status}."
                    ),
                    evidence_refs=[
                        f"product_commercial:llms_txt_status={llms_txt_status}"
                    ],
                    impact="medium",
                )
            )

        # ── Product / calculator / comparison page counts ──────────
        try:
            aem_pages = list(SitemapAEMAdapter().iter_pages())
        except Exception as exc:  # noqa: BLE001
            logger.info("aem load failed: %s", exc)
            aem_pages = []

        product_re = re.compile(
            r"/(term-insurance|ulip|whole-life|endowment|money-back|"
            r"retirement|pension|child-|annuity|critical-illness|"
            r"investment-plan|savings-plan)",
            re.IGNORECASE,
        )
        calc_re = re.compile(
            r"/(calculator|calculate-|premium-calc|quote-)", re.IGNORECASE
        )
        comp_re = re.compile(
            r"/(vs-|compare-|comparison|-vs-)", re.IGNORECASE
        )

        product_urls = [
            p.public_url for p in aem_pages if product_re.search(p.public_url or "")
        ]
        calc_urls = [
            p.public_url for p in aem_pages if calc_re.search(p.public_url or "")
        ]
        comp_urls = [
            p.public_url for p in aem_pages if comp_re.search(p.public_url or "")
        ]

        self.log_system_event(
            "product_commercial.aem_counts",
            {
                "product_pages": len(product_urls),
                "calculator_pages": len(calc_urls),
                "comparison_pages": len(comp_urls),
            },
        )

        if len(comp_urls) <= 2:
            out.append(
                FindingDraft(
                    category="product_commercial_comparison_pages",
                    severity="warning",
                    title=(
                        f"Only {len(comp_urls)} comparison / vs-rival "
                        f"page(s) on our AEM site"
                    ),
                    description=(
                        "Comparison-style pages have the highest AI "
                        "citation share (~33%) per SKILL.md research. "
                        "A thin footprint here is a major opportunity "
                        "gap."
                    ),
                    evidence_refs=[
                        f"product_commercial:comparison_pages={len(comp_urls)}"
                    ],
                    impact="high",
                )
            )

        if len(calc_urls) <= 3:
            out.append(
                FindingDraft(
                    category="product_commercial_calculators",
                    severity="notice",
                    title=(
                        f"Only {len(calc_urls)} calculator / quote tool "
                        f"page(s)"
                    ),
                    description=(
                        "Interactive calculators are top-of-funnel CTAs "
                        "and earn outsized AI citation share. Several "
                        "rivals expose 10+ such pages."
                    ),
                    evidence_refs=[
                        f"product_commercial:calculator_pages={len(calc_urls)}"
                    ],
                    impact="medium",
                )
            )

        # ── Schema + CTA audit on a sample of product pages ────────
        if product_urls:
            crawler = CompetitorCrawler()
            sample = product_urls[:6]
            no_product_schema = []
            low_cta = []
            for url in sample:
                page = crawler.fetch_one(url)
                if page.status_code != 200:
                    continue
                types = set(page.schema_types or [])
                if not (types & {"Product", "Offer", "FinancialProduct",
                                 "InsurancePolicy"}):
                    no_product_schema.append(url)
                if (page.cta_count or 0) < 3:
                    low_cta.append(url)

            if no_product_schema:
                sample_urls = no_product_schema[:3]
                out.append(
                    FindingDraft(
                        category="product_commercial_schema",
                        severity="warning",
                        title=(
                            f"Product schema missing on "
                            f"{len(no_product_schema)}/{len(sample)} "
                            f"sampled product pages"
                        ),
                        description=(
                            "Pages lacked Product / Offer / "
                            "FinancialProduct / InsurancePolicy schema. "
                            "Without this, rich results and AI entity "
                            "extraction skip the product. Examples: "
                            + ", ".join(sample_urls)
                        ),
                        evidence_refs=[
                            f"product_commercial:no_product_schema[{i}]={u}"
                            for i, u in enumerate(sample_urls)
                        ],
                        impact="medium",
                    )
                )
            if low_cta:
                sample_urls = low_cta[:3]
                out.append(
                    FindingDraft(
                        category="product_commercial_cta",
                        severity="notice",
                        title=(
                            f"Low CTA density on {len(low_cta)}/"
                            f"{len(sample)} sampled product pages"
                        ),
                        description=(
                            "Fewer than 3 CTA verbs detected "
                            "(buy now / get quote / calculate / apply "
                            "now / register / download …). Conversion "
                            "paths look thin on these pages. Examples: "
                            + ", ".join(sample_urls)
                        ),
                        evidence_refs=[
                            f"product_commercial:low_cta[{i}]={u}"
                            for i, u in enumerate(sample_urls)
                        ],
                        impact="low",
                    )
                )

        return out

    def valid_evidence_keys(self) -> set[str]:
        return {"product_commercial:detection_only"}
