"""Celery application configuration.

Queue topology (Phase 5 load-balancing):

  * ``bajaj_crawl``  — apps.crawler.tasks.run_crawl_task. Playwright +
                        full-site crawl. RAM-hungry; concurrency=1.
  * ``comp_crawl``   — seo_ai.walk_competitor*, psi_enrich_snapshot.
                        Scrapy subprocesses. concurrency=2.
  * ``default``      — everything else (LLM, grade, gap pipeline, ad-hoc
                        single-page fetch). concurrency=4.

Each queue maps to its own worker container in docker-compose.yml so a
slow Playwright run on the Bajaj queue can't starve a 50 ms grade task
on the default queue, and vice versa.

``acks_late=True`` + ``task_reject_on_worker_lost=True`` are set
globally so a SIGKILL'd worker mid-crawl re-queues the task once
rather than silently losing it.
"""

import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

app = Celery("seo_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Queue routing — each crawl flavour lives on its own queue so RAM-
# hungry Playwright runs don't block fast LLM/grade tasks.
app.conf.task_routes = {
    "apps.crawler.tasks.run_crawl_task": {"queue": "bajaj_crawl"},
    "seo_ai.walk_competitor": {"queue": "comp_crawl"},
    "seo_ai.walk_competitor_roster": {"queue": "comp_crawl"},
    "seo_ai.psi_enrich_snapshot": {"queue": "comp_crawl"},
}
app.conf.task_default_queue = "default"

# Resilience defaults — a SIGKILL'd worker mid-crawl re-queues the task
# once instead of silently losing it. Prefetch=1 prevents one worker
# from grabbing a queue of crawl tasks and starving its peers.
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
app.conf.worker_prefetch_multiplier = 1
# Bound subprocess leakage (Playwright/Chromium) by recycling workers
# every 20 tasks. Cheap; restarts in <2 s with our base image.
app.conf.worker_max_tasks_per_child = 20

# Auto-discover task modules in all installed apps
app.autodiscover_tasks()

# Import beat schedule
try:
    from core.scheduler.scheduler import CELERY_BEAT_SCHEDULE
    app.conf.beat_schedule = CELERY_BEAT_SCHEDULE
except ImportError:
    pass
