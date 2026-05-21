"""Scrapy spiders for the SEO-AI side of the platform.

The competitor spider is the symmetric counterpart to
``apps.crawler.spiders.bajaj_spider.BajajSpider``:

  * Same Scrapy + scrapy-playwright stack.
  * Same Playwright gate middleware (re-renders SPA shells).
  * Same Postgres dual-write pattern (writes to CrawlerPageResult with
    kind='competitor' so per-competitor Health Score works without a
    parallel table).

What differs:

  * URL-list driven, not seed + link walking. The caller already knows
    which competitor URLs to fetch (typically pulled from SEMrush top
    pages + SERP results upstream in the gap pipeline).
  * One CrawlSnapshot per competitor domain — fetch_pages() with mixed
    hosts shards the spider run per host so each competitor has its
    own snapshot row.
  * Full body_text is captured + persisted, because the AEM-vs-
    competitor content comparison view diffs raw text downstream.

Activated via ``COMPETITOR_ENGINE=scrapy`` (default 'legacy' keeps the
in-process requests+BS4 path running). Both engines expose the same
``CompetitorCrawler`` public API so the six existing callers (gap
pipeline, competitor agent, technical_audit, etc.) are unaffected.
"""
from .competitor_spider import CompetitorSpider

__all__ = ["CompetitorSpider"]
