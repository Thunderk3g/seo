"""
Crawl Session snapshot architecture.

Models:
  - CrawlSession: Central container for each crawl execution
  - Page: Per-URL crawl intelligence within a session
  - Link: Internal & external link graph
  - URLClassification: GSC-style coverage buckets
  - SitemapURL: URLs discovered from sitemap files
  - StructuredData: Detected schema/JSON-LD data

All models are scoped to a CrawlSession to enable snapshot-based
historical analysis as per the Database Design specification.
"""

from django.db import models
from apps.common.mixins import UUIDPrimaryKeyMixin, TimestampMixin
from apps.common import constants


class CrawlSession(UUIDPrimaryKeyMixin, TimestampMixin):
    """Central container for every crawl execution and snapshot.

    One Crawl = One Session = One Complete Snapshot of Website State.
    Dashboard reads the latest completed session as current website state.
    """
    website = models.ForeignKey(
        "crawler.Website",
        on_delete=models.CASCADE,
        related_name="crawl_sessions",
        db_index=True,
    )
    session_type = models.CharField(
        max_length=20,
        choices=constants.SESSION_TYPE_CHOICES,
        default=constants.SESSION_TYPE_SCHEDULED,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=constants.SESSION_STATUS_CHOICES,
        default=constants.SESSION_STATUS_PENDING,
        db_index=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # ── Crawl Metrics ──────────────────────────────────────────
    total_urls_discovered = models.PositiveIntegerField(default=0)
    total_urls_crawled = models.PositiveIntegerField(default=0)
    total_urls_failed = models.PositiveIntegerField(default=0)
    total_urls_skipped = models.PositiveIntegerField(default=0)

    # ── Coverage Metrics ───────────────────────────────────────
    total_urls_queued = models.PositiveIntegerField(default=0)
    total_urls_rendered = models.PositiveIntegerField(default=0)
    total_index_eligible = models.PositiveIntegerField(default=0)
    total_excluded = models.PositiveIntegerField(default=0)
    exclusion_breakdown = models.JSONField(
        default=dict,
        blank=True,
        help_text="Count of excluded URLs by lifecycle state",
    )

    # ── Operational Metadata ───────────────────────────────────
    max_depth_reached = models.PositiveIntegerField(default=0)
    avg_response_time_ms = models.FloatField(default=0.0)
    error_summary = models.JSONField(
        default=dict,
        blank=True,
        help_text="Summary of errors: {error_type: count}",
    )

    # ── Optional: target URL for URL inspection sessions ──────
    target_url = models.URLField(
        max_length=2048,
        blank=True,
        default="",
        help_text="Target URL for url_inspection sessions",
    )
    # ── Optional: target path prefix for sectional crawls ─────
    target_path_prefix = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Path prefix for sectional crawls (e.g. /blog/)",
    )

    class Meta:
        db_table = "crawl_sessions"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["website", "status"]),
            models.Index(fields=["website", "session_type", "-started_at"]),
        ]

    def __str__(self):
        return f"Session {str(self.id)[:8]} [{self.session_type}] – {self.status}"

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class Page(UUIDPrimaryKeyMixin):
    """Per-URL crawl intelligence within a session.

    Stores all signals extracted from a single page fetch:
    HTTP status, metadata, content hash, timing, etc.
    Unique constraint: (crawl_session, url) – same URL can
    exist across sessions for historical tracking.
    """
    crawl_session = models.ForeignKey(
        CrawlSession,
        on_delete=models.CASCADE,
        related_name="pages",
        db_index=True,
    )
    url = models.URLField(max_length=2048, db_index=True)
    normalized_url = models.URLField(max_length=2048, blank=True, default="")

    # ── GSC Lifecycle State ────────────────────────────────────
    url_lifecycle_state = models.CharField(
        max_length=40,
        choices=constants.LIFECYCLE_STATE_CHOICES,
        default=constants.LIFECYCLE_STATE_DISCOVERED,
        db_index=True,
    )

    # ── Response Signals ───────────────────────────────────────
    http_status_code = models.PositiveSmallIntegerField(
        null=True, blank=True,
    )
    final_url = models.URLField(
        max_length=2048, blank=True, default="",
        help_text="Destination URL after all redirects",
    )
    redirect_chain = models.JSONField(
        default=list, blank=True,
        help_text="Ordered list of redirect hops",
    )

    # ── Content Signals ────────────────────────────────────────
    title = models.CharField(max_length=1000, blank=True, default="")
    meta_description = models.TextField(blank=True, default="")
    h1 = models.TextField(blank=True, default="")
    h2_list = models.JSONField(default=list, blank=True)
    h3_list = models.JSONField(default=list, blank=True)
    canonical_url = models.URLField(max_length=2048, blank=True, default="")
    canonical_resolved = models.URLField(
        max_length=2048, blank=True, default="",
        help_text="The true canonical resolved by the crawler",
    )
    canonical_match = models.BooleanField(
        default=True,
        help_text="Does declared match resolved canonical?",
    )
    robots_meta = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Robots meta tag directives (e.g. noindex, nofollow)",
    )

    # ── Performance & Size ─────────────────────────────────────
    crawl_depth = models.PositiveSmallIntegerField(default=0)
    load_time_ms = models.FloatField(null=True, blank=True)
    content_size_bytes = models.PositiveIntegerField(default=0)
    word_count = models.PositiveIntegerField(default=0)

    # ── Security & Protocol ────────────────────────────────────
    is_https = models.BooleanField(default=False)

    # ── Change Detection ───────────────────────────────────────
    page_hash = models.CharField(
        max_length=64, blank=True, default="",
        help_text="SHA-256 hash of page content for change detection",
    )

    # ── Discovery Metadata ─────────────────────────────────────
    source = models.CharField(
        max_length=20,
        choices=constants.SOURCE_CHOICES,
        default=constants.SOURCE_LINK,
    )
    discovery_source_first = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Where this URL was initially discovered",
    )
    discovery_sources_all = models.JSONField(
        default=list, blank=True,
        help_text="All methods by which this URL was discovered",
    )
    directory_segment = models.CharField(
        max_length=200, blank=True, default="",
        db_index=True, help_text="Top-level subfolder path",
    )
    page_template = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Identified page layout or framework template",
    )
    crawl_timestamp = models.DateTimeField(auto_now_add=True)

    # ── Images ─────────────────────────────────────────────────
    total_images = models.PositiveIntegerField(default=0)
    images_without_alt = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "pages"
        constraints = [
            models.UniqueConstraint(
                fields=["crawl_session", "url"],
                name="unique_session_url",
            ),
        ]
        indexes = [
            models.Index(fields=["crawl_session", "http_status_code"]),
            models.Index(fields=["crawl_session", "crawl_depth"]),
        ]

    def __str__(self):
        return f"[{self.http_status_code}] {self.url}"


