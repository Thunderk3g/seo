"""Run orchestrator.

Wires the four-stage sequential pipeline defined in the plan:

    refresh facts → specialists (parallel-able) → score+critic → narrator

We keep it deliberately synchronous Python rather than reaching for a
graph framework: at this scale the orchestration is ~80 lines and
threading a state machine adds more bugs than it removes. If/when the
agent count exceeds 6 specialists or we add a real debate loop, this
is the place to swap in LangGraph.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from django.conf import settings
from django.utils import timezone as dj_tz

from ..adapters.semrush import SemrushError
from ..llm import get_provider
from ..models import (
    FindingSeverity,
    SEORun,
    SEORunFinding,
    SEORunStatus,
)
from .. import scoring
from .ai_visibility import AISearchVisibilityAgent
from .architecture_audit import ArchitectureAuditAgent
from .base import Agent, FindingDraft
from .competitor import CompetitorAgent
from .competitor_discovery import CompetitorDiscoveryAgent
from .content_extractability import ContentExtractabilityAgent
from .critic import CriticAgent
from .keyword import KeywordAgent
from .narrator import NarratorAgent
from .product_commercial import ProductCommercialAgent
from .serp_visibility import SERPVisibilityAgent
from .technical import TechnicalAgent
from .technical_audit import TechnicalAuditAgent

logger = logging.getLogger("seo.ai.orchestrator")


_SEVERITY_PRIORITY = {"critical": 95, "warning": 70, "notice": 45}


# Detection-only agents run in Stage 1B. Order matters because some
# agents read prior agents' findings from the DB (e.g. TechnicalAudit
# uses CompetitorDiscovery's host list).
DETECTION_AGENTS: list[type[Agent]] = [
    AISearchVisibilityAgent,
    SERPVisibilityAgent,
    CompetitorDiscoveryAgent,
    TechnicalAuditAgent,
    ArchitectureAuditAgent,
    ContentExtractabilityAgent,
    ProductCommercialAgent,
]


class Orchestrator:
    def __init__(self, run: SEORun) -> None:
        self.run = run
        self.provider = get_provider()
        self.step = 0
        self.total_cost = 0.0

    # ── entrypoint ─────────────────────────────────────────────────────

    def execute(self) -> None:
        run = self.run
        run.status = SEORunStatus.RUNNING
        run.save(update_fields=["status"])
        t0 = time.time()
        try:
            sources_snapshot = self._gather_sources_snapshot()
            run.sources_snapshot = sources_snapshot
            run.save(update_fields=["sources_snapshot"])

            # ── Stage 1: specialists ──────────────────────────────────
            technical_payload, tech_facts = self._run_technical()
            keyword_payload, keyword_facts = self._run_keyword(domain=run.domain)
            competitor_payload, competitor_facts = self._run_competitor(
                domain=run.domain
            )

            # ── Stage 1B: detection-only gap agents ───────────────────
            # Each agent is fully optional: it self-gates on its API
            # keys / settings flags and the runner below catches any
            # exception so one crashing agent never aborts the whole
            # grading pipeline.
            for agent_cls in DETECTION_AGENTS:
                self._run_detection(agent_cls, domain=run.domain)

            # ── Stage 2: critic on combined findings ──────────────────
            combined = (
                list(technical_payload.get("findings") or [])
                + list(keyword_payload.get("findings") or [])
                + list((competitor_payload or {}).get("findings") or [])
            )
            # Build the authoritative reference-key list deterministically
            # (Python, not LLM). Critic checks set-membership, not deep
            # object resolution — keeps the critic prompt tiny and the
            # decision strict.
            valid_keys = _enumerate_evidence_keys(
                {
                    "crawler": tech_facts.get("crawler", {}),
                    "aem": tech_facts.get("aem", {}),
                    "gsc": keyword_facts.get("gsc", {}),
                    "semrush": keyword_facts.get("semrush", {}),
                    "competitor": (competitor_facts or {}).get("competitor", {}),
                }
            )
            run.status = SEORunStatus.CRITIC
            run.save(update_fields=["status"])
            critic = CriticAgent(run=run, step_index_start=self.step)
            verdict = critic.review(
                findings=combined, valid_evidence_keys=valid_keys
            )
            self.step = critic.step_index
            accepted, rejected = CriticAgent.filter_findings(combined, verdict)
            logger.info(
                "critic: verdict=%s accepted=%d rejected=%d",
                verdict.get("verdict"),
                len(accepted),
                len(rejected),
            )

            # ── Stage 3: deterministic scoring ────────────────────────
            sub = scoring.compute_sub_scores(
                crawler_summary=tech_facts["crawler"]["summary"],
                aem_summary=tech_facts["aem"]["summary"],
                gsc_summary=keyword_facts["gsc"].get("summary", {}),
                semrush_overview=(keyword_facts.get("semrush") or {}).get("overview"),
            )
            overall, weights = scoring.compute_overall(sub)
            run.overall_score = overall
            run.sub_scores = sub.as_dict()
            run.weights = weights
            run.save(update_fields=["overall_score", "sub_scores", "weights"])

            # ── Stage 4: persist findings + narrate ───────────────────
            self._persist_findings("technical", technical_payload.get("findings") or [], accepted)
            self._persist_findings("keyword", keyword_payload.get("findings") or [], accepted)
            if competitor_payload:
                self._persist_findings(
                    "competitor",
                    competitor_payload.get("findings") or [],
                    accepted,
                )

            narrator = NarratorAgent(run=run, step_index_start=self.step)
            narrative = narrator.narrate(
                overall_score=overall,
                sub_scores=sub.as_dict(),
                accepted_findings=accepted,
                domain=run.domain,
            )
            self.step = narrator.step_index

            # ── done ──────────────────────────────────────────────────
            self.total_cost = sum(
                m.cost_usd for m in run.messages.all()
            )
            run.total_cost_usd = round(self.total_cost, 6)
            run.finished_at = dj_tz.now()
            run.model_versions = {
                "provider": self.provider.name,
                "model": getattr(self.provider, "model", ""),
                "narrative": narrative,
                "critic_verdict": verdict,
            }
            run.status = (
                SEORunStatus.DEGRADED
                if verdict.get("verdict") == "revise" and rejected
                else SEORunStatus.COMPLETE
            )
            run.save(
                update_fields=[
                    "total_cost_usd",
                    "finished_at",
                    "model_versions",
                    "status",
                ]
            )
            logger.info(
                "run %s done score=%s cost=$%.4f elapsed=%.1fs",
                run.id,
                overall,
                self.total_cost,
                time.time() - t0,
            )
        except Exception as exc:  # noqa: BLE001 - top-level
            logger.exception("run %s failed: %s", run.id, exc)
            run.status = SEORunStatus.FAILED
            run.error = str(exc)[:4000]
            run.finished_at = dj_tz.now()
            run.save(update_fields=["status", "error", "finished_at"])
            raise

    # ── stages ─────────────────────────────────────────────────────────

    def _run_technical(self) -> tuple[dict[str, Any], dict[str, Any]]:
        agent = TechnicalAgent(run=self.run, step_index_start=self.step)
        facts = agent.build_facts()
        payload = agent.call_model(
            facts,
            instruction=(
                "Audit the technical SEO health of this site using ONLY "
                "the facts below. Surface 8–15 prioritised findings."
            ),
        ).payload
        self.step = agent.step_index
        return payload, facts

    def _run_keyword(self, *, domain: str) -> tuple[dict[str, Any], dict[str, Any]]:
        agent = KeywordAgent(run=self.run, step_index_start=self.step)
        facts = agent.build_facts(domain=domain)
        payload = agent.call_model(
            facts,
            instruction=(
                "Identify 8–15 high-value SERP and keyword opportunities "
                "based ONLY on the facts. Prioritise by impact."
            ),
        ).payload
        self.step = agent.step_index
        return payload, facts

    def _run_competitor(
        self, *, domain: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Competitor gap analysis — optional, never crashes the run.

        Skips silently when SEMrush is unconfigured or the
        ``COMPETITOR_ENABLED`` flag is off. Catches both SEMrush errors
        and bare-network errors from the competitor crawler so a flaky
        rival host can't take down the whole grading pipeline.
        """
        if not settings.SEMRUSH.get("api_key"):
            self._log_skip("competitor.skipped", reason="SEMRUSH_API_KEY not set")
            return None, None
        if not settings.COMPETITOR.get("enabled", True):
            self._log_skip("competitor.skipped", reason="COMPETITOR_ENABLED=false")
            return None, None
        try:
            agent = CompetitorAgent(run=self.run, step_index_start=self.step)
            facts = agent.build_facts(domain=domain)
            payload = agent.call_model(
                facts,
                instruction=(
                    "Compare the focus domain against its rivals using "
                    "ONLY the facts below. Surface 6-12 prioritised "
                    "competitor gap findings."
                ),
            ).payload
            self.step = agent.step_index
            return payload, facts
        except SemrushError as exc:
            logger.warning("competitor agent skipped (semrush): %s", exc)
            self._log_skip("competitor.skipped", reason=f"semrush: {exc}")
            return None, None
        except Exception as exc:  # noqa: BLE001 - keep grading running
            logger.warning("competitor agent skipped (other): %s", exc)
            self._log_skip("competitor.skipped", reason=str(exc)[:200])
            return None, None

    def _run_detection(
        self, agent_cls: type[Agent], *, domain: str
    ) -> list[SEORunFinding]:
        """Run one detection-only agent and persist its FindingDrafts.

        Catches every exception so a buggy / network-flaky agent never
        aborts the run. Findings land in :class:`SEORunFinding` with
        ``recommendation=""`` since detection is the current scope.
        """
        agent_name = getattr(agent_cls, "name", agent_cls.__name__)
        try:
            agent = agent_cls(run=self.run, step_index_start=self.step)
            drafts = agent.detect(domain=domain)
            self.step = agent.step_index
        except Exception as exc:  # noqa: BLE001 - keep the run alive
            logger.exception(
                "detection agent %s crashed: %s", agent_name, exc
            )
            self._log_skip(
                f"{agent_name}.crashed",
                reason=f"{type(exc).__name__}: {exc}"[:300],
            )
            return []

        if not drafts:
            return []

        max_n = settings.SEO_AI["max_findings_per_agent"]
        created: list[SEORunFinding] = []
        for d in drafts[:max_n]:
            severity = d.severity if d.severity in FindingSeverity.values else "notice"
            row = SEORunFinding.objects.create(
                run=self.run,
                agent=agent_name,
                severity=severity,
                category=(d.category or "")[:128],
                title=(d.title or "")[:255],
                description=(d.description or "")[:4000],
                recommendation="",  # Detection-only: fixes ship later.
                evidence_refs=list(d.evidence_refs or []),
                impact=(d.impact or "medium")[:16],
                effort=(d.effort or "")[:16],
                priority=_SEVERITY_PRIORITY.get(severity, 40),
            )
            created.append(row)
        logger.info(
            "detection agent %s wrote %d findings", agent_name, len(created)
        )
        return created

    def _log_skip(self, event: str, *, reason: str) -> None:
        """Audit-trail entry when an optional stage is skipped."""
        from ..models import SEORunMessage

        SEORunMessage.objects.create(
            run=self.run,
            step_index=self.step,
            from_agent="orchestrator",
            to_agent="",
            role="system",
            content={"event": event, "reason": reason},
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
        )
        self.step += 1

    # ── persistence helpers ────────────────────────────────────────────

    def _persist_findings(
        self,
        agent: str,
        findings: list[dict[str, Any]],
        accepted: list[dict[str, Any]],
    ) -> None:
        """Write all findings; mark accepted vs. rejected via priority.

        Rejected findings still land in the DB with a lower priority so
        the audit trail is complete — they just don't surface in the
        default dashboard view.
        """
        accepted_keys = {(f.get("title"), f.get("category")) for f in accepted}
        max_n = settings.SEO_AI["max_findings_per_agent"]
        for f in findings[:max_n]:
            severity = f.get("severity", "notice")
            base_priority = _SEVERITY_PRIORITY.get(severity, 40)
            is_accepted = (f.get("title"), f.get("category")) in accepted_keys
            priority = base_priority if is_accepted else max(10, base_priority - 30)
            SEORunFinding.objects.create(
                run=self.run,
                agent=agent,
                severity=severity if severity in FindingSeverity.values else "notice",
                category=(f.get("category") or "")[:128],
                title=(f.get("title") or "")[:255],
                description=(f.get("description") or "")[:4000],
                recommendation=(f.get("recommendation") or "")[:4000],
                evidence_refs=f.get("evidence_refs") or [],
                impact=f.get("impact") or "medium",
                effort=f.get("effort") or "medium",
                priority=priority,
            )

    def _gather_sources_snapshot(self) -> dict[str, Any]:
        """Record which data dirs we read so a run can be replayed."""
        ai = settings.SEO_AI
        comp = getattr(settings, "COMPETITOR", {})
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "crawler_data_dir": str(ai["data_dir"]),
            "gsc_data_dir": str(ai["gsc_data_dir"]),
            "sitemap_dir": str(ai["sitemap_dir"]),
            "semrush_database": settings.SEMRUSH["database"],
            "llm_provider": settings.LLM["provider"],
            "llm_model": settings.LLM["groq"]["model"],
            "competitor_enabled": comp.get("enabled", True),
            "competitor_top_n": comp.get("top_n", 10),
            "competitor_pages_per_competitor": comp.get("pages_per_competitor", 50),
            "competitor_cache_dir": str(ai["data_dir"] / "_competitor_cache"),
        }


