"""Export generation service for the Lattice SEO crawler dashboard.

Powers the Exports page (list + generate + download) and the per-screen
"Export CSV" buttons across Pages/Issues/etc.

This module owns:
- The six format generators (`_gen_urls_csv`, `_gen_issues_xlsx`, ...).
- The :class:`ExportService` facade used by the views layer.

Design notes
------------
* All generators are pure: they take a :class:`CrawlSession` and return
  a ``(content, content_type, filename, row_count)`` tuple. They do NOT
  persist anything; persistence happens in :meth:`ExportService.create_export`.
* Content is held in-memory and stored in the ``ExportRecord.content``
  TextField. v1 cap is 50k URLs ~ 10MB worst case, which Postgres TEXT
  handles trivially.
* CSV writers use ``lineterminator="\\n"`` so output is platform-stable
  and tests can split on ``"\\n"`` without CRLF surprises.
"""

from __future__ import annotations

import csv
import io
import json
from xml.sax.saxutils import escape as xml_escape

from apps.crawl_sessions.models import CrawlSession, ExportRecord, Link, Page
from apps.crawl_sessions.services.issue_service import IssueService


# Cap source URLs per row in the broken-links export to keep cells small.
_BROKEN_LINK_SOURCE_CAP = 5


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _csv_writer(buf: io.StringIO):
    """Return a csv.writer that emits LF line endings (no CRLF)."""
    return csv.writer(buf, lineterminator="\n")


# ─────────────────────────────────────────────────────────────
# Generators — one per export kind
# Each returns (content, content_type, filename, row_count).
# ─────────────────────────────────────────────────────────────

def _gen_urls_csv(session: CrawlSession) -> tuple[str, str, str, int]:
    """Generate ``urls.csv`` — one row per Page in the session."""
    buf = io.StringIO()
    writer = _csv_writer(buf)
    writer.writerow([
        "url", "http_status_code", "title", "crawl_depth",
        "load_time_ms", "word_count", "is_https", "source",
    ])

    pages = (
        Page.objects.filter(crawl_session=session)
        .only(
            "url", "http_status_code", "title", "crawl_depth",
            "load_time_ms", "word_count", "is_https", "source",
        )
        .order_by("url")
    )
    row_count = 0
    for p in pages:
        writer.writerow([
            p.url,
            p.http_status_code if p.http_status_code is not None else "",
            p.title,
            p.crawl_depth,
            p.load_time_ms if p.load_time_ms is not None else "",
            p.word_count,
            "true" if p.is_https else "false",
            p.source,
        ])
        row_count += 1

    return buf.getvalue(), "text/csv", "urls.csv", row_count


def _gen_issues_xlsx(session: CrawlSession) -> tuple[str, str, str, int]:
    """Generate the Issues export.

    The ``.xlsx`` filename is preserved in the URL for forward
    compatibility, but the body is CSV until the project picks up the
    ``openpyxl`` dependency.

    # TODO: real xlsx via openpyxl when the package lands
    """
    buf = io.StringIO()
    writer = _csv_writer(buf)
    writer.writerow(["id", "name", "severity", "count", "description"])

    issues = IssueService.derive_issues(session)
    for issue in issues:
        writer.writerow([
            issue["id"],
            issue["name"],
            issue["severity"],
            issue["count"],
            issue["description"],
        ])

    # content_type stays text/csv because the body is CSV; the filename
    # carries the .xlsx extension so URL routing stays stable.
    return buf.getvalue(), "text/csv", "issues.xlsx", len(issues)


def _gen_sitemap_xml(session: CrawlSession) -> tuple[str, str, str, int]:
    """Generate a sitemap XML listing every status-200 page in the session."""
    pages = (
        Page.objects.filter(crawl_session=session, http_status_code=200)
        .only("url")
        .order_by("url")
    )

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    row_count = 0
    for p in pages:
        parts.append(f"  <url><loc>{xml_escape(p.url)}</loc></url>")
        row_count += 1
    parts.append("</urlset>")
    parts.append("")  # trailing newline

    return "\n".join(parts), "application/xml", "sitemap.xml", row_count


def _gen_broken_links_csv(session: CrawlSession) -> tuple[str, str, str, int]:
    """Generate ``broken-links.csv`` — one row per page with status >= 400."""
    buf = io.StringIO()
    writer = _csv_writer(buf)
    writer.writerow(["url", "http_status_code", "source_urls"])

    broken = (
        Page.objects.filter(
            crawl_session=session,
            http_status_code__gte=400,
        )
        .only("url", "http_status_code")
        .order_by("url")
    )
    row_count = 0
    for p in broken:
        sources = list(
            Link.objects.filter(
                crawl_session=session,
                target_url=p.url,
                link_type="internal",
            )
            .values_list("source_url", flat=True)
            .distinct()[:_BROKEN_LINK_SOURCE_CAP]
        )
        writer.writerow([
            p.url,
            p.http_status_code if p.http_status_code is not None else "",
            ";".join(sources),
        ])
        row_count += 1

    return buf.getvalue(), "text/csv", "broken-links.csv", row_count


