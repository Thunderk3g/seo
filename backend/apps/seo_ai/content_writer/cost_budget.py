"""Per-run cost guard for the content_writer pipeline.

The operator runs Claude on a fixed prepaid balance, so a single revamp
must stay under a hard cap (default $0.75). This is a small in-memory
accumulator threaded through ``run_revamp``: each LLM stage reports its
spend, optional stages check ``would_exceed`` before running, and the
final state lands in telemetry + warnings.

It is NOT persisted as a model — its job is to bound one run. SerpAPI
calls are billed on a separate key and are NOT counted here.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("seo.ai.content_writer.cost_budget")


class CostBudget:
    """Accumulates USD spend against a cap and records degradations."""

    def __init__(self, cap_usd: float) -> None:
        self.cap_usd = float(cap_usd)
        self._spent = 0.0
        self._degraded = False
        self._notes: list[str] = []

    # ── recording ────────────────────────────────────────────────────
    def add(self, resp) -> float:
        """Add an LLMResponse's cost. Returns the amount added."""
        amount = float(getattr(resp, "cost_usd", 0.0) or 0.0)
        self._spent += amount
        return amount

    def add_usd(self, usd: float) -> float:
        amount = float(usd or 0.0)
        self._spent += amount
        return amount

    # ── queries ──────────────────────────────────────────────────────
    def spent(self) -> float:
        return round(self._spent, 6)

    def remaining(self) -> float:
        return max(0.0, self.cap_usd - self._spent)

    def would_exceed(self, est_usd: float) -> bool:
        """True if spending ``est_usd`` more would breach the cap."""
        return (self._spent + float(est_usd or 0.0)) > self.cap_usd

    def degraded(self) -> bool:
        return self._degraded

    # ── degradation bookkeeping ──────────────────────────────────────
    def note(self, msg: str) -> None:
        """Record that a stage was skipped/trimmed to stay under cap."""
        self._degraded = True
        self._notes.append(msg)
        logger.info("content_writer budget degrade: %s", msg)

    def notes(self) -> list[str]:
        return list(self._notes)
