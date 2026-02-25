"""URL Frontier Manager – Priority Queue System.

Acts as the brain of the crawler, managing which URLs to crawl and when.
Implements Section 5 (URL Frontier) and Section 4 (Priority-Aware Frontier
Management) from the specs.

The Frontier uses a priority-based queue (heapq) with BFS traversal,
deduplication via URL hashing, and depth-aware scheduling.
"""

import heapq
import time
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

from apps.common import constants
from apps.common.helpers import compute_url_hash
from apps.common.logging import frontier_logger, log_discovery_event
from apps.common.exceptions import (
    MaxDepthExceededError,
    MaxURLsExceededError,
    DuplicateURLError,
    LoopDetectedError,
)


@dataclass(order=True)
class FrontierEntry:
    """A single entry in the URL Frontier priority queue.

    Lower priority_score = higher priority (heapq is a min-heap).
    We negate the priority so that higher-value items come first.
    """
    priority_score: float
    timestamp: float = field(compare=False)
    url: str = field(compare=False)
    depth: int = field(compare=False)
    source: str = field(compare=False)
    parent_url: str = field(compare=False, default="")

    @property
    def url_hash(self) -> str:
        return compute_url_hash(self.url)


class FrontierManager:
    """Priority-aware URL Frontier with BFS support.

    Key Functions (from spec):
    - Maintain queue of pending URLs
    - Prevent duplicate crawling via deduplication hashes
    - Track crawl depth and assign priorities
    - Support re-crawling logic for updated content

    Priority Ranking (High to Low):
    1. Sitemap Entries (1.0)
    2. Home & Navigation (0.9)
    3. Recent Updates (0.8)
    4. High-Link Hubs (0.7)
    5. Content Pages (0.5)
    6. Parameters/Filters (0.2)
    """

    def __init__(
        self,
        max_depth: int = constants.DEFAULT_MAX_DEPTH,
        max_urls: int = constants.DEFAULT_MAX_URLS_PER_SESSION,
    ):
        self._queue: list[FrontierEntry] = []
        self._seen: set[str] = set()            # URL hashes of discovered URLs
        self._crawled: set[str] = set()          # URL hashes of crawled URLs
        self._failed: set[str] = set()           # URL hashes of failed URLs

        self.max_depth = max_depth
        self.max_urls = max_urls

        # Loop detection: track URL pattern frequencies
        self._pattern_counts: dict[str, int] = defaultdict(int)
        self._loop_threshold = 50  # Max URLs from same pattern

        # Metrics
        self.total_discovered = 0
        self.total_crawled = 0

    @property
    def size(self) -> int:
        """Number of URLs currently waiting in the queue."""
        return len(self._queue)

    @property
    def is_empty(self) -> bool:
        return self.size == 0

    @property
    def total_seen(self) -> int:
        return len(self._seen)

    def add(
        self,
        url: str,
        depth: int,
        source: str = constants.SOURCE_LINK,
        priority: Optional[float] = None,
        parent_url: str = "",
    ) -> bool:
        """Add a URL to the frontier with priority scoring.

        Returns True if the URL was added, False if it was a duplicate
        or exceeded limits.
        """
        url_hash = compute_url_hash(url)

        # ── Deduplication Check ────────────────────────────────
        if url_hash in self._seen:
            return False

        # ── Depth Limit Check ──────────────────────────────────
        if depth > self.max_depth:
            frontier_logger.debug(
                "Depth limit exceeded for %s (depth=%d, max=%d)",
                url, depth, self.max_depth,
            )
            return False

        # ── URL Cap Check ──────────────────────────────────────
        if self.total_discovered >= self.max_urls:
            frontier_logger.warning(
                "URL cap reached (%d). Rejecting: %s",
                self.max_urls, url,
            )
            return False

        # ── Loop Detection ─────────────────────────────────────
        pattern = self._extract_url_pattern(url)
        self._pattern_counts[pattern] += 1
        if self._pattern_counts[pattern] > self._loop_threshold:
            frontier_logger.warning(
                "Loop detected for pattern '%s'. Skipping: %s",
                pattern, url,
            )
            return False

        # ── Calculate Priority ─────────────────────────────────
        if priority is None:
            priority = self._calculate_priority(url, depth, source)

        # Negate for min-heap (higher priority = lower score)
        entry = FrontierEntry(
            priority_score=-priority,
            timestamp=time.time(),
            url=url,
            depth=depth,
            source=source,
            parent_url=parent_url,
        )

        heapq.heappush(self._queue, entry)
        self._seen.add(url_hash)
        self.total_discovered += 1

        return True

    def add_batch(
        self,
        urls: list[dict],
    ) -> int:
        """Add multiple URLs to the frontier at once.

        Each dict should have: url, depth, source, and optionally priority.
        Returns the number of URLs successfully added.
        """
        added = 0
        for item in urls:
            success = self.add(
                url=item["url"],
                depth=item.get("depth", 0),
                source=item.get("source", constants.SOURCE_LINK),
                priority=item.get("priority"),
                parent_url=item.get("parent_url", ""),
            )
            if success:
                added += 1

        if added > 0:
            log_discovery_event(added)

        return added

    def pop(self) -> Optional[FrontierEntry]:
        """Pop the highest-priority URL from the frontier.

        Returns None if the queue is empty.
        """
        while self._queue:
            entry = heapq.heappop(self._queue)
            url_hash = compute_url_hash(entry.url)

            # Skip if already crawled (could happen with re-adds)
            if url_hash in self._crawled:
                continue

            return entry
        return None

    def mark_crawled(self, url: str):
        """Mark a URL as successfully crawled."""
        url_hash = compute_url_hash(url)
        self._crawled.add(url_hash)
        self.total_crawled += 1

    def mark_failed(self, url: str):
        """Mark a URL as failed (fetch error, timeout, etc.)."""
        url_hash = compute_url_hash(url)
        self._failed.add(url_hash)

    def is_seen(self, url: str) -> bool:
        """Check if a URL has been seen (discovered) already."""
        return compute_url_hash(url) in self._seen

    def is_crawled(self, url: str) -> bool:
        """Check if a URL has been successfully crawled."""
        return compute_url_hash(url) in self._crawled

    def get_metrics(self) -> dict:
        """Return current frontier operational metrics."""
        return {
            "total_discovered": self.total_discovered,
            "total_crawled": self.total_crawled,
            "total_failed": len(self._failed),
            "queue_size": self.size,
            "unique_patterns": len(self._pattern_counts),
        }

    def _calculate_priority(
        self, url: str, depth: int, source: str,
    ) -> float:
        """Calculate priority score based on source and depth.

        Priority Ranking (from Crawling Strategies spec):
        1. Sitemap Entries (1.0)
        2. Home & Navigation (0.9)
        3. Recent Updates (0.8)
        4. High-Link Hubs (0.7)
        5. Content Pages (0.5)
        6. Parameters/Filters (0.2)
        """
        # Base priority from source type
        source_priorities = {
            constants.SOURCE_SITEMAP: constants.PRIORITY_SITEMAP,
            constants.SOURCE_SEED: constants.PRIORITY_HOME_NAVIGATION,
            constants.SOURCE_CANONICAL: constants.PRIORITY_CONTENT_PAGE,
            constants.SOURCE_REDIRECT: constants.PRIORITY_CONTENT_PAGE,
            constants.SOURCE_LINK: constants.PRIORITY_CONTENT_PAGE,
            constants.SOURCE_MANUAL: constants.PRIORITY_HOME_NAVIGATION,
        }
        base_priority = source_priorities.get(source, constants.PRIORITY_CONTENT_PAGE)

        # Depth penalty: deeper pages get lower priority
        depth_penalty = depth * 0.05

        # Query parameter penalty
        if "?" in url:
            base_priority = min(base_priority, constants.PRIORITY_PARAMETER_FILTER)

        # Home page boost
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path or path in ("index.html", "index.php"):
            base_priority = max(base_priority, constants.PRIORITY_HOME_NAVIGATION)

        return max(0.0, base_priority - depth_penalty)

    @staticmethod
    def _extract_url_pattern(url: str) -> str:
        """Extract a URL pattern for loop detection.

        Replaces numeric segments with {N} to detect
        repetitive pagination patterns like:
        /products?page=1, /products?page=2, ...
        """
        from urllib.parse import urlparse
        import re

        parsed = urlparse(url)
        path = re.sub(r"/\d+", "/{N}", parsed.path)
        if parsed.query:
            # Replace numeric query values
            query = re.sub(r"=\d+", "={N}", parsed.query)
            return f"{path}?{query}"
        return path
