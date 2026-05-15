"""SERPVisibilityAgent — detection-only.

Calls SerpAPI for each (engine × query) cell and flags ranking gaps,
featured-snippet takeovers, and AI Overview presence. Detection only —
fix recommendations come later.

Graceful degradation:
  * ``SERP_API_ENABLED=false`` or no API key → returns empty.
  * SerpAPI returns an error for one (query, engine) → that cell is
    counted as "attempted" with no organic data, run continues.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

from django.conf import settings

from ..adapters.ai_visibility.base import AdapterDisabledError
from ..adapters.serp_api import SerpAPIAdapter, SerpResult
from ..queries import load_queries
from .base import Agent, FindingDraft

logger = logging.getLogger("seo.ai.agents.serp_visibility")


def _bare(domain: str) -> str:
    bare = re.sub(r"^www\d?\.", "", (domain or "").lower())
    return bare.split("/")[0]


def _is_us(host: str, focus: str) -> bool:
    if not host or not focus:
        return False
    return host == focus or host.endswith("." + focus)


class SERPVisibilityAgent(Agent):
    name = "serp_visibility"
    system_prompt = "Detection-only agent. Does not call the LLM directly."

    def detect(self, *, domain: str) -> list[FindingDraft]:
        cfg = getattr(settings, "SERP_API", {}) or {}
        if not cfg.get("enabled", True):
            self.log_system_event(
                "serp_visibility.skipped",
                {"reason": "SERP_API_ENABLED=false"},
            )
            return []
        try:
            adapter = SerpAPIAdapter()
        except AdapterDisabledError as exc:
            self.log_system_event(
                "serp_visibility.skipped", {"reason": str(exc)}
            )
            return []
        except Exception as exc:  # noqa: BLE001 - never crash
            self.log_system_event(
                "serp_visibility.skipped",
                {"reason": f"init_error: {type(exc).__name__}: {exc}"[:200]},
            )
            return []

        engines: tuple[str, ...] = tuple(cfg.get("engines") or ("google",))
        max_q = max(1, int(cfg.get("max_queries", 20)))
        queries = load_queries()[:max_q]
        if not queries:
            return []

        results: list[SerpResult] = []
        for engine in engines:
            for q in queries:
                results.append(adapter.search(q, engine=engine))

        ok = [r for r in results if not r.error]
        self.log_system_event(
            "serp_visibility.probes_complete",
            {
                "engines": list(engines),
                "queries": len(queries),
                "total": len(results),
                "ok": len(ok),
                "errored": len(results) - len(ok),
                "cached": sum(1 for r in results if r.cached),
            },
        )
        return self._build_findings(focus=_bare(domain), results=ok, engines=engines)

    def valid_evidence_keys(self) -> set[str]:
        return {"serp_visibility:detection_only"}

    def _build_findings(
        self,
        *,
        focus: str,
        results: list[SerpResult],
        engines: tuple[str, ...],
    ) -> list[FindingDraft]:
        findings: list[FindingDraft] = []
        if not results:
            return findings

        # ── per-engine top-10 absence count ──────────────────────────
        engine_stats: dict[str, dict[str, int]] = {}
        domain_citations: dict[str, int] = defaultdict(int)
        featured_takeovers: list[tuple[str, str, str]] = []
        ai_overview_rivals: list[tuple[str, str]] = []

        for r in results:
            slot = engine_stats.setdefault(
                r.engine,
                {"queries": 0, "we_in_top10": 0, "we_in_top3": 0,
                 "featured_we": 0, "featured_them": 0, "ai_overview_we": 0,
                 "ai_overview_them": 0},
            )
            slot["queries"] += 1
            we_seen_top10 = False
            we_seen_top3 = False
            for row in r.organic[:10]:
                domain_citations[row.domain] += 1
                if _is_us(row.domain, focus):
                    we_seen_top10 = True
                    if row.position <= 3:
                        we_seen_top3 = True
            if we_seen_top10:
                slot["we_in_top10"] += 1
            if we_seen_top3:
                slot["we_in_top3"] += 1
            # Featured snippet ownership.
            if r.featured_snippet:
                fs_host = r.featured_snippet.get("domain") or ""
                if _is_us(fs_host, focus):
                    slot["featured_we"] += 1
                else:
                    slot["featured_them"] += 1
                    if fs_host:
                        featured_takeovers.append(
                            (r.engine, r.query, fs_host)
                        )
            # AI Overview citations.
            if r.ai_overview and r.ai_overview.get("citations"):
                we_in = any(
                    _is_us(c.get("domain") or "", focus)
                    for c in r.ai_overview["citations"]
                )
                if we_in:
                    slot["ai_overview_we"] += 1
                else:
                    slot["ai_overview_them"] += 1
                    rival_hosts = [
                        (c.get("domain") or "")
                        for c in r.ai_overview["citations"][:3]
                    ]
                    rival_hosts = [h for h in rival_hosts if h]
                    if rival_hosts:
                        ai_overview_rivals.append(
                            (r.query, ", ".join(rival_hosts))
                        )

        # Top-10 / top-3 visibility findings per engine.
        for engine, slot in engine_stats.items():
            qcount = slot["queries"]
            if qcount == 0:
                continue
            top10_rate = slot["we_in_top10"] / qcount
            top3_rate = slot["we_in_top3"] / qcount
            severity = (
                "critical"
                if top10_rate < 0.20
                else "warning" if top10_rate < 0.50 else "notice"
            )
            findings.append(
                FindingDraft(
                    category="serp_visibility_top10",
                    severity=severity,
                    title=(
                        f"{engine}: in top 10 for "
                        f"{slot['we_in_top10']}/{qcount} priority queries "
                        f"({top10_rate * 100:.0f}%)"
                    ),
                    description=(
                        f"Top-3 share is {slot['we_in_top3']}/{qcount} "
                        f"({top3_rate * 100:.0f}%) on {engine}. Below "
                        f"top-10 means effectively zero organic clicks "
                        f"for those queries on this engine."
                    ),
                    evidence_refs=[
                        f"serp_visibility:{engine}.top10_rate={top10_rate:.2f}",
                        f"serp_visibility:{engine}.top3_rate={top3_rate:.2f}",
                    ],
                    impact="high" if top10_rate < 0.30 else "medium",
                )
            )

        # Featured snippet takeovers — show up to 5.
        if featured_takeovers:
            sample = featured_takeovers[:5]
            findings.append(
                FindingDraft(
                    category="serp_visibility_featured_snippet",
                    severity="warning",
                    title=(
                        f"Competitors own {len(featured_takeovers)} "
                        f"featured snippets across our priority queries"
                    ),
                    description=(
                        "Featured snippets capture the bulk of the click-"
                        "through above the fold. Examples: "
                        + "; ".join(
                            f"'{q}' ({eng}) → {host}"
                            for eng, q, host in sample
                        )
                    ),
                    evidence_refs=[
                        f"serp_visibility:featured[{i}]={host}"
                        for i, (_, _, host) in enumerate(sample)
                    ],
                    impact="high",
                )
            )

        # AI Overview rival citations.
        if ai_overview_rivals:
            sample = ai_overview_rivals[:5]
            findings.append(
                FindingDraft(
                    category="serp_visibility_ai_overview",
                    severity="warning",
                    title=(
                        f"AI Overview cites competitors on "
                        f"{len(ai_overview_rivals)} priority queries, not us"
                    ),
                    description=(
                        "Google's AI Overview surfaces competitor sources "
                        "for these queries. Examples: "
                        + "; ".join(f"'{q}' → {hosts}" for q, hosts in sample)
                    ),
                    evidence_refs=[
                        f"serp_visibility:ai_overview[{i}]={hosts}"
                        for i, (_, hosts) in enumerate(sample)
                    ],
                    impact="high",
                )
            )

        # Domain leaderboard: who's the most-cited rival across all
        # organic positions (top 10 only — keeps the signal high).
        rival_domains = [
            (host, n)
            for host, n in domain_citations.items()
            if host and not _is_us(host, focus) and n >= 3
        ]
        rival_domains.sort(key=lambda x: x[1], reverse=True)
        top_rivals = rival_domains[:8]
        if top_rivals:
            findings.append(
                FindingDraft(
                    category="serp_visibility_rival_dominance",
                    severity="warning",
                    title=(
                        f"{len(top_rivals)} domains dominate the SERP "
                        f"across our priority queries"
                    ),
                    description=(
                        "Most-cited domains across "
                        f"{len(engines)} engines × {results[0].query and len(results)} cells: "
                        + ", ".join(f"{h} ({n})" for h, n in top_rivals)
                    ),
                    evidence_refs=[
                        f"serp_visibility:rival[{i}]={h}"
                        for i, (h, _) in enumerate(top_rivals)
                    ],
                    impact="high",
                )
            )

        return findings
