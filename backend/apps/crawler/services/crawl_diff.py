"""Compare two CrawlSnapshot rows — Phase 5b.

Produces a SEMrush "Compare Crawls"-style diff between any two
snapshots regardless of engine (legacy / scrapy). The UI surfaces:

  * Fixed   — URLs in A with at least one error, no errors in B
  * New     — URLs without errors in A, at least one error in B
  * Changed — URLs in both A and B but with a different error set
  * Pages   — added / removed / status-changed at the URL level

Reads CrawlerPageResult + CrawlIssue rows directly so it works
regardless of which engine produced either snapshot — both engines
write the same shape via the Phase 3c dual-write hook.

When CrawlIssue rows are absent (audit runner hasn't backfilled the
snapshot yet — common today, where issues are computed on-the-fly per
request rather than persisted) we fall back to running the audit
against the snapshot's page rows in memory. Slower but always works.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

log = logging.getLogger("apps.crawler.services.crawl_diff")


@dataclass
class IssueDiff:
    slug: str
    title: str
    severity: str
    category: str
    a_count: int
    b_count: int
    delta: int      # b_count - a_count (negative = improvement)
    fixed_urls: list[str]
    new_urls: list[str]
    changed_urls: list[str]


@dataclass
class PageDiff:
    url: str
    in_a: bool
    in_b: bool
    a_status: str
    b_status: str
    a_word_count: int
    b_word_count: int


@dataclass
class CrawlDiff:
    a_snapshot_id: str
    b_snapshot_id: str
    a_started_at: str
    b_started_at: str
    a_engine: str
    b_engine: str
    a_health_score: int | None
    b_health_score: int | None
    health_score_delta: int | None
    # Per-issue diffs (sorted by abs(delta) desc — biggest moves first)
    issues: list[IssueDiff]
    # Per-URL diffs (capped at 1000 to keep payload bounded)
    pages_added: list[PageDiff]
    pages_removed: list[PageDiff]
    pages_status_changed: list[PageDiff]
    # Aggregates
    fixed_count: int       # URL-level fixed across all issues
    new_count: int
    changed_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "a_snapshot_id": self.a_snapshot_id,
            "b_snapshot_id": self.b_snapshot_id,
            "a_started_at": self.a_started_at,
            "b_started_at": self.b_started_at,
            "a_engine": self.a_engine,
            "b_engine": self.b_engine,
            "a_health_score": self.a_health_score,
            "b_health_score": self.b_health_score,
            "health_score_delta": self.health_score_delta,
            "issues": [asdict(d) for d in self.issues],
            "pages_added": [asdict(p) for p in self.pages_added],
            "pages_removed": [asdict(p) for p in self.pages_removed],
            "pages_status_changed": [asdict(p) for p in self.pages_status_changed],
            "fixed_count": self.fixed_count,
            "new_count": self.new_count,
            "changed_count": self.changed_count,
        }


def _issue_urls_for_snapshot(snap, page_rows: dict[str, dict]) -> dict[str, set[str]]:
    """Return {issue_slug: {urls_that_triggered}} for one snapshot.

    First tries the persisted CrawlIssue rows. If empty (the audit
    runner hasn't been wired to persist yet), falls back to running
    the audit catalog against the snapshot's page rows in memory.
    """
    from ..models import CrawlIssue
    from ..audits import run_all

    persisted = (
        CrawlIssue.objects.filter(snapshot=snap)
        .values_list("issue_slug", "url")
    )
    persisted = list(persisted)
    if persisted:
        out: dict[str, set[str]] = defaultdict(set)
        for slug, url in persisted:
            if url:
                out[slug].add(url)
        return dict(out)

    # Fallback: re-run the audit catalog against the snapshot's pages.
    # Convert ORM rows to CSV-row-dict shape (matches what audit
    # detectors expect — same shape as the legacy CSV read path).
    rows = [
        {
            "url": p.get("url") or "",
            "status_code": p.get("status_code") or "",
            "title": p.get("title") or "",
            "word_count": str(p.get("word_count") or 0),
            "response_time_ms": str(p.get("response_time_ms") or 0),
            "content_type": p.get("content_type") or "",
            "error_type": p.get("error_type") or "",
            "error_message": p.get("error_message") or "",
            "subdomain": p.get("subdomain") or "",
            "page_type": p.get("page_type") or "",
            "category_key": p.get("category_key") or "",
            "from_sitemap": "1" if p.get("from_sitemap") else "0",
            "indexed_status": p.get("indexed_status") or "unknown",
            "pagespeed_score": "" if p.get("pagespeed_score") is None else str(p["pagespeed_score"]),
            "lcp_ms": "" if p.get("lcp_ms") is None else str(p["lcp_ms"]),
            "cls": "" if p.get("cls") is None else str(p["cls"]),
            "inp_ms": "" if p.get("inp_ms") is None else str(p["inp_ms"]),
        }
        for p in page_rows.values()
    ]
    audit = run_all(rows)
    out: dict[str, set[str]] = defaultdict(set)
    for occ in audit.occurrences:
        if occ.count == 0:
            continue
        for r in occ.affected_urls:
            url = (r.get("url") or "").strip()
            if url:
                out[occ.issue.slug].add(url)
    return dict(out)


def _page_rows_for_snapshot(snap) -> dict[str, dict]:
    """Return {url: dict} for every CrawlerPageResult in a snapshot.

    Only loads the fields the diff actually needs to keep memory small
    on large snapshots."""
    from ..models import CrawlerPageResult
    out: dict[str, dict] = {}
    qs = CrawlerPageResult.objects.filter(snapshot=snap).only(
        "url", "status_code", "title", "word_count",
        "response_time_ms", "content_type", "error_type",
        "error_message", "subdomain", "page_type",
        "category_key", "from_sitemap", "indexed_status",
        "pagespeed_score", "lcp_ms", "cls", "inp_ms",
    )
    for p in qs.iterator(chunk_size=1000):
        out[p.url] = {
            "url": p.url,
            "status_code": p.status_code,
            "title": p.title,
            "word_count": p.word_count,
            "response_time_ms": p.response_time_ms,
            "content_type": p.content_type,
            "error_type": p.error_type,
            "error_message": p.error_message,
            "subdomain": p.subdomain,
            "page_type": p.page_type,
            "category_key": p.category_key,
            "from_sitemap": p.from_sitemap,
            "indexed_status": p.indexed_status,
            "pagespeed_score": p.pagespeed_score,
            "lcp_ms": p.lcp_ms,
            "cls": p.cls,
            "inp_ms": p.inp_ms,
        }
    return out


def diff(a_snapshot_id: str, b_snapshot_id: str, *, url_cap: int = 1000) -> CrawlDiff:
    """Compute a full diff between two snapshot ids.

    Either id can refer to any engine (legacy or scrapy). Returns a
    structured CrawlDiff dataclass; callers serialize via as_dict()
    for the JSON response.
    """
    from ..audits.catalog import ISSUES_BY_SLUG
    from ..models import CrawlSnapshot

    a = CrawlSnapshot.objects.get(pk=a_snapshot_id)
    b = CrawlSnapshot.objects.get(pk=b_snapshot_id)

    a_pages = _page_rows_for_snapshot(a)
    b_pages = _page_rows_for_snapshot(b)
    a_issues = _issue_urls_for_snapshot(a, a_pages)
    b_issues = _issue_urls_for_snapshot(b, b_pages)

    # ── Per-issue diff ──
    all_slugs = set(a_issues) | set(b_issues)
    issue_diffs: list[IssueDiff] = []
    fixed_total: set[str] = set()
    new_total: set[str] = set()
    changed_total: set[str] = set()

    for slug in all_slugs:
        a_set = a_issues.get(slug, set())
        b_set = b_issues.get(slug, set())
        fixed = sorted(a_set - b_set)
        new = sorted(b_set - a_set)
        changed = sorted(a_set & b_set)  # still firing on both sides
        fixed_total.update(fixed)
        new_total.update(new)
        changed_total.update(changed)
        meta = ISSUES_BY_SLUG.get(slug)
        title = meta.title if meta else slug
        severity = meta.severity if meta else "warning"
        category = meta.category if meta else "unknown"
        issue_diffs.append(IssueDiff(
            slug=slug,
            title=title,
            severity=severity,
            category=category,
            a_count=len(a_set),
            b_count=len(b_set),
            delta=len(b_set) - len(a_set),
            fixed_urls=fixed[:url_cap],
            new_urls=new[:url_cap],
            changed_urls=changed[:url_cap],
        ))

    # Sort by abs delta desc so the biggest movers surface first;
    # ties broken by b_count desc.
    issue_diffs.sort(key=lambda d: (-abs(d.delta), -d.b_count))

    # ── Per-URL page diff ──
    a_urls = set(a_pages)
    b_urls = set(b_pages)
    common = a_urls & b_urls
    added_urls = sorted(b_urls - a_urls)[:url_cap]
    removed_urls = sorted(a_urls - b_urls)[:url_cap]
    status_changed: list[PageDiff] = []
    for url in common:
        ap = a_pages[url]; bp = b_pages[url]
        if (ap.get("status_code") or "") != (bp.get("status_code") or ""):
            status_changed.append(PageDiff(
                url=url, in_a=True, in_b=True,
                a_status=ap.get("status_code") or "",
                b_status=bp.get("status_code") or "",
                a_word_count=ap.get("word_count") or 0,
                b_word_count=bp.get("word_count") or 0,
            ))
    status_changed = status_changed[:url_cap]

    pages_added = [
        PageDiff(
            url=u, in_a=False, in_b=True,
            a_status="", b_status=b_pages[u].get("status_code") or "",
            a_word_count=0, b_word_count=b_pages[u].get("word_count") or 0,
        )
        for u in added_urls
    ]
    pages_removed = [
        PageDiff(
            url=u, in_a=True, in_b=False,
            a_status=a_pages[u].get("status_code") or "", b_status="",
            a_word_count=a_pages[u].get("word_count") or 0, b_word_count=0,
        )
        for u in removed_urls
    ]

    return CrawlDiff(
        a_snapshot_id=str(a.id),
        b_snapshot_id=str(b.id),
        a_started_at=a.started_at.isoformat() if a.started_at else "",
        b_started_at=b.started_at.isoformat() if b.started_at else "",
        a_engine=a.engine,
        b_engine=b.engine,
        a_health_score=a.health_score,
        b_health_score=b.health_score,
        health_score_delta=(
            (b.health_score - a.health_score)
            if (a.health_score is not None and b.health_score is not None)
            else None
        ),
        issues=issue_diffs,
        pages_added=pages_added,
        pages_removed=pages_removed,
        pages_status_changed=status_changed,
        fixed_count=len(fixed_total),
        new_count=len(new_total),
        changed_count=len(changed_total),
    )


def latest_two_snapshots() -> tuple[str, str] | None:
    """Convenience for the /compare endpoint when no IDs are given —
    returns (older_id, newer_id) so the operator sees most-recent
    movement by default."""
    from ..models import CrawlSnapshot
    rows = list(
        CrawlSnapshot.objects.order_by("-started_at").values_list("id", flat=True)[:2]
    )
    if len(rows) < 2:
        return None
    return (str(rows[1]), str(rows[0]))
