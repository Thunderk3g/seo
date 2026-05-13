"""Base settings for Django 12-factor project."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.common",
    "apps.crawler",
    "apps.seo_ai",
    # apps.crawl_sessions removed — replaced by the file-backed crawler-engine
    # port now living in apps.crawler. The following apps still reference
    # the deleted ORM models (CrawlSession / Page / Link / etc.) and will
    # need rework before they can be re-enabled:
    #   - apps.ai_agents
    #   - apps.gsc_integration
    #   - apps.dashboard
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "seo_db"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

STATIC_URL = "/static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─────────────────────────────────────────────────────────────
# REST Framework
# ─────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# ─────────────────────────────────────────────────────────────
# Celery Configuration
# ─────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

# ─────────────────────────────────────────────────────────────
# SEO AI Agent System
# ─────────────────────────────────────────────────────────────
# All data sources live under backend/data/ so the deployable backend
# is self-contained — no scratch directories in the project root, no
# absolute paths to host-specific scratch dirs. Subtypes:
#   backend/data/                  → crawler CSVs + crawl_state.json (legacy default)
#   backend/data/gsc/              → Search Console pull (gsc_pull.py output + OAuth files)
#   backend/data/aem/              → AEM page-model JSON exports
#   backend/data/_semrush_cache/   → SEMrush response cache
# Every path is still overridable via .env so prod can mount volumes
# elsewhere.

SEO_AI = {
    "data_dir": Path(
        os.environ.get("SEO_AI_DATA_DIR") or (BASE_DIR / "data")
    ),
    "gsc_data_dir": Path(
        os.environ.get("SEO_AI_GSC_DATA_DIR") or (BASE_DIR / "data" / "gsc")
    ),
    "sitemap_dir": Path(
        os.environ.get("SEO_AI_SITEMAP_DIR") or (BASE_DIR / "data" / "aem")
    ),
    "max_findings_per_agent": int(os.environ.get("SEO_AI_MAX_FINDINGS_PER_AGENT", "20")),
    "budget_usd_per_run": float(os.environ.get("SEO_AI_BUDGET_USD_PER_RUN", "2.00")),
}

LLM = {
    "provider": os.environ.get("LLM_PROVIDER", "groq"),
    # TLS verification for outbound LLM calls. Accepts:
    #   "" / unset / "true"  → default (certifi + truststore on Windows)
    #   "false"              → disable verification (dev only — corp MITM)
    #   "/path/to/ca.pem"    → custom CA bundle, e.g. corporate root CA
    "ssl_verify": os.environ.get("LLM_SSL_VERIFY", "").strip(),
    "groq": {
        "api_key": os.environ.get("GROQ_API_KEY", ""),
        "base_url": os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        "max_tokens": int(os.environ.get("GROQ_MAX_TOKENS", "4096")),
        "temperature": float(os.environ.get("GROQ_TEMPERATURE", "0.2")),
    },
}

SEMRUSH = {
    "api_key": os.environ.get("SEMRUSH_API_KEY", ""),
    "database": os.environ.get("SEMRUSH_DATABASE", "in"),
    "default_limit": int(os.environ.get("SEMRUSH_DEFAULT_LIMIT", "100")),
}

# ─────────────────────────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "loggers": {
        "seo": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
        },
    },
}
