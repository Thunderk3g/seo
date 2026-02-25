"""Shared helper functions for the SEO Intelligence Platform."""

import hashlib
import re
import time
from typing import Optional
from urllib.parse import urlparse


def compute_content_hash(content: str) -> str:
    """Generate a SHA-256 hash of page content for change detection.

    Used to compare page states between crawl sessions without
    storing full content in memory.
    """
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def compute_url_hash(url: str) -> str:
    """Generate an MD5 hash of a normalized URL for deduplication.

    MD5 is sufficient here as we're not using it for security,
    only for fast set-membership checks.
    """
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def extract_domain(url: str) -> str:
    """Extract the registered domain from a full URL.

    Examples:
        https://www.example.com/page → example.com
        https://blog.example.co.uk/  → example.co.uk
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    # Strip www. prefix
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname.lower()


def is_same_domain(url: str, base_domain: str) -> bool:
    """Check if a URL belongs to the same domain (including subdomains)."""
    url_domain = extract_domain(url)
    base = base_domain.lower().lstrip("www.")
    return url_domain == base or url_domain.endswith(f".{base}")


def get_url_depth(url: str) -> int:
    """Calculate the directory depth of a URL path.

    Examples:
        /          → 0
        /about     → 1
        /blog/post → 2
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return 0
    return len(path.split("/"))


def word_count(text: str) -> int:
    """Count meaningful words in extracted text content."""
    if not text:
        return 0
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def content_size_bytes(content: str) -> int:
    """Return the byte size of HTML/text content."""
    return len(content.encode("utf-8", errors="replace"))


def truncate(text: str, max_length: int = 500) -> str:
    """Safely truncate text to a maximum character length."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def is_valid_http_url(url: str) -> bool:
    """Check if the URL is a valid HTTP/HTTPS URL."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def retry_with_backoff(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
):
    """Decorator for retrying a function with exponential backoff.

    Usage:
        @retry_with_backoff(max_retries=3, backoff_factor=2.0)
        async def fetch_page(url):
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception: Optional[Exception] = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if attempt < max_retries:
                        time.sleep(delay)
                        delay *= backoff_factor
            raise last_exception  # type: ignore[misc]
        return wrapper
    return decorator
