"""AISearchVisibilityAgent — detection-only.

Probes the AI search layer (ChatGPT, Claude, Gemini, Perplexity, Grok)
with a curated query list and surfaces weak-point findings about
brand citation gaps vs. competitors.

This agent **detects only**. No fix recommendations — those ship in a
later phase. It gracefully degrades when:

  * ``AI_VISIBILITY_ENABLED=false`` → agent returns empty.
  * Every provider key is missing → agent returns empty.
  * Any individual provider's adapter raises ``AdapterDisabledError``
    on construction → that provider is silently skipped, the others
    still run.
  * Any individual ``provider.probe(query)`` returns an error → counted
    as "attempted" but doesn't crash the agent.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings

from ..adapters.ai_visibility import PROVIDER_REGISTRY, AdapterDisabledError
from ..adapters.ai_visibility.base import AIProbeResult
from ..queries import load_queries
from .base import Agent, FindingDraft

logger = logging.getLogger("seo.ai.agents.ai_visibility")


def _brand_token(domain: str) -> str:
    """Extract a recognisable brand token from a domain.

    ``bajajlifeinsurance.com``  → ``bajaj``
    ``hdfclife.com``            → ``hdfc``
    """
    bare = re.sub(r"^www\d?\.", "", (domain or "").lower()).split("/")[0]
    parts = bare.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "net", "org", "gov", "ac"}:
        root = parts[-3]
    elif len(parts) >= 2:
        root = parts[-2]
    else:
        root = bare
    # Strip recognised insurance / corp suffixes so "bajajlife" → "bajaj".
    core = re.sub(
        r"(life|insurance|pru|prulife|allianz|general|india|gi|wealth|finserv)+$",
        "",
        root,
    )
    return core if len(core) >= 3 else root


def _mentions_brand(text: str, brand_token: str) -> bool:
    if not text or not brand_token:
        return False
    return re.search(rf"\b{re.escape(brand_token)}\b", text, re.IGNORECASE) is not None


class AISearchVisibilityAgent(Agent):
    """Detection-only agent for Phase 2 (AI search citations)."""

    name = "ai_visibility"
    system_prompt = (
        "Detection-only agent. Does not call the LLM directly."
    )

    # ── public ───────────────────────────────────────────────────────

    def detect(self, *, domain: str) -> list[FindingDraft]:
        cfg = getattr(settings, "AI_VISIBILITY", {}) or {}
        if not cfg.get("enabled", True):
            self.log_system_event(
                "ai_visibility.skipped", {"reason": "AI_VISIBILITY_ENABLED=false"}
            )
            return []

        # Spin up every provider we can; skip the ones that self-gate.
        adapters = self._build_adapters()
        if not adapters:
            self.log_system_event(
                "ai_visibility.skipped",
                {"reason": "no AI providers configured (every API key missing)"},
            )
            return []

        max_queries = max(1, int(cfg.get("max_queries", 20)))
        queries = load_queries()[:max_queries]
        if not queries:
            self.log_system_event(
                "ai_visibility.skipped", {"reason": "no seed queries"}
            )
            return []

        focus_brand = _brand_token(domain)
        # Run every (provider, query) cell. Each probe is best-effort
        # — its own internal try/except returns an AIProbeResult with
        # ``error`` set on failure, never raising up here.
        results: list[AIProbeResult] = []
        for adapter in adapters:
            for q in queries:
                results.append(adapter.probe(q))

        ok_results = [r for r in results if not r.error]
        self.log_system_event(
            "ai_visibility.probes_complete",
            {
                "providers": [a.provider for a in adapters],
                "query_count": len(queries),
                "results_total": len(results),
                "results_ok": len(ok_results),
                "results_errored": len(results) - len(ok_results),
                "results_cached": sum(1 for r in results if r.cached),
            },
        )

        return self._build_findings(
            focus_brand=focus_brand,
            domain=domain,
            results=ok_results,
            adapters_used=[a.provider for a in adapters],
            query_count=len(queries),
        )

    def valid_evidence_keys(self) -> set[str]:
        return {"ai_visibility:detection_only"}

    # ── private ──────────────────────────────────────────────────────

    def _build_adapters(self) -> list:
        adapters = []
        for cls in PROVIDER_REGISTRY:
            try:
                adapters.append(cls())
            except AdapterDisabledError as exc:
                self.log_system_event(
                    "ai_visibility.provider_skipped",
                    {"provider": cls.provider, "reason": str(exc)},
                )
            except Exception as exc:  # noqa: BLE001 - never crash
                logger.warning(
                    "%s adapter init crashed: %s", cls.provider, exc
                )
                self.log_system_event(
                    "ai_visibility.provider_skipped",
                    {
                        "provider": cls.provider,
                        "reason": f"init_error: {type(exc).__name__}: {exc}"[:200],
                    },
                )
        return adapters

    def _build_findings(
        self,
        *,
        focus_brand: str,
        domain: str,
        results: list[AIProbeResult],
        adapters_used: list[str],
        query_count: int,
    ) -> list[FindingDraft]:
        findings: list[FindingDraft] = []
        if not results:
            return findings

        # Per-provider brand-mention rate (% of queries where the
        # provider's answer mentioned the brand token at all).
        per_provider: dict[str, dict[str, int]] = {}
        # Per-domain citation counts across all (provider × query) cells.
        domain_citations: dict[str, int] = {}
        focus_domain_bare = re.sub(r"^www\d?\.", "", domain.lower())
        for r in results:
            slot = per_provider.setdefault(
                r.provider, {"answered": 0, "brand_mentioned": 0}
            )
            slot["answered"] += 1
            if _mentions_brand(r.answer_text, focus_brand):
                slot["brand_mentioned"] += 1
            for host in r.mentioned_domains:
                domain_citations[host] = domain_citations.get(host, 0) + 1

        # ── Finding 1: overall AI mention rate ──────────────────────
        total_answered = sum(p["answered"] for p in per_provider.values())
        total_mentioned = sum(p["brand_mentioned"] for p in per_provider.values())
        rate = total_mentioned / total_answered if total_answered else 0.0
        if total_answered:
            severity = (
                "critical" if rate < 0.10 else "warning" if rate < 0.30 else "notice"
            )
            findings.append(
                FindingDraft(
                    category="ai_visibility_overall",
                    severity=severity,
                    title=(
                        f"AI search mentions brand in {total_mentioned}/"
                        f"{total_answered} answers ({rate * 100:.0f}%)"
                    ),
                    description=(
                        f"Across {len(adapters_used)} AI providers "
                        f"({', '.join(adapters_used)}) and "
                        f"{query_count} priority queries, our brand "
                        f"appears in {total_mentioned} of {total_answered} "
                        f"answers. Brand recognition is the leading "
                        f"indicator for AI-search citation share."
                    ),
                    evidence_refs=[
                        f"ai_visibility:rate={rate:.2f}",
                        f"ai_visibility:providers={','.join(adapters_used)}",
                    ],
                    impact="high" if rate < 0.30 else "medium",
                )
            )

        # ── Finding 2: per-provider gaps ────────────────────────────
        for prov, slot in per_provider.items():
            if slot["answered"] == 0:
                continue
            prov_rate = slot["brand_mentioned"] / slot["answered"]
            if prov_rate < 0.10:
                findings.append(
                    FindingDraft(
                        category="ai_visibility_per_provider",
                        severity="warning",
                        title=(
                            f"{prov}: brand absent in "
                            f"{slot['answered'] - slot['brand_mentioned']}/"
                            f"{slot['answered']} answers"
                        ),
                        description=(
                            f"{prov.capitalize()} mentioned the brand in "
                            f"{slot['brand_mentioned']} of {slot['answered']} "
                            f"probed answers ({prov_rate * 100:.0f}%). "
                            f"Low presence on a specific provider often "
                            f"reflects gaps in third-party citations that "
                            f"that provider weights heavily."
                        ),
                        evidence_refs=[f"ai_visibility:{prov}.rate={prov_rate:.2f}"],
                        impact="medium",
                    )
                )

        # ── Finding 3: rivals dominating AI citations ───────────────
        # Drop our own domain from the leaderboard and drop very low-
        # frequency hosts that are just noise (random news sites). The
        # cut-off is 3 citations so a domain has to appear repeatedly
        # to count as a "rival presence".
        rivals = [
            (host, count)
            for host, count in domain_citations.items()
            if host and focus_domain_bare not in host and host not in focus_domain_bare
            and count >= 3
        ]
        rivals.sort(key=lambda x: x[1], reverse=True)
        top_rivals = rivals[:8]
        if top_rivals:
            rival_text = ", ".join(f"{h} ({c})" for h, c in top_rivals)
            us_citations = sum(
                count
                for host, count in domain_citations.items()
                if focus_domain_bare in host or host in focus_domain_bare
            )
            severity = (
                "critical"
                if us_citations == 0 and len(top_rivals) >= 3
                else "warning"
            )
            findings.append(
                FindingDraft(
                    category="ai_visibility_rival_dominance",
                    severity=severity,
                    title=(
                        f"{len(top_rivals)} domains dominate AI citations "
                        f"(we appear in {us_citations})"
                    ),
                    description=(
                        f"Across the probed queries, AI answers most "
                        f"frequently cited: {rival_text}. Our own domain "
                        f"appeared in {us_citations} citation slots."
                    ),
                    evidence_refs=[
                        f"ai_visibility:top_cited[{i}]={h}"
                        for i, (h, _) in enumerate(top_rivals)
                    ]
                    + [f"ai_visibility:us_citations={us_citations}"],
                    impact="high",
                )
            )

        return findings
