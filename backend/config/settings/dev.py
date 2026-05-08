"""Development settings."""

from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Use console email backend
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Show browsable API in development
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# Verbose logging in development
LOGGING["loggers"]["seo"]["level"] = "DEBUG"  # noqa: F405
LOGGING["loggers"]["django"]["level"] = "INFO"  # noqa: F405
