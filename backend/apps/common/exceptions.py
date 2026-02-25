"""Custom exception definitions for the SEO Intelligence Platform."""


class CrawlerException(Exception):
    """Base exception for all crawler-related errors."""

    def __init__(self, message: str = "", url: str = "", **kwargs):
        self.url = url
        self.extra = kwargs
        super().__init__(message)


class FetchError(CrawlerException):
    """Raised when a page fetch fails (timeout, connection error, etc.)."""
    pass


class RobotsBlockedError(CrawlerException):
    """Raised when a URL is blocked by robots.txt rules."""
    pass


class MaxDepthExceededError(CrawlerException):
    """Raised when crawl depth exceeds the configured limit."""
    pass


class MaxURLsExceededError(CrawlerException):
    """Raised when the crawl session hits the maximum URL cap."""
    pass


class CrawlBudgetExhaustedError(CrawlerException):
    """Raised when the crawl budget for this session is fully consumed."""
    pass


class InvalidURLError(CrawlerException):
    """Raised when a URL is malformed or fails normalization."""
    pass


class RenderingError(CrawlerException):
    """Raised when JavaScript rendering fails via Playwright."""
    pass


class SitemapParseError(CrawlerException):
    """Raised when sitemap XML parsing encounters an error."""
    pass


class SessionNotFoundError(CrawlerException):
    """Raised when a crawl session ID does not exist."""
    pass


class DuplicateURLError(CrawlerException):
    """Raised when a URL has already been processed in the current session."""
    pass


class LoopDetectedError(CrawlerException):
    """Raised when an infinite pagination / URL loop is detected."""
    pass