def _gen_redirects_csv(session: CrawlSession) -> tuple[str, str, str, int]:
    """Generate ``redirects.csv`` — one row per page with 300 <= status < 400."""
    buf = io.StringIO()
    writer = _csv_writer(buf)
    writer.writerow([
        "url", "http_status_code", "final_url", "redirect_chain",
    ])

    redirects = (
        Page.objects.filter(
            crawl_session=session,
            http_status_code__gte=300,
            http_status_code__lt=400,
        )
        .only("url", "http_status_code", "final_url", "redirect_chain")
        .order_by("url")
    )
    row_count = 0
    for p in redirects:
        chain = p.redirect_chain or []
        # redirect_chain is stored as a JSONField list of hops; flatten
        # each hop to a string so the cell is reader-friendly.
        chain_text = ";".join(str(hop) for hop in chain)
        writer.writerow([
            p.url,
            p.http_status_code if p.http_status_code is not None else "",
            p.final_url,
            chain_text,
        ])
        row_count += 1

    return buf.getvalue(), "text/csv", "redirects.csv", row_count


def _gen_metadata_json(session: CrawlSession) -> tuple[str, str, str, int]:
    """Generate ``metadata.json`` — session core fields + totals + issue summary.

    ``row_count`` is set to the number of issue summary entries (always 12)
    so it is non-zero and meaningful for the UI badge.
    """
    pages_qs = Page.objects.filter(crawl_session=session)
    links_qs = Link.objects.filter(crawl_session=session)

    issue_summary = IssueService.derive_issues(session)

    payload = {
        "session": {
            "id": str(session.id),
            "website": session.website.domain if session.website_id else "",
            "session_type": session.session_type,
            "status": session.status,
            "started_at": session.started_at,
            "finished_at": session.finished_at,
            "duration_seconds": session.duration_seconds,
            "total_urls_discovered": session.total_urls_discovered,
            "total_urls_crawled": session.total_urls_crawled,
            "total_urls_failed": session.total_urls_failed,
            "max_depth_reached": session.max_depth_reached,
            "avg_response_time_ms": session.avg_response_time_ms,
        },
        "totals": {
            "pages": pages_qs.count(),
            "links": links_qs.count(),
            "issues": sum(item["count"] for item in issue_summary),
        },
        "issue_summary": issue_summary,
    }

    # ``default=str`` handles datetime/UUID values without us having to
    # serialize them by hand.
    content = json.dumps(payload, indent=2, default=str)
    return content, "application/json", "metadata.json", len(issue_summary)


# ─────────────────────────────────────────────────────────────
# Generator registry
# ─────────────────────────────────────────────────────────────
_GENERATORS = {
    ExportRecord.KIND_URLS_CSV: _gen_urls_csv,
    ExportRecord.KIND_ISSUES_XLSX: _gen_issues_xlsx,
    ExportRecord.KIND_SITEMAP_XML: _gen_sitemap_xml,
    ExportRecord.KIND_BROKEN_LINKS_CSV: _gen_broken_links_csv,
    ExportRecord.KIND_REDIRECTS_CSV: _gen_redirects_csv,
    ExportRecord.KIND_METADATA_JSON: _gen_metadata_json,
}


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────
class ExportService:
    """Generate, list, and retrieve export artifacts for a crawl session.

    All methods are static — no instance state. Mirrors the shape of
    :class:`SnapshotService`/:class:`IssueService` for consistency.
    """

    KINDS = (
        ExportRecord.KIND_URLS_CSV,
        ExportRecord.KIND_ISSUES_XLSX,
        ExportRecord.KIND_SITEMAP_XML,
        ExportRecord.KIND_BROKEN_LINKS_CSV,
        ExportRecord.KIND_REDIRECTS_CSV,
        ExportRecord.KIND_METADATA_JSON,
    )

    @staticmethod
    def list_exports(session: CrawlSession) -> list[dict]:
        """Return existing ExportRecord rows as serialized dicts.

        Each item: ``{id, kind, filename, content_type, row_count,
        size_bytes, generated_at}``. Ordered by ``-generated_at``.
        """
        records = (
            ExportRecord.objects
            .filter(crawl_session=session)
            .only(
                "id", "kind", "filename", "content_type",
                "row_count", "size_bytes", "generated_at",
            )
            # Secondary ``-id`` keeps ordering deterministic when two
            # records share a generated_at — possible on fast machines
            # where ``auto_now_add`` writes land in the same microsecond.
            .order_by("-generated_at", "-id")
        )
        return [
            {
                "id": str(r.id),
                "kind": r.kind,
                "filename": r.filename,
                "content_type": r.content_type,
                "row_count": r.row_count,
                "size_bytes": r.size_bytes,
                "generated_at": r.generated_at,
            }
            for r in records
        ]

    @staticmethod
    def create_export(session: CrawlSession, kind: str) -> ExportRecord:
        """Generate a new export of the given kind and persist it.

        Raises:
            ValueError: when ``kind`` is not one of :attr:`KINDS`.

        Returns the persisted :class:`ExportRecord` with ``content``
        populated.
        """
        if kind not in _GENERATORS:
            raise ValueError(
                f"Unknown export kind: {kind!r}. "
                f"Expected one of {ExportService.KINDS}."
            )

        generator = _GENERATORS[kind]
        content, content_type, filename, row_count = generator(session)

        # size_bytes is computed centrally so generators stay simple and
        # consistent — UTF-8 byte length matches what the download view
        # would actually transmit.
        size_bytes = len(content.encode("utf-8"))

        record = ExportRecord.objects.create(
            crawl_session=session,
            kind=kind,
            content=content,
            content_type=content_type,
            filename=filename,
            row_count=row_count,
            size_bytes=size_bytes,
        )
        return record

    @staticmethod
    def get_export(session: CrawlSession, export_id: str) -> ExportRecord:
        """Retrieve a single ExportRecord by id, scoped to ``session``.

        Raises:
            ExportRecord.DoesNotExist: when no record matches both
            ``id == export_id`` AND ``crawl_session == session``.
        """
        return ExportRecord.objects.get(pk=export_id, crawl_session=session)
