"""Crawler persistence — Phase 3 introduces Postgres tables.

Until Phase 3 the crawler stored everything as append-only CSVs under
``settings.CRAWLER_DATA_DIR`` (with a checkpointed ``crawl_state.json``).
That model worked for the v1 vertical slice but blocks:

  * Trend tracking (every run overwrites the file).
  * Page Explorer-class sortable / filterable queries beyond ~10k rows.
  * Joining crawl data to GSC + SEMrush + audit findings at write time.
  * Compare Crawls (snapshot diff).
  * The Health Score historical chart in Phase 5.

This module introduces three tables to unblock all of the above without
disturbing the legacy CSV path (kept as the operator-facing export
format and as the durable write-ahead log).

Schema rules:

  * UUID PKs so snapshot IDs are URL-safe and don't leak ordering.
  * Typed columns for fields we filter / sort on in the UI.
  * ``extra`` JSONB column for additive fields (future audit columns,
    Phase 6 GEO signals) — avoids a migration per new field.
  * Composite indexes on the access patterns the Page Explorer uses.

Data flow after Phase 3c lands:

    legacy engine.py
        ├─ writes CSV (unchanged — durable WAL)
        └─ writes CrawlerPageResult row (dual-write pipeline)

  Scrapy bajaj_spider (Phase 3d)
        ├─ writes CrawlerPageResult row via PostgresPipeline
        ├─ writes CSV via CsvExportPipeline (for legacy reports)
        └─ writes JSONL event via JsonlEventPipeline (for log shipping)

Reads:
  * Page Explorer / Health Score swap CSV → ORM when
    ``CRAWLER_ENGINE=scrapy``.
  * Audit runner (apps/crawler/audits/runner.py) iterates either CSV
    or ORM based on the same flag.
"""
from __future__ import annotations

import uuid

from django.db import models


