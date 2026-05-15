"""Celery tasks for SEO grading.

The synchronous entrypoint lives in :mod:`agents.orchestrator`; this
module is the thin async wrapper so the API can return 202 + a run id
and have the worker do the actual LLM calls.
"""
from __future__ import annotations

import logging

from celery import shared_task

from .agents.orchestrator import Orchestrator
from .gap_pipeline.orchestrator import GapPipelineOrchestrator
from .models import GapPipelineRun, SEORun

logger = logging.getLogger("seo.ai.tasks")


@shared_task(name="seo_ai.run_grade", bind=True, max_retries=0)
def run_grade_task(self, run_id: str) -> str:
    """Execute a grading run that was already created in the DB.

    Pattern: API view creates the SEORun row (so the client can poll it
    immediately), then enqueues this task. The task picks the row up
    and runs the orchestrator. Splitting creation from execution means
    we never lose track of a run that fails before the worker can pick
    it up — the row already exists.
    """
    try:
        run = SEORun.objects.get(id=run_id)
    except SEORun.DoesNotExist:
        logger.error("run_grade_task: SEORun %s not found", run_id)
        return "not_found"
    Orchestrator(run).execute()
    return str(run.status)


@shared_task(name="seo_ai.run_gap_pipeline", bind=True, max_retries=0)
def run_gap_pipeline_task(
    self, run_id: str, *, top_n: int = 10, query_count: int = 24
) -> str:
    """Execute a gap-detection pipeline run that's already in the DB.

    Same split-create-then-execute pattern as :func:`run_grade_task`:
    the API view creates the ``GapPipelineRun`` row so the client can
    poll its status immediately, then enqueues this task. The 6-stage
    pipeline writes intermediate data into child tables and updates
    ``stage_status`` after each stage, which is what the polling UI
    reads to render live progress.
    """
    try:
        run = GapPipelineRun.objects.get(id=run_id)
    except GapPipelineRun.DoesNotExist:
        logger.error("run_gap_pipeline_task: GapPipelineRun %s not found", run_id)
        return "not_found"
    GapPipelineOrchestrator(run).execute(top_n=top_n, query_count=query_count)
    return str(run.status)
