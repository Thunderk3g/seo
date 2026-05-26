"""ChangeWatcher — append competitor-page revisions and emit change events.

The competitor link-walking spider re-crawls a domain on a schedule
(Celery beat job, Day 4). Each crawl produces CrawlerPageResult rows
that get overwritten next crawl. The ChangeWatcher reads those fresh
rows, hashes them three ways (title / content / structure), and:

  1. Appends a :class:`CompetitorPageHistory` row when any hash differs
     from the most recent prior history row for that URL.
  2. Emits a :class:`CompetitorChangeEvent` for the operator-visible
     "this competitor changed X" surface — one event per distinct
     hash transition (title, content, structure all fire separately).
  3. Detects new-URL events on first sight, and dropped-URL events
     when a previously-known URL is missing from a fresh crawl of
     its competitor.

Why this is a service, not a Scrapy pipeline:

* The pipeline persists CrawlerPageResult; that table is the source
  of truth for "what does this page look like right now". History is
  a *downstream* projection. Keeping them separated means the
  ChangeWatcher can be re-run against historical CrawlerPageResult
  snapshots without re-crawling, which is gold for backfilling.
* Scrapy pipelines run inside the Twisted reactor — Django ORM
  writes there require ``sync_to_async`` dance. ChangeWatcher runs
  in the regular Celery worker, no async dance needed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid as _uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


def _coerce_uuid(val) -> _uuid.UUID | None:
    """Coerce a snapshot_id-ish value into a UUID or None.

    The real CrawlerPageResult row already carries a UUID, but the
    backfill / replay paths (and unit tests) sometimes pass strings
    or already-UUIDs. UUIDField rejects non-canonical strings outright;
    we want a tolerant adapter, not a hard failure.
    """
    if val is None or val == "":
        return None
    if isinstance(val, _uuid.UUID):
        return val
    try:
        return _uuid.UUID(str(val))
    except (TypeError, ValueError):
        return None

from django.db import transaction

from ..models import (
    CompetitorChangeEvent,
    CompetitorPageHistory,
)

log = logging.getLogger("seo.ai.services.change_watcher")


# ── Hash helpers ─────────────────────────────────────────────────────


def _short_sha(text: str) -> str:
    """16-char hex prefix of sha256 — enough collision resistance for
    1M URLs (collision prob ~1e-10) and 4× shorter than full sha256."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _title_hash(row) -> str:
    return _short_sha((row.title or "").strip().lower())


def _content_hash(row) -> str:
    """Coarse body-content hash.

    We deliberately *don't* hash the raw body_text — that's noisy with
    ad rotations, A/B price tags, JS-injected widgets. Instead we hash
    a normalised slug: lowercased, whitespace-collapsed, first 8000
    chars. Stable enough that two re-crawls of the same page hash
    identically; sensitive enough to flip when a paragraph changes.
    """
    text = (row.body_text or "").strip().lower()
    text = " ".join(text.split())[:8000]
    return _short_sha(text)


def _structure_hash(row) -> str:
    """Hash of the page outline — heading text + internal-link kinds.

    Fires when sections get added/removed/reordered or when the IA
    pattern (which kinds of links the page exposes) changes. Title
    rewording alone doesn't flip this; restructuring does.
    """
    headings = row.headings_json or []
    links = row.internal_links_json or []
    skeleton = {
        "h": [
            f"h{int(h.get('level') or 1)}:{(h.get('text') or '')[:120].lower()}"
            for h in headings
        ],
        "k": sorted({
            (l.get("kind") or "other") for l in links if l
        }),
    }
    return _short_sha(json.dumps(skeleton, sort_keys=True))


# ── public API ───────────────────────────────────────────────────────


@dataclass
class WatchResult:
    """What ChangeWatcher did on one row.

    ``history`` is the persisted CompetitorPageHistory row (always
    present — first sight always creates a row). ``events`` is the
    list of CompetitorChangeEvent rows fired this run (empty when
    nothing changed).
    """

    history: CompetitorPageHistory
    events: list[CompetitorChangeEvent]
    is_first_sight: bool


