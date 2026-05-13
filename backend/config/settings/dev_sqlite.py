"""Dev settings backed by SQLite.

Use this when Postgres isn't running locally — e.g. for the SEO AI
smoke test, where we want migrations + a single grading run without
spinning up the full Docker stack. Pure SQLite cannot match
Postgres's JSONB query semantics, but every SEO AI query is a simple
``filter / order_by / count`` against indexed columns, so the dev
ergonomics win.
"""
from .dev import *  # noqa: F401, F403
from .base import BASE_DIR  # noqa: F401

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
