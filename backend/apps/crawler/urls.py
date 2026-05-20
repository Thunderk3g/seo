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

    # Site tree
    path("tree", views.tree_view, name="tree"),

    # Live logs (polling replaces WebSocket)
    path("logs", views.logs_view, name="logs"),
]
