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
        SCRAPY_COMPETITOR = "scrapy_competitor", "Scrapy competitor spider"

    class Kind(models.TextChoices):
        BAJAJ = "bajaj", "Bajaj (own site)"
        COMPETITOR = "competitor", "Competitor"

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETE = "complete", "Complete"
        FAILED = "failed", "Failed"
        STOPPED = "stopped", "Stopped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    engine = models.CharField(
        max_length=24, choices=Engine.choices, default=Engine.LEGACY,
    )
    kind = models.CharField(
        max_length=16, choices=Kind.choices, default=Kind.BAJAJ,
        help_text="bajaj for own-site crawls; competitor for rival domains.",
    )
    target_domain = models.CharField(
        max_length=255, blank=True, default="",
        help_text="Primary host being crawled — equals urlparse(seed_url).netloc "
                  "for Bajaj, and the competitor's apex domain for competitor crawls. "
                  "Indexed for per-domain Health Score lookups.",
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
            models.Index(fields=["kind", "target_domain", "-started_at"]),
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
    # Full visible body text — populated by the competitor spider so the
    # AEM-vs-competitor content comparison view has the raw text to
    # diff against. Empty for in-house Bajaj crawls (those keep body
    # extraction in the legacy CSV pipeline). Field is nullable + indexed
    # nowhere because we never filter on it; it's a read-when-you-need-it
    # blob. Cap via COMPETITOR_BODY_TEXT_MAX_CHARS env.
    body_text = models.TextField(blank=True, default="")
    meta_description = models.CharField(max_length=1024, blank=True, default="")
    canonical = models.CharField(max_length=2048, blank=True, default="")
    meta_robots = models.CharField(max_length=256, blank=True, default="")
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
    # PSI / Core Web Vitals — LEGACY headline columns (mobile strategy).
    # Kept for backward compat with code that reads these directly. They
    # mirror ``mobile_*`` for the same row. Field (CrUX p75) preferred,
    # lab fallback. Populated by engine/psi_scheduler.py via
    # engine/psi_capture.py::_merge_into_results_csv.
    pagespeed_score = models.IntegerField(null=True, blank=True)
    lcp_ms = models.IntegerField(null=True, blank=True)
    cls = models.FloatField(null=True, blank=True)
    inp_ms = models.IntegerField(null=True, blank=True)
    # Full dual-strategy CWV — populated when PSI runs both strategies.
    # Lab metrics (tbt, si) are present whenever the URL was successfully
    # scored by Lighthouse on that device; field metrics (inp, *_category,
    # has_field_data) only populate when CrUX has 28-day real-user data.
    mobile_pagespeed_score = models.IntegerField(null=True, blank=True)
    mobile_lcp_ms = models.IntegerField(null=True, blank=True)
    mobile_cls = models.FloatField(null=True, blank=True)
    mobile_inp_ms = models.IntegerField(null=True, blank=True)
    mobile_fcp_ms = models.IntegerField(null=True, blank=True)
    mobile_ttfb_ms = models.IntegerField(null=True, blank=True)
    mobile_tbt_ms = models.IntegerField(null=True, blank=True)
    mobile_si_ms = models.IntegerField(null=True, blank=True)
    mobile_lcp_category = models.CharField(max_length=24, blank=True, default="")
    mobile_cls_category = models.CharField(max_length=24, blank=True, default="")
    mobile_inp_category = models.CharField(max_length=24, blank=True, default="")
    mobile_has_field_data = models.BooleanField(default=False)
    desktop_pagespeed_score = models.IntegerField(null=True, blank=True)
    desktop_lcp_ms = models.IntegerField(null=True, blank=True)
    desktop_cls = models.FloatField(null=True, blank=True)
    desktop_inp_ms = models.IntegerField(null=True, blank=True)
    desktop_fcp_ms = models.IntegerField(null=True, blank=True)
    desktop_ttfb_ms = models.IntegerField(null=True, blank=True)
    desktop_tbt_ms = models.IntegerField(null=True, blank=True)
    desktop_si_ms = models.IntegerField(null=True, blank=True)
    desktop_lcp_category = models.CharField(max_length=24, blank=True, default="")
    desktop_cls_category = models.CharField(max_length=24, blank=True, default="")
    desktop_inp_category = models.CharField(max_length=24, blank=True, default="")
    desktop_has_field_data = models.BooleanField(default=False)
    # JS rendering (Phase 3e: filled when Playwright re-renders a page
    # because its static fetch returned < 500 chars of body text)
    static_word_count = models.IntegerField(null=True, blank=True)
    rendered_word_count = models.IntegerField(null=True, blank=True)
    playwright_used = models.BooleanField(default=False)

    # ── Phase A.1 — Security headers ──────────────────────────────
    # Captured from HTTP response headers on every successful fetch.
    # Empty string = header absent (which is the SEO problem).
    hsts = models.CharField(max_length=512, blank=True, default="")
    csp = models.TextField(blank=True, default="")
    x_frame_options = models.CharField(max_length=128, blank=True, default="")
    x_content_type_options = models.CharField(max_length=64, blank=True, default="")
    referrer_policy = models.CharField(max_length=128, blank=True, default="")
    permissions_policy = models.TextField(blank=True, default="")
    # Aggregate flag: true if the page has at least one form posting over
    # HTTP (insecure-form audit) or any mixed-content asset loaded.
    has_mixed_content = models.BooleanField(default=False)
    has_insecure_form = models.BooleanField(default=False)

    # ── Phase A.2 — Redirect chain ────────────────────────────────
    # Number of hops from initial URL to final URL (0 = no redirect).
    redirect_hops = models.IntegerField(default=0)
    # Chain as a JSON list of {url, status, type}. type ∈ {http, hsts,
    # js, meta, server} — most are http; the others come from JS
    # render-delta or HSTS upgrade detection.
    redirect_chain = models.JSONField(default=list, blank=True)
    # Final URL (after all redirects) — may differ from `final_url`
    # for URLs that 200'd directly.
    redirect_final_url = models.URLField(max_length=2048, blank=True, default="")
    redirect_loop = models.BooleanField(default=False)

    # ── Phase A.3 — Title + meta pixel widths ─────────────────────
    # Computed at parse time from Google's snippet font metrics
    # (Arial 20px desktop, 18px mobile). Stored as integer px.
    title_pixel_width = models.IntegerField(default=0)
    meta_description_pixel_width = models.IntegerField(default=0)

    # ── Phase A.4 — Canonical chain ──────────────────────────────
    # Canonical URL extracted from HTML <link rel="canonical"> and/or
    # HTTP Link header. Distinct field from final_url which is the
    # post-redirect URL.
    canonical_html = models.URLField(max_length=2048, blank=True, default="")
    canonical_http = models.URLField(max_length=2048, blank=True, default="")
    canonical_mismatch = models.BooleanField(default=False)  # HTML vs HTTP
    multiple_canonicals = models.BooleanField(default=False)
    canonical_chain_length = models.IntegerField(default=0)
    canonical_to_noindex = models.BooleanField(default=False)

    # ── Phase A.5 — Image audit ───────────────────────────────────
    # Aggregates per page. Detail (per-image list) lives in `extra`
    # to keep the row width manageable.
    image_count = models.IntegerField(default=0)
    image_missing_alt = models.IntegerField(default=0)
    image_empty_alt = models.IntegerField(default=0)
    image_oversized_count = models.IntegerField(default=0)  # > 100 KB
    image_broken_count = models.IntegerField(default=0)
    image_audit_extra = models.JSONField(default=dict, blank=True)

    # ── Phase B.1 — Hreflang ──────────────────────────────────────
    # Per-page hreflang signals; cross-page return-tag + 404 + noindex
    # validation happens at audit time by joining rows on absolute URL.
    hreflang_count = models.IntegerField(default=0)
    hreflang_entries = models.JSONField(default=list, blank=True)
    hreflang_has_x_default = models.BooleanField(default=False)
    hreflang_invalid_codes = models.JSONField(default=list, blank=True)
    hreflang_self_reference = models.BooleanField(default=False)

    # ── Phase B.2 — Schema.org structured data ────────────────────
    # JSON-LD is the primary signal; microdata/RDFa counts surface
    # legacy-markup migrations the page hasn't done yet.
    jsonld_count = models.IntegerField(default=0)
    jsonld_types = models.JSONField(default=list, blank=True)
    jsonld_blocks = models.JSONField(default=list, blank=True)
    jsonld_invalid_count = models.IntegerField(default=0)
    jsonld_missing_required = models.JSONField(default=list, blank=True)
    jsonld_rich_result_eligible = models.JSONField(default=list, blank=True)
    microdata_count = models.IntegerField(default=0)
    rdfa_count = models.IntegerField(default=0)

    # ── Phase C.1 — JS render-delta ───────────────────────────────
    # static_word_count + rendered_word_count are stamped in Phase 3e
    # already (legacy columns); these add ratio + booleans the
    # detector layer keys off.
    js_rendered = models.BooleanField(default=False)
    content_delta_ratio = models.FloatField(default=0.0)
    link_delta_ratio = models.FloatField(default=0.0)
    jsonld_delta_ratio = models.FloatField(default=0.0)

    # ── Phase C.2 — PDF metadata ──────────────────────────────────
    pdf_title = models.CharField(max_length=512, blank=True, default="")
    pdf_author = models.CharField(max_length=256, blank=True, default="")
    pdf_subject = models.CharField(max_length=512, blank=True, default="")
    pdf_page_count = models.IntegerField(default=0)
    pdf_language = models.CharField(max_length=32, blank=True, default="")
    pdf_has_text_layer = models.BooleanField(default=False)
    pdf_is_encrypted = models.BooleanField(default=False)
    pdf_byte_size = models.BigIntegerField(default=0)

    # ── Phase C.3 — Custom XPath / CSS extractors ─────────────────
    # Result of user-defined extractors. Keys match CustomExtractor.name.
    custom_extracted = models.JSONField(default=dict, blank=True)

    # ── Phase 2A.5 — Structural mirror ────────────────────────────
    # Mirrors the competitor crawler's structural capture so the
    # in-house Inspector can show our pages with the same UI.
    # headings        : ordered [{level, text, idx}, ...]
    # internal_links  : every internal <a> [{anchor, href, section, kind, rel}]
    # external_links  : every external <a> same shape
    # images          : every <img> [{src, alt, width, height, section, loading}]
    headings_json = models.JSONField(default=list, blank=True)
    internal_links_json = models.JSONField(default=list, blank=True)
    external_links_json = models.JSONField(default=list, blank=True)
    images_json = models.JSONField(default=list, blank=True)

    # ── Phase C.4 — Readability + spelling ────────────────────────
    flesch_score = models.FloatField(default=0.0)
    grade_level = models.FloatField(default=0.0)
    readable_word_count = models.IntegerField(default=0)
    readable_sentence_count = models.IntegerField(default=0)
    spelling_error_count = models.IntegerField(default=0)
    spelling_errors = models.JSONField(default=list, blank=True)

    # ── Phase D.1 — Cookies + privacy ─────────────────────────────
    cookie_count = models.IntegerField(default=0)
    cookies = models.JSONField(default=list, blank=True)
    cookies_insecure_count = models.IntegerField(default=0)
    cookies_no_samesite_count = models.IntegerField(default=0)
    cookies_no_httponly_session_count = models.IntegerField(default=0)
    cookies_third_party_count = models.IntegerField(default=0)
    cookies_tracker_count = models.IntegerField(default=0)
    has_consent_banner = models.BooleanField(default=False)

    # ── Phase D.2 — AMP ───────────────────────────────────────────
    is_amp_page = models.BooleanField(default=False)
    has_amp_alternate = models.BooleanField(default=False)
    amp_alternate_url = models.URLField(max_length=2048, blank=True, default="")
    amp_canonical_target = models.URLField(max_length=2048, blank=True, default="")
    amp_required_missing = models.JSONField(default=list, blank=True)
    amp_invalid = models.BooleanField(default=False)

    # ── Phase D.3 — Accessibility-lite WCAG checks ────────────────
    html_lang = models.CharField(max_length=16, blank=True, default="")
    h1_count = models.IntegerField(default=0)
    heading_skip_count = models.IntegerField(default=0)
    form_inputs_no_label = models.IntegerField(default=0)
    links_no_text = models.IntegerField(default=0)
    links_generic_text = models.IntegerField(default=0)
    invalid_aria_roles = models.JSONField(default=list, blank=True)
    has_skip_link = models.BooleanField(default=False)

    # ── Phase E — LanguageTool grammar ────────────────────────────
    grammar_error_count = models.IntegerField(default=0)
    grammar_errors = models.JSONField(default=list, blank=True)
    grammar_categories = models.JSONField(default=dict, blank=True)
    grammar_lang_detected = models.CharField(max_length=16, blank=True, default="")
    grammar_tool_used = models.CharField(max_length=24, blank=True, default="")

    # ── Phase E — AXE color contrast ──────────────────────────────
    color_contrast_violations_count = models.IntegerField(default=0)
    color_contrast_violations = models.JSONField(default=list, blank=True)
    axe_tool_used = models.CharField(max_length=24, blank=True, default="")

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


# ── Phase 6 — GEO suite tables ──────────────────────────────────────────────


class AIBotLog(models.Model):
    """A single verified AI-bot hit parsed from CDN access logs.

    ``verified`` is the security-critical field: a request claiming
    to be GPTBot from a non-OpenAI IP gets ``verified=False`` and is
    treated as user-agent spoofing. The bot_log_parser does rDNS
    + forward-confirmed DNS against the published IP ranges from each
    bot's owner before persisting.
    """

    BOT_CHOICES = (
        ("gptbot", "GPTBot (OpenAI)"),
        ("chatgpt-user", "ChatGPT-User (browsing)"),
        ("oai-searchbot", "OAI-SearchBot"),
        ("claudebot", "ClaudeBot (Anthropic)"),
        ("claude-user", "Claude-User (browsing)"),
        ("perplexitybot", "PerplexityBot"),
        ("perplexity-user", "Perplexity-User"),
        ("google-extended", "Google-Extended (Gemini)"),
        ("bytespider", "Bytespider (ByteDance/Doubao)"),
        ("ccbot", "CCBot (Common Crawl)"),
        ("meta-externalagent", "Meta-ExternalAgent"),
        ("other", "Other AI bot"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seen_at = models.DateTimeField(db_index=True)
    bot = models.CharField(max_length=32, choices=BOT_CHOICES, db_index=True)
    user_agent = models.TextField(blank=True, default="")
    remote_ip = models.GenericIPAddressField(null=True, blank=True)
    verified = models.BooleanField(default=False, db_index=True)
    url = models.URLField(max_length=2000, db_index=True)
    status_code = models.PositiveSmallIntegerField(default=0)
    bytes_sent = models.PositiveIntegerField(default=0)
    referer = models.TextField(blank=True, default="")
    raw = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-seen_at",)
        indexes = [
            models.Index(fields=["-seen_at", "bot"]),
            models.Index(fields=["url", "-seen_at"]),
            models.Index(fields=["bot", "verified"]),
        ]

    def __str__(self) -> str:
        return f"{self.bot} {self.url} @ {self.seen_at:%Y-%m-%d %H:%M}"


class Backlink(models.Model):
    """Inbound link discovered via Common Crawl WAT or operator import.

    Stores only (source_url -> target_url, anchor) plus the discovery
    pass + first/last seen dates. Per the Common Crawl adapter we
    stream-filter the WAT and keep only edges whose ``target_domain``
    is Bajaj or a tracked competitor, so the table never exceeds
    a few hundred thousand rows even after several months.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_url = models.URLField(max_length=2000, db_index=True)
    source_domain = models.CharField(max_length=255, db_index=True)
    target_url = models.URLField(max_length=2000, db_index=True)
    target_domain = models.CharField(max_length=255, db_index=True)
    anchor_text = models.TextField(blank=True, default="")
    rel = models.CharField(max_length=64, blank=True, default="")
    nofollow = models.BooleanField(default=False)
    discovered_in = models.CharField(
        max_length=64,
        help_text="Common Crawl release ID (e.g. CC-MAIN-2026-09) or 'manual'.",
        default="manual",
        db_index=True,
    )
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-last_seen",)
        constraints = [
            models.UniqueConstraint(
                fields=["source_url", "target_url"],
                name="uniq_backlink_source_target",
            ),
        ]
        indexes = [
            models.Index(fields=["target_domain", "-last_seen"]),
            models.Index(fields=["source_domain", "target_domain"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_domain} -> {self.target_url}"


class PageEmbedding(models.Model):
    """One vector per content chunk per page. Drives similarity search
    and the 3D content-map projection.

    Schema decision: we use pgvector through django-pgvector's VectorField
    when available; falls back to JSONField in environments without the
    extension. The migration uses RunSQL for the actual `vector(384)`
    column so the ORM stays version-tolerant.
    """

    id              = models.BigAutoField(primary_key=True)
    page            = models.ForeignKey(
        "CrawlerPageResult", on_delete=models.CASCADE, related_name="embeddings",
    )
    chunk_idx       = models.IntegerField(default=0)
    chunk_text      = models.TextField(blank=True, default="")
    # vector(384) column added via RunSQL migration; this field is for
    # ORM completeness only (raw selects use the SQL column directly).
    embedding_json  = models.JSONField(default=list, blank=True)
    # Classification copy — denormalised so similarity search can filter
    # without joining to a separate classifications table.
    products        = models.JSONField(default=list, blank=True)
    page_type       = models.CharField(max_length=32, blank=True, default="")
    confidence      = models.FloatField(default=0.0)
    # 3D projection coords cached per snapshot. Updated by Phase 3.
    coord_x         = models.FloatField(null=True, blank=True)
    coord_y         = models.FloatField(null=True, blank=True)
    coord_z         = models.FloatField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["page_type"]),
            models.Index(fields=["confidence"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["page", "chunk_idx"], name="uniq_page_embedding_chunk",
            ),
        ]


class CustomExtractor(models.Model):
    """User-defined XPath / CSS extractor — Screaming Frog parity.

    Each row is one extractor that the fetcher applies to every page
    during the crawl, storing the matched value in
    ``CrawlerPageResult.custom_extracted`` under the extractor's
    ``name`` key. Active extractors are pulled at the start of each
    crawl run; mid-crawl edits do not affect rows already written.
    """

    EXTRACTOR_TYPES = (("css", "CSS selector"), ("xpath", "XPath"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=128, blank=True, default="")
    selector_type = models.CharField(max_length=8, choices=EXTRACTOR_TYPES, default="css")
    selector = models.CharField(max_length=1024)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        indexes = [models.Index(fields=["is_active", "name"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.selector_type})"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.selector_type,
            "selector": self.selector,
        }
