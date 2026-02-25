"""Crawler-specific utilities.

Provides convenience functions for common crawler operations
that do not belong in a specific service module.
"""

from typing import Optional
from urllib.parse import urlparse, urljoin


def build_absolute_url(base: str, relative: str) -> str:
    """Convert a relative URL to absolute using the base URL."""
    return urljoin(base, relative)


def extract_path(url: str) -> str:
    """Extract the path component from a URL."""
    return urlparse(url).path


def get_domain_with_scheme(url: str) -> str:
    """Extract scheme + domain from a full URL.

    Example: https://www.example.com/page → https://www.example.com
    """
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def is_pagination_url(url: str) -> bool:
    """Detect common pagination URL patterns.

    Helps with loop detection by identifying URLs that look
    like paginated content.
    """
    path = urlparse(url).path.lower()
    query = urlparse(url).query.lower()

    pagination_patterns = [
        "page=", "p=", "offset=",
        "/page/", "/pages/",
        "start=", "from=",
        "pagenum=", "pg=",
    ]

    for pattern in pagination_patterns:
        if pattern in path or pattern in query:
            return True
    return False


def estimate_crawl_duration(
    total_urls: int,
    concurrency: int,
    avg_delay: float,
) -> float:
    """Estimate crawl duration in seconds based on parameters.

    Simple estimation: (total_urls / concurrency) * avg_delay
    """
    if concurrency <= 0:
        return 0.0
    return (total_urls / concurrency) * avg_delay
