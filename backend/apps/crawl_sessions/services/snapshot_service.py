"""Snapshot construction and retrieval logic.

Provides read access to session snapshots for dashboards,
comparisons, and trend analysis.
"""

from typing import Optional
from django.db.models import Count, Avg, Q

from apps.common import constants
from apps.crawl_sessions.models import (
    CrawlSession,
    Page,
    Link,
    URLClassification,
    SitemapURL,
    StructuredData,
)
from apps.crawler.models import Website


class SnapshotService:
    """Construct and query session-based website snapshots.

    The dashboard reads the latest completed session as the current
    website state. This service provides optimized queries for that.
    """

    @staticmethod
    def get_current_snapshot(website: Website) -> Optional[CrawlSession]:
        """Get the latest completed session (current website state)."""
        return (
            CrawlSession.objects
            .filter(
                website=website,
                status=constants.SESSION_STATUS_COMPLETED,
            )
            .order_by("-started_at")
            .first()
        )

    @staticmethod
    def get_session_overview(session: CrawlSession) -> dict:
        """Get a high-level overview of a crawl session.

        Returns aggregate metrics for dashboard rendering.
        """
        pages = Page.objects.filter(crawl_session=session)

        # Status code distribution
        status_dist = (
            pages
            .values("http_status_code")
            .annotate(count=Count("id"))
            .order_by("http_status_code")
        )

        # Classification distribution
        class_dist = (
            URLClassification.objects
            .filter(crawl_session=session)
            .values("classification")
            .annotate(count=Count("id"))
            .order_by("classification")
        )

        # Link stats
        link_stats = (
            Link.objects
            .filter(crawl_session=session)
            .values("link_type")
            .annotate(count=Count("id"))
        )

        return {
            "session_id": str(session.id),
            "website": session.website.domain,
            "session_type": session.session_type,
            "status": session.status,
            "started_at": session.started_at,
            "finished_at": session.finished_at,
            "duration_seconds": session.duration_seconds,
            "total_urls_discovered": session.total_urls_discovered,
            "total_urls_crawled": session.total_urls_crawled,
            "total_urls_failed": session.total_urls_failed,
            "max_depth_reached": session.max_depth_reached,
            "avg_response_time_ms": session.avg_response_time_ms,
            "status_code_distribution": {
                entry["http_status_code"]: entry["count"]
                for entry in status_dist
            },
            "classification_distribution": {
                entry["classification"]: entry["count"]
                for entry in class_dist
            },
            "link_stats": {
                entry["link_type"]: entry["count"]
                for entry in link_stats
            },
            "error_summary": session.error_summary,
        }

    @staticmethod
    def get_pages_by_status(
        session: CrawlSession,
        status_code: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Get pages filtered by HTTP status code."""
        pages = (
            Page.objects
            .filter(crawl_session=session, http_status_code=status_code)
            .values(
                "url", "title", "http_status_code",
                "crawl_depth", "load_time_ms", "word_count",
            )
            [offset:offset + limit]
        )
        return list(pages)

    @staticmethod
    def get_pages_by_classification(
        session: CrawlSession,
        classification: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Get URLs filtered by classification bucket."""
        classifications = (
            URLClassification.objects
            .filter(crawl_session=session, classification=classification)
            .select_related("page")
            .values("url", "classification", "reason")
            [offset:offset + limit]
        )
        return list(classifications)

    @staticmethod
    def get_sitemap_reconciliation(session: CrawlSession) -> dict:
        """Compare sitemap URLs vs. actually crawled URLs.

        Identifies:
        - Sitemap URLs that were crawled
        - Sitemap URLs that were not crawled (missing)
        - Crawled URLs not in sitemap (orphans)
        """
        sitemap_urls = set(
            SitemapURL.objects
            .filter(crawl_session=session)
            .values_list("page_url", flat=True)
        )

        crawled_urls = set(
            Page.objects
            .filter(crawl_session=session)
            .values_list("url", flat=True)
        )

        in_both = sitemap_urls & crawled_urls
        in_sitemap_only = sitemap_urls - crawled_urls
        in_crawl_only = crawled_urls - sitemap_urls

        return {
            "sitemap_total": len(sitemap_urls),
            "crawled_total": len(crawled_urls),
            "in_both": len(in_both),
            "in_sitemap_only": len(in_sitemap_only),
            "in_crawl_only": len(in_crawl_only),
            "missing_from_crawl": sorted(in_sitemap_only)[:100],
            "orphan_pages": sorted(in_crawl_only)[:100],
        }

    @staticmethod
    def get_structured_data_summary(session: CrawlSession) -> dict:
        """Get structured data summary for a session."""
        schemas = (
            StructuredData.objects
            .filter(page__crawl_session=session)
            .values("schema_type", "is_valid")
            .annotate(count=Count("id"))
        )

        summary: dict[str, dict] = {}
        for entry in schemas:
            st = entry["schema_type"]
            if st not in summary:
                summary[st] = {"total": 0, "valid": 0, "invalid": 0}
            summary[st]["total"] += entry["count"]
            if entry["is_valid"]:
                summary[st]["valid"] += entry["count"]
            else:
                summary[st]["invalid"] += entry["count"]

        return summary

    @staticmethod
    def get_session_history(
        website: Website,
        limit: int = 30,
    ) -> list[dict]:
        """Get recent session history for trend analysis."""
        sessions = (
            CrawlSession.objects
            .filter(
                website=website,
                status=constants.SESSION_STATUS_COMPLETED,
            )
            .order_by("-started_at")
            .values(
                "id", "session_type", "started_at", "finished_at",
                "total_urls_discovered", "total_urls_crawled",
                "total_urls_failed", "avg_response_time_ms",
            )
            [:limit]
        )
        return list(sessions)
