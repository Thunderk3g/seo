"""Scrapy spiders for the crawler.

Phase 3d of the tool-clone roadmap. The spider package mirrors the
legacy ``apps.crawler.engine.engine.run_crawl`` behaviour but uses
Scrapy's request scheduler, downloader middleware chain, and item
pipelines instead of a custom BFS loop.

Runs alongside the legacy engine behind the ``CRAWLER_ENGINE`` env
flag (defined in apps.crawler.conf). Triggered via:

    python manage.py crawl_scrapy --max-pages 500

Both engines write to the same persistence layer (CSV via csv_writer +
Postgres via the Phase 3c dual-write hook), so the read path stays
identical regardless of which engine produced the data.
"""
from .bajaj_spider import BajajSpider

__all__ = ["BajajSpider"]
