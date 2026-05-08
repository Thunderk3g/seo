"""API views for the crawler and crawl session subsystems.

Thin views that delegate logic to the services layer.
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime

from apps.crawler.models import Website
from apps.crawl_sessions.models import (
    CrawlSession, CrawlEvent, ExportRecord, Page, Link, URLClassification,
)
from apps.crawl_sessions.services.snapshot_service import SnapshotService
from apps.crawl_sessions.services.issue_service import IssueService
from apps.crawl_sessions.services.analytics_service import AnalyticsService
from apps.crawl_sessions.services.tree_service import TreeService
from apps.crawl_sessions.services.export_service import ExportService
from apps.crawl_sessions.services.overview_service import OverviewService
from apps.crawler.services.settings_service import SettingsService
from apps.crawler.serializers import (
    WebsiteSerializer,
    WebsiteCreateSerializer,
    CrawlSessionListSerializer,
    CrawlSessionDetailSerializer,
    PageListSerializer,
    PageDetailSerializer,
    LinkSerializer,
    URLClassificationSerializer,
    CrawlEventSerializer,
    StartCrawlSerializer,
    URLInspectionSerializer,
)


# Per-page cap for the /pages/ endpoint cursor pagination.
_PAGES_PAGE_SIZE = 50

# Allowed ?ordering= columns for /pages/ — anything else is silently ignored.
_PAGES_ORDERING_WHITELIST = {
    "url", "-url", "title", "-title", "http_status_code", "-http_status_code",
    "crawl_depth", "-crawl_depth", "load_time_ms", "-load_time_ms",
    "word_count", "-word_count", "crawl_timestamp", "-crawl_timestamp",
}


class _PagesPagination(PageNumberPagination):
    page_size = _PAGES_PAGE_SIZE
    page_size_query_param = "page_size"
    max_page_size = 200


# Maps the ?content_type= query param to a URL-extension predicate (Q object).
# Mirrors the design's tabs (All / HTML / Images / 4xx / 3xx / 5xx) — the
# status-class tabs are handled separately via ?status_class=.
_HTML_EXTS = (".html", ".htm", ".php", ".aspx", ".jsp")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico")


def _filter_pages_by_content_type(qs, content_type: str):
    """Return pages whose URL path matches a coarse content type bucket.

    Uses URL extension as a heuristic since Page has no content_type column
    (matches IssueService._is_html_page semantics).
    """
    ct = content_type.lower().strip()
    if ct in {"", "all"}:
        return qs
    if ct == "html":
        # HTML = no extension OR extension in HTML set. Practical filter: NOT
        # one of the asset extensions. Implemented via NOT(suffix matches asset).
        asset_q = Q()
        for ext in _IMAGE_EXTS + (".css", ".js", ".pdf", ".xml", ".txt",
                                  ".json", ".woff", ".woff2", ".ttf"):
            asset_q |= Q(url__iendswith=ext)
        return qs.exclude(asset_q)
    if ct == "image":
        image_q = Q()
        for ext in _IMAGE_EXTS:
            image_q |= Q(url__iendswith=ext)
        return qs.filter(image_q)
    if ct == "css":
        return qs.filter(url__iendswith=".css")
    if ct == "js":
        return qs.filter(url__iendswith=".js")
    return qs


def _filter_pages_by_status_class(qs, status_class: str):
    """Filter pages by HTTP status class (2xx / 3xx / 4xx / 5xx)."""
    sc = status_class.lower().strip()
    if sc == "2xx":
        return qs.filter(http_status_code__gte=200, http_status_code__lt=300)
    if sc == "3xx":
        return qs.filter(http_status_code__gte=300, http_status_code__lt=400)
    if sc == "4xx":
        return qs.filter(http_status_code__gte=400, http_status_code__lt=500)
    if sc == "5xx":
        return qs.filter(http_status_code__gte=500, http_status_code__lt=600)
    return qs
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

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        """Cancel a running or pending crawl session."""
        from apps.crawl_sessions.services.session_manager import SessionManager

        session = self.get_object()
        cancelled = SessionManager.cancel_session(session)
        if not cancelled:
            return Response(
                {"detail": f"Session is already {session.status} and cannot be cancelled."},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = CrawlSessionDetailSerializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="pages")
    def pages(self, request, pk=None):
        """List pages in this session with filtering, search, sort, and pagination.

        Query params:
            status_code     int          exact HTTP status filter (legacy)
            depth           int          exact crawl-depth filter (legacy)
            status_class    str          one of: 2xx, 3xx, 4xx, 5xx
            content_type    str          one of: all, html, image, css, js
            q               str          ILIKE search across url + title
            ordering        str          column from PAGES_ORDERING_WHITELIST
            page            int          1-indexed page number
            page_size       int          rows per page (max 200)
        """
        session = self.get_object()
        params = request.query_params

        pages = Page.objects.filter(crawl_session=session)

        # Legacy exact filters (kept for backward compatibility).
        if params.get("status_code"):
            try:
                pages = pages.filter(http_status_code=int(params["status_code"]))
            except (TypeError, ValueError):
                pass
        if params.get("depth"):
            try:
                pages = pages.filter(crawl_depth=int(params["depth"]))
            except (TypeError, ValueError):
                pass

        # New: status class (2xx/3xx/4xx/5xx) — matches the design's tabs.
        if params.get("status_class"):
            pages = _filter_pages_by_status_class(pages, params["status_class"])

        # New: content-type bucket (html/image/css/js) — extension heuristic.
        if params.get("content_type"):
            pages = _filter_pages_by_content_type(pages, params["content_type"])

        # New: free-text search across url + title (ILIKE).
        q = (params.get("q") or "").strip()
        if q:
            pages = pages.filter(Q(url__icontains=q) | Q(title__icontains=q))

        # New: ordering — whitelist guards against arbitrary column injection.
        ordering = params.get("ordering")
        if ordering and ordering in _PAGES_ORDERING_WHITELIST:
            pages = pages.order_by(ordering, "url")
        else:
            pages = pages.order_by("crawl_depth", "url")

        paginator = _PagesPagination()
        page = paginator.paginate_queryset(pages, request, view=self)
        serializer = PageListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @action(detail=True, methods=["get"], url_path="activity")
    def activity(self, request, pk=None):
        """Activity-feed entries for the dashboard live panel.

        Merges persisted CrawlEvent rows (session lifecycle) with synthesized
        per-URL events derived from the Page table.

        KNOWN LIMITATION (phase 2.5 follow-up): per-URL events only appear
        once the session completes, because Pages are bulk-created at end of
        crawl by SessionManager.persist_crawl_results. The 1.5s polling that
        spec §5.4.1 calls for therefore returns mostly empty results during
        the running window — only lifecycle events ("Crawl started") show up
        live. To deliver the full spec UX, the engine needs a periodic event
        flush via sync_to_async (tracked separately).

        Query params:
            since   ISO-8601 timestamp; only return entries after this point
            limit   max rows to return (default 100, capped at 500)
        """
        session = self.get_object()
        since_raw = request.query_params.get("since")
        since = parse_datetime(since_raw) if since_raw else None
        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (TypeError, ValueError):
            limit = 100

        # 1) Persisted CrawlEvent rows.
        event_qs = CrawlEvent.objects.filter(crawl_session=session)
        if since:
            event_qs = event_qs.filter(timestamp__gt=since)
        events = list(event_qs.order_by("-timestamp")[:limit])
        event_payload = CrawlEventSerializer(events, many=True).data

        # 2) Synthesized per-URL "crawl" events from Page rows.
        page_qs = Page.objects.filter(crawl_session=session).only(
            "url", "http_status_code", "crawl_depth", "load_time_ms",
            "crawl_timestamp",
        )
        if since:
            page_qs = page_qs.filter(crawl_timestamp__gt=since)
        page_qs = page_qs.order_by("-crawl_timestamp")[:limit]

        # ISO-8601 strings on both sides — required for the merge sort below.
        # CrawlEventSerializer's ModelSerializer auto-converts DateTimeField to
        # ISO string. We do the same here on the synthesized side. Comparing a
        # datetime against a str raises TypeError in Python 3, and ISO 8601
        # strings sort lexicographically the same as their datetime values.
        synthesized = [
            {
                "id": f"page-{p.id}",
                "timestamp": p.crawl_timestamp.isoformat() if p.crawl_timestamp else "",
                "kind": (
                    CrawlEvent.KIND_ERROR
                    if p.http_status_code and p.http_status_code >= 400
                    else CrawlEvent.KIND_REDIRECT
                    if p.http_status_code and 300 <= p.http_status_code < 400
                    else CrawlEvent.KIND_CRAWL
                ),
                "url": p.url,
                "message": (
                    f"{p.http_status_code or '—'} {p.url}"
                ),
                "metadata": {
                    "status_code": p.http_status_code,
                    "depth": p.crawl_depth,
                    "load_time_ms": p.load_time_ms,
                },
            }
            for p in page_qs
        ]

        # Merge and sort DESC by timestamp; cap at limit.
        merged = sorted(
            list(event_payload) + synthesized,
            key=lambda e: e["timestamp"] or "",
            reverse=True,
        )[:limit]
        return Response(merged)

    @action(detail=True, methods=["get"], url_path="issues")
    def issues(self, request, pk=None):
        """Return the 12-category issue summary for this session."""
        session = self.get_object()
        return Response(IssueService.derive_issues(session))

    @action(
        detail=True,
        methods=["get"],
        url_path=r"issues/(?P<issue_id>[a-z0-9-]+)",
    )
    def issue_detail(self, request, pk=None, issue_id=None):
        """Return detail for one issue, including affected URLs."""
        session = self.get_object()
        try:
            limit = int(request.query_params.get("limit", 200))
        except (TypeError, ValueError):
            limit = 200
        try:
            payload = IssueService.get_issue_detail(session, issue_id, limit=limit)
        except ValueError:
            return Response(
                {"detail": f"Unknown issue id: {issue_id!r}."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(payload)

    @action(detail=True, methods=["get"], url_path="analytics")
    def analytics(self, request, pk=None):
        """Return the four chart datasets for the analytics page."""
        session = self.get_object()
        return Response(AnalyticsService.get_chart_data(session))

    @action(detail=True, methods=["get"], url_path="overview")
    def overview(self, request, pk=None):
        """Return the Dashboard snapshot (KPIs + health + system metrics)."""
        session = self.get_object()
        return Response(OverviewService.get_overview(session))

    @action(detail=True, methods=["get"], url_path="tree")
    def tree(self, request, pk=None):
        """Folder-hierarchy site tree for the Visualizations page.

        Powers the Site tree + Treemap tabs and the Dashboard's
        "Site structure" mini panel. Optional ``max_depth`` query param
        (default 4, clamped to 1..10).
        """
        session = self.get_object()
        try:
            max_depth = int(request.query_params.get("max_depth", 4))
        except (TypeError, ValueError):
            max_depth = 4
        max_depth = max(1, min(max_depth, 10))
        return Response(TreeService.build_tree(session, max_depth=max_depth))

    @action(detail=True, methods=["get"], url_path="exports")
    def exports(self, request, pk=None):
        """List previously generated export artifacts for this session."""
        session = self.get_object()
        return Response(ExportService.list_exports(session))

    @action(
        detail=True,
        methods=["post"],
        url_path=r"exports/(?P<kind>[a-z0-9.-]+)",
    )
    def create_export(self, request, pk=None, kind=None):
        """Generate a new export of the given kind."""
        session = self.get_object()
        try:
            record = ExportService.create_export(session, kind)
        except ValueError:
            return Response(
                {"detail": f"Unknown export kind: {kind!r}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "id": str(record.id),
                "kind": record.kind,
                "filename": record.filename,
                "content_type": record.content_type,
                "row_count": record.row_count,
                "size_bytes": record.size_bytes,
                "generated_at": record.generated_at,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path=r"exports/(?P<export_id>[0-9a-f-]+)/download",
    )
    def download_export(self, request, pk=None, export_id=None):
        """Stream the export body with attachment headers.

        Uses :meth:`ExportRecord.body` so binary kinds (xlsx) come from
        the ``content_bytes`` column while text kinds (csv/xml/json)
        come from the ``content`` TextField — the caller never sees the
        split.
        """
        session = self.get_object()
        try:
            record = ExportService.get_export(session, export_id)
        except ExportRecord.DoesNotExist:
            return Response(
                {"detail": "Export not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        response = HttpResponse(record.body(), content_type=record.content_type)
        response["Content-Disposition"] = (
            f'attachment; filename="{record.filename}"'
        )
        return response

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


# ─────────────────────────────────────────────────────────────
# Settings endpoint — keyed by ?website=<uuid> rather than a path PK so
# the topbar's "active site" toggle maps to one URL. Spec §5.4.8.
# ─────────────────────────────────────────────────────────────

@api_view(["GET", "PATCH"])
def settings_view(request):
    """GET / PATCH /api/v1/settings/?website=<uuid>.

    Thin wrapper around SettingsService:
      * 400 if ?website= is missing or not a UUID.
      * 404 if the website doesn't exist.
      * 400 if a PATCH payload fails range/type validation
        (ValueError messages from the service flow through verbatim).
    """
    website_id = request.query_params.get("website")
    if not website_id:
        return Response(
            {"detail": "Query parameter 'website' is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        website = get_object_or_404(Website, pk=website_id)
    except (ValueError, ValidationError):
        # Non-UUID strings raise ValidationError on Postgres / ValueError
        # elsewhere — both mean "malformed id" → 400, not 500.
        return Response(
            {"detail": f"Invalid website id: {website_id!r}."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if request.method == "GET":
        return Response(SettingsService.get_settings(website))

    try:
        updated = SettingsService.update_settings(website, request.data or {})
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(updated)