def watch_row(row, *, competitor_domain: str = "") -> WatchResult:
    """Record one CrawlerPageResult row in the history log and fire
    change events for any hash transition.

    Idempotent: re-running against the same row with identical hashes
    is a no-op (no new history row, no events). The caller (the
    pipeline-close hook or the periodic Celery job) is free to call
    this repeatedly.
    """
    # Derive competitor domain if caller didn't supply one. The
    # pipeline stamps row.category_key with the target domain; falls
    # back to URL host if that's empty.
    if not competitor_domain:
        competitor_domain = (
            row.category_key
            or (urlparse(row.url).hostname or "")
        ).lower().lstrip("www.")

    t_hash = _title_hash(row)
    c_hash = _content_hash(row)
    s_hash = _structure_hash(row)

    prior = (
        CompetitorPageHistory.objects.filter(url=row.url)
        .order_by("-seen_at")
        .first()
    )

    # No prior → first sight. Always append.
    if prior is None:
        with transaction.atomic():
            history = CompetitorPageHistory.objects.create(
                url=row.url,
                competitor_domain=competitor_domain,
                snapshot_id=_coerce_uuid(getattr(row, "snapshot_id", None)),
                title=(row.title or "")[:1024],
                meta_description=(row.meta_description or "")[:1024],
                word_count=row.word_count or 0,
                heading_count=len(row.headings_json or []),
                internal_link_count=len(row.internal_links_json or []),
                image_count=len(row.images_json or []),
                title_hash=t_hash,
                content_hash=c_hash,
                structure_hash=s_hash,
                delta={},
            )
            event = CompetitorChangeEvent.objects.create(
                url=row.url,
                competitor_domain=competitor_domain,
                kind=CompetitorChangeEvent.ChangeKind.NEW,
                from_history=None,
                to_history=history,
                delta={
                    "title": history.title,
                    "headings": history.heading_count,
                    "links": history.internal_link_count,
                },
            )
        return WatchResult(history=history, events=[event], is_first_sight=True)

    # Identical hashes → no-op. Don't pollute the log with re-crawls
    # that found nothing.
    if (
        prior.title_hash == t_hash
        and prior.content_hash == c_hash
        and prior.structure_hash == s_hash
    ):
        return WatchResult(history=prior, events=[], is_first_sight=False)

    # Something flipped → append history + fire one event per dimension.
    delta: dict[str, Any] = {}
    fired_kinds: list[str] = []

    if prior.title_hash != t_hash:
        delta["title"] = {"from": prior.title, "to": (row.title or "")[:300]}
        fired_kinds.append(CompetitorChangeEvent.ChangeKind.TITLE)
    if prior.content_hash != c_hash:
        delta["content"] = {
            "word_count_from": prior.word_count,
            "word_count_to": row.word_count or 0,
        }
        fired_kinds.append(CompetitorChangeEvent.ChangeKind.CONTENT)
    if prior.structure_hash != s_hash:
        delta["structure"] = {
            "heading_count_from": prior.heading_count,
            "heading_count_to": len(row.headings_json or []),
            "link_count_from": prior.internal_link_count,
            "link_count_to": len(row.internal_links_json or []),
        }
        fired_kinds.append(CompetitorChangeEvent.ChangeKind.STRUCTURE)

    events: list[CompetitorChangeEvent] = []
    with transaction.atomic():
        history = CompetitorPageHistory.objects.create(
            url=row.url,
            competitor_domain=competitor_domain,
            snapshot_id=_coerce_uuid(getattr(row, "snapshot_id", None)),
            title=(row.title or "")[:1024],
            meta_description=(row.meta_description or "")[:1024],
            word_count=row.word_count or 0,
            heading_count=len(row.headings_json or []),
            internal_link_count=len(row.internal_links_json or []),
            image_count=len(row.images_json or []),
            title_hash=t_hash,
            content_hash=c_hash,
            structure_hash=s_hash,
            delta=delta,
        )
        for kind in fired_kinds:
            events.append(
                CompetitorChangeEvent.objects.create(
                    url=row.url,
                    competitor_domain=competitor_domain,
                    kind=kind,
                    from_history=prior,
                    to_history=history,
                    delta=delta.get(kind, {}),
                )
            )
    log.info(
        "ChangeWatcher: %s url=%s kinds=%s",
        competitor_domain, row.url, fired_kinds,
    )
    return WatchResult(history=history, events=events, is_first_sight=False)


