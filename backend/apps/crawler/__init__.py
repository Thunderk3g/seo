"""Bajaj Crawler Engine — Django app port of crawler-engine/.

Threaded BFS crawler with retry/backoff, resumable state, append-only CSV
storage, sitemap + robots compliance, and crawler-trap detection. Logic
ported verbatim from crawler-engine/app/; FastAPI routes converted to DRF
views; pydantic-settings converted to Django settings + env vars.
"""

__version__ = "2.0.0"
