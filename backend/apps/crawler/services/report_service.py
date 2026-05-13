"""Report-generation orchestration."""
from __future__ import annotations

from pathlib import Path

from ..conf import settings
from ..storage.excel_writer import build_report


def generate_xlsx() -> Path:
    return build_report(settings.reports_path / "crawl_report.xlsx")
