"""Production settings.

Tightens what ``base.py`` leaves dev-friendly: requires a real
SECRET_KEY, locks ALLOWED_HOSTS, demands TLS, and (optionally) wires
Sentry.

Boot-time guards
----------------
This module **raises at import time** when a required prod-only
secret is missing. The intent is to fail loud on a misconfigured
deploy rather than silently boot with a development default. The
list of guards is exactly:

  * ``SECRET_KEY`` must be set and must NOT be the base.py default
    ``dev-secret-key``.
  * ``ALLOWED_HOSTS`` must contain at least one non-empty host.

Both are checked AFTER the ``from .base import *`` line so any value
the operator put in the env actually wins.

What we don't enforce (operator's call):

  * ``SSL_VERIFY=false`` env vars — dev sometimes needs them behind a
    corp MITM proxy that intercepts outbound TLS; prod usually wants
    them all flipped to true or pointed at the corp CA bundle. We
    log warnings instead of crashing.
"""

import logging
import os

from .base import *  # noqa: F401, F403
from .base import BASE_DIR, INSTALLED_APPS, MIDDLEWARE

log = logging.getLogger("config.settings.prod")

DEBUG = False

# ── ALLOWED_HOSTS guard ───────────────────────────────────────────
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",")
    if h.strip()
]
if not ALLOWED_HOSTS:
    raise RuntimeError(
        "ALLOWED_HOSTS must be set in production. Add the deploy "
        "hostnames to your .env (comma-separated)."
    )

# ── SECRET_KEY guard ──────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY in ("dev-secret-key", "replace-me-in-production"):
    raise RuntimeError(
        "SECRET_KEY must be set to a real secret in production. "
        "Generate one with: "
        "python -c 'from django.core.management.utils import "
        "get_random_secret_key; print(get_random_secret_key())'"
    )

# ── HTTPS + cookies + headers ─────────────────────────────────────
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
# Tell Django that the upstream proxy already terminated TLS — needed
# so request.is_secure() returns True behind ALB/nginx and our HTTPS
# redirects don't loop.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get(
    "SECURE_SSL_REDIRECT", "true",
).lower() in ("1", "true", "yes")
# HSTS — opt-in via env so dev can boot with prod settings locally
# without breaking subsequent http:// connections.
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

# ── Static files ──────────────────────────────────────────────────
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
# WhiteNoise — serves static files directly from gunicorn so we don't
# need nginx in front for /static/. Inserted just below the security
# middleware per the project's recommendation.
if "whitenoise.middleware.WhiteNoiseMiddleware" not in MIDDLEWARE:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ── CORS (django-cors-headers) ────────────────────────────────────
# Optional — only enabled when CORS_ALLOWED_ORIGINS is non-empty. The
# Vite dev proxy handles same-origin in dev; prod typically serves the
# SPA + API from the same host so CORS is rarely needed. Set the env
# only when the SPA lives on a different origin from the API.
_cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_env:
    CORS_ALLOWED_ORIGINS = [
        o.strip() for o in _cors_env.split(",") if o.strip()
    ]
    if "corsheaders" not in INSTALLED_APPS:
        INSTALLED_APPS.append("corsheaders")
    if "corsheaders.middleware.CorsMiddleware" not in MIDDLEWARE:
        MIDDLEWARE.insert(0, "corsheaders.middleware.CorsMiddleware")

# ── Sentry (optional) ────────────────────────────────────────────
# Enabled by setting SENTRY_DSN. Errors + traces go to the project
# matching the DSN. We deliberately don't send PII (default Sentry
# behaviour); ``sample_rate=1.0`` for errors but ``traces_sample_rate``
# stays low to keep ingestion costs sane.
_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=_sentry_dsn,
            integrations=[DjangoIntegration(), CeleryIntegration()],
            environment=os.environ.get("SENTRY_ENV", "production"),
            release=os.environ.get("APP_VERSION", "unknown"),
            send_default_pii=False,
            traces_sample_rate=float(
                os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05"),
            ),
            profiles_sample_rate=float(
                os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.0"),
            ),
        )
        log.info("Sentry initialised (env=%s)", os.environ.get("SENTRY_ENV"))
    except ImportError:
        log.warning(
            "SENTRY_DSN set but sentry-sdk is not installed — add it "
            "to requirements/prod.txt or unset SENTRY_DSN.",
        )

# ── Logging ───────────────────────────────────────────────────────
# Plain stdout JSON so cloud-native log shippers can ingest without
# parser quirks. Default level INFO, env-overridable.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.request": {"level": "WARNING", "propagate": True},
        "django.server": {"level": "INFO", "propagate": True},
        "django.utils.autoreload": {"level": "WARNING", "propagate": False},
    },
}

# ── App version (surfaced by /api/v1/health/) ─────────────────────
APP_VERSION = os.environ.get("APP_VERSION", "unknown")

# ── Outbound TLS posture audit (warn, don't crash) ───────────────
_disabled = []
for env_key in (
    "LLM_SSL_VERIFY", "COMPETITOR_SSL_VERIFY", "SEMRUSH_SSL_VERIFY",
    "PSI_SSL_VERIFY", "AI_VISIBILITY_SSL_VERIFY", "ADOBE_SSL_VERIFY",
    "APIFY_SSL_VERIFY", "BRAND_MENTIONS_SSL_VERIFY", "SERP_API_SSL_VERIFY",
):
    val = os.environ.get(env_key, "").strip().lower()
    if val in ("false", "0", "no"):
        _disabled.append(env_key)
if _disabled:
    log.warning(
        "TLS verification disabled for outbound calls: %s — flip to "
        "true or point at the corp CA bundle before going live.",
        ", ".join(_disabled),
    )
