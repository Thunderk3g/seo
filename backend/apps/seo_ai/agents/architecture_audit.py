"""ArchitectureAuditAgent — detection-only.

Site-shape comparison: total URL counts, URL counts by path-pattern
class (product / category / blog / landing / comparison / calculator),
average click depth (from sitemap path segments), breadcrumb schema
presence in the homepage sample.

Detection only. Skips silently when no rivals are available.
"""
from __future__ import annotations

import logging
import re
import statistics
from typing import Any

from ..adapters.competitor_crawler import CompetitorCrawler
from ..adapters.sitemap_aem import SitemapAEMAdapter
from ..adapters.sitemap_xml import SitemapXMLAdapter
from .base import Agent, FindingDraft

logger = logging.getLogger("seo.ai.agents.architecture_audit")


def _bare(domain: str) -> str:
    return re.sub(r"^www\d?\.", "", (domain or "").lower()).split("/")[0]


# Path-pattern classifiers. Order matters: more specific first.
_PATH_CLASSES: list[tuple[str, re.Pattern]] = [
    ("comparison", re.compile(r"/(vs-|compare-|comparison|-vs-)", re.IGNORECASE)),
    ("calculator", re.compile(r"/(calculator|calculate-|premium-calc)", re.IGNORECASE)),
    ("blog", re.compile(r"/(blog|article|news|insight)", re.IGNORECASE)),
    ("product", re.compile(
        r"/(term-insurance|ulip|whole-life|endowment|money-back|"
        r"retirement|pension|child-|annuity|critical-illness)", re.IGNORECASE,
    )),
    ("category", re.compile(r"/(category|categories|products|plans|solutions)", re.IGNORECASE)),
    ("landing", re.compile(r"/(lp/|landing|campaign|promo)", re.IGNORECASE)),
]


def _classify_path(path: str) -> str:
    for name, regex in _PATH_CLASSES:
        if regex.search(path):
            return name
    return "other"


