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

    # Site tree
    path("tree", views.tree_view, name="tree"),

    # Live logs (polling replaces WebSocket)
    path("logs", views.logs_view, name="logs"),
]