def run_grade(*, domain: str, triggered_by: str = "api") -> SEORun:
    """Synchronous entrypoint. Celery wraps this for async usage."""
    run = SEORun.objects.create(domain=domain, triggered_by=triggered_by)
    Orchestrator(run).execute()
    return run


# ── helpers ──────────────────────────────────────────────────────────────


_MAX_KEYS = 200


def _enumerate_evidence_keys(namespaces: dict[str, Any]) -> list[str]:
    """Flatten a nested facts dict into the dotted-path keys the
    specialist agents can legitimately cite.

    For lists we emit ``parent[i].field`` for the first three items
    (representative sample) plus ``parent[*].field`` so generic
    "queries had this pattern" claims can match without naming each
    row. Caps the total at ``_MAX_KEYS`` so the critic prompt stays
    bounded regardless of fact-payload size.
    """
    keys: list[str] = []
    seen: set[str] = set()

    def _push(key: str) -> bool:
        if key in seen:
            return True
        seen.add(key)
        keys.append(key)
        return len(keys) < _MAX_KEYS

    def _walk(prefix: str, node: Any) -> bool:
        if not _push(prefix):
            return False
        if isinstance(node, dict):
            for k, v in node.items():
                if not _walk(f"{prefix}.{k}", v):
                    return False
        elif isinstance(node, list):
            sample_to = min(3, len(node))
            for i in range(sample_to):
                if not _walk(f"{prefix}[{i}]", node[i]):
                    return False
            if node and not _push(f"{prefix}[*]"):
                return False
        return True

    for namespace, data in namespaces.items():
        if isinstance(data, dict):
            for k, v in data.items():
                if not _walk(f"{namespace}:{k}", v):
                    return keys
        else:
            _push(f"{namespace}:value")
    return keys
