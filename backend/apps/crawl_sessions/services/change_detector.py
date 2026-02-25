"""Change Detection between crawl snapshots.

Compares page hashes between sessions to identify modified,
added, and removed pages. Powers incremental crawling strategy
as defined in Crawling Strategies Section 3.2.
"""

from dataclasses import dataclass, field
from typing import Optional

from apps.common.logging import session_logger
from apps.crawl_sessions.models import CrawlSession, Page


@dataclass
class ChangeReport:
    """Report of changes between two crawl sessions."""
    current_session_id: str = ""
    previous_session_id: str = ""
    new_urls: list[str] = field(default_factory=list)
    removed_urls: list[str] = field(default_factory=list)
    modified_urls: list[str] = field(default_factory=list)
    unchanged_urls: list[str] = field(default_factory=list)

    @property
    def total_new(self) -> int:
        return len(self.new_urls)

    @property
    def total_removed(self) -> int:
        return len(self.removed_urls)

    @property
    def total_modified(self) -> int:
        return len(self.modified_urls)

    @property
    def total_unchanged(self) -> int:
        return len(self.unchanged_urls)

    @property
    def has_changes(self) -> bool:
        return bool(self.new_urls or self.removed_urls or self.modified_urls)

    def summary(self) -> dict:
        return {
            "new": self.total_new,
            "removed": self.total_removed,
            "modified": self.total_modified,
            "unchanged": self.total_unchanged,
        }


class ChangeDetector:
    """Detect changes between two crawl sessions using page hashes.

    Implements the Change Detection Strategy from the Database Design doc:
    Compare page_hash between current and previous sessions to:
    - Detect modified pages
    - Find new URLs
    - Identify removed URLs
    - Report on unchanged content
    """

    @staticmethod
    def compare_sessions(
        current_session: CrawlSession,
        previous_session: CrawlSession,
    ) -> ChangeReport:
        """Compare two crawl sessions and generate a change report.

        Args:
            current_session: The latest crawl session
            previous_session: The earlier session to compare against

        Returns:
            ChangeReport with categorized URL changes
        """
        report = ChangeReport(
            current_session_id=str(current_session.id),
            previous_session_id=str(previous_session.id),
        )

        # Get page data from both sessions
        current_pages = {
            page.url: page.page_hash
            for page in Page.objects.filter(
                crawl_session=current_session,
            ).only("url", "page_hash")
        }

        previous_pages = {
            page.url: page.page_hash
            for page in Page.objects.filter(
                crawl_session=previous_session,
            ).only("url", "page_hash")
        }

        current_urls = set(current_pages.keys())
        previous_urls = set(previous_pages.keys())

        # ── New URLs (in current but not previous) ─────────────
        report.new_urls = sorted(current_urls - previous_urls)

        # ── Removed URLs (in previous but not current) ─────────
        report.removed_urls = sorted(previous_urls - current_urls)

        # ── Modified vs Unchanged (in both sessions) ───────────
        common_urls = current_urls & previous_urls
        for url in sorted(common_urls):
            if current_pages[url] != previous_pages[url]:
                report.modified_urls.append(url)
            else:
                report.unchanged_urls.append(url)

        session_logger.info(
            "Change detection complete: %s", report.summary(),
        )

        return report

    @staticmethod
    def get_urls_needing_recrawl(
        report: ChangeReport,
    ) -> list[str]:
        """Get URLs that should be recrawled in an incremental crawl.

        Prioritizes:
        1. Modified URLs (content changed)
        2. New URLs (recently discovered)
        3. Removed URLs are excluded (they no longer exist)
        """
        return report.modified_urls + report.new_urls

    @staticmethod
    def calculate_change_rate(report: ChangeReport) -> float:
        """Calculate the percentage of URLs that changed.

        Used to determine if a full recrawl or incremental is optimal.
        Per the Crawling Strategies spec, incremental crawling
        reduces redundant crawls by 70-90%.
        """
        total = (
            report.total_new + report.total_removed
            + report.total_modified + report.total_unchanged
        )
        if total == 0:
            return 0.0

        changed = report.total_new + report.total_removed + report.total_modified
        return round((changed / total) * 100, 2)
