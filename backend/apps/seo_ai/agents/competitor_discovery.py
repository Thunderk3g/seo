"""CompetitorDiscoveryAgent — detection-only aggregator.

Combines outputs from upstream sources to produce a unified competitor
master list with rough cluster tags. Pure aggregation — no external
APIs, no LLM.

Sources (any subset; all optional):

  1. AI-citation domain counts (from AI-visibility probes in this run).
  2. SERP organic / featured / AI-overview hosts (from SERP-visibility
     probes in this run).
  3. SEMrush ``organic_competitors`` (when the key is configured).

Findings emitted point out **weak points** — e.g. dominant clusters we
don't compete in, review-aggregator capture, etc. No fix suggestions.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.conf import settings

from ..adapters.semrush import SemrushAdapter, SemrushError
from .base import Agent, FindingDraft

logger = logging.getLogger("seo.ai.agents.competitor_discovery")


# Domain → cluster heuristic. First match wins; longer / more specific
# patterns ordered first.
_CLUSTERS: list[tuple[str, re.Pattern]] = [
    ("review_aggregator", re.compile(
        r"(policybazaar|bankbazaar|insurancedekho|coverfox|trustpilot|g2|capterra)",
        re.IGNORECASE,
    )),
    ("forum_social", re.compile(
        r"(reddit|quora|stackexchange|stackoverflow|community|forum)",
        re.IGNORECASE,
    )),
    ("informational", re.compile(
        r"(wikipedia|investopedia|economictimes|moneycontrol|livemint|nerdwallet|youtube)",
        re.IGNORECASE,
    )),
    ("marketplace", re.compile(
        r"(amazon|flipkart|paytm)", re.IGNORECASE,
    )),
    ("direct", re.compile(
        r"(life|insurance|allianz|prudential|metlife|axa|aviva|tata|bajaj|"
        r"hdfc|icici|sbi|kotak|lic\b|max\b|reliance|birla|pnb|aegon|edelweiss|"
        r"futuregenerali|exide|canara|pramerica|indiafirst|ageas|shriram)",
        re.IGNORECASE,
    )),
]


def _classify(host: str) -> str:
    for name, regex in _CLUSTERS:
        if regex.search(host):
            return name
    return "other"


@dataclass
class _CompetitorRecord:
    domain: str
    cluster: str
    ai_citations: int = 0
    serp_organic_count: int = 0
    serp_featured_count: int = 0
    serp_ai_overview_count: int = 0
    semrush_common_keywords: int = 0
    score: float = 0.0


class CompetitorDiscoveryAgent(Agent):
    name = "competitor_discovery"
    system_prompt = "Detection-only aggregator. Does not call the LLM."

    def detect(self, *, domain: str) -> list[FindingDraft]:
        focus_host = re.sub(r"^www\d?\.", "", domain.lower()).split("/")[0]
        records: dict[str, _CompetitorRecord] = {}

        # ── SEMrush competitors (when configured) ──────────────────
        if (settings.SEMRUSH.get("api_key") or "").strip():
            try:
                semrush = SemrushAdapter()
                comp_rows = semrush.organic_competitors(domain, limit=30)
                for c in comp_rows:
                    host = re.sub(r"^www\d?\.", "", (c.domain or "").lower())
                    if not host or host == focus_host:
                        continue
                    rec = records.setdefault(
                        host,
                        _CompetitorRecord(domain=host, cluster=_classify(host)),
                    )
                    rec.semrush_common_keywords += int(c.common_keywords or 0)
            except SemrushError as exc:
                self.log_system_event(
                    "competitor_discovery.semrush_skipped",
                    {"reason": str(exc)},
                )
            except Exception as exc:  # noqa: BLE001 - never crash
                logger.warning("semrush discovery failed: %s", exc)
                self.log_system_event(
                    "competitor_discovery.semrush_skipped",
                    {"reason": f"{type(exc).__name__}: {exc}"[:200]},
                )

        # ── AI / SERP citation tallies from this run's system events
        # The other agents persist their per-domain counts as system
        # events; we re-read them rather than passing state around to
        # keep agent isolation intact.
        for evt in self.run.messages.filter(role="system").order_by("step_index"):
            content = evt.content or {}
            event_name = content.get("event") or ""
            data = content.get("data") or {}
            if event_name == "ai_visibility.probes_complete":
                # No per-domain breakdown here; that's emitted as a
                # finding by AISearchVisibilityAgent. We rely on the
                # finding's evidence_refs for top_cited[N]=domain.
                pass
            if event_name == "serp_visibility.probes_complete":
                pass

        # Pull per-domain counts from this run's existing findings
        # (cheaper than re-running the upstream probes). Both agents
        # emit ``evidence_refs`` of the form ``<scope>:top_cited[i]=host``
        # or similar — parse those.
        for f in self.run.findings.filter(
            agent__in=("ai_visibility", "serp_visibility")
        ).only("agent", "evidence_refs"):
            for ref in (f.evidence_refs or []):
                if "=" not in ref:
                    continue
                _, _, value = ref.partition("=")
                value = value.strip()
                # Skip refs that look like scalar metrics, not hosts.
                if not value or "/" in value or " " in value:
                    continue
                if "." not in value:
                    continue
                host = re.sub(r"^www\d?\.", "", value.lower())
                if host == focus_host or host == "":
                    continue
                rec = records.setdefault(
                    host,
                    _CompetitorRecord(domain=host, cluster=_classify(host)),
                )
                if f.agent == "ai_visibility":
                    rec.ai_citations += 1
                else:
                    rec.serp_organic_count += 1

        if not records:
            self.log_system_event(
                "competitor_discovery.empty",
                {"reason": "no competitor sources produced data"},
            )
            return []

        # Composite score: SEMrush carries the broadest signal, SERP
        # confirms public ranking, AI confirms LLM citation share.
        for rec in records.values():
            rec.score = (
                (rec.semrush_common_keywords / 100.0) * 1.0
                + rec.serp_organic_count * 1.5
                + rec.ai_citations * 2.0
                + rec.serp_featured_count * 3.0
                + rec.serp_ai_overview_count * 3.0
            )

        ordered = sorted(records.values(), key=lambda r: r.score, reverse=True)
        top = ordered[:15]
        self.log_system_event(
            "competitor_discovery.assembled",
            {
                "count": len(records),
                "top": [
                    {
                        "domain": r.domain,
                        "cluster": r.cluster,
                        "score": round(r.score, 2),
                        "ai_citations": r.ai_citations,
                        "serp_count": r.serp_organic_count,
                        "semrush_kw": r.semrush_common_keywords,
                    }
                    for r in top
                ],
            },
        )

        findings: list[FindingDraft] = []
        # ── Finding A: dominant cluster takeover ──────────────────
        cluster_counts: dict[str, int] = {}
        for r in top:
            cluster_counts[r.cluster] = cluster_counts.get(r.cluster, 0) + 1
        if cluster_counts.get("review_aggregator", 0) >= 2:
            sample = [r.domain for r in top if r.cluster == "review_aggregator"][:5]
            findings.append(
                FindingDraft(
                    category="competitor_cluster_review",
                    severity="warning",
                    title=(
                        f"{cluster_counts['review_aggregator']} review "
                        f"aggregator sites in top competitors"
                    ),
                    description=(
                        "Comparison / review aggregators dominate the "
                        "competitive set — they convert clicks before "
                        "users reach insurer sites. Examples: "
                        + ", ".join(sample)
                    ),
                    evidence_refs=[
                        f"competitor_discovery:review[{i}]={d}"
                        for i, d in enumerate(sample)
                    ],
                    impact="high",
                )
            )
        if cluster_counts.get("forum_social", 0) >= 2:
            sample = [r.domain for r in top if r.cluster == "forum_social"][:5]
            findings.append(
                FindingDraft(
                    category="competitor_cluster_forum",
                    severity="notice",
                    title=(
                        f"{cluster_counts['forum_social']} forum / social "
                        f"sites cited prominently"
                    ),
                    description=(
                        "Reddit / Quora / community threads appear repeatedly "
                        "in the citation set: "
                        + ", ".join(sample)
                        + ". These are high-leverage targets for third-"
                        "party brand presence."
                    ),
                    evidence_refs=[
                        f"competitor_discovery:forum[{i}]={d}"
                        for i, d in enumerate(sample)
                    ],
                    impact="medium",
                )
            )

        # ── Finding B: top 5 leaderboard ──────────────────────────
        leaderboard = [r for r in top if r.cluster != "other"][:5]
        if leaderboard:
            desc = "; ".join(
                f"{r.domain} ({r.cluster}, score {r.score:.1f})"
                for r in leaderboard
            )
            findings.append(
                FindingDraft(
                    category="competitor_leaderboard",
                    severity="notice",
                    title=(
                        f"Top {len(leaderboard)} competitors identified "
                        f"across AI + SERP + SEMrush sources"
                    ),
                    description=desc,
                    evidence_refs=[
                        f"competitor_discovery:top[{i}]={r.domain}"
                        for i, r in enumerate(leaderboard)
                    ],
                    impact="medium",
                )
            )

        return findings

    def valid_evidence_keys(self) -> set[str]:
        return {"competitor_discovery:detection_only"}
