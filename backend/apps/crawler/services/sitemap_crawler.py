"""Sitemap Crawling System.

Implements Section 7 (Sitemap Crawling System) of the Web Crawler Engine spec:
- Supported types: sitemap.xml, sitemap_index.xml, Image/Video sitemaps
- Data points: loc, lastmod, changefreq, priority
- Recursive crawling of child sitemaps in index files
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from apps.common.logging import discovery_logger
from apps.common.exceptions import SitemapParseError


@dataclass
class SitemapEntry:
    """A single URL entry discovered from a sitemap."""
    url: str
    lastmod: Optional[datetime] = None
    changefreq: str = ""
    priority: Optional[float] = None
    sitemap_source: str = ""


@dataclass
class SitemapResult:
    """Result of processing one or more sitemaps."""
    entries: list[SitemapEntry] = field(default_factory=list)
    child_sitemaps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_sitemaps_processed: int = 0


class SitemapCrawler:
    """Parse and extract URLs from XML sitemaps.

    Supports standard sitemaps, sitemap index files (recursive),
    and extracts loc, lastmod, changefreq, and priority data.
    """

    # XML namespaces for sitemap parsing
    SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

    def __init__(self, fetcher=None):
        """Initialize with an optional async fetcher.

        Args:
            fetcher: An instance of the Fetcher service for downloading sitemaps
        """
        self.fetcher = fetcher

    def parse_sitemap_xml(
        self, xml_content: str, sitemap_url: str = "",
    ) -> SitemapResult:
        """Parse a sitemap XML string.

        Auto-detects whether the XML is a sitemap index or a
        standard urlset sitemap.
        """
        result = SitemapResult()

        if not xml_content or not xml_content.strip():
            result.errors.append(f"Empty sitemap content from {sitemap_url}")
            return result

        try:
            root = ET.fromstring(xml_content.strip())
        except ET.ParseError as exc:
            result.errors.append(f"XML parse error in {sitemap_url}: {exc}")
            return result

        root_tag = root.tag.lower()

        # Detect type: sitemapindex vs urlset
        if "sitemapindex" in root_tag:
            result = self._parse_sitemap_index(root, sitemap_url)
        elif "urlset" in root_tag:
            result = self._parse_urlset(root, sitemap_url)
        else:
            result.errors.append(
                f"Unknown root element '{root.tag}' in {sitemap_url}"
            )

        result.total_sitemaps_processed = 1

        discovery_logger.info(
            "Parsed sitemap %s: %d URLs, %d child sitemaps",
            sitemap_url, len(result.entries), len(result.child_sitemaps),
        )

        return result

    def _parse_urlset(
        self, root: ET.Element, sitemap_url: str,
    ) -> SitemapResult:
        """Parse a standard <urlset> sitemap."""
        result = SitemapResult()
        ns = self.SITEMAP_NS

        for url_elem in root.findall(f"{ns}url"):
            loc_elem = url_elem.find(f"{ns}loc")
            if loc_elem is None or not loc_elem.text:
                continue

            entry = SitemapEntry(
                url=loc_elem.text.strip(),
                sitemap_source=sitemap_url,
            )

            # lastmod
            lastmod_elem = url_elem.find(f"{ns}lastmod")
            if lastmod_elem is not None and lastmod_elem.text:
                entry.lastmod = self._parse_date(lastmod_elem.text.strip())

            # changefreq
            changefreq_elem = url_elem.find(f"{ns}changefreq")
            if changefreq_elem is not None and changefreq_elem.text:
                entry.changefreq = changefreq_elem.text.strip()

            # priority
            priority_elem = url_elem.find(f"{ns}priority")
            if priority_elem is not None and priority_elem.text:
                try:
                    entry.priority = float(priority_elem.text.strip())
                except ValueError:
                    pass

            result.entries.append(entry)

        return result

    def _parse_sitemap_index(
        self, root: ET.Element, sitemap_url: str,
    ) -> SitemapResult:
        """Parse a <sitemapindex> file and collect child sitemap URLs."""
        result = SitemapResult()
        ns = self.SITEMAP_NS

        for sitemap_elem in root.findall(f"{ns}sitemap"):
            loc_elem = sitemap_elem.find(f"{ns}loc")
            if loc_elem is not None and loc_elem.text:
                result.child_sitemaps.append(loc_elem.text.strip())

        return result

    async def crawl_sitemaps(
        self,
        sitemap_urls: list[str],
        max_sitemaps: int = 100,
    ) -> SitemapResult:
        """Recursively crawl sitemap URLs, including sitemap indexes.

        Fetches each sitemap, parses it, and if it is a sitemap index,
        recursively processes child sitemaps up to max_sitemaps.
        """
        if not self.fetcher:
            raise SitemapParseError("Fetcher not provided for sitemap crawling")

        combined = SitemapResult()
        pending = list(sitemap_urls)
        processed: set[str] = set()

        while pending and combined.total_sitemaps_processed < max_sitemaps:
            url = pending.pop(0)

            if url in processed:
                continue
            processed.add(url)

            try:
                xml_content = await self.fetcher.fetch_sitemap(url)
                if not xml_content:
                    combined.errors.append(f"Failed to fetch: {url}")
                    continue

                result = self.parse_sitemap_xml(xml_content, url)
                combined.entries.extend(result.entries)
                combined.errors.extend(result.errors)
                combined.total_sitemaps_processed += result.total_sitemaps_processed

                # Queue child sitemaps for processing
                for child in result.child_sitemaps:
                    if child not in processed:
                        pending.append(child)

            except Exception as exc:
                combined.errors.append(f"Error processing {url}: {exc}")

        discovery_logger.info(
            "Sitemap crawl complete: %d total URLs from %d sitemaps",
            len(combined.entries), combined.total_sitemaps_processed,
        )

        return combined

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Parse lastmod date from common formats."""
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%Y-%m-%dT%H:%M:%S.%f%z",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