class Link(UUIDPrimaryKeyMixin):
    """Internal & external link graph within a crawl session.

    Stores source→target relationships with type classification,
    anchor text, and rel attributes.
    """
    crawl_session = models.ForeignKey(
        CrawlSession,
        on_delete=models.CASCADE,
        related_name="links",
        db_index=True,
    )
    source_url = models.URLField(max_length=2048)
    target_url = models.URLField(max_length=2048, db_index=True)
    link_type = models.CharField(
        max_length=20,
        choices=constants.LINK_TYPE_CHOICES,
        default=constants.LINK_TYPE_INTERNAL,
    )
    anchor_text = models.TextField(blank=True, default="")
    rel_attributes = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Rel attribute values (nofollow, sponsored, ugc, etc.)",
    )
    is_navigation = models.BooleanField(
        default=False,
        help_text="Whether this link is part of site navigation",
    )

    class Meta:
        db_table = "links"
        indexes = [
            models.Index(fields=["crawl_session", "link_type"]),
            models.Index(fields=["crawl_session", "source_url"]),
        ]

    def __str__(self):
        return f"{self.source_url} → {self.target_url} [{self.link_type}]"


class URLClassification(UUIDPrimaryKeyMixin):
    """GSC-style coverage bucket classification per URL per session.

    Derived from crawl signals to categorize each URL into
    indexing/coverage states.
    """
    crawl_session = models.ForeignKey(
        CrawlSession,
        on_delete=models.CASCADE,
        related_name="url_classifications",
        db_index=True,
    )
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name="classifications",
        null=True,
        blank=True,
    )
    url = models.URLField(max_length=2048, db_index=True)
    classification = models.CharField(
        max_length=40,
        choices=constants.CLASSIFICATION_CHOICES,
        db_index=True,
    )
    reason = models.TextField(
        blank=True, default="",
        help_text="Human-readable explanation for this classification",
    )
    classified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "url_classifications"
        constraints = [
            models.UniqueConstraint(
                fields=["crawl_session", "url"],
                name="unique_classification_session_url",
            ),
        ]

    def __str__(self):
        return f"{self.url} → {self.classification}"


class SitemapURL(UUIDPrimaryKeyMixin):
    """URLs discovered from sitemap XML files.

    Used for sitemap vs. crawl reconciliation, missing pages
    detection, and orphan URL identification.
    """
    crawl_session = models.ForeignKey(
        CrawlSession,
        on_delete=models.CASCADE,
        related_name="sitemap_urls",
        db_index=True,
    )
    sitemap_source = models.URLField(
        max_length=2048,
        help_text="The sitemap file URL this was found in",
    )
    page_url = models.URLField(max_length=2048, db_index=True)
    lastmod = models.DateTimeField(null=True, blank=True)
    changefreq = models.CharField(max_length=20, blank=True, default="")
    priority = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "sitemap_urls"
        indexes = [
            models.Index(fields=["crawl_session", "page_url"]),
        ]

    def __str__(self):
        return f"Sitemap: {self.page_url}"


