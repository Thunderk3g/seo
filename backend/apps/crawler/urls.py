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
    # Live section-wise report (Reports page).
    path("report/sections", views.report_sections_view, name="report-sections"),
    path("report/broken-links", views.report_broken_links_view,
         name="report-broken-links"),
    path("report/robots", views.report_robots_view, name="report-robots"),
    path("report/external-links", views.report_external_links_view,
         name="report-external-links"),
    path("report/soft-404", views.report_soft_404_view, name="report-soft-404"),
    path("report/cwv", views.report_cwv_view, name="report-cwv"),
    # Restored 2026-06-05: dashboard health widget (view body was kept).
    path("health-score", views.health_score_view, name="health-score"),
    path("tables", views.tables_list_view, name="tables"),
    path("tables/<str:key>", views.table_detail_view, name="table-detail"),
    path("download/<str:key>", views.download_csv_view, name="download"),

    # Snapshot picker — drives the inspector UIs so the operator
    # can switch between the latest Bajaj snapshot and any competitor
    # snapshot the link-walker has populated.
    path("snapshots", views.snapshots_list_view, name="snapshots-list"),
    # Ad-hoc URL crawler — quick fetch + parse of any URL into a
    # singleton "adhoc" snapshot, so the dashboard can route the user
    # to the unified PageDetailPage with full structured data.
    path("adhoc", views.adhoc_crawl_view, name="adhoc-crawl"),
    # Comprehensive XLSX report — 11 sheets covering Phase A-D data.
    path("report/comprehensive.xlsx", views.comprehensive_report_view,
         name="report-comprehensive"),

    # Page Explorer — Ahrefs-style sortable/filterable URL inventory.
    # Phase 2: reads CSV via in-process mtime cache. Phase 3 will swap
    # to Postgres with the same response contract.
    path("pages", views.page_explorer_view, name="pages"),
    path("pages/facets", views.page_explorer_facets_view, name="pages-facets"),

    # Phase 4 — PageRank / Near-duplicate services.
    path("pagerank", views.pagerank_view, name="pagerank"),
    path("near-duplicates", views.near_duplicates_view, name="near-duplicates"),

    # Phase 5 — Thematic Reports.
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
    # GSC Crawl Stats — ingest of the export-only Settings > Crawl stats
    # report (no Search Console API exists for it). GET reads the parsed
    # bundle; POST flushes the cache after a fresh export is dropped into
    # data/gsc_crawl_stats/.
    path("gsc/crawl-stats", views.gsc_crawl_stats_view, name="gsc-crawl-stats"),

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
    # Post-crawl PSI sweep — fill CWV gaps (GET=count, POST=start sweep).
    path("psi/sweep", views.psi_sweep_view, name="psi-sweep"),

    # Site tree
    path("tree", views.tree_view, name="tree"),

    # Live logs (polling replaces WebSocket)
    path("logs", views.logs_view, name="logs"),
]
