"""Sequential six-stage runner for the gap detection pipeline.

Each stage is wrapped in a uniform try/except so one crashing stage
never aborts the run — it lands in ``stage_status`` as ``failed`` with
the error reason, and the next stage starts on whatever data the
previous stage *did* persist.

``stage_status`` shape, updated atomically after every transition so the
polling UI sees progress in real time:

    {
      "queries":    {"status": "ok",       "started_at": "...", "finished_at": "...", "data": {...}},
      "llm_search": {"status": "running",  "started_at": "...", "finished_at": null,  "data": {}},
      "serp_search":{"status": "pending",  "started_at": null,  "finished_at": null,  "data": {}},
      ...
    }

``status`` values: ``pending``, ``running``, ``ok``, ``skipped``,
``failed``, ``no_gaps_found``, ``empty``.
"""
from __future__ import annotations

import logging
import time
import traceback
from typing import Any, Callable

from django.utils import timezone as dj_tz

from ..models import GapPipelineQuery, GapPipelineRun, GapPipelineStatus
from . import (
    comparison,
    competitor_aggregation,
    deep_crawl,
    llm_search,
    query_synthesis,
    serp_search,
)

logger = logging.getLogger("seo.ai.gap_pipeline.orchestrator")


STAGE_ORDER: tuple[str, ...] = (
    "queries",
    "llm_search",
    "serp_search",
    "competitors",
    "deep_crawl",
    "comparison",
)


def _empty_stage_status() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "data": {},
            "error": "",
        }
        for name in STAGE_ORDER
    }


