"""Scrapy downloader middlewares for the crawler.

Phase 3e:
  * ``playwright_gate.PlaywrightGateMiddleware`` — auto-routes thin
    static responses through scrapy-playwright for JS rendering.
  * ``similar_url_collapse.SimilarUrlCollapseMiddleware`` — Katana
    `-fsu` pattern; collapses faceted-search explosions before they
    flood the frontier.
"""
from .playwright_gate import PlaywrightGateMiddleware
from .similar_url_collapse import SimilarUrlCollapseMiddleware

__all__ = ["PlaywrightGateMiddleware", "SimilarUrlCollapseMiddleware"]
