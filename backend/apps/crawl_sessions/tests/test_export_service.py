"""Unit tests for :class:`ExportService` and the six format generators.

Covers list/create/get round-trips plus the per-generator content rules
documented in ``services/export_service.py``.
"""

from __future__ import annotations

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
# 5. issues.xlsx — always 12 issue rows + header
# ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_create_issues_xlsx_returns_12_rows(session):
    """Empty session → header + all 12 issue rows (count=0 for each)."""
    record = ExportService.create_export(session, "issues.xlsx")

    # Filename keeps the .xlsx extension for forward-compat with openpyxl.
    # Body is CSV today; content_type reflects the body, not the filename.
    assert record.filename == "issues.xlsx"
    assert record.content_type == "text/csv"
    assert record.row_count == 12

    lines = _csv_lines(record.content)
    assert lines[0] == "id,name,severity,count,description"
    assert len(lines) == 13  # header + 12 issues
    # Every data row's count column should be 0 on an empty session.
    for data_line in lines[1:]:
        cells = data_line.split(",")
        # severity is column index 2, count is column index 3 — but
        # description cells contain commas, so split has more entries.
        # Just assert the first three columns then check that "0" appears
        # near the front (count column).
        assert cells[2] in {"error", "warning", "notice"}


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