class GapPipelineOrchestrator:
    """Runs all 6 stages sequentially against one ``GapPipelineRun``."""

    def __init__(self, run: GapPipelineRun) -> None:
        self.run = run
        # Initialise stage_status if this is a fresh run.
        if not run.stage_status:
            run.stage_status = _empty_stage_status()
            run.save(update_fields=["stage_status"])

    # ── public ────────────────────────────────────────────────────────

    def execute(self, *, top_n: int = 10, query_count: int = 24) -> None:
        run = self.run
        run.status = GapPipelineStatus.RUNNING
        run.save(update_fields=["status"])

        t0 = time.time()
        any_failed = False

        # Stage 1: queries
        ok1, queries = self._run_stage_with_payload(
            "queries",
            lambda: self._run_query_synthesis(query_count=query_count),
        )
        if not ok1 or not queries:
            logger.warning(
                "gap_pipeline %s: no queries produced — aborting downstream stages",
                run.id,
            )
            for name in STAGE_ORDER[1:]:
                self._set_stage(name, status="skipped", data={"reason": "no queries"})
            self._finish(failed=True, elapsed=time.time() - t0)
            return

        # Stage 2: LLM search
        ok2 = self._run_stage(
            "llm_search",
            lambda: llm_search.execute(
                run=run, domain=run.domain, queries=queries
            ),
        )
        any_failed = any_failed or not ok2

        # Stage 3: SERP search
        ok3 = self._run_stage(
            "serp_search",
            lambda: serp_search.execute(
                run=run, domain=run.domain, queries=queries
            ),
        )
        any_failed = any_failed or not ok3

        # Stage 4: competitor aggregation. Only meaningful when either
        # LLM or SERP data exists — otherwise the leaderboard is empty.
        ok4 = self._run_stage(
            "competitors",
            lambda: competitor_aggregation.execute(
                run=run, domain=run.domain, top_n=top_n
            ),
        )
        any_failed = any_failed or not ok4

        # Stage 5: deep crawl. Skips silently if no competitors landed.
        if run.competitor_count == 0:
            self._set_stage(
                "deep_crawl",
                status="skipped",
                data={"reason": "no competitors to crawl"},
            )
        else:
            ok5 = self._run_stage(
                "deep_crawl",
                lambda: deep_crawl.execute(run=run, domain=run.domain),
            )
            any_failed = any_failed or not ok5

        # Stage 6: comparison.
        ok6 = self._run_stage(
            "comparison",
            lambda: comparison.execute(run=run),
        )
        any_failed = any_failed or not ok6

        self._finish(failed=any_failed, elapsed=time.time() - t0)

    # ── internals ─────────────────────────────────────────────────────

    def _run_query_synthesis(self, *, query_count: int) -> tuple[dict[str, Any], list[GapPipelineQuery]]:
        """Wrap stage 1 so it returns both a status dict + the persisted
        queries (downstream stages need the rows)."""
        queries = query_synthesis.synthesize_queries(
            run=self.run, domain=self.run.domain, n=query_count
        )
        return (
            {
                "status": "ok" if queries else "empty",
                "query_count": len(queries),
                "seed_keyword_count": self.run.seed_keyword_count,
            },
            queries,
        )

    def _run_stage_with_payload(
        self, name: str, fn: Callable[[], tuple[dict[str, Any], Any]]
    ) -> tuple[bool, Any]:
        """Run a stage whose callable returns (status_dict, side_payload).
        Returns (ok_flag, side_payload). Side payload is forwarded to
        downstream stages — used for stage 1's GapPipelineQuery list.
        """
        self._set_stage(name, status="running")
        try:
            status, side = fn()
        except Exception as exc:  # noqa: BLE001 - never crash the pipeline
            self._set_stage(
                name,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:500],
                trace=traceback.format_exc()[-2000:],
            )
            return False, None
        self._set_stage(name, **{"status": status.get("status", "ok"), "data": status})
        return True, side

    def _run_stage(self, name: str, fn: Callable[[], dict[str, Any]]) -> bool:
        """Run a stage whose callable returns a status dict. Side-effects
        on the DB are the actual output; the dict is metadata for the UI."""
        self._set_stage(name, status="running")
        try:
            status = fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception("gap_pipeline stage %s crashed", name)
            self._set_stage(
                name,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:500],
                trace=traceback.format_exc()[-2000:],
            )
            return False
        self._set_stage(name, **{"status": status.get("status", "ok"), "data": status})
        return True

    def _set_stage(
        self,
        name: str,
        *,
        status: str,
        data: dict[str, Any] | None = None,
        error: str = "",
        trace: str = "",
    ) -> None:
        """Atomically update one stage's status. Done by re-reading the
        run, mutating the JSON, and saving — Django doesn't support
        sub-key updates without raw SQL, and the polling endpoint is
        cheap so collisions aren't a concern at our concurrency."""
        run = GapPipelineRun.objects.get(pk=self.run.pk)
        ss = run.stage_status or _empty_stage_status()
        if name not in ss:
            ss[name] = {
                "status": "pending",
                "started_at": None,
                "finished_at": None,
                "data": {},
                "error": "",
            }
        slot = ss[name]
        slot["status"] = status
        now = dj_tz.now().isoformat()
        if status == "running":
            slot["started_at"] = now
            slot["finished_at"] = None
        else:
            slot["finished_at"] = now
            if not slot.get("started_at"):
                slot["started_at"] = now
        if data is not None:
            slot["data"] = data
        if error:
            slot["error"] = error
        if trace:
            slot["trace"] = trace
        run.stage_status = ss
        run.save(update_fields=["stage_status"])
        # Keep our in-memory copy in sync.
        self.run.stage_status = ss

    def _finish(self, *, failed: bool, elapsed: float) -> None:
        run = self.run
        # Final status: COMPLETE if every stage was ok/skipped/empty/no_gaps_found,
        # DEGRADED if at least one stage failed but some data persisted,
        # FAILED only when the run produced nothing at all.
        any_ok = False
        for slot in (run.stage_status or {}).values():
            if slot.get("status") in {"ok", "no_gaps_found", "empty"}:
                any_ok = True
                break
        if failed and any_ok:
            run.status = GapPipelineStatus.DEGRADED
        elif failed:
            run.status = GapPipelineStatus.FAILED
        else:
            run.status = GapPipelineStatus.COMPLETE
        run.finished_at = dj_tz.now()
        run.save(update_fields=["status", "finished_at"])
        logger.info(
            "gap_pipeline %s %s elapsed=%.1fs queries=%d llm=%d serp=%d "
            "competitors=%d crawl_pages=%d",
            run.id,
            run.status,
            elapsed,
            run.query_count,
            run.llm_call_count,
            run.serp_call_count,
            run.competitor_count,
            run.deep_crawl_pages,
        )


def run_gap_pipeline(
    *, domain: str, triggered_by: str = "api", top_n: int = 10, query_count: int = 24
) -> GapPipelineRun:
    """Synchronous entrypoint — used by tests + dev sync mode."""
    run = GapPipelineRun.objects.create(domain=domain, triggered_by=triggered_by)
    run.config_snapshot = {
        "top_n": top_n,
        "query_count": query_count,
        "domain": domain,
    }
    run.save(update_fields=["config_snapshot"])
    GapPipelineOrchestrator(run).execute(top_n=top_n, query_count=query_count)
    return run
