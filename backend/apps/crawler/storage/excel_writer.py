"""Beautified XLSX report bundler.

Produces ``crawl_report.xlsx`` with Bajaj-branded styling: Summary +
Results + 404s + HTTP / Connection / Chunked errors + Console Log +
Discovered Edges, each sheet with frozen header, auto-filter, fitted
column widths, brand-coloured header, zebra-striped body, conditional
formatting on status / HTTP code, plus a pie chart of error distribution.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ..conf import settings

# ── Bajaj brand palette ────────────────────────────────────────────────────
BRAND_NAVY = "003DA5"
BRAND_GOLD = "FDB913"
OK_GREEN = "34A853"
OK_GREEN_LT = "E6F4EA"
ERR_RED = "EA4335"
ERR_RED_LT = "FCE8E6"
WARN_ORANGE_LT = "FEF7E0"
ZEBRA = "F8F9FA"
WHITE = "FFFFFF"
TEXT_DARK = "202124"
TEXT_MUTED = "5F6368"

_HEADER_FONT = Font(name="Calibri", size=11, bold=True, color=WHITE)
_SUBHEAD_FONT = Font(name="Calibri", size=10, bold=True, color=TEXT_DARK)
_TITLE_FONT = Font(name="Calibri", size=20, bold=True, color=BRAND_NAVY)
_SUB_FONT = Font(name="Calibri", size=11, color=TEXT_MUTED)
_KPI_LABEL = Font(name="Calibri", size=10, bold=True, color=TEXT_MUTED)
_KPI_VALUE = Font(name="Calibri", size=20, bold=True, color=BRAND_NAVY)

_HEADER_FILL = PatternFill("solid", fgColor=BRAND_NAVY)
_ACCENT_FILL = PatternFill("solid", fgColor=BRAND_GOLD)
_ZEBRA_FILL = PatternFill("solid", fgColor=ZEBRA)
_OK_FILL = PatternFill("solid", fgColor=OK_GREEN_LT)
_ERR_FILL = PatternFill("solid", fgColor=ERR_RED_LT)
_WARN_FILL = PatternFill("solid", fgColor=WARN_ORANGE_LT)  # noqa: F841 reserved for warn rows

_THIN = Side(style="thin", color="E0E4E8")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_CENTER = Alignment(horizontal="center", vertical="center")
_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=False)


def _read_csv(name: str) -> tuple[list[str], list[list[str]]]:
    path = settings.data_path / name
    if not path.exists():
        return [], []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        headers = next(reader, [])
        rows = list(reader)
    return headers, rows


def _fit_columns(ws: Worksheet, headers: list[str], rows: list[list[str]],
                 min_w: int = 10, max_w: int = 60) -> None:
    for i, header in enumerate(headers, start=1):
        longest = max(
            [len(header)] + [len(r[i - 1]) if i - 1 < len(r) else 0 for r in rows[:200]]
        )
        ws.column_dimensions[get_column_letter(i)].width = max(min_w, min(max_w, longest + 2))


def _style_header(ws: Worksheet, row: int, cols: int,
                  fill: PatternFill = _HEADER_FILL, font: Font = _HEADER_FONT) -> None:
    for c in range(1, cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = font
        cell.fill = fill
        cell.alignment = _CENTER
        cell.border = _BORDER


def _dump_table(ws: Worksheet, headers: list[str], rows: list[list[str]],
                *, freeze: bool = True, auto_filter: bool = True,
                status_col: str | None = None,
                code_col: str | None = None) -> None:
    """Write a data table with header + zebra body + conditional fills."""
    if not headers:
        ws.cell(row=1, column=1, value="(no data)").font = _SUB_FONT
        return
    status_idx = headers.index(status_col) + 1 if status_col and status_col in headers else None
    code_idx = headers.index(code_col) + 1 if code_col and code_col in headers else None

    ws.append(headers)
    _style_header(ws, 1, len(headers))

    for ri, row in enumerate(rows, start=2):
        padded = (row + [""] * (len(headers) - len(row)))[: len(headers)]
        ws.append(padded)
        base_fill = _ZEBRA_FILL if ri % 2 == 0 else None
        for ci in range(1, len(headers) + 1):
            cell = ws.cell(row=ri, column=ci)
            if base_fill and cell.fill.fgColor.rgb in (None, "00000000"):
                cell.fill = base_fill
            cell.alignment = _LEFT
            cell.border = _BORDER
            cell.font = Font(name="Calibri", size=10, color=TEXT_DARK)

        if status_idx:
            val = padded[status_idx - 1]
            sc = ws.cell(row=ri, column=status_idx)
            if val == "OK":
                sc.fill = _OK_FILL
                sc.font = Font(name="Calibri", size=10, bold=True, color=OK_GREEN)
            elif val and val != "pending":
                sc.fill = _ERR_FILL
                sc.font = Font(name="Calibri", size=10, bold=True, color=ERR_RED)
        if code_idx:
            val = padded[code_idx - 1]
            sc = ws.cell(row=ri, column=code_idx)
            if val == "200":
                sc.font = Font(name="Calibri", size=10, bold=True, color=OK_GREEN)
            elif val.startswith("4") or val.startswith("5"):
                sc.font = Font(name="Calibri", size=10, bold=True, color=ERR_RED)

    if freeze:
        ws.freeze_panes = "A2"
    if auto_filter:
        ws.auto_filter.ref = ws.dimensions
    _fit_columns(ws, headers, rows)
    ws.sheet_view.showGridLines = False


def _build_summary(ws: Worksheet, totals: dict) -> None:
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    for col in ("B", "C", "D", "E", "F"):
        ws.column_dimensions[col].width = 22

    ws["B2"] = "Bajaj Life · Crawl Report"
    ws["B2"].font = _TITLE_FONT
    ws["B3"] = f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ·  seed: {settings.seed_url}"
    ws["B3"].font = _SUB_FONT
    ws.merge_cells("B2:F2")
    ws.merge_cells("B3:F3")

    for c in range(2, 7):
        ws.cell(row=4, column=c).fill = _ACCENT_FILL
    ws.row_dimensions[4].height = 4

    cards = [
        ("Pages Crawled", totals["pages_crawled"]),
        ("OK (200)", totals["ok_pages"]),
        ("Total Errors", totals["total_errors"]),
        ("404 Errors", totals["errors_404"]),
        ("Discovered Edges", totals["discovered_edges"]),
    ]
    for i, (label, value) in enumerate(cards):
        col = 2 + i
        ws.cell(row=6, column=col, value=label).font = _KPI_LABEL
        ws.cell(row=6, column=col).alignment = _CENTER
        vc = ws.cell(row=7, column=col, value=value)
        vc.font = _KPI_VALUE
        vc.alignment = _CENTER
        for r in (6, 7, 8):
            c = ws.cell(row=r, column=col)
            c.border = Border(left=_THIN, right=_THIN, top=_THIN if r == 6 else None,
                              bottom=_THIN if r == 8 else None)
        ws.row_dimensions[6].height = 22
        ws.row_dimensions[7].height = 32
        ws.row_dimensions[8].height = 4

    ws["B10"] = "Error breakdown"
    ws["B10"].font = _SUBHEAD_FONT
    ws.append([])
    brk_headers = ["Category", "Count"]
    breakdown = [
        ("404 Not Found", totals["errors_404"]),
        ("HTTP Error (non-404)", totals["errors_http"]),
        ("Connection Error", totals["errors_connection"]),
        ("Chunked Encoding Error", totals["errors_chunked"]),
        ("Console Errors (in source)", totals["console_entries"]),
    ]
    start_row = 12
    for i, h in enumerate(brk_headers):
        cell = ws.cell(row=start_row, column=2 + i, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _BORDER
    for ri, (cat, count) in enumerate(breakdown, start=start_row + 1):
        ws.cell(row=ri, column=2, value=cat).border = _BORDER
        ws.cell(row=ri, column=3, value=count).border = _BORDER
        ws.cell(row=ri, column=2).font = Font(name="Calibri", size=10, color=TEXT_DARK)
        ws.cell(row=ri, column=3).font = Font(name="Calibri", size=10, bold=True, color=TEXT_DARK)
        if ri % 2 == 0:
            ws.cell(row=ri, column=2).fill = _ZEBRA_FILL
            ws.cell(row=ri, column=3).fill = _ZEBRA_FILL

    if sum(c for _, c in breakdown) > 0:
        chart = PieChart()
        chart.title = "Error distribution"
        labels = Reference(ws, min_col=2, min_row=start_row + 1,
                           max_row=start_row + len(breakdown))
        data = Reference(ws, min_col=3, min_row=start_row,
                         max_row=start_row + len(breakdown))
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(labels)
        chart.height = 9
        chart.width = 14
        chart.dataLabels = DataLabelList(showPercent=True)
        ws.add_chart(chart, "E10")


SHEETS: list[tuple[str, str, str | None, str | None]] = [
    ("Results", "crawl_results.csv", "status", "status_code"),
    ("404 Errors", "crawl_404_errors.csv", None, None),
    ("HTTP Errors", "crawl_errors_httperror.csv", None, None),
    ("Connection Errors", "crawl_errors_connectionerror.csv", None, None),
    ("Chunked Errors", "crawl_errors_chunkedencodingerror.csv", None, None),
    ("All Errors", "crawl_errors.csv", None, None),
    ("Console Log", "crawl_console_log.csv", None, None),
    ("Discovered Edges", "crawl_discovered.csv", None, None),
]


def build_report(output_path: Path | None = None) -> Path:
    """Assemble the full XLSX report from current ``data/`` CSVs."""
    out = output_path or (settings.reports_path / "crawl_report.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Summary"

    totals = _compute_totals()
    _build_summary(summary_ws, totals)

    for sheet_name, csv_file, status_col, code_col in SHEETS:
        ws = wb.create_sheet(title=sheet_name)
        headers, rows = _read_csv(csv_file)
        _dump_table(ws, headers, rows, status_col=status_col, code_col=code_col)

    wb.save(out)
    return out


def _compute_totals() -> dict:
    def count(name: str) -> int:
        _, rows = _read_csv(name)
        return len(rows)

    r_hdr, r_rows = _read_csv("crawl_results.csv")
    ok = 0
    if r_hdr:
        try:
            idx = r_hdr.index("status_code")
            ok = sum(1 for r in r_rows if idx < len(r) and r[idx] == "200")
        except ValueError:
            pass
    return {
        "pages_crawled": len(r_rows),
        "ok_pages": ok,
        "total_errors": count("crawl_errors.csv"),
        "errors_404": count("crawl_404_errors.csv"),
        "errors_http": count("crawl_errors_httperror.csv"),
        "errors_connection": count("crawl_errors_connectionerror.csv"),
        "errors_chunked": count("crawl_errors_chunkedencodingerror.csv"),
        "console_entries": count("crawl_console_log.csv"),
        "discovered_edges": count("crawl_discovered.csv"),
    }
