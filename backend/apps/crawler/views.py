"""API views for the crawler and crawl session subsystems.

Thin views that delegate logic to the services layer.
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.crawler.models import Website
from apps.crawl_sessions.models import CrawlSession, Page, Link, URLClassification
from apps.crawl_sessions.services.snapshot_service import SnapshotService
from apps.crawler.serializers import (
    WebsiteSerializer,
    WebsiteCreateSerializer,
    CrawlSessionListSerializer,
    CrawlSessionDetailSerializer,
    PageListSerializer,
    PageDetailSerializer,
    LinkSerializer,
    URLClassificationSerializer,
    StartCrawlSerializer,
    URLInspectionSerializer,
)
from apps.crawler.tasks import (
    run_on_demand_crawl,
    run_url_inspection,
    run_change_detection,
)


class WebsiteViewSet(viewsets.ModelViewSet):
    """CRUD operations for monitored websites."""
    queryset = Website.objects.all().select_related("crawl_config")
    serializer_class = WebsiteSerializer

    def get_serializer_class(self):
        if self.action == "create":
            return WebsiteCreateSerializer
        return WebsiteSerializer

    @action(detail=True, methods=["post"], url_path="crawl")
    def trigger_crawl(self, request, pk=None):
        """Trigger an on-demand crawl for this website."""
        website = self.get_object()
        target_path_prefix = request.data.get("target_path_prefix", "")

        task = run_on_demand_crawl.delay(
            website_id=str(website.id),
            target_path_prefix=target_path_prefix,
        )

        return Response(
            {
                "message": f"Crawl started for {website.domain}",
                "task_id": task.id,
                "website_id": str(website.id),
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["post"], url_path="inspect")
    def inspect_url(self, request, pk=None):
        """Trigger a single URL inspection."""
        website = self.get_object()
        serializer = URLInspectionSerializer(data={
            "website_id": str(website.id),
            "target_url": request.data.get("target_url", ""),
        })
        serializer.is_valid(raise_exception=True)

        task = run_url_inspection.delay(
            website_id=str(website.id),
            target_url=serializer.validated_data["target_url"],
        )

        return Response(
            {
                "message": f"URL inspection started",
                "task_id": task.id,
                "target_url": serializer.validated_data["target_url"],
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=["get"], url_path="sessions")
    def list_sessions(self, request, pk=None):
        """List crawl sessions for this website."""
        website = self.get_object()
        sessions = CrawlSession.objects.filter(
            website=website,
        ).order_by("-started_at")[:50]

        serializer = CrawlSessionListSerializer(sessions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="snapshot")
    def current_snapshot(self, request, pk=None):
        """Get the current website snapshot (latest completed session)."""
        website = self.get_object()
        session = SnapshotService.get_current_snapshot(website)

        if not session:
            return Response(
                {"error": "No completed crawl sessions found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        overview = SnapshotService.get_session_overview(session)
        return Response(overview)

    @action(detail=True, methods=["post"], url_path="change-detection")
    def change_detection(self, request, pk=None):
        """Run change detection between the two latest sessions."""
        website = self.get_object()
        task = run_change_detection.delay(website_id=str(website.id))

        return Response(
            {
                "message": "Change detection started",
                "task_id": task.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class CrawlSessionViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to crawl sessions."""
    queryset = CrawlSession.objects.all().select_related("website")
    serializer_class = CrawlSessionListSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CrawlSessionDetailSerializer
        return CrawlSessionListSerializer

    @action(detail=True, methods=["get"], url_path="overview")
    def overview(self, request, pk=None):
        """Get detailed session overview with aggregated metrics."""
        session = self.get_object()
        overview = SnapshotService.get_session_overview(session)
        return Response(overview)

    @action(detail=True, methods=["get"], url_path="pages")
    def pages(self, request, pk=None):
        """List pages in this session with optional filtering."""
        session = self.get_object()
        status_filter = request.query_params.get("status_code")
        depth_filter = request.query_params.get("depth")

        pages = Page.objects.filter(crawl_session=session)

        if status_filter:
            pages = pages.filter(http_status_code=int(status_filter))
        if depth_filter:
            pages = pages.filter(crawl_depth=int(depth_filter))

        pages = pages.order_by("crawl_depth", "url")[:200]
        serializer = PageListSerializer(pages, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="classifications")
    def classifications(self, request, pk=None):
        """Get URL classifications for this session."""
        session = self.get_object()
        classification_filter = request.query_params.get("type")

        qs = URLClassification.objects.filter(crawl_session=session)
        if classification_filter:
            qs = qs.filter(classification=classification_filter)

        qs = qs.order_by("classification", "url")[:200]
        serializer = URLClassificationSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="links")
    def links(self, request, pk=None):
        """Get link graph data for this session."""
        session = self.get_object()
        link_type = request.query_params.get("type")

        qs = Link.objects.filter(crawl_session=session)
        if link_type:
            qs = qs.filter(link_type=link_type)

        qs = qs.order_by("link_type", "source_url")[:500]
        serializer = LinkSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="sitemap-reconciliation")
    def sitemap_reconciliation(self, request, pk=None):
        """Compare sitemap URLs vs crawled URLs."""
        session = self.get_object()
        result = SnapshotService.get_sitemap_reconciliation(session)
        return Response(result)

    @action(detail=True, methods=["get"], url_path="structured-data")
    def structured_data_summary(self, request, pk=None):
        """Get structured data summary for this session."""
        session = self.get_object()
        summary = SnapshotService.get_structured_data_summary(session)
        return Response(summary)


class PageViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only access to individual page records."""
    queryset = Page.objects.all()
    serializer_class = PageDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        session_id = self.request.query_params.get("session_id")
        if session_id:
            qs = qs.filter(crawl_session_id=session_id)
        return qs
