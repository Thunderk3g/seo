"""TechnicalAuditAgent — detection-only.

Per-domain technical SEO snapshot of us + top competitors. Focuses on
the signals AI search engines weight heavily (per SKILL.md):

  * AI bot access in robots.txt (GPTBot / ClaudeBot / PerplexityBot /
    Google-Extended / Bingbot).
  * Sitemap.xml presence + indexable URL count.
  * Median response time across crawled pages.
  * HTTPS / canonical / viewport / structured-data coverage.

Detection only — no recommendations. Graceful degradation: missing
competitor data (no SEMrush) → just audits the focus domain.
"""
from __future__ import annotations

import logging
import re
import statistics
from typing import Any
from urllib.parse import urlparse

import requests

from ..adapters.competitor_crawler import CompetitorCrawler
from ..adapters.sitemap_xml import SitemapXMLAdapter
from .base import Agent, FindingDraft

logger = logging.getLogger("seo.ai.agents.technical_audit")


_AI_BOTS = (
    "GPTBot",
    "ChatGPT-User",
    "PerplexityBot",
    "ClaudeBot",
    "anthropic-ai",
    "Google-Extended",
    "Bingbot",
)


def _bare(domain: str) -> str:
    return re.sub(r"^www\d?\.", "", (domain or "").lower()).split("/")[0]


def _fetch_robots(host: str, timeout: int = 10) -> str:
    try:
        resp = requests.get(
            f"https://{host}/robots.txt",
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; bajaj-seo-audit)"},
        )
        if resp.status_code == 200:
            return resp.text
    except requests.RequestException as exc:
        logger.info("robots.txt fetch %s failed: %s", host, exc)
    return ""


def _bot_blocked(robots_text: str, bot: str) -> bool:
    """Heuristic: does any Disallow line target ``bot`` and forbid root?"""
    if not robots_text:
        return False
    in_block = False
    user_agent_match = False
    for raw in robots_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("user-agent:"):
            value = line.split(":", 1)[1].strip().lower()
            user_agent_match = value == bot.lower() or value == "*"
            in_block = user_agent_match and value == bot.lower()
        elif user_agent_match and lower.startswith("disallow:"):
            value = line.split(":", 1)[1].strip()
            # Disallow: / blocks everything.
            if value == "/":
                # Only count "blocked" when the block actually named this bot.
                if in_block:
                    return True
    return False


