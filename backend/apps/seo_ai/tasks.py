"""Celery tasks for SEO grading.

The synchronous entrypoint lives in :mod:`agents.orchestrator`; this
module is the thin async wrapper so the API can return 202 + a run id
and have the worker do the actual LLM calls.
"""
from __future__ import annotations

import logging

from celery import shared_task

from .agents.orchestrator import Orchestrator
from .models import SEORun

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