class StructuredData(UUIDPrimaryKeyMixin):
    """Detected structured data (JSON-LD, Schema.org) per page.

    Powers enhancement panels for breadcrumb validity, review
    snippets, and unprocessable structured data warnings.
    """
    page = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name="structured_data",
    )
    schema_type = models.CharField(
        max_length=100,
        help_text="Detected schema type (e.g. FAQ, Product, Article)",
    )
    raw_json = models.JSONField(
        default=dict, blank=True,
        help_text="Raw JSON-LD data block",
    )
    is_valid = models.BooleanField(default=True)
    validation_state = models.CharField(
        max_length=20,
        choices=constants.VALIDATION_STATE_CHOICES,
        default=constants.VALIDATION_STATE_VALID,
    )
    validation_errors = models.JSONField(
        default=list, blank=True,
        help_text="List of missing/invalid schema properties",
    )
    error_message = models.TextField(blank=True, default="")
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "structured_data"

    def __str__(self):
        return f"{self.schema_type} on {self.page.url}"


class CrawlEvent(UUIDPrimaryKeyMixin):
    """Lightweight per-session activity feed entry.

    Powers the Dashboard "Live activity" widget. Written from the engine's
    log helpers (apps.common.logging) when they are passed a session_id.
    Capped at 5,000 rows per session via a post-crawl cleanup task.
    """

    KIND_CRAWL = "crawl"
    KIND_DISCOVERY = "discovery"
    KIND_SKIP = "skip"
    KIND_ERROR = "error"
    KIND_BLOCKED = "blocked"
    KIND_REDIRECT = "redirect"
    KIND_SESSION = "session"

    KIND_CHOICES = [
        (KIND_CRAWL, "Crawled"),
        (KIND_DISCOVERY, "Discovery"),
        (KIND_SKIP, "Skipped"),
        (KIND_ERROR, "Error"),
        (KIND_BLOCKED, "Blocked"),
        (KIND_REDIRECT, "Redirect"),
        (KIND_SESSION, "Session"),
    ]

    crawl_session = models.ForeignKey(
        CrawlSession,
        on_delete=models.CASCADE,
        related_name="events",
        db_index=True,
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        db_index=True,
    )
    url = models.CharField(
        max_length=2048, blank=True, default="",
        help_text="Target URL for the event (empty for session-level events)",
    )
    message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "crawl_events"
        indexes = [
            models.Index(fields=["crawl_session", "-timestamp"]),
        ]
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.kind}] {self.url or self.message}"


class ExportRecord(UUIDPrimaryKeyMixin):
    """Generated export artifact for a crawl session.

    Stores file content directly in a TextField for v1 (small files —
    sites cap at 50k URLs, ~10MB worst case). Future: stream to disk and
    track via filepath. The `kind` enumeration matches the design's
    Exports page card grid.
    """
    KIND_URLS_CSV = "urls.csv"
    KIND_ISSUES_XLSX = "issues.xlsx"
    KIND_SITEMAP_XML = "sitemap.xml"
    KIND_BROKEN_LINKS_CSV = "broken-links.csv"
    KIND_REDIRECTS_CSV = "redirects.csv"
    KIND_METADATA_JSON = "metadata.json"
    KIND_CHOICES = [
        (KIND_URLS_CSV, "URLs (CSV)"),
        (KIND_ISSUES_XLSX, "Issues (CSV)"),  # see note below
        (KIND_SITEMAP_XML, "Sitemap (XML)"),
        (KIND_BROKEN_LINKS_CSV, "Broken Links (CSV)"),
        (KIND_REDIRECTS_CSV, "Redirects (CSV)"),
        (KIND_METADATA_JSON, "Metadata (JSON)"),
    ]

    crawl_session = models.ForeignKey(
        CrawlSession,
        on_delete=models.CASCADE,
        related_name="exports",
        db_index=True,
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, db_index=True)
    content = models.TextField(blank=True, default="")
    content_type = models.CharField(max_length=100, blank=True, default="")
    filename = models.CharField(max_length=255, blank=True, default="")
    row_count = models.PositiveIntegerField(default=0)
    size_bytes = models.PositiveIntegerField(default=0)
    generated_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "export_records"
        indexes = [models.Index(fields=["crawl_session", "-generated_at"])]
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.kind} for session {str(self.crawl_session_id)[:8]}"