class TechnicalAuditAgent(Agent):
    name = "technical_audit"
    system_prompt = "Detection-only agent."

    def detect(self, *, domain: str) -> list[FindingDraft]:
        focus = _bare(domain)
        rivals = self._rival_hosts()
        sitemap = SitemapXMLAdapter()
        crawler = CompetitorCrawler()

        # ── per-domain audit ────────────────────────────────────────
        domains_to_audit = [focus] + rivals[:5]  # cap competitor audits
        snapshots: dict[str, dict[str, Any]] = {}
        for host in domains_to_audit:
            snap: dict[str, Any] = {"host": host}
            # robots.txt + AI bot access.
            robots = _fetch_robots(host, timeout=10)
            snap["robots_present"] = bool(robots)
            snap["ai_bots_blocked"] = [
                b for b in _AI_BOTS if _bot_blocked(robots, b)
            ]
            # Sitemap discovery (count only — already 7-day cached).
            try:
                summary = sitemap.discover(host)
                snap["sitemap_url_count"] = int(summary.total_url_count or 0)
                snap["sitemap_present"] = bool(snap["sitemap_url_count"])
            except Exception as exc:  # noqa: BLE001 - best-effort
                logger.info("sitemap discover %s failed: %s", host, exc)
                snap["sitemap_url_count"] = 0
                snap["sitemap_present"] = False
            # Homepage fetch — gives us response time + structural signals.
            page = crawler.fetch_one(f"https://{host}/")
            snap["status_code"] = page.status_code
            snap["response_time_ms"] = page.response_time_ms
            snap["canonical"] = bool(page.canonical)
            snap["has_schema_org"] = page.has_schema_org
            snap["schema_types"] = list(page.schema_types or [])
            snap["meta_robots"] = page.meta_robots
            snap["https"] = (page.final_url or page.url or "").lower().startswith(
                "https://"
            )
            snapshots[host] = snap

        self.log_system_event(
            "technical_audit.snapshots", {"snapshots": snapshots}
        )
        return self._build_findings(focus=focus, snapshots=snapshots)

    def valid_evidence_keys(self) -> set[str]:
        return {"technical_audit:detection_only"}

    # ── helpers ──────────────────────────────────────────────────────

    def _rival_hosts(self) -> list[str]:
        """Pull rival hosts from this run's CompetitorDiscoveryAgent
        findings if they exist. Returns hosts in priority order, deduped.
        """
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

    def _build_findings(
        self, *, focus: str, snapshots: dict[str, dict[str, Any]]
    ) -> list[FindingDraft]:
        findings: list[FindingDraft] = []
        focus_snap = snapshots.get(focus, {})
        rival_snaps = [s for h, s in snapshots.items() if h != focus]

        # ── 1. AI bot access in our own robots.txt ───────────────────
        blocked = focus_snap.get("ai_bots_blocked") or []
        if blocked:
            findings.append(
                FindingDraft(
                    category="technical_audit_ai_bots",
                    severity="critical",
                    title=(
                        f"{len(blocked)} AI bot(s) disallowed in our "
                        f"robots.txt"
                    ),
                    description=(
                        "These AI bots are blocked: "
                        + ", ".join(blocked)
                        + ". Each blocked bot represents an AI search "
                        "platform that cannot cite our pages."
                    ),
                    evidence_refs=[
                        f"technical_audit:ai_bots_blocked={','.join(blocked)}"
                    ],
                    impact="high",
                )
            )

        # ── 2. sitemap presence ────────────────────────────────────
        if not focus_snap.get("sitemap_present"):
            findings.append(
                FindingDraft(
                    category="technical_audit_sitemap",
                    severity="warning",
                    title="No discoverable sitemap.xml",
                    description=(
                        "Neither robots.txt's Sitemap: directive, "
                        "/sitemap.xml, nor /sitemap_index.xml returned a "
                        "usable sitemap. Search engines cannot enumerate "
                        "our indexable URLs."
                    ),
                    evidence_refs=["technical_audit:sitemap_present=false"],
                    impact="high",
                )
            )

        # ── 3. response time vs. rivals ────────────────────────────
        rival_rt = [
            int(s.get("response_time_ms") or 0)
            for s in rival_snaps
            if s.get("status_code") == 200 and (s.get("response_time_ms") or 0) > 0
        ]
        our_rt = int(focus_snap.get("response_time_ms") or 0)
        if our_rt > 0 and rival_rt:
            rival_med = int(statistics.median(rival_rt))
            if our_rt > rival_med * 1.5 and our_rt - rival_med > 500:
                findings.append(
                    FindingDraft(
                        category="technical_audit_response_time",
                        severity="warning",
                        title=(
                            f"Homepage response time {our_rt} ms vs. rival "
                            f"median {rival_med} ms"
                        ),
                        description=(
                            f"Our homepage response was {our_rt} ms; the "
                            f"median across {len(rival_rt)} competitors "
                            f"was {rival_med} ms. Response time is a "
                            f"ranking signal and a CWV input."
                        ),
                        evidence_refs=[
                            f"technical_audit:response_time_ms={our_rt}",
                            f"technical_audit:rival_median_ms={rival_med}",
                        ],
                        impact="medium",
                    )
                )

        # ── 4. structured data coverage ─────────────────────────────
        our_schema = len(focus_snap.get("schema_types") or [])
        rival_schema = [
            len(s.get("schema_types") or []) for s in rival_snaps
            if s.get("status_code") == 200
        ]
        if rival_schema:
            rival_med_schema = statistics.median(rival_schema)
            if our_schema < rival_med_schema - 1:
                findings.append(
                    FindingDraft(
                        category="technical_audit_schema",
                        severity="warning",
                        title=(
                            f"Homepage has {our_schema} schema.org types "
                            f"vs. rival median {int(rival_med_schema)}"
                        ),
                        description=(
                            "Schema.org structured data is a primary "
                            "input for AI search systems building entity "
                            "graphs and rich-result eligibility."
                        ),
                        evidence_refs=[
                            f"technical_audit:schema_types_count={our_schema}",
                            f"technical_audit:rival_median_schema={int(rival_med_schema)}",
                        ],
                        impact="medium",
                    )
                )

        # ── 5. HTTPS hygiene ────────────────────────────────────────
        if not focus_snap.get("https", True):
            findings.append(
                FindingDraft(
                    category="technical_audit_https",
                    severity="critical",
                    title="Homepage not served over HTTPS",
                    description=(
                        "The homepage did not resolve via HTTPS after "
                        "redirects. Modern search and AI crawlers down-"
                        "rank or refuse mixed-protocol sites."
                    ),
                    evidence_refs=["technical_audit:https=false"],
                    impact="high",
                )
            )

        # ── 6. meta_robots noindex ─────────────────────────────────
        mr = (focus_snap.get("meta_robots") or "").lower()
        if "noindex" in mr:
            findings.append(
                FindingDraft(
                    category="technical_audit_meta_robots",
                    severity="critical",
                    title="Homepage carries meta robots=noindex",
                    description=(
                        f"Detected meta robots: {mr!r}. The homepage is "
                        "self-excluded from search indexes."
                    ),
                    evidence_refs=[f"technical_audit:meta_robots={mr}"],
                    impact="high",
                )
            )

        return findings
