"""Unit tests for :class:`ExportService` and the six format generators.

Covers list/create/get round-trips plus the per-generator content rules
documented in ``services/export_service.py``.
"""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET

import pytest

from apps.common import constants
from apps.crawl_sessions.models import (
    CrawlSession, ExportRecord, Link, Page,
)
from apps.crawl_sessions.services.export_service import ExportService
from apps.crawler.models import Website


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def website(db):
    return Website.objects.create(domain="example.com", name="Example")


@pytest.fixture
def session(db, website):
    return CrawlSession.objects.create(
        website=website,
        status=constants.SESSION_STATUS_COMPLETED,
    )


def _make_page(session: CrawlSession, url: str, **kwargs) -> Page:
    """Create a Page with sensible defaults for export testing."""
    defaults = {
        "http_status_code": 200,
        "title": "Default Title",
        "meta_description": "A reasonably long meta description "
                            "that satisfies the 70-char minimum easily.",
        "crawl_depth": 1,
        "load_time_ms": 250.0,
        "content_size_bytes": 5_000,
        "word_count": 400,
        "is_https": True,
    }
    defaults.update(kwargs)
    return Page.objects.create(crawl_session=session, url=url, **defaults)


def _csv_lines(content: str) -> list[str]:
    """Split CSV content on LF, dropping the trailing empty line."""
    lines = content.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


# ─────────────────────────────────────────────────────────────
# 1. list_exports — empty
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_list_exports_empty(session):
    """A fresh session has no exports."""
    assert ExportService.list_exports(session) == []


# ─────────────────────────────────────────────────────────────
# 2. create_export — unknown kind
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_export_unknown_kind_raises(session):
    """Unknown kind raises ValueError."""
    with pytest.raises(ValueError):
        ExportService.create_export(session, "foo.csv")


# ─────────────────────────────────────────────────────────────
# 3. urls.csv — one page
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_urls_csv_one_page(session):
    """One page → header + 1 data row, correct metadata."""
    _make_page(session, "https://example.com/a", word_count=123)
    record = ExportService.create_export(session, "urls.csv")

    assert record.filename == "urls.csv"
    assert record.content_type == "text/csv"
    assert record.row_count == 1

    lines = _csv_lines(record.content)
    assert lines[0] == (
        "url,http_status_code,title,crawl_depth,"
        "load_time_ms,word_count,is_https,source"
    )
    assert len(lines) == 2
    assert "https://example.com/a" in lines[1]
    assert ",123," in lines[1]  # word_count cell


# ─────────────────────────────────────────────────────────────
# 4. urls.csv — zero pages
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_urls_csv_zero_pages(session):
    """Empty session → header only, row_count == 0."""
    record = ExportService.create_export(session, "urls.csv")
    lines = _csv_lines(record.content)

    assert record.row_count == 0
    assert len(lines) == 1
    assert lines[0].startswith("url,http_status_code,")


# ─────────────────────────────────────────────────────────────
# 5. issues.xlsx — real openpyxl-backed workbook
# ─────────────────────────────────────────────────────────────
_XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


@pytest.mark.django_db
def test_issues_xlsx_is_valid_openpyxl_workbook(session):
    """The body is a real .xlsx that openpyxl can re-open and inspect."""
    # ``openpyxl`` is imported inside the test so collection still works
    # if the dependency is missing; the test itself will skip.
    openpyxl = pytest.importorskip("openpyxl")

    # Seed a few pages so derive_issues has at least one non-zero count
    # — exercises the data-row path, not just the header.
    _make_page(session, "https://example.com/missing", http_status_code=404)
    _make_page(session, "https://example.com/down", http_status_code=503)

    record = ExportService.create_export(session, "issues.xlsx")

    # Body MUST round-trip through openpyxl — that proves it's a real
    # zip-container xlsx and not utf-8-mangled bytes.
    wb = openpyxl.load_workbook(io.BytesIO(record.body()))
    assert wb.sheetnames == ["Issues"]

    ws = wb["Issues"]
    header = [cell.value for cell in ws[1]]
    assert header == ["Issue", "Severity", "Description", "URL count"]

    # 12 canonical issues + 1 header row.
    assert ws.max_row == 13
    # Pull a representative data row and assert the URL-count column is
    # an int (openpyxl preserves Python types).
    second_row = [cell.value for cell in ws[2]]
    assert isinstance(second_row[3], int)