class ArchitectureAuditAgent(Agent):
    name = "architecture_audit"
    system_prompt = "Detection-only agent."

    def detect(self, *, domain: str) -> list[FindingDraft]:
        focus = _bare(domain)
        rivals = self._rival_hosts()[:5]

        sitemap = SitemapXMLAdapter()
        crawler = CompetitorCrawler()

        # ── Sitemap URL counts ─────────────────────────────────────
        url_counts: dict[str, int] = {}
        for host in [focus] + rivals:
            try:
                summary = sitemap.discover(host)
                url_counts[host] = int(summary.total_url_count or 0)
            except Exception as exc:  # noqa: BLE001 - best-effort
                logger.info("sitemap discover %s failed: %s", host, exc)
                url_counts[host] = 0

        # ── Our AEM page classification (we have the full list) ──
        try:
            aem_pages = list(SitemapAEMAdapter().iter_pages())
        except Exception as exc:  # noqa: BLE001
            logger.info("aem load failed: %s", exc)
            aem_pages = []

        our_classes: dict[str, int] = {}
        depths: list[int] = []
        for page in aem_pages:
            url = page.public_url or ""
            cls = _classify_path(url)
            our_classes[cls] = our_classes.get(cls, 0) + 1
            path = re.sub(r"^https?://[^/]+", "", url)
            depths.append(max(1, path.count("/") - 1))
        our_avg_depth = (statistics.mean(depths) if depths else 0.0)

        # ── Rival homepage crawl: count internal/external links + breadcrumb
        rival_breadcrumb_yes = 0
        rival_breadcrumb_total = 0
        rival_internal_link_counts: list[int] = []
        for host in rivals:
            page = crawler.fetch_one(f"https://{host}/")
            if page.status_code != 200:
                continue
            rival_breadcrumb_total += 1
            if "BreadcrumbList" in (page.schema_types or []):
                rival_breadcrumb_yes += 1
            if page.internal_link_count:
                rival_internal_link_counts.append(page.internal_link_count)

        # Our homepage breadcrumb check via the same crawler.
        our_page = crawler.fetch_one(f"https://{focus}/")
        our_breadcrumb = (
            "BreadcrumbList" in (our_page.schema_types or [])
            if our_page.status_code == 200 else None
        )
        our_internal_links = (
            our_page.internal_link_count if our_page.status_code == 200 else 0
        )

        self.log_system_event(
            "architecture_audit.snapshots",
            {
                "url_counts": url_counts,
                "our_classes": our_classes,
                "our_avg_depth": round(our_avg_depth, 2),
                "rival_breadcrumb_rate": (
                    f"{rival_breadcrumb_yes}/{rival_breadcrumb_total}"
                    if rival_breadcrumb_total else "n/a"
                ),
                "rival_internal_link_median": (
                    int(statistics.median(rival_internal_link_counts))
                    if rival_internal_link_counts else 0
                ),
            },
        )

        return self._findings(
            focus=focus,
            url_counts=url_counts,
            our_classes=our_classes,
            our_avg_depth=our_avg_depth,
            rival_breadcrumb_yes=rival_breadcrumb_yes,
            rival_breadcrumb_total=rival_breadcrumb_total,
            rival_internal_link_counts=rival_internal_link_counts,
            our_breadcrumb=our_breadcrumb,
            our_internal_links=our_internal_links,
        )

    def valid_evidence_keys(self) -> set[str]:
        return {"architecture_audit:detection_only"}

    # ── helpers ──────────────────────────────────────────────────────

    def _rival_hosts(self) -> list[str]:
        hosts: list[str] = []
        seen: set[str] = set()
        for f in self.run.findings.filter(
            agent="competitor_discovery"
        ).only("evidence_refs"):
            for ref in f.evidence_refs or []:
                if "=" not in ref:
                    continue
                _, _, value = ref.partition("=")
                value = value.strip()
                if not value or "." not in value:
                    continue
                host = _bare(value)
                if host and host not in seen:
                    seen.add(host)
                    hosts.append(host)
        return hosts

    def _findings(
        self,
        *,
        focus: str,
        url_counts: dict[str, int],
        our_classes: dict[str, int],
        our_avg_depth: float,
        rival_breadcrumb_yes: int,
        rival_breadcrumb_total: int,
        rival_internal_link_counts: list[int],
        our_breadcrumb: bool | None,
        our_internal_links: int,
    ) -> list[FindingDraft]:
        out: list[FindingDraft] = []
        our_url_count = url_counts.get(focus, 0)
        rival_counts = [c for h, c in url_counts.items() if h != focus and c > 0]
        if rival_counts:
            rival_med = int(statistics.median(rival_counts))
            if rival_med > our_url_count * 3 and rival_med >= 1000:
                ratio = rival_med / max(1, our_url_count)
                out.append(
                    FindingDraft(
                        category="architecture_url_breadth",
                        severity="warning",
                        title=(
                            f"Site-breadth gap: rivals median "
                            f"{rival_med:,} indexable URLs vs. our "
                            f"{our_url_count:,} ({ratio:.1f}×)"
                        ),
                        description=(
                            f"Rivals' sitemap.xml exposes a median of "
                            f"{rival_med:,} URLs to crawlers. Our "
                            f"sitemap exposes {our_url_count:,}. Total "
                            f"indexable surface area is a coarse but "
                            f"reliable predictor of long-tail capture."
                        ),
                        evidence_refs=[
                            f"architecture_audit:our_urls={our_url_count}",
                            f"architecture_audit:rival_median_urls={rival_med}",
                        ],
                        impact="high",
                    )
                )

        # Breadcrumb schema gap.
        if our_breadcrumb is False and rival_breadcrumb_total:
            rate = rival_breadcrumb_yes / rival_breadcrumb_total
            if rate >= 0.5:
                out.append(
                    FindingDraft(
                        category="architecture_breadcrumb_schema",
                        severity="warning",
                        title=(
                            "No BreadcrumbList schema on homepage "
                            f"(rivals: {rival_breadcrumb_yes}/"
                            f"{rival_breadcrumb_total})"
                        ),
                        description=(
                            "BreadcrumbList structured data helps both "
                            "Google rich results and AI systems "
                            "understand site hierarchy. Most rivals ship "
                            "it on their homepage; we do not."
                        ),
                        evidence_refs=[
                            "architecture_audit:our_breadcrumb=false",
                            f"architecture_audit:rival_breadcrumb_rate={rate:.2f}",
                        ],
                        impact="medium",
                    )
                )

        # Internal-link mesh.
        if rival_internal_link_counts and our_internal_links:
            rival_med_links = int(statistics.median(rival_internal_link_counts))
            if our_internal_links < rival_med_links / 2 and rival_med_links > 60:
                out.append(
                    FindingDraft(
                        category="architecture_internal_links",
                        severity="warning",
                        title=(
                            f"Homepage internal-link count "
                            f"{our_internal_links} vs. rival median "
                            f"{rival_med_links}"
                        ),
                        description=(
                            "Internal links spread topical authority "
                            "across the site. Below half the rival "
                            "median means orphan / weakly-connected "
                            "pages are likely."
                        ),
                        evidence_refs=[
                            f"architecture_audit:our_internal_links={our_internal_links}",
                            f"architecture_audit:rival_median_internal_links={rival_med_links}",
                        ],
                        impact="medium",
                    )
                )

        # Click depth signal — only fire if it's clearly high.
        if our_avg_depth and our_avg_depth >= 4.0:
            out.append(
                FindingDraft(
                    category="architecture_click_depth",
                    severity="notice",
                    title=(
                        f"Average click depth ~{our_avg_depth:.1f} "
                        f"segments (target ≤ 3)"
                    ),
                    description=(
                        "Pages buried more than 3 clicks from the root "
                        "see disproportionately low organic crawl + "
                        "ranking weight."
                    ),
                    evidence_refs=[
                        f"architecture_audit:our_avg_depth={our_avg_depth:.2f}"
                    ],
                    impact="medium",
                )
            )

        # Page-class imbalance: very few comparison or calculator pages.
        for cls, label in (
            ("comparison", "comparison / vs-rival"),
            ("calculator", "calculator / tool"),
        ):
            cls_count = our_classes.get(cls, 0)
            if cls_count <= 1:
                out.append(
                    FindingDraft(
                        category=f"architecture_class_{cls}",
                        severity="notice",
                        title=(
                            f"Only {cls_count} {label} page(s) on our site"
                        ),
                        description=(
                            f"Comparison-style and calculator pages are "
                            f"among the highest AI-citation-share content "
                            f"types per the AI SEO guidance. {cls_count} "
                            f"is a thin footprint."
                        ),
                        evidence_refs=[
                            f"architecture_audit:our_{cls}_count={cls_count}"
                        ],
                        impact="medium",
                    )
                )

        return out
