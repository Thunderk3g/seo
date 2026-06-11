"""Claude-Code smart content-clustering pass.

Writes a per-domain topic-cluster spec to
``{data_dir}/content_clusters/<domain>.json`` for every competitor we've
crawled (plus the curated roster). The ``competitor_content_clusters``
endpoint loads each spec and applies it to that rival's live crawl:
``url_patterns`` are matched as substrings against each page URL and
``keywords`` against the page title + H1 (page-specific, nav-free), so a
topic gathers every page about it and each page's real content headings
show as its sections. One topic spans many pages; a page can sit in
several topics.

This is the deterministic taxonomy Claude authored from the rivals' real
crawled URL structures. Swapping to an LLM provider later only changes how
the spec is produced — the on-disk schema and the endpoint stay identical.

    python manage.py gen_cluster_specs            # crawled domains + roster
    python manage.py gen_cluster_specs --all-roster-only
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Ordered most-specific → most-general. The endpoint records a page under
# every cluster it matches, so product topics precede the broad service /
# knowledge / about buckets to win the obvious URL hits first. url_patterns
# match as substrings, so "/term-insurance" also claims
# "/term-insurance-plans/...".
CLUSTERS = [
    {"id": "term-insurance", "name": "Term Insurance",
     "intro": "Pure-protection term plans — cover, premiums, return-of-premium, term vs other plans.",
     "url_patterns": ["/term-insurance", "/term-plan", "/term-life", "/term/"],
     "keywords": ["term insurance", "term plan", "term life", "pure protection",
                  "return of premium", "trop", "1 crore cover", "term cover"]},
    {"id": "ulip", "name": "ULIP / Unit-Linked Plans",
     "intro": "Market-linked insurance + investment (ULIPs) — fund options, charges, returns.",
     "url_patterns": ["/ulip", "/unit-linked", "/unit-link", "/wealth"],
     "keywords": ["ulip", "unit linked", "unit-linked", "market linked",
                  "market-linked", "fund value", "wealth plan", "wealth secure"]},
    {"id": "savings-guaranteed", "name": "Savings, Endowment & Guaranteed Plans",
     "intro": "Guaranteed-return savings, endowment, money-back and guaranteed-income plans.",
     "url_patterns": ["/savings", "/endowment", "/guaranteed", "/money-back",
                      "/moneyback", "/assured", "/income-plan", "/par-plan"],
     "keywords": ["savings plan", "endowment", "guaranteed return", "guaranteed income",
                  "money back", "money-back", "assured", "guaranteed maturity",
                  "guaranteed savings"]},
    {"id": "retirement-pension", "name": "Retirement, Pension & Annuity",
     "intro": "Retirement corpus, pension and annuity plans — immediate & deferred annuity.",
     "url_patterns": ["/retirement", "/pension", "/annuity"],
     "keywords": ["retirement", "pension", "annuity", "immediate annuity",
                  "deferred annuity", "retirement plan", "guaranteed pension"]},
    {"id": "child-plans", "name": "Child & Education Plans",
     "intro": "Child future / education plans — milestone payouts, premium waiver.",
     "url_patterns": ["/child", "/children", "/education", "/young"],
     "keywords": ["child plan", "children", "child education", "education plan",
                  "child future", "young star", "smart kid"]},
    {"id": "fund-performance", "name": "Fund Performance / NAV",
     "intro": "Fund fact sheets, NAV, portfolio and fund performance disclosures.",
     "url_patterns": ["/investment-funds", "/fund-performance", "/funds", "/nav",
                      "/portfolio", "/fund-fact", "/fund/"],
     "keywords": ["fund performance", "net asset value", "nav", "fund fact sheet",
                  "fund factsheet", "portfolio", "fund house", "fund name"]},
    {"id": "investment-plans", "name": "Investment Plans",
     "intro": "General investment / wealth-creation plans (non-ULIP, non-fund-sheet).",
     "url_patterns": ["/investment", "/invest", "/sip"],
     "keywords": ["investment plan", "wealth creation", "grow your money",
                  "smart wealth", "systematic investment", "best investment"]},
    {"id": "health-insurance", "name": "Health & Critical Illness",
     "intro": "Health, critical-illness and hospital-cash cover.",
     "url_patterns": ["/health-insurance", "/health-plan", "/critical-illness",
                      "/health-cover", "/cancer", "/heart"],
     "keywords": ["health insurance", "critical illness", "hospital cash",
                  "medical cover", "health cover", "cancer cover", "surgical"]},
    {"id": "group-business", "name": "Group / Employer & Business Solutions",
     "intro": "Group life, employee benefits, credit-life and business solutions.",
     "url_patterns": ["/group-insurance", "/group", "/business-solution",
                      "/employer", "/employee", "/corporate", "/credit-life"],
     "keywords": ["group insurance", "group term", "employee benefit", "employer",
                  "business solution", "credit life", "gratuity", "group savings"]},
    {"id": "nri", "name": "NRI Plans",
     "intro": "Plans and guidance for non-resident Indians.",
     "url_patterns": ["/nri"],
     "keywords": ["nri", "non resident", "non-resident indian", "nri insurance",
                  "nri term"]},
    {"id": "riders", "name": "Riders & Add-ons",
     "intro": "Optional riders — accidental death, waiver of premium, critical-illness add-ons.",
     "url_patterns": ["/rider", "/add-on", "/addon"],
     "keywords": ["rider", "add-on", "add on", "waiver of premium",
                  "accidental death", "accidental total", "income benefit rider"]},
    {"id": "calculators-tools", "name": "Calculators & Tools",
     "intro": "Premium / HLV / retirement calculators and planning tools.",
     "url_patterns": ["/calculator", "/calculators", "/tools", "/financial-tools",
                      "/tools-calculators", "/tools-and-calculators"],
     "keywords": ["calculator", "premium calculator", "hlv", "human life value",
                  "retirement calculator", "income tax calculator", "planning tool"]},
    {"id": "claims", "name": "Claims",
     "intro": "Claim process, death-claim filing, claim-settlement ratio and documents.",
     "url_patterns": ["/claim", "/claims", "/claims-centre", "/claims-center"],
     "keywords": ["claim", "claim settlement", "death claim", "claim process",
                  "claim form", "claim settlement ratio", "intimate claim"]},
    {"id": "tax-benefits", "name": "Tax & GST",
     "intro": "Tax benefits under 80C / 10(10D), GST and income-tax guidance.",
     "url_patterns": ["/tax", "/income-tax", "/gst"],
     "keywords": ["tax benefit", "section 80c", "80c", "10(10d)", "income tax",
                  "tax saving", "gst", "tax deduction"]},
    {"id": "life-insurance-general", "name": "Life Insurance (overview & landing)",
     "intro": "Top-level life-insurance landing / overview pages not tied to one product.",
     "url_patterns": ["/life-insurance", "/insurance-plans", "/all-plans",
                      "/our-plans", "/plans/"],
     "keywords": ["life insurance plan", "types of life insurance", "life cover",
                  "best life insurance", "buy life insurance"]},
    {"id": "customer-service", "name": "Customer Service & Support",
     "intro": "Policy servicing, premium payment, renewal, grievance and how-to support.",
     "url_patterns": ["/customer-service", "/customer-servicing", "/customer-services",
                      "/help-center", "/help-centre", "/how-do-i", "/servicing",
                      "/support", "/grievance", "/contact", "/pay-premium",
                      "/premium-payment", "/quicklinks", "/login"],
     "keywords": ["customer service", "customer support", "grievance", "contact us",
                  "pay premium", "premium payment", "policy servicing", "renew",
                  "update details", "how do i", "track application"]},
    {"id": "downloads-forms", "name": "Downloads, Forms & Documents",
     "intro": "Brochures, policy documents, forms, annexures and disclosures.",
     "url_patterns": ["/download", "/downloads", "/documents", "/forms",
                      "/static-page", "/policy-document", "/brochure",
                      "/other-disclosure", "/disclosure"],
     "keywords": ["download", "brochure", "policy document", "application form",
                  "annexure", "proposal form", "product brochure"]},
    {"id": "knowledge-blog", "name": "Blog, Guides & Knowledge Centre",
     "intro": "Educational blog posts, guides, glossaries, web-stories and knowledge centre.",
     "url_patterns": ["/blog", "/blogs", "/article", "/articles", "/knowledge",
                      "/insurance-guide", "/life-insurance-library", "/insights",
                      "/pblearn", "/web-stories", "/insurance-advisor",
                      "/knowledge-centre", "/learn", "/guide"],
     "keywords": ["what is", "how to", "meaning of", "difference between",
                  "explained", "guide to", "benefits of", "things to know"]},
    {"id": "about-trust", "name": "About, Trust & Governance",
     "intro": "About-us, why-choose, awards, governance, investor relations and careers.",
     "url_patterns": ["/about", "/about-us", "/why-", "/policy-governance",
                      "/investor-relations", "/careers", "/newsroom", "/news",
                      "/awards", "/csr", "/leadership", "/about-company"],
     "keywords": ["about us", "why choose", "awards", "claim settlement ratio",
                  "board of directors", "leadership", "careers", "our journey",
                  "corporate social"]},
    {"id": "branches-locations", "name": "Branches & Locations",
     "intro": "Branch locator and office-location pages.",
     "url_patterns": ["/branch", "/branches", "/location", "/locate", "/find-branch"],
     "keywords": ["branch", "locate us", "office address", "find a branch",
                  "branch locator", "nearest branch"]},
]

# Always-write roster even before a crawl exists, so the spec is in place
# the moment pages land.
ROSTER = [
    "hdfclife.com", "tataaia.com", "axismaxlife.com", "sbilife.co.in",
    "kotaklife.com", "pnbmetlife.com", "policybazaar.com", "iciciprulife.com",
    "iciciprulife.in", "bandhanlife.com", "canarahsbclife.com", "licindia.in",
    "indiafirstlife.com", "adityabirlacapital.com",
]


class Command(BaseCommand):
    help = "Write Claude-authored topic-cluster specs for every competitor."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-roster-only", action="store_true",
            help="Skip DB discovery; write only the curated roster.",
        )

    def handle(self, *args, **opts):
        domains = set(ROSTER)
        if not opts["all_roster_only"]:
            try:
                from apps.crawler.models import CrawlSnapshot
                crawled = (CrawlSnapshot.objects.filter(kind="competitor")
                           .exclude(target_domain="")
                           .values_list("target_domain", flat=True).distinct())
                domains.update(d.lower().lstrip("www.") for d in crawled if d)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"DB discovery skipped: {exc}")

        out_dir = Path(settings.SEO_AI["data_dir"]) / "content_clusters"
        out_dir.mkdir(parents=True, exist_ok=True)
        spec = {
            "generated_at": "2026-06-12",
            "generated_by": "claude-code-smart-clustering",
            "note": ("Topic clusters authored by Claude Code from the rivals' "
                     "real crawled URL structures. Each topic spans every page "
                     "whose URL or title/H1 matches; a page's sections show its "
                     "real content headings (template nav stripped). Swap to an "
                     "LLM provider later — same schema."),
            "clusters": CLUSTERS,
        }
        written = 0
        for dom in sorted(domains):
            safe = "".join(c if (c.isalnum() or c in ".-") else "_" for c in dom)
            (out_dir / f"{safe}.json").write_text(
                json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
            written += 1
        self.stdout.write(self.style.SUCCESS(
            f"wrote {written} cluster spec(s) ({len(CLUSTERS)} topics each) "
            f"to {out_dir}"))