@pytest.mark.django_db
def test_issues_xlsx_content_type_is_excel_mime(session):
    """The persisted content_type is the OOXML spreadsheet MIME."""
    pytest.importorskip("openpyxl")
    record = ExportService.create_export(session, "issues.xlsx")
    assert record.content_type == _XLSX_MIME


@pytest.mark.django_db
def test_issues_xlsx_filename_uses_xlsx_extension(session):
    """The download filename keeps the .xlsx extension."""
    pytest.importorskip("openpyxl")
    record = ExportService.create_export(session, "issues.xlsx")
    assert record.filename == "issues.xlsx"


@pytest.mark.django_db
def test_issues_xlsx_body_lives_in_content_bytes(session):
    """Binary records store bytes in content_bytes, not in content TextField.

    Guards against accidental regression where a future generator returns
    str again — the persistence path would silently encode and break the
    download."""
    pytest.importorskip("openpyxl")
    record = ExportService.create_export(session, "issues.xlsx")
    assert record.content == ""
    raw = bytes(record.content_bytes) if record.content_bytes else b""
    # XLSX is a zip container — magic bytes "PK\x03\x04".
    assert raw.startswith(b"PK\x03\x04")
    assert record.is_binary() is True
    assert record.body() == raw
    assert record.row_count == 12


