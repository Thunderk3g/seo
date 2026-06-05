"""Celery Beat schedule for the SEO platform.

Periodic tasks ordered by cadence:

  * ``crawl-bajaj-daily``      02:00 IST — re-crawl bajajlifeinsurance.com
    (in-house, full sweep + PSI). Output: fresh CrawlerPageResult rows
    + Health Score recompute.

  * ``walk-competitors-daily`` 03:00 IST — link-walk every domain in
    ``COMPETITOR["roster"]``. Output: fresh competitor CrawlerPageResult
    rows + ChangeWatcher events (title/content/structure deltas).

  * ``gc-competitor-history-weekly`` Sun 04:30 IST — prune history +
    events older than 90 days. Keeps Postgres bounded.

All times in IST (the user is in India). Celery beat reads its clock
from ``settings.TIME_ZONE`` (set to "Asia/Kolkata" elsewhere in
config). The tasks here are pure ``shared_task`` references — they
have their own ``time_limit`` envelopes; beat just kicks them off and
moves on.

To run beat:

    docker compose run --rm worker celery -A config beat --loglevel=info

The worker container already runs ``celery worker``; add a second
service (``beat``) to actually fire the schedule. In dev you can
``docker compose exec worker celery -A config beat -l info`` and it
shares the same DJANGO_SETTINGS_MODULE.
"""
from __future__ import annotations

from celery.schedules import crontab

CELERY_BEAT_SCHEDULE: dict = {
    # ── In-house Bajaj crawl ──────────────────────────────────────
    # Daily full sweep at 02:00 IST. Bajaj's traffic is lowest then.
    "crawl-bajaj-daily": {
        "task": "apps.crawler.tasks.run_crawl_task",
        "schedule": crontab(hour=2, minute=0),
        "options": {"expires": 60 * 60},  # drop if missed by >1 h
    },

    # ── Competitor walks ──────────────────────────────────────────
    # 03:00 IST — runs after Bajaj crawl so the Postgres write
    # contention is staggered. Walks all domains in COMPETITOR["roster"]
    # sequentially. ChangeWatcher fires from the pipeline's close_spider
    # hook, so this task's side-effect IS the entire monitoring layer.
    "walk-competitors-daily": {
        "task": "seo_ai.walk_competitor_roster",
        "schedule": crontab(hour=3, minute=0),
        "kwargs": {"mode": "sitemap", "sitemap_url_cap": 5000},
        "options": {"expires": 6 * 60 * 60},
    },

    # ── GC: prune old history + events ───────────────────────────
    # Weekly Sunday 04:30 IST. 90-day retention covers the operator-
    # visible "what changed in the last quarter" view; longer-horizon
    # analytics belong in a warehouse, not Postgres.
    "gc-competitor-history-weekly": {
        "task": "seo_ai.gc_competitor_history",
        "schedule": crontab(hour=4, minute=30, day_of_week="sun"),
        "kwargs": {"retain_days": 90},
        "options": {"expires": 60 * 60},
    },
}
