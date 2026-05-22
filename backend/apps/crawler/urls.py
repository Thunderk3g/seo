"""URL routes — mounted under ``/api/v1/crawler/`` by the parent api/urls.py."""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "crawler"

urlpatterns = [
    # Lifecycle
    path("status", views.status_view, name="status"),
    path("start", views.start_view, name="start"),
    path("stop", views.stop_view, name="stop"),

    # Data access
    path("summary", views.summary_view, name="summary"),
    path("summary/breakdown", views.summary_breakdown_view, name="summary-breakdown"),
    path("tables", views.tables_list_view, name="tables"),
    path("tables/<str:key>", views.table_detail_view, name="table-detail"),
    path("download/<str:key>", views.download_csv_view, name="download"),

    # Audit engine — Health Score KPI + Issues triage inbox
    # Phase 1 of the tool-clone roadmap: typed issue catalogue + Ahrefs-
    # style transparent Health Score formula. Drives the new dashboard
    # widget, the /crawler/issues page, and the chat tools.
    path("health-score", views.health_score_view, name="health-score"),
    # Per-competitor Health Score — populated by the Scrapy competitor
    # crawler. Reads the most-recent completed snapshot for the domain
    # and scores its CrawlerPageResult rows against the same 52
    # detectors that grade the Bajaj site.
    path(
        "competitors/<str:domain>/health-score",
        views.competitor_health_score_view,
        name="competitor-health-score",
    ),
    path("issues", views.issues_view, name="issues"),
    path("issues/<str:slug>", views.issue_detail_view, name="issue-detail"),
    # Compliance dashboard — WCAG / GDPR / OWASP aggregated view.
    path("compliance", views.compliance_view, name="compliance"),
    path("compliance.csv", views.compliance_csv_view, name="compliance-csv"),

    # Page Explorer — Ahrefs-style sortable/filterable URL inventory.
    # Phase 2: reads CSV via in-process mtime cache. Phase 3 will swap
    # to Postgres with the same response contract.
    path("pages", views.page_explorer_view, name="pages"),
    path("pages/facets", views.page_explorer_facets_view, name="pages-facets"),

    # Phase 4 — PageRank / Near-duplicate services.
    path("pagerank", views.pagerank_view, name="pagerank"),
    path("near-duplicates", views.near_duplicates_view, name="near-duplicates"),

    # Phase 5 — Trends + Compare Crawls + Thematic Reports.
    path("trends", views.trends_view, name="trends"),
    path("compare", views.compare_view, name="compare"),
    path("themes", views.themes_list_view, name="themes"),
    path("themes/<str:slug>", views.theme_detail_view, name="theme-detail"),

    # Reports
    path("reports/xlsx", views.report_xlsx_view, name="report-xlsx"),

    # GSC coverage cache control (POST to flush after dropping a new CSV)
    path("gsc/coverage/refresh", views.gsc_coverage_refresh_view,
         name="gsc-coverage-refresh"),
    # GSC coverage builder — derive coverage CSV from existing performance
    # data + a fresh sitemap.xml fetch (no URL Inspection quota burn).
    path("gsc/coverage/build", views.gsc_coverage_build_view,
         name="gsc-coverage-build"),
    # GSC URL Inspection runner — convert `unknown` rows into definitive
    # indexed / not_indexed / excluded verdicts. Rate-limited (2000/day).
    path("gsc/coverage/inspect", views.gsc_inspect_unknowns_view,
         name="gsc-coverage-inspect"),

    # Browser-side console capture (Playwright headless Chromium)
    path("console/capture", views.console_capture_start_view,
         name="console-capture-start"),
    path("console/capture/status", views.console_capture_status_view,
         name="console-capture-status"),
    path("console/capture/stop", views.console_capture_stop_view,
         name="console-capture-stop"),

    # PSI / Core Web Vitals — last-run status surface for the UI banner.
    # Reads _psi_status.json written by psi_capture at the end of each
    # run. Returns {} if no PSI run has happened yet.
    path("psi/status", views.psi_status_view, name="psi-status"),
    # Live progress of the inline PSI scheduler during an active crawl.
    # Frontend polls this every ~5 s while is_running is true. Returns
    # {} when no crawl/scheduler is in flight.
    path("psi/progress", views.psi_progress_view, name="psi-progress"),

    # Site tree
    path("tree", views.tree_view, name="tree"),

    # Live logs (polling replaces WebSocket)
    path("logs", views.logs_view, name="logs"),

    # Phase 6 — GEO suite (AI-search readiness).
    path("geo/llms-txt", views.llms_txt_audit_view, name="geo-llms-txt"),
    path("geo/llms-txt/draft", views.llms_txt_draft_view, name="geo-llms-txt-draft"),
    path("geo/indexnow/ping", views.indexnow_ping_view, name="geo-indexnow-ping"),
    path("geo/ai-bots", views.ai_bot_hits_view, name="geo-ai-bots"),
    path("geo/backlinks", views.backlinks_view, name="geo-backlinks"),
]
