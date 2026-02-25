"""Metadata Extractor – Derive page-level intelligence.

Converts raw ParseResult data into structured page metadata
suitable for storage in the Page model.
"""

from dataclasses import dataclass
from typing import Optional

from apps.crawler.services.parser import ParseResult


@dataclass
class PageMetadata:
    """Structured metadata extracted from a parsed page."""
    title: str = ""
    meta_description: str = ""
    h1: str = ""
    h2_list: list[str] = None
    h3_list: list[str] = None
    canonical_url: str = ""
    robots_meta: str = ""
    word_count: int = 0
    content_size_bytes: int = 0
    page_hash: str = ""
    total_images: int = 0
    images_without_alt: int = 0
    lang: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""

    # Derived signals
    is_noindex: bool = False
    is_nofollow: bool = False
    has_canonical: bool = False
    is_thin_content: bool = False  # word_count < 200

    def __post_init__(self):
        if self.h2_list is None:
            self.h2_list = []
        if self.h3_list is None:
            self.h3_list = []


class MetadataExtractor:
    """Extract and derive page metadata from ParseResult.

    Converts parser output into a PageMetadata object with
    additional derived signals for classification.
    """

    THIN_CONTENT_THRESHOLD = 200  # words

    def extract(self, parse_result: ParseResult) -> PageMetadata:
        """Extract PageMetadata from a ParseResult.

        Also derives additional boolean signals like is_noindex,
        is_nofollow, has_canonical, and is_thin_content.
        """
        robots = parse_result.robots_meta.lower()

        metadata = PageMetadata(
            title=parse_result.title,
            meta_description=parse_result.meta_description,
            h1=parse_result.h1,
            h2_list=parse_result.h2_list,
            h3_list=parse_result.h3_list,
            canonical_url=parse_result.canonical_url,
            robots_meta=parse_result.robots_meta,
            word_count=parse_result.word_count,
            content_size_bytes=parse_result.content_size_bytes,
            page_hash=parse_result.page_hash,
            total_images=parse_result.total_images,
            images_without_alt=parse_result.images_without_alt,
            lang=parse_result.lang,
            og_title=parse_result.og_title,
            og_description=parse_result.og_description,
            og_image=parse_result.og_image,
            is_noindex="noindex" in robots,
            is_nofollow="nofollow" in robots,
            has_canonical=bool(parse_result.canonical_url),
            is_thin_content=parse_result.word_count < self.THIN_CONTENT_THRESHOLD,
        )

        return metadata

    @staticmethod
    def detect_soft_404(
        parse_result: ParseResult,
        status_code: int,
    ) -> bool:
        """Detect soft 404 pages (returns 200 but is actually a not-found page).

        Heuristics:
        - Title contains common 404 indicators
        - Very thin content (< 50 words)
        - H1 contains error-related text
        """
        if status_code != 200:
            return False

        title_lower = parse_result.title.lower()
        h1_lower = parse_result.h1.lower()

        error_indicators = [
            "404", "not found", "page not found",
            "does not exist", "no longer available",
            "error", "oops",
        ]

        for indicator in error_indicators:
            if indicator in title_lower or indicator in h1_lower:
                return True

        # Extremely thin content on a 200 page
        if parse_result.word_count < 50:
            return True

        return False
