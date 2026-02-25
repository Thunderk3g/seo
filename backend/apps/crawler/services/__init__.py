"""Crawler services package."""

from apps.crawler.services.crawler_engine import CrawlerEngine, CrawlResult
from apps.crawler.services.fetcher import Fetcher, FetchResult
from apps.crawler.services.frontier_manager import FrontierManager
from apps.crawler.services.normalization import URLNormalizer
from apps.crawler.services.parser import HTMLParser, ParseResult
from apps.crawler.services.renderer import JSRenderer
from apps.crawler.services.robots_parser import RobotsParser
from apps.crawler.services.sitemap_crawler import SitemapCrawler

__all__ = [
    "CrawlerEngine",
    "CrawlResult",
    "Fetcher",
    "FetchResult",
    "FrontierManager",
    "URLNormalizer",
    "HTMLParser",
    "ParseResult",
    "JSRenderer",
    "RobotsParser",
    "SitemapCrawler",
]
