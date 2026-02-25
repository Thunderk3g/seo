"""Celery Beat schedule for daily crawl automation.

Defines the periodic task schedule that triggers daily
scheduled crawls for all active websites.
"""

from celery.schedules import crontab


# Celery Beat schedule configuration.
# Import this into your Celery app config or settings.
CELERY_BEAT_SCHEDULE = {
    "daily-scheduled-crawl": {
        "task": "crawler.run_daily_crawl_all",
        "schedule": crontab(hour=2, minute=0),  # Run at 2:00 AM UTC daily
        "options": {"queue": "crawl"},
    },
    "daily-change-detection": {
        "task": "crawler.run_daily_change_detection",
        "schedule": crontab(hour=6, minute=0),  # Run at 6:00 AM UTC daily
        "options": {"queue": "analysis"},
    },
}
