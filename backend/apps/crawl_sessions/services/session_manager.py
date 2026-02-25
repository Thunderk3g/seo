"""Session creation and management service.

Manages the lifecycle of crawl sessions:
- Session creation (scheduled, on-demand, URL inspection)
- Session status transitions
- Persisting crawl results into the database
- Metrics update on session completion
"""

from typing import Optional
from django.utils import timezone
from django.db import transaction

from apps.common import constants
from apps.common.logging import log_session_event
from apps.common.exceptions import SessionNotFoundError
from apps.crawl_sessions.models import (
    CrawlSession,
    Page,
    Link,
    URLClassification,
    SitemapURL,
    StructuredData,
)
from apps.crawler.models import Website, CrawlConfig


class SessionManager:
    """Manage the lifecycle of crawl sessions.

    Handles creation, status transitions, result persistence,
    and metric aggregation for crawl sessions.
    """

    @staticmethod
    def create_session(
        website: Website,
        session_type: str = constants.SESSION_TYPE_SCHEDULED,
        target_url: str = "",
        target_path_prefix: str = "",
    ) -> CrawlSession:
        """Create a new crawl session for a website.

        Args:
            website: The Website to crawl
            session_type: scheduled / on_demand / url_inspection
            target_url: Optional target URL for url_inspection sessions
            target_path_prefix: Optional path prefix for sectional crawls
        """
        session = CrawlSession.objects.create(
            website=website,
            session_type=session_type,
            status=constants.SESSION_STATUS_PENDING,
            target_url=target_url,
            target_path_prefix=target_path_prefix,
        )

        log_session_event(
            str(session.id),
            "CREATED",
            f"Type: {session_type} | Website: {website.domain}",
        )

        return session

    @staticmethod
    def start_session(session: CrawlSession) -> CrawlSession:
        """Transition a session to running state."""
        session.status = constants.SESSION_STATUS_RUNNING
        session.started_at = timezone.now()
        session.save(update_fields=["status", "started_at", "updated_at"])

        log_session_event(str(session.id), "STARTED")
        return session

    @staticmethod
    def complete_session(session: CrawlSession) -> CrawlSession:
        """Mark a session as completed."""
        session.status = constants.SESSION_STATUS_COMPLETED
        session.finished_at = timezone.now()
        session.save(update_fields=["status", "finished_at", "updated_at"])

        log_session_event(
            str(session.id), "COMPLETED",
            f"Duration: {session.duration_seconds:.1f}s" if session.duration_seconds else "",
        )
        return session

    @staticmethod
    def fail_session(session: CrawlSession, error: str = "") -> CrawlSession:
        """Mark a session as failed."""
        session.status = constants.SESSION_STATUS_FAILED
        session.finished_at = timezone.now()
        session.save(update_fields=["status", "finished_at", "updated_at"])

        log_session_event(str(session.id), "FAILED", error)
        return session

    @staticmethod
    def cancel_session(session: CrawlSession) -> CrawlSession:
        """Cancel a running session."""
        session.status = constants.SESSION_STATUS_CANCELLED
        session.finished_at = timezone.now()
        session.save(update_fields=["status", "finished_at", "updated_at"])

        log_session_event(str(session.id), "CANCELLED")
        return session

    @staticmethod
    @transaction.atomic
    def persist_crawl_results(session: CrawlSession, crawl_result) -> None:
        """Persist all crawl results into the database.

        Bulk creates Pages, Links, Classifications, SitemapURLs,
        and StructuredData within a single database transaction.
        """
        log_session_event(
            str(session.id), "PERSISTING",
            f"Pages: {crawl_result.total_pages} | Links: {crawl_result.total_links}",
        )

        # ── Persist Pages ──────────────────────────────────────
        page_objects = []
        page_url_map: dict[str, Page] = {}

        for page_data in crawl_result.pages:
            page = Page(
                crawl_session=session,
                url=page_data["url"],
                normalized_url=page_data.get("normalized_url", page_data["url"]),
                http_status_code=page_data.get("http_status_code"),
                final_url=page_data.get("final_url", ""),
                redirect_chain=page_data.get("redirect_chain", []),
                title=page_data.get("title", ""),
                meta_description=page_data.get("meta_description", ""),
                h1=page_data.get("h1", ""),
                h2_list=page_data.get("h2_list", []),
                h3_list=page_data.get("h3_list", []),
                canonical_url=page_data.get("canonical_url", ""),
                robots_meta=page_data.get("robots_meta", ""),
                crawl_depth=page_data.get("crawl_depth", 0),
                load_time_ms=page_data.get("load_time_ms"),
                content_size_bytes=page_data.get("content_size_bytes", 0),
                word_count=page_data.get("word_count", 0),
                is_https=page_data.get("is_https", False),
                page_hash=page_data.get("page_hash", ""),
                source=page_data.get("source", constants.SOURCE_LINK),
                total_images=page_data.get("total_images", 0),
                images_without_alt=page_data.get("images_without_alt", 0),
            )
            page_objects.append(page)

        created_pages = Page.objects.bulk_create(
            page_objects, ignore_conflicts=True,
        )

        # Build URL → Page ID map for relationships
        for page in Page.objects.filter(crawl_session=session):
            page_url_map[page.url] = page

        # ── Persist Links ──────────────────────────────────────
        link_objects = [
            Link(
                crawl_session=session,
                source_url=link_data["source_url"],
                target_url=link_data["target_url"],
                link_type=link_data.get("link_type", constants.LINK_TYPE_INTERNAL),
                anchor_text=link_data.get("anchor_text", ""),
                rel_attributes=link_data.get("rel_attributes", ""),
                is_navigation=link_data.get("is_navigation", False),
            )
            for link_data in crawl_result.links
        ]
        Link.objects.bulk_create(link_objects, batch_size=5000)

        # ── Persist Classifications ────────────────────────────
        classification_objects = [
            URLClassification(
                crawl_session=session,
                page=page_url_map.get(cls_data["url"]),
                url=cls_data["url"],
                classification=cls_data["classification"],
                reason=cls_data.get("reason", ""),
            )
            for cls_data in crawl_result.classifications
        ]
        URLClassification.objects.bulk_create(
            classification_objects, ignore_conflicts=True,
        )

        # ── Persist Sitemap URLs ───────────────────────────────
        sitemap_objects = [
            SitemapURL(
                crawl_session=session,
                sitemap_source=entry["sitemap_source"],
                page_url=entry["page_url"],
                lastmod=entry.get("lastmod"),
                changefreq=entry.get("changefreq", ""),
                priority=entry.get("priority"),
            )
            for entry in crawl_result.sitemap_entries
        ]
        SitemapURL.objects.bulk_create(sitemap_objects, batch_size=5000)

        # ── Persist Structured Data ────────────────────────────
        schema_objects = []
        for sd_data in crawl_result.structured_data:
            page = page_url_map.get(sd_data.get("page_url", ""))
            if page:
                schema_objects.append(
                    StructuredData(
                        page=page,
                        schema_type=sd_data["schema_type"],
                        raw_json=sd_data.get("raw_json", {}),
                        is_valid=sd_data.get("is_valid", True),
                        error_message=sd_data.get("error_message", ""),
                    )
                )
        StructuredData.objects.bulk_create(schema_objects, batch_size=1000)

        # ── Update Session Metrics ─────────────────────────────
        metrics = crawl_result.metrics
        session.total_urls_discovered = metrics.get("total_urls_discovered", 0)
        session.total_urls_crawled = metrics.get("total_urls_crawled", 0)
        session.total_urls_failed = metrics.get("total_urls_failed", 0)
        session.max_depth_reached = metrics.get("max_depth_reached", 0)
        session.avg_response_time_ms = metrics.get("avg_response_time_ms", 0.0)
        session.error_summary = metrics.get("error_summary", {})
        session.save(update_fields=[
            "total_urls_discovered", "total_urls_crawled",
            "total_urls_failed", "max_depth_reached",
            "avg_response_time_ms", "error_summary", "updated_at",
        ])

        log_session_event(str(session.id), "PERSISTED")

    @staticmethod
    def get_latest_session(
        website: Website,
        session_type: Optional[str] = None,
    ) -> Optional[CrawlSession]:
        """Get the latest completed crawl session for a website."""
        qs = CrawlSession.objects.filter(
            website=website,
            status=constants.SESSION_STATUS_COMPLETED,
        )
        if session_type:
            qs = qs.filter(session_type=session_type)
        return qs.order_by("-started_at").first()

    @staticmethod
    def get_session_by_id(session_id: str) -> CrawlSession:
        """Retrieve a crawl session by its UUID."""
        try:
            return CrawlSession.objects.get(id=session_id)
        except CrawlSession.DoesNotExist:
            raise SessionNotFoundError(
                f"Session {session_id} not found", url="",
            )