def watch_snapshot(snapshot_id: str) -> dict[str, int]:
    """Run :func:`watch_row` over every row in a competitor CrawlSnapshot.

    Returns counters: ``{rows, new_urls, title_changes, content_changes,
    structure_changes, no_op}``. Use this from the Celery post-crawl
    hook or the management command.
    """
    from apps.crawler.models import CrawlerPageResult

    counters = {
        "rows": 0, "new_urls": 0,
        "title_changes": 0, "content_changes": 0,
        "structure_changes": 0, "no_op": 0,
    }
    rows = CrawlerPageResult.objects.filter(snapshot_id=snapshot_id)
    for row in rows.iterator(chunk_size=200):
        counters["rows"] += 1
        try:
            result = watch_row(row)
        except Exception as exc:  # noqa: BLE001 — never break the crawl
            log.warning(
                "ChangeWatcher: skipping %s (%s)", row.url, exc,
            )
            continue
        if result.is_first_sight:
            counters["new_urls"] += 1
            continue
        if not result.events:
            counters["no_op"] += 1
            continue
        for ev in result.events:
            if ev.kind == CompetitorChangeEvent.ChangeKind.TITLE:
                counters["title_changes"] += 1
            elif ev.kind == CompetitorChangeEvent.ChangeKind.CONTENT:
                counters["content_changes"] += 1
            elif ev.kind == CompetitorChangeEvent.ChangeKind.STRUCTURE:
                counters["structure_changes"] += 1
    log.info("ChangeWatcher snapshot=%s counters=%s", snapshot_id, counters)
    return counters


def watch_removed_urls(
    competitor_domain: str,
    *,
    fresh_urls: set[str],
) -> list[CompetitorChangeEvent]:
    """Detect URLs that disappeared between crawls.

    Given a freshly crawled URL set for ``competitor_domain``, find any
    URLs we've previously seen for this competitor but which are not
    in ``fresh_urls``, and fire a REMOVED event for each. We only fire
    REMOVED once per (url, gone) transition — if the last history row
    is already REMOVED we skip.

    This is a separate function because Scrapy doesn't tell us "URLs
    we DIDN'T find" — we have to diff after the fact against the
    history.
    """
    if not competitor_domain:
        return []
    domain = competitor_domain.lower().lstrip("www.")
    known_urls = set(
        CompetitorPageHistory.objects.filter(
            competitor_domain=domain,
        )
        .order_by("url", "-seen_at")
        .values_list("url", flat=True)
        .distinct()
    )
    removed = known_urls - fresh_urls
    if not removed:
        return []
    events: list[CompetitorChangeEvent] = []
    for url in removed:
        # Skip if the most recent event for this URL is already REMOVED.
        last_ev = (
            CompetitorChangeEvent.objects.filter(
                competitor_domain=domain, url=url,
            )
            .order_by("-detected_at")
            .first()
        )
        if last_ev and last_ev.kind == CompetitorChangeEvent.ChangeKind.REMOVED:
            continue
        last_hist = (
            CompetitorPageHistory.objects.filter(url=url)
            .order_by("-seen_at")
            .first()
        )
        events.append(
            CompetitorChangeEvent.objects.create(
                url=url,
                competitor_domain=domain,
                kind=CompetitorChangeEvent.ChangeKind.REMOVED,
                from_history=last_hist,
                to_history=None,
                delta={"last_seen_at": (
                    last_hist.seen_at.isoformat() if last_hist else None
                )},
            )
        )
    log.info(
        "ChangeWatcher: %s removed %d URL(s)", domain, len(events),
    )
    return events
