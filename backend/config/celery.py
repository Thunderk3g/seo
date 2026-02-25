"""Celery application configuration."""

import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

app = Celery("seo_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover task modules in all installed apps
app.autodiscover_tasks()

# Import beat schedule
try:
    from core.scheduler.scheduler import CELERY_BEAT_SCHEDULE
    app.conf.beat_schedule = CELERY_BEAT_SCHEDULE
except ImportError:
    pass
