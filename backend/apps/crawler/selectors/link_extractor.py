"""Link Extraction Engine.

Implements Section 11 (Link Extraction Engine) of the
Web Crawler Engine spec:

- Internal: Navigation, breadcrumbs, content, footer links
- External: Outbound domain tracking and anchor text analysis
- Classification: Tagging as Internal, External, Media, Resource
"""

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from apps.common.constants import (
    LINK_TYPE_INTERNAL,
    LINK_TYPE_EXTERNAL,
    LINK_TYPE_MEDIA,
    LINK_TYPE_RESOURCE,
    RESOURCE_EXTENSIONS,
    MEDIA_EXTENSIONS,
    IGNORED_SCHEMES,
)
from apps.crawler.services.normalization import URLNormalizer


@dataclass
class ExtractedLink:
    """A classified, normalized link extracted from a page."""
    source_url: str
    target_url: str
    link_type: str = LINK_TYPE_INTERNAL
    anchor_text: str = ""
    rel_attributes: str = ""
    is_navigation: bool = False


class LinkExtractor:
    """Classify and filter links extracted by the HTML parser.

    Takes raw links from ParseResult and produces classified
    ExtractedLink objects with proper normalization and type tagging.
    """

    def __init__(self, normalizer: URLNormalizer, include_subdomains: bool = False):
        self.normalizer = normalizer
        self.include_subdomains = include_subdomains

    def extract(
        self,
        raw_links: list[dict],
        source_url: str,
    ) -> list[ExtractedLink]:
        """Process raw links from parser into classified ExtractedLink objects.

        Args:
            raw_links: List of raw link dicts from HTMLParser.parse().raw_links
            source_url: The page URL these links were found on

        Returns:
            List of classified and normalized ExtractedLink objects
        """
        results: list[ExtractedLink] = []
        seen_targets: set[str] = set()

        for raw in raw_links:
            target = raw.get("url", "")
            if not target:
                continue

            # Skip non-HTTP schemes
            if any(target.lower().startswith(s) for s in IGNORED_SCHEMES):
                continue

            # Normalize the target URL
            normalized = self.normalizer.normalize(target, source_url=source_url)
            if not normalized:
                continue

            # Deduplicate within this page
            if normalized in seen_targets:
                continue
            seen_targets.add(normalized)

            # Classify link type
            link_type = self._classify(normalized)

            results.append(ExtractedLink(
                source_url=source_url,
                target_url=normalized,
                link_type=link_type,
                anchor_text=raw.get("anchor_text", ""),
                rel_attributes=raw.get("rel", ""),
                is_navigation=raw.get("is_navigation", False),
            ))

        return results

    def _classify(self, url: str) -> str:
        """Classify a URL as internal, external, media, or resource."""
        parsed = urlparse(url)
        path_lower = parsed.path.lower()

        # Check resource extensions
        for ext in RESOURCE_EXTENSIONS:
            if path_lower.endswith(ext):
                return LINK_TYPE_RESOURCE

        # Check media extensions
        for ext in MEDIA_EXTENSIONS:
            if path_lower.endswith(ext):
                return LINK_TYPE_MEDIA

        # Internal vs external
        if self.normalizer.is_internal(url, self.include_subdomains):
            return LINK_TYPE_INTERNAL

        return LINK_TYPE_EXTERNAL

    def filter_crawlable(self, links: list[ExtractedLink]) -> list[ExtractedLink]:
        """Filter links to only those that should be added to the frontier.

        Only internal HTML page links are crawlable.
        Media, resource, and external links are logged but not recursively crawled.
        """
        return [
            link for link in links
            if link.link_type == LINK_TYPE_INTERNAL
        ]

    @staticmethod
    def get_link_stats(links: list[ExtractedLink]) -> dict:
        """Generate summary statistics for extracted links."""
        stats = {
            "total": len(links),
            "internal": 0,
            "external": 0,
            "media": 0,
            "resource": 0,
            "navigation": 0,
            "nofollow": 0,
        }
        for link in links:
            if link.link_type == LINK_TYPE_INTERNAL:
                stats["internal"] += 1
            elif link.link_type == LINK_TYPE_EXTERNAL:
                stats["external"] += 1
            elif link.link_type == LINK_TYPE_MEDIA:
                stats["media"] += 1
            elif link.link_type == LINK_TYPE_RESOURCE:
                stats["resource"] += 1
            if link.is_navigation:
                stats["navigation"] += 1
            if "nofollow" in link.rel_attributes.lower():
                stats["nofollow"] += 1
        return stats