class CrawlSnapshot(models.Model):
    """One end-to-end crawl run.

    Created at the start of every crawl (legacy or Scrapy). The
    ``finished_at`` timestamp marks completion; partial crawls show
    ``status='running'`` with a NULL finished_at. Health Score history
    in Phase 5 reads ``health_score`` off this table once-daily.
    """

    class Engine(models.TextChoices):
        LEGACY = "legacy", "Legacy BFS engine"
        SCRAPY = "scrapy", "Scrapy spider"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"
        STOPPED = "stopped", "Stopped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    engine = models.CharField(
        max_length=16, choices=Engine.choices, default=Engine.LEGACY,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.RUNNING,
    )
    seed_url = models.URLField(max_length=2048, blank=True, default="")
    allowed_domains = models.JSONField(default=list, blank=True)
    pages_attempted = models.IntegerField(default=0)
    pages_ok = models.IntegerField(default=0)
    pages_errored = models.IntegerField(default=0)
    health_score = models.IntegerField(null=True, blank=True)
    health_tier = models.CharField(max_length=16, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    # Free-form metadata captured at run start so we can replay the run
    # config later (workers, throttle, sitemap discovery toggle, etc.).
    config_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-started_at",)
        indexes = [
            models.Index(fields=["-started_at"]),
            models.Index(fields=["status", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.engine}@{self.started_at.isoformat() if self.started_at else 'pending'}"


class CrawlerPageResult(models.Model):
    """One URL per snapshot.

    Mirrors the columns from ``crawl_results.csv`` 1:1 plus an ``extra``
    JSONB for additive future fields (Phase 6 GEO signals like
    citation density, AI-bot hits per URL, etc.). Use this table for
    all Page Explorer + Health Score reads once Phase 3c flips the
    flag.

    Indexes cover the access patterns observed in production:
      * Listing all rows for a snapshot.
      * Filtering by status_code, subdomain, page_type, indexed_status.
      * Sorting by word_count, response_time_ms, pagespeed_score.
      * Substring search on URL + title (GIN index added in 3c).
    """

    class IndexedStatus(models.TextChoices):
        INDEXED = "indexed", "Indexed"
        NOT_INDEXED = "not_indexed", "Not indexed"
        EXCLUDED = "excluded", "Excluded"
        UNKNOWN = "unknown", "Unknown"

    id = models.BigAutoField(primary_key=True)
    snapshot = models.ForeignKey(
        CrawlSnapshot, on_delete=models.CASCADE, related_name="pages",
    )
    # Per-row identity
    url = models.URLField(max_length=2048)
    final_url = models.URLField(max_length=2048, blank=True, default="")
    # HTTP layer
    status_code = models.CharField(max_length=4, blank=True, default="")
    status = models.CharField(max_length=64, blank=True, default="")
    content_type = models.CharField(max_length=128, blank=True, default="")
    response_time_ms = models.IntegerField(default=0)
    # Content
    title = models.CharField(max_length=1024, blank=True, default="")
    word_count = models.IntegerField(default=0)
    # Error metadata
    error_type = models.CharField(max_length=64, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    # Enrichment (the five columns csv_writer auto-stamps)
    subdomain = models.CharField(max_length=64, blank=True, default="")
    page_type = models.CharField(max_length=64, blank=True, default="")
    category_key = models.CharField(max_length=128, blank=True, default="")
    from_sitemap = models.BooleanField(default=False)
    indexed_status = models.CharField(
        max_length=16,
        choices=IndexedStatus.choices,
        default=IndexedStatus.UNKNOWN,
    )
    # PSI / Core Web Vitals (mobile strategy by default; populated by
    # the PSI scheduler — see engine/psi_scheduler.py + psi_capture.py).
    pagespeed_score = models.IntegerField(null=True, blank=True)
    lcp_ms = models.IntegerField(null=True, blank=True)
    cls = models.FloatField(null=True, blank=True)
    inp_ms = models.IntegerField(null=True, blank=True)
    # JS rendering (Phase 3e: filled when Playwright re-renders a page
    # because its static fetch returned < 500 chars of body text)
    static_word_count = models.IntegerField(null=True, blank=True)
    rendered_word_count = models.IntegerField(null=True, blank=True)
    playwright_used = models.BooleanField(default=False)
    # Free-form bag for additive future fields without a migration
    extra = models.JSONField(default=dict, blank=True)
    # Bookkeeping
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "url"], name="uniq_pageresult_snapshot_url",
            ),
        ]
        indexes = [
            models.Index(fields=["snapshot", "status_code"]),
            models.Index(fields=["snapshot", "subdomain"]),
            models.Index(fields=["snapshot", "page_type"]),
            models.Index(fields=["snapshot", "indexed_status"]),
            models.Index(fields=["snapshot", "-word_count"]),
            models.Index(fields=["snapshot", "-response_time_ms"]),
            # For "all rows by URL across history" lookups (Compare
            # Crawls). Without this the snapshot-diff query is slow.
            models.Index(fields=["url", "-fetched_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.status_code} {self.url}"


class CrawlIssue(models.Model):
    """One (snapshot × url × issue_type) row.

    Populated by the audit runner after each crawl (Phase 1 detectors +
    Phase 4 expansion). Phase 1 today recomputes the audit on every
    request; this table caches the result keyed by snapshot so /issues
    queries become O(rows) instead of O(detectors × rows).

    ``payload`` carries any per-occurrence extras the detector wants to
    persist (e.g., duplicate-title group hash, redirect chain length).
    """

    class Severity(models.TextChoices):
        ERROR = "error", "Error"
        WARNING = "warning", "Warning"
        NOTICE = "notice", "Notice"

    id = models.BigAutoField(primary_key=True)
    snapshot = models.ForeignKey(
        CrawlSnapshot, on_delete=models.CASCADE, related_name="issues",
    )
    page = models.ForeignKey(
        CrawlerPageResult,
        on_delete=models.CASCADE,
        related_name="issues",
        null=True,
        blank=True,
    )
    # Denormalised URL (snapshotted alongside) so we can render issues
    # without a join — page FK is for drill-in only.
    url = models.URLField(max_length=2048)
    # Catalogue slug (matches audits/catalog.py IssueDef.slug)
    issue_slug = models.CharField(max_length=64)
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.WARNING,
    )
    category = models.CharField(max_length=32, blank=True, default="")
    title = models.CharField(max_length=255, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["snapshot", "issue_slug"]),
            models.Index(fields=["snapshot", "severity"]),
            models.Index(fields=["snapshot", "category"]),
            models.Index(fields=["url", "-detected_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.severity}: {self.issue_slug} on {self.url}"


class MetricSnapshot(models.Model):
    """Daily Health Score + per-category counters snapshot.

    Phase 5a. Populated by ``services.snapshot_runner.take_snapshot``
    which runs nightly via Celery beat (and on demand via the
    management command ``snapshot_metrics``). One row per
    (date × engine) so the trends UI can show the Health Score
    trajectory over 30 / 90 days.

    Storage choice: own table, not piggybacking on CrawlSnapshot,
    because CrawlSnapshot fires on every crawl (potentially many per
    day during testing) and we want a stable daily heartbeat for the
    chart. MetricSnapshot writes once per day even if zero crawls
    ran — read-only re-computes the Health Score from the most-recent
    CrawlSnapshot's data.

    Trend chart contract: the frontend pulls 30/90/365-day windows
    by ordering by recorded_date desc and reverses for left-to-right
    display.
    """

    id = models.BigAutoField(primary_key=True)
    recorded_date = models.DateField(db_index=True)
    # Engine label matches CrawlSnapshot.Engine — lets us track legacy
    # and scrapy trajectories independently during the 30-day overlap.
    engine = models.CharField(max_length=16, default="legacy")
    # Headline Health Score for the day.
    health_score = models.IntegerField(null=True, blank=True)
    health_tier = models.CharField(max_length=16, blank=True, default="")
    # Crawl totals so the chart can show pages-attempted alongside score
    # (a falling score with rising attempted is more meaningful than
    # just the score number alone).
    pages_attempted = models.IntegerField(default=0)
    pages_ok = models.IntegerField(default=0)
    pages_errored = models.IntegerField(default=0)
    # Severity counts (distinct issue TYPES firing, not raw URL counts).
    # Per-category breakdown stays in `category_counts`.
    errors = models.IntegerField(default=0)
    warnings = models.IntegerField(default=0)
    notices = models.IntegerField(default=0)
    # Per-issue-type counts as { slug: affected_url_count }. Big enough
    # to power deep drill-ins ("show me how 'duplicate_title' moved over
    # time") without an extra table.
    issue_counts = models.JSONField(default=dict, blank=True)
    # Per-category counts as { category: distinct_issue_type_count }.
    # Same shape the Health Score endpoint already returns.
    category_counts = models.JSONField(default=dict, blank=True)
    # PageRank + near-duplicate summary numbers for the day, so the
    # trend chart can plot non-Health-Score metrics on a second axis.
    pagerank_node_count = models.IntegerField(default=0)
    pagerank_orphan_count = models.IntegerField(default=0)
    near_dup_cluster_count = models.IntegerField(default=0)
    near_dup_total_dupes = models.IntegerField(default=0)
    # Bookkeeping
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-recorded_date",)
        constraints = [
            models.UniqueConstraint(
                fields=["recorded_date", "engine"],
                name="uniq_metricsnapshot_date_engine",
            ),
        ]
        indexes = [
            models.Index(fields=["-recorded_date"]),
            models.Index(fields=["engine", "-recorded_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.recorded_date} {self.engine} score={self.health_score}"
