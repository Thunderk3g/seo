"""Celery Beat schedule — empty post-migration.

The previous schedule pointed at ``crawler.run_daily_crawl_all`` and
``crawler.run_daily_change_detection`` tasks defined in the deleted
async-Django crawler. The new file-backed crawler ships no Celery tasks
of its own; trigger crawls via the management command (``manage.py crawl``)
or the ``POST /api/v1/crawler/start`` endpoint.

Add new periodic tasks here when needed.
"""
from __future__ import annotations

CELERY_BEAT_SCHEDULE: dict = {}
