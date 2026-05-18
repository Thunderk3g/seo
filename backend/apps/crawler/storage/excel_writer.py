"""Beautified XLSX report bundler.

Produces ``crawl_report.xlsx`` with Bajaj-branded styling. The workbook is
organised by URL category (subdomain + page-type), not just by error type:

  * Summary sheet — KPIs + error pie chart + a category × indexed_status
    pivot block grouping product / knowledge / branch / etc.
  * Per-subdomain overview sheets — www / branch / investmentcorner.
  * Per-category data sheets — only emitted when non-empty.
  * Existing raw sheets — Results / All Errors / 404s / HTTP / Connection /
    Chunked / Console / Discovered — preserved with the five new enrichment
    columns and auto-filter so users can re-slice in Excel.
  * Noise sheet — branch 404s where ``indexed_status != indexed`` — split
    out so the user can ignore it without scrolling past it.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ..conf import settings
from . import url_classifier

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
    idx_idx = headers.index("indexed_status") + 1 if "indexed_status" in headers else None

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
        if idx_idx:
            val = padded[idx_idx - 1]
            sc = ws.cell(row=ri, column=idx_idx)
            if val == "indexed":
                sc.fill = _OK_FILL
                sc.font = Font(name="Calibri", size=10, bold=True, color=OK_GREEN)
            elif val == "not_indexed":
                sc.fill = _ERR_FILL
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


RAW_SHEETS: list[tuple[str, str, str | None, str | None]] = [
    ("All Results (raw)", "crawl_results.csv", "status", "status_code"),
    ("All 404 Errors (raw)", "crawl_404_errors.csv", None, None),
    ("HTTP Errors", "crawl_errors_httperror.csv", None, None),
    # Connection / Chunked-encoding sheets retired — they were rarely
    # non-empty and not actioned on by any operator workflow.
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

    res_hdr, res_rows = _read_csv("crawl_results.csv")
    totals = _compute_totals(res_hdr, res_rows)
    breakdown = _compute_breakdown(res_hdr, res_rows)
    _build_summary(summary_ws, totals)
    _build_category_pivot(summary_ws, breakdown)

    # Per-subdomain overview sheets — readable at-a-glance KPIs per surface.
    for sub in ("www", "branch", "investmentcorner"):
        sub_rows = _filter_rows_by(res_hdr, res_rows, "subdomain", sub)
        if not sub_rows:
            continue
        ws = wb.create_sheet(title=f"{_pretty_sub(sub)} Overview")
        _build_subdomain_overview(ws, sub, res_hdr, sub_rows, breakdown)

    # Per-category data sheets — only emit when there is at least one row.
    for cat in url_classifier.CATEGORY_DEFS:
        cat_rows = _filter_rows_by(res_hdr, res_rows, "category_key", cat["key"])
        if not cat_rows:
            continue
        ws = wb.create_sheet(title=_sheet_name_for_category(cat))
        _dump_table(ws, res_hdr, cat_rows, status_col="status",
                    code_col="status_code")

    # Noise sheet — branch 404s that GSC says are NOT indexed.
    noise_rows = _branch_404_noise_rows(res_hdr, res_rows)
    if noise_rows:
        ws = wb.create_sheet(title="Branch 404 Noise")
        _dump_table(ws, res_hdr, noise_rows, status_col="status",
                    code_col="status_code")

    # Preserved raw sheets for in-Excel re-slicing.
    for sheet_name, csv_file, status_col, code_col in RAW_SHEETS:
        ws = wb.create_sheet(title=sheet_name)
        headers, rows = _read_csv(csv_file)
        _dump_table(ws, headers, rows, status_col=status_col, code_col=code_col)

    wb.save(out)
    return out


# ── New helpers ────────────────────────────────────────────────────────────


def _filter_rows_by(headers: list[str], rows: list[list[str]],
                    column: str, value: str) -> list[list[str]]:
    if column not in headers:
        return []
    idx = headers.index(column)
    return [r for r in rows if idx < len(r) and r[idx] == value]


def _branch_404_noise_rows(headers: list[str],
                           rows: list[list[str]]) -> list[list[str]]:
    if not headers:
        return []
    try:
        sub_i = headers.index("subdomain")
        code_i = headers.index("status_code")
        idx_i = headers.index("indexed_status")
    except ValueError:
        return []
    out = []
    for r in rows:
        if max(sub_i, code_i, idx_i) >= len(r):
            continue
        if r[sub_i] == "branch" and r[code_i] == "404" and r[idx_i] != "indexed":
            out.append(r)
    return out


def _sheet_name_for_category(cat: dict) -> str:
    """Build a stable, Excel-safe sheet name (max 31 chars)."""
    sub = _pretty_sub(cat["subdomain"])
    label = cat["label"]
    raw = f"{sub} · {label}"
    cleaned = raw.replace("·", "-").replace(":", "-").replace("/", "-")
    return cleaned[:31]


def _pretty_sub(sub: str) -> str:
    return {
        "www": "WWW",
        "branch": "Branch",
        "investmentcorner": "InvCorner",
        "external": "External",
    }.get(sub, sub.title())


def _compute_breakdown(headers: list[str],
                       rows: list[list[str]]) -> dict:
    """Per-subdomain × per-category counts for the Summary pivot block."""
    out: dict = {
        "by_subdomain": defaultdict(lambda: Counter()),
        "by_category": defaultdict(lambda: Counter()),
        "noise_404_branch_not_indexed": 0,
    }
    if not headers:
        return out
    try:
        i_sub = headers.index("subdomain")
        i_cat = headers.index("category_key")
        i_code = headers.index("status_code")
        i_idx = headers.index("indexed_status")
        i_src = headers.index("from_sitemap")
    except ValueError:
        return out

    for r in rows:
        if max(i_sub, i_cat, i_code, i_idx, i_src) >= len(r):
            continue
        sub = r[i_sub] or "external"
        cat = r[i_cat] or "unknown"
        code = r[i_code] or ""
        idx = r[i_idx] or "unknown"
        src = r[i_src] or ""

        for bucket_key, bucket in (("by_subdomain", out["by_subdomain"][sub]),
                                   ("by_category",  out["by_category"][cat])):
            bucket["crawled"] += 1
            if code == "200":
                bucket["ok"] += 1
            elif code == "404":
                bucket["errors_404"] += 1
                bucket["errors"] += 1
            elif code and not code.startswith("2"):
                bucket["errors"] += 1
            bucket[f"index_{idx}"] += 1
            if src == "1":
                bucket["from_sitemap"] += 1

        if sub == "branch" and code == "404" and idx != "indexed":
            out["noise_404_branch_not_indexed"] += 1
    return out


def _build_category_pivot(ws: Worksheet, breakdown: dict) -> None:
    """Render the category × indexed pivot block on the Summary sheet."""
    start_row = 20
    ws.cell(row=start_row, column=2, value="Category breakdown").font = _SUBHEAD_FONT

    headers = ["Subdomain", "Category", "Crawled", "OK", "404",
               "Other errors", "Indexed", "Not indexed", "Excluded",
               "Unknown", "From sitemap"]
    header_row = start_row + 1
    for i, h in enumerate(headers, start=2):
        cell = ws.cell(row=header_row, column=i, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _CENTER
        cell.border = _BORDER

    row = header_row + 1
    cat_counts = breakdown["by_category"]
    for cat in url_classifier.CATEGORY_DEFS:
        c = cat_counts.get(cat["key"], Counter())
        if not c:
            continue
        values = [
            _pretty_sub(cat["subdomain"]),
            cat["label"],
            c.get("crawled", 0),
            c.get("ok", 0),
            c.get("errors_404", 0),
            max(c.get("errors", 0) - c.get("errors_404", 0), 0),
            c.get("index_indexed", 0),
            c.get("index_not_indexed", 0),
            c.get("index_excluded", 0),
            c.get("index_unknown", 0),
            c.get("from_sitemap", 0),
        ]
        for i, v in enumerate(values, start=2):
            cell = ws.cell(row=row, column=i, value=v)
            cell.font = Font(name="Calibri", size=10, color=TEXT_DARK)
            cell.border = _BORDER
            if row % 2 == 0:
                cell.fill = _ZEBRA_FILL
        # Conditional red fill on `Not indexed` for product / knowledge
        # categories — these are the ones we genuinely care about.
        ni_cell = ws.cell(row=row, column=8)
        if cat["key"].startswith("product") or cat["key"] == "knowledge":
            if (ni_cell.value or 0) > 0:
                ni_cell.fill = _ERR_FILL
                ni_cell.font = Font(name="Calibri", size=10, bold=True, color=ERR_RED)
        row += 1

    ws.cell(row=row + 1, column=2,
            value=f"Noise: branch 404s NOT indexed = "
                  f"{breakdown.get('noise_404_branch_not_indexed', 0)}"
            ).font = _SUB_FONT


def _build_subdomain_overview(ws: Worksheet, sub: str,
                              headers: list[str], rows: list[list[str]],
                              breakdown: dict) -> None:
    """Per-subdomain summary + the top 20 problem URLs on that surface."""
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    for col in ("B", "C", "D", "E", "F"):
        ws.column_dimensions[col].width = 22

    title = f"{_pretty_sub(sub)} surface"
    ws["B2"] = title
    ws["B2"].font = _TITLE_FONT
    ws["B3"] = f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ·  {len(rows)} rows"
    ws["B3"].font = _SUB_FONT
    ws.merge_cells("B2:F2")
    ws.merge_cells("B3:F3")

    counts = breakdown["by_subdomain"].get(sub, Counter())
    cards = [
        ("Pages", counts.get("crawled", len(rows))),
        ("OK (200)", counts.get("ok", 0)),
        ("Errors", counts.get("errors", 0)),
        ("Indexed", counts.get("index_indexed", 0)),
        ("Not Indexed", counts.get("index_not_indexed", 0)),
    ]
    for i, (label, value) in enumerate(cards):
        col = 2 + i
        ws.cell(row=6, column=col, value=label).font = _KPI_LABEL
        ws.cell(row=6, column=col).alignment = _CENTER
        vc = ws.cell(row=7, column=col, value=value)
        vc.font = _KPI_VALUE
        vc.alignment = _CENTER

    # Top problem URLs — anything non-200 on this surface.
    code_i = headers.index("status_code") if "status_code" in headers else None
    url_i = headers.index("url") if "url" in headers else 0
    idx_i = headers.index("indexed_status") if "indexed_status" in headers else None
    cat_i = headers.index("category_key") if "category_key" in headers else None
    problems = []
    if code_i is not None:
        for r in rows:
            if code_i < len(r) and r[code_i] not in ("200", ""):
                problems.append([
                    r[url_i] if url_i < len(r) else "",
                    r[code_i],
                    r[idx_i] if idx_i is not None and idx_i < len(r) else "",
                    r[cat_i] if cat_i is not None and cat_i < len(r) else "",
                ])
    problems = problems[:20]

    if problems:
        block = 11
        for i, h in enumerate(["URL", "Status", "Indexed", "Category"], start=2):
            cell = ws.cell(row=block, column=i, value=h)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
            cell.alignment = _CENTER
            cell.border = _BORDER
        for ri, row in enumerate(problems, start=block + 1):
            for ci, v in enumerate(row, start=2):
                c = ws.cell(row=ri, column=ci, value=v)
                c.font = Font(name="Calibri", size=10, color=TEXT_DARK)
                c.border = _BORDER
                if ri % 2 == 0:
                    c.fill = _ZEBRA_FILL


def _compute_totals(res_hdr: list[str], res_rows: list[list[str]]) -> dict:
    def count(name: str) -> int:
        _, rows = _read_csv(name)
        return len(rows)

    ok = 0
    if res_hdr:
        try:
            idx = res_hdr.index("status_code")
            ok = sum(1 for r in res_rows if idx < len(r) and r[idx] == "200")
        except ValueError:
            pass
    return {
        "pages_crawled": len(res_rows),
        "ok_pages": ok,
        "total_errors": count("crawl_errors.csv"),
        "errors_404": count("crawl_404_errors.csv"),
        "errors_http": count("crawl_errors_httperror.csv"),
        "console_entries": count("crawl_console_log.csv"),
        "discovered_edges": count("crawl_discovered.csv"),
    }