# ─────────────────────────────────────────────────────────────
# 6. sitemap.xml — well-formed
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_sitemap_xml_well_formed(session):
    """Pages 200, 200, 404 → sitemap with 2 <url> entries."""
    _make_page(session, "https://example.com/a", http_status_code=200)
    _make_page(session, "https://example.com/b", http_status_code=200)
    _make_page(session, "https://example.com/c", http_status_code=404)

    record = ExportService.create_export(session, "sitemap.xml")

    assert record.filename == "sitemap.xml"
    assert record.content_type == "application/xml"
    assert record.row_count == 2
    assert record.content.startswith("<?xml")

    # Parses cleanly.
    root = ET.fromstring(record.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = root.findall("sm:url", ns)
    assert len(urls) == 2
    locs = sorted(u.find("sm:loc", ns).text for u in urls)
    assert locs == ["https://example.com/a", "https://example.com/b"]


# ─────────────────────────────────────────────────────────────
# 7. sitemap.xml — escapes special chars
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_sitemap_xml_escapes_special_chars(session):
    """A URL with ``&`` is escaped to ``&amp;``."""
    _make_page(
        session,
        "https://example.com/page?a=1&b=2",
        http_status_code=200,
    )
    record = ExportService.create_export(session, "sitemap.xml")
    assert "&amp;" in record.content
    # No bare ampersand outside the entity.
    assert "a=1&b=2" not in record.content
    # Still parses.
    ET.fromstring(record.content)


# ─────────────────────────────────────────────────────────────
# 8. broken-links.csv
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_broken_links_csv(session):
    """Pages 200/404/503 + one link to /missing → 2 rows; 404 row has source."""
    _make_page(session, "https://example.com/home", http_status_code=200)
    _make_page(session, "https://example.com/missing", http_status_code=404)
    _make_page(session, "https://example.com/down", http_status_code=503)

    Link.objects.create(
        crawl_session=session,
        source_url="https://example.com/home",
        target_url="https://example.com/missing",
        link_type=constants.LINK_TYPE_INTERNAL,
    )

    record = ExportService.create_export(session, "broken-links.csv")
    assert record.filename == "broken-links.csv"
    assert record.content_type == "text/csv"
    assert record.row_count == 2

    lines = _csv_lines(record.content)
    assert lines[0] == "url,http_status_code,source_urls"
    assert len(lines) == 3

    # Find the 404 row.
    missing_row = next(line for line in lines[1:] if "/missing" in line)
    assert "404" in missing_row
    assert "https://example.com/home" in missing_row


# ─────────────────────────────────────────────────────────────
# 9. redirects.csv
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_redirects_csv(session):
    """Pages 200/301/404 → only the 301 row appears."""
    _make_page(session, "https://example.com/ok", http_status_code=200)
    _make_page(
        session,
        "https://example.com/old",
        http_status_code=301,
        final_url="https://example.com/new",
        redirect_chain=["https://example.com/old", "https://example.com/new"],
    )
    _make_page(session, "https://example.com/missing", http_status_code=404)

    record = ExportService.create_export(session, "redirects.csv")
    assert record.filename == "redirects.csv"
    assert record.content_type == "text/csv"
    assert record.row_count == 1

    lines = _csv_lines(record.content)
    assert lines[0] == "url,http_status_code,final_url,redirect_chain"
    assert len(lines) == 2

    data_line = lines[1]
    assert "https://example.com/old" in data_line
    assert "301" in data_line
    assert "https://example.com/new" in data_line


# ─────────────────────────────────────────────────────────────
# 10. metadata.json — structure
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_metadata_json_structure(session):
    """Metadata JSON has session/totals/issue_summary keys and parses."""
    _make_page(session, "https://example.com/a")

    record = ExportService.create_export(session, "metadata.json")
    assert record.filename == "metadata.json"
    assert record.content_type == "application/json"

    payload = json.loads(record.content)
    assert set(payload.keys()) == {"session", "totals", "issue_summary"}
    assert payload["totals"]["pages"] == 1
    assert isinstance(payload["issue_summary"], list)
    assert len(payload["issue_summary"]) == 12


# ─────────────────────────────────────────────────────────────
# 11. create_export persists a row
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_export_persists_record(session):
    """After create, exactly one ExportRecord exists for the session."""
    ExportService.create_export(session, "urls.csv")
    assert (
        ExportRecord.objects.filter(crawl_session=session).count() == 1
    )


# ─────────────────────────────────────────────────────────────
# 12. get_export round-trip
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_get_export_returns_record(session):
    """Round-trip: create then fetch by id."""
    record = ExportService.create_export(session, "urls.csv")
    fetched = ExportService.get_export(session, str(record.id))
    assert fetched.id == record.id
    assert fetched.kind == "urls.csv"


# ─────────────────────────────────────────────────────────────
# 13. get_export wrong session raises
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_get_export_wrong_session_raises(website, session):
    """A record from session A is not visible to session B."""
    other_session = CrawlSession.objects.create(website=website)
    record = ExportService.create_export(session, "urls.csv")

    with pytest.raises(ExportRecord.DoesNotExist):
        ExportService.get_export(other_session, str(record.id))


# ─────────────────────────────────────────────────────────────
# 14. list_exports shape
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_list_exports_returns_serialized_dicts(session):
    """Each item carries the documented key set."""
    ExportService.create_export(session, "urls.csv")
    items = ExportService.list_exports(session)

    assert len(items) == 1
    expected_keys = {
        "id", "kind", "filename", "content_type",
        "row_count", "size_bytes", "generated_at",
    }
    assert set(items[0].keys()) == expected_keys


# ─────────────────────────────────────────────────────────────
# 15. list_exports ordering — newest first
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_two_exports_ordered_newest_first(session):
    """Two exports → list_exports[0] is the most recent (sitemap.xml).

    On fast machines two consecutive ``auto_now_add`` writes can land in
    the same microsecond, so we explicitly back-date the first record to
    keep the assertion deterministic.
    """
    from datetime import timedelta
    from django.utils import timezone

    first = ExportService.create_export(session, "urls.csv")
    # Force the older record to have an earlier generated_at so the
    # ordering test is independent of system clock resolution.
    older_ts = timezone.now() - timedelta(seconds=1)
    ExportRecord.objects.filter(pk=first.pk).update(generated_at=older_ts)

    ExportService.create_export(session, "sitemap.xml")

    items = ExportService.list_exports(session)
    assert len(items) == 2
    assert items[0]["kind"] == "sitemap.xml"
    assert items[1]["kind"] == "urls.csv"


# ─────────────────────────────────────────────────────────────
# Bonus: broken-links source-URL cap (stated requirement)
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_broken_links_csv_caps_source_urls_at_five(session):
    """When a 404 has many sources, only 5 appear in source_urls cell."""
    target = "https://example.com/missing"
    _make_page(session, target, http_status_code=404)
    for i in range(10):
        Link.objects.create(
            crawl_session=session,
            source_url=f"https://example.com/source-{i}",
            target_url=target,
            link_type=constants.LINK_TYPE_INTERNAL,
        )

    record = ExportService.create_export(session, "broken-links.csv")
    lines = _csv_lines(record.content)
    data = lines[1]
    # Count semicolons — 5 sources → 4 separators within the source cell.
    sources_cell = data.rsplit(",", 1)[-1]
    assert sources_cell.count(";") == 4
    assert sources_cell.count("https://example.com/source-") == 5
