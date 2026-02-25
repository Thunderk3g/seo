"""HTML Parser Module – DOM Analysis.

Implements Section 10 (Parser Module) of the Web Crawler Engine spec:
- Metadata: Title, Meta Description, Robots meta directives
- Structure: Headings (H1-H3), Canonical links
- Assets: Images (src/alt), Scripts, CSS files
- Intelligence: Structured data (JSON-LD, Schema) and main textual content
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from apps.common.helpers import word_count, content_size_bytes, compute_content_hash
from apps.common.logging import parse_logger


@dataclass
class ImageInfo:
    """Extracted image data."""
    src: str
    alt: str = ""
    has_alt: bool = False


@dataclass
class AssetInfo:
    """Extracted asset data (scripts, stylesheets, etc.)."""
    url: str
    asset_type: str  # "script", "stylesheet", "font"


@dataclass
class ParseResult:
    """Complete result of parsing a fetched HTML page."""
    # ── Metadata ───────────────────────────────────────────────
    title: str = ""
    meta_description: str = ""
    robots_meta: str = ""
    canonical_url: str = ""

    # ── Headings ───────────────────────────────────────────────
    h1: str = ""
    h2_list: list[str] = field(default_factory=list)
    h3_list: list[str] = field(default_factory=list)

    # ── Content ────────────────────────────────────────────────
    word_count: int = 0
    content_size_bytes: int = 0
    page_hash: str = ""
    main_text: str = ""

    # ── Images ─────────────────────────────────────────────────
    images: list[ImageInfo] = field(default_factory=list)
    total_images: int = 0
    images_without_alt: int = 0

    # ── Assets ─────────────────────────────────────────────────
    scripts: list[str] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)

    # ── Structured Data ────────────────────────────────────────
    json_ld: list[dict] = field(default_factory=list)

    # ── Discovered Links (raw, before normalization) ──────────
    raw_links: list[dict] = field(default_factory=list)

    # ── Pagination ─────────────────────────────────────────────
    pagination_next: str = ""
    pagination_prev: str = ""

    # ── Language / Open Graph ──────────────────────────────────
    lang: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""


class HTMLParser:
    """Extract crawl-relevant elements from fetched HTML.

    Parses both raw HTML and rendered DOM to extract all signals
    required by the crawler engine for storage and classification.
    """

    def __init__(self, base_url: str = ""):
        self.base_url = base_url

    def parse(self, html: str, page_url: str = "") -> ParseResult:
        """Parse HTML content and extract all signals.

        Args:
            html: Raw HTML string
            page_url: The URL this HTML was fetched from (for relative URL resolution)

        Returns:
            ParseResult with all extracted data
        """
        if not html:
            return ParseResult()

        result = ParseResult()
        resolve_base = page_url or self.base_url

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            parse_logger.error("Failed to parse HTML for %s: %s", page_url, exc)
            return result

        # ── Metadata Extraction ────────────────────────────────
        result.title = self._extract_title(soup)
        result.meta_description = self._extract_meta(soup, "description")
        result.robots_meta = self._extract_meta(soup, "robots")
        result.canonical_url = self._extract_canonical(soup, resolve_base)
        result.lang = self._extract_lang(soup)

        # ── Open Graph ─────────────────────────────────────────
        result.og_title = self._extract_og(soup, "og:title")
        result.og_description = self._extract_og(soup, "og:description")
        result.og_image = self._extract_og(soup, "og:image")

        # ── Headings ───────────────────────────────────────────
        result.h1 = self._extract_heading(soup, "h1")
        result.h2_list = self._extract_headings(soup, "h2")
        result.h3_list = self._extract_headings(soup, "h3")

        # ── Content ────────────────────────────────────────────
        result.main_text = self._extract_main_text(soup)
        result.word_count = word_count(result.main_text)
        result.content_size_bytes = content_size_bytes(html)
        result.page_hash = compute_content_hash(html)

        # ── Images ─────────────────────────────────────────────
        result.images = self._extract_images(soup, resolve_base)
        result.total_images = len(result.images)
        result.images_without_alt = sum(1 for img in result.images if not img.has_alt)

        # ── Assets ─────────────────────────────────────────────
        result.scripts = self._extract_scripts(soup, resolve_base)
        result.stylesheets = self._extract_stylesheets(soup, resolve_base)

        # ── Structured Data (JSON-LD) ──────────────────────────
        result.json_ld = self._extract_json_ld(soup)

        # ── Raw Links ──────────────────────────────────────────
        result.raw_links = self._extract_raw_links(soup, resolve_base)

        # ── Pagination ─────────────────────────────────────────
        result.pagination_next = self._extract_rel_link(soup, "next", resolve_base)
        result.pagination_prev = self._extract_rel_link(soup, "prev", resolve_base)

        return result

    # ────────────────────────────────────────────────────────────
    # Private extraction methods
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        tag = soup.find("title")
        return tag.get_text(strip=True) if tag else ""

    @staticmethod
    def _extract_meta(soup: BeautifulSoup, name: str) -> str:
        tag = soup.find("meta", attrs={"name": re.compile(f"^{name}$", re.I)})
        if tag and isinstance(tag, Tag):
            return tag.get("content", "")
        return ""

    @staticmethod
    def _extract_og(soup: BeautifulSoup, property_name: str) -> str:
        tag = soup.find("meta", attrs={"property": property_name})
        if tag and isinstance(tag, Tag):
            return tag.get("content", "")
        return ""

    @staticmethod
    def _extract_canonical(soup: BeautifulSoup, base_url: str) -> str:
        tag = soup.find("link", attrs={"rel": "canonical"})
        if tag and isinstance(tag, Tag):
            href = tag.get("href", "")
            if href:
                return urljoin(base_url, href)
        return ""

    @staticmethod
    def _extract_lang(soup: BeautifulSoup) -> str:
        html_tag = soup.find("html")
        if html_tag and isinstance(html_tag, Tag):
            return html_tag.get("lang", "")
        return ""

    @staticmethod
    def _extract_heading(soup: BeautifulSoup, tag_name: str) -> str:
        tag = soup.find(tag_name)
        return tag.get_text(strip=True) if tag else ""

    @staticmethod
    def _extract_headings(soup: BeautifulSoup, tag_name: str) -> list[str]:
        return [tag.get_text(strip=True) for tag in soup.find_all(tag_name)]

    @staticmethod
    def _extract_main_text(soup: BeautifulSoup) -> str:
        """Extract main textual content, stripping nav/header/footer/script."""
        # Remove template elements
        for tag in soup.find_all(["script", "style", "noscript", "nav", "header", "footer"]):
            tag.decompose()

        # Try to find main content container
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main:
            return main.get_text(separator=" ", strip=True)
        return soup.get_text(separator=" ", strip=True)

    @staticmethod
    def _extract_images(soup: BeautifulSoup, base_url: str) -> list[ImageInfo]:
        images = []
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src:
                src = urljoin(base_url, src)
            alt = img.get("alt", "")
            images.append(ImageInfo(
                src=src,
                alt=alt,
                has_alt=bool(alt and alt.strip()),
            ))
        return images

    @staticmethod
    def _extract_scripts(soup: BeautifulSoup, base_url: str) -> list[str]:
        scripts = []
        for tag in soup.find_all("script", src=True):
            src = tag.get("src", "")
            if src:
                scripts.append(urljoin(base_url, src))
        return scripts

    @staticmethod
    def _extract_stylesheets(soup: BeautifulSoup, base_url: str) -> list[str]:
        sheets = []
        for tag in soup.find_all("link", rel="stylesheet"):
            href = tag.get("href", "")
            if href:
                sheets.append(urljoin(base_url, href))
        return sheets

    @staticmethod
    def _extract_json_ld(soup: BeautifulSoup) -> list[dict]:
        """Extract all JSON-LD structured data blocks."""
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict):
                    results.append(data)
            except (json.JSONDecodeError, TypeError):
                pass
        return results

    @staticmethod
    def _extract_raw_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
        """Extract all anchor links with metadata."""
        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "")
            if not href:
                continue

            absolute_url = urljoin(base_url, href)
            anchor_text = a_tag.get_text(strip=True)
            rel = a_tag.get("rel", [])
            if isinstance(rel, list):
                rel = " ".join(rel)

            # Detect if link is in nav/header/footer
            is_navigation = False
            for parent in a_tag.parents:
                if parent.name in ("nav", "header", "footer"):
                    is_navigation = True
                    break

            links.append({
                "url": absolute_url,
                "anchor_text": anchor_text,
                "rel": rel,
                "is_navigation": is_navigation,
            })

        return links

    @staticmethod
    def _extract_rel_link(soup: BeautifulSoup, rel_value: str, base_url: str) -> str:
        tag = soup.find("link", attrs={"rel": rel_value})
        if tag and isinstance(tag, Tag):
            href = tag.get("href", "")
            if href:
                return urljoin(base_url, href)
        return ""
