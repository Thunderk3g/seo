"""Base settings for Django 12-factor project."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.crawler",
    "apps.crawl_sessions",
    "apps.ai_agents",
    "apps.gsc_integration",
    "apps.dashboard",
    "apps.common",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "seo_db",
    }
}
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
