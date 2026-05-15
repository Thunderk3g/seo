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
    # Same semantics as LLM_SSL_VERIFY above. Needed inside the Docker
    # image because the Debian-slim trust store lacks the corp MITM root.
    "ssl_verify": os.environ.get("SEMRUSH_SSL_VERIFY", "").strip(),
    # Competitor-discovery and top-pages calls bill the same units but
    # change far less often than headline overviews — give them a much
    # longer TTL so day-to-day grade re-runs don't burn the budget.
    "competitor_cache_ttl": int(
        os.environ.get("SEMRUSH_COMPETITOR_CACHE_TTL", str(7 * 24 * 3600))
    ),
}

# Competitor SEO Gap analysis — discovers our top organic rivals via
# SEMrush, samples their best pages, and feeds the CompetitorAgent.
# Disabled silently when SEMRUSH_API_KEY is unset or COMPETITOR_ENABLED
# is "false"; never crashes a grading run.
COMPETITOR = {
    "enabled": os.environ.get("COMPETITOR_ENABLED", "true").lower()
    in ("1", "true", "yes", "on"),
    "top_n": int(os.environ.get("COMPETITOR_TOP_N", "10")),
    "pages_per_competitor": int(os.environ.get("COMPETITOR_PAGES_PER_COMP", "50")),
    "keywords_per_competitor": int(os.environ.get("COMPETITOR_KW_PER_COMP", "100")),
    "rate_limit_sec": float(os.environ.get("COMPETITOR_RATE_LIMIT_SEC", "1.0")),
    "timeout_sec": int(os.environ.get("COMPETITOR_TIMEOUT_SEC", "15")),
    # Phase 2A — how many of OUR top URLs to crawl live for the
    # symmetric comparison. 200 ≈ 4 min crawl at 1 req/s.
    "our_pages_limit": int(os.environ.get("COMPETITOR_OUR_PAGES_LIMIT", "200")),
    # Bot-identifiable UA strings get 403'd by Cloudflare/Akamai on
    # most enterprise sites, so default to a recent Chrome UA. We still
    # respect robots.txt and rate-limit at COMPETITOR_RATE_LIMIT_SEC,
    # i.e. behave as a single human user.
    "user_agent": os.environ.get(
        "COMPETITOR_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    ),
    "cache_ttl_seconds": int(
        os.environ.get("COMPETITOR_CACHE_TTL_SECONDS", str(7 * 24 * 3600))
    ),
    # Same semantics as SEMRUSH_SSL_VERIFY. Inside the Docker image set
    # to "false" because the Debian trust store doesn't include the
    # corporate MITM root that intercepts competitor HTTPS traffic.
    "ssl_verify": os.environ.get("COMPETITOR_SSL_VERIFY", "").strip(),
}

# ─────────────────────────────────────────────────────────────
# AI Search Visibility (Phase 2 of the competitor-gap detection suite)
# ─────────────────────────────────────────────────────────────
# Probes multiple LLM-based search engines to detect whether the focus
# domain is cited / mentioned vs. its rivals. Every provider key is
# independent — missing OPENAI_API_KEY skips the OpenAI probe but the
# Anthropic / Gemini / Perplexity / xAI probes still run. The agent
# itself is disabled silently when AI_VISIBILITY_ENABLED is "false" or
# every provider key is empty.
AI_VISIBILITY = {
    "enabled": os.environ.get("AI_VISIBILITY_ENABLED", "true").lower()
    in ("1", "true", "yes", "on"),
    "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
    "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    "google_api_key": os.environ.get("GOOGLE_API_KEY", ""),
    "perplexity_api_key": os.environ.get("PERPLEXITY_API_KEY", ""),
    "xai_api_key": os.environ.get("XAI_API_KEY", ""),
    # Optional model overrides per provider — leave blank to use each
    # adapter's documented default.
    "openai_model": os.environ.get("OPENAI_AI_VISIBILITY_MODEL", "gpt-4o-mini"),
    "anthropic_model": os.environ.get(
        "ANTHROPIC_AI_VISIBILITY_MODEL", "claude-3-5-haiku-latest"
    ),
    "google_model": os.environ.get(
        "GOOGLE_AI_VISIBILITY_MODEL", "gemini-2.0-flash"
    ),
    "perplexity_model": os.environ.get(
        "PERPLEXITY_AI_VISIBILITY_MODEL", "sonar"
    ),
    "xai_model": os.environ.get("XAI_AI_VISIBILITY_MODEL", "grok-2-latest"),
    "max_queries": int(os.environ.get("AI_VISIBILITY_MAX_QUERIES", "20")),
    "request_timeout_sec": int(
        os.environ.get("AI_VISIBILITY_REQUEST_TIMEOUT_SEC", "30")
    ),
    "cache_ttl_seconds": int(
        os.environ.get("AI_VISIBILITY_CACHE_TTL", str(7 * 24 * 3600))
    ),
    "ssl_verify": os.environ.get("AI_VISIBILITY_SSL_VERIFY", "").strip(),
}

# ─────────────────────────────────────────────────────────────
# SERP API (Phase 3 of the competitor-gap detection suite)
# ─────────────────────────────────────────────────────────────
# Traditional SERP visibility via SerpAPI. The provider key allows
# swapping in DataForSEO / Zenserp later without changing the adapter
# interface; only SerpAPI is implemented this iteration. The agent is
# silently skipped when no SERPAPI_API_KEY is configured.
SERP_API = {
    "enabled": os.environ.get("SERP_API_ENABLED", "true").lower()
    in ("1", "true", "yes", "on"),
    "provider": os.environ.get("SERP_API_PROVIDER", "serpapi"),
    "api_key": os.environ.get("SERPAPI_API_KEY", ""),
    "engines": tuple(
        e.strip()
        for e in os.environ.get(
            "SERP_API_ENGINES", "google,bing,duckduckgo"
        ).split(",")
        if e.strip()
    ),
    "country": os.environ.get("SERP_API_COUNTRY", "in"),
    "language": os.environ.get("SERP_API_LANGUAGE", "en"),
    "max_queries": int(os.environ.get("SERP_API_MAX_QUERIES", "20")),
    "request_timeout_sec": int(
        os.environ.get("SERP_API_REQUEST_TIMEOUT_SEC", "30")
    ),
    "cache_ttl_seconds": int(
        os.environ.get("SERP_API_CACHE_TTL", str(7 * 24 * 3600))
    ),
    "ssl_verify": os.environ.get("SERP_API_SSL_VERIFY", "").strip(),
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
