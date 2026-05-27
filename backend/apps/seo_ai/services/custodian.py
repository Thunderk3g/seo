"""DataCustodian services — single source of truth per domain.

The agent fleet vision:

    OurDataCustodian        — owns everything about bajajlifeinsurance.com.
    TheirDataCustodian(N)   — one instance per competitor, owns everything
                              we know about that competitor.
    SiteDifferAgent         — calls both, computes deltas, surfaces gaps.
    ContentWriterAgent      — calls custodians for evidence, writes rewrites.

This module is the DATA layer of that pyramid: pure functions that
read Postgres and emit structured summaries. The LLM agent layer
(`agents/*_custodian_agent.py` — to be added) wraps these with
prompting + critic so the same data is consumable by both
deterministic differ pipelines AND LLM-driven narrators.

Why split data from agent: LLM calls cost money and rate-limit. A
deterministic differ doesn't need them; a dashboard widget doesn't
need them. Only the human-readable "tell me what's interesting"
narration needs them.
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from django.db.models import Avg, Count, Max

log = logging.getLogger("seo.ai.services.custodian")


# ── dataclasses ───────────────────────────────────────────────────────


@dataclass
class DomainSummary:
    """One custodian's report on its domain.

    Used identically for our domain and each competitor — the
    SiteDifferAgent compares two summaries field-by-field.
    """

    domain: str
    is_ours: bool
    snapshot_id: str | None
    snapshot_date: str | None
    page_count: int = 0
    ok_page_count: int = 0
    median_word_count: int = 0
    avg_word_count: int = 0
    has_schema_pct: float = 0.0
    avg_pagespeed_score: float | None = None
    median_lcp_ms: int | None = None
    median_cls: float | None = None
    median_inp_ms: int | None = None
    page_types: dict[str, int] = field(default_factory=dict)
    schema_types: list[str] = field(default_factory=list)
    top_internal_link_kinds: list[tuple[str, int]] = field(default_factory=list)
    top_headings: list[str] = field(default_factory=list)
    # ChangeWatcher signal — only populated for competitor custodians.
    recent_changes: dict[str, int] = field(default_factory=dict)
    recent_change_urls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DiffReport:
    """SiteDiffer output — what they have that we don't, and vice-versa."""

    our_domain: str
    their_domains: list[str]
    page_count_delta: dict[str, int] = field(default_factory=dict)
    schema_only_theirs: dict[str, list[str]] = field(default_factory=dict)
    schema_only_ours: list[str] = field(default_factory=list)
    page_type_gaps: dict[str, dict[str, int]] = field(default_factory=dict)
    link_kind_gaps: dict[str, list[str]] = field(default_factory=dict)
    cwv_deltas: dict[str, dict[str, Any]] = field(default_factory=dict)


# ── private helpers ──────────────────────────────────────────────────


def _percentile(values: list[float], pct: float) -> float | None:
    """Cheap p50/p75 — sort + index. Returns None for empty input."""
    if not values:
        return None
    vs = sorted(v for v in values if v is not None)
    if not vs:
        return None
    k = max(0, min(len(vs) - 1, int(pct * len(vs))))
    return vs[k]


def _safe_median(qs, field: str) -> int | None:
    """Median for an integer column, skipping NULLs."""
    vals = list(
        qs.exclude(**{f"{field}__isnull": True}).values_list(field, flat=True)
    )
    p = _percentile([float(v) for v in vals], 0.5)
    return int(p) if p is not None else None


def _safe_median_float(qs, field: str) -> float | None:
    vals = list(
        qs.exclude(**{f"{field}__isnull": True}).values_list(field, flat=True)
    )
    return _percentile([float(v) for v in vals], 0.5)


def _latest_snapshot(*, kind: str, target_domain: str | None = None):
    """Latest non-empty CrawlSnapshot of the given kind.

    Empty snapshots (in-flight crawls with 0 rows yet) are skipped —
    a custodian whose snapshot has no data is useless. We require at
    least 5 rows so a single trailing PDF row from an aborted crawl
    doesn't get picked as "the dataset".
    """
    from apps.crawler.models import CrawlSnapshot

    qs = CrawlSnapshot.objects.annotate(n=Count("pages")).filter(
        kind=kind, n__gte=5,
    )
    if target_domain:
        qs = qs.filter(target_domain__icontains=target_domain)
    return qs.order_by("-started_at").first()


def _summarise_snapshot_pages(snap) -> dict[str, Any]:
    """Common per-page rollup — used for our + their custodians."""
    from apps.crawler.models import CrawlerPageResult

    rows = CrawlerPageResult.objects.filter(snapshot=snap).exclude(
        status_code__in=["404", "500", "0"],
    )
    page_count = rows.count()
    ok_rows = rows.filter(status_code="200")
    ok_page_count = ok_rows.count()
    word_counts = list(ok_rows.values_list("word_count", flat=True))
    median_word = int(_percentile([float(w) for w in word_counts], 0.5) or 0)
    avg_word_raw = ok_rows.aggregate(avg=Avg("word_count"))["avg"] or 0
    avg_word = int(avg_word_raw)

    schema_yes = ok_rows.exclude(jsonld_types=[]).count()
    schema_pct = round(100.0 * schema_yes / max(1, ok_page_count), 1)

    # Aggregate schema_types JSONField — flatten the lists.
    schema_set: set[str] = set()
    for types in ok_rows.values_list("jsonld_types", flat=True):
        for t in types or []:
            if isinstance(t, str):
                schema_set.add(t)
    schema_types = sorted(schema_set)

    page_types = dict(
        Counter(
            (r["page_type"] or "unknown")
            for r in ok_rows.values("page_type")
        ).most_common(20),
    )

    # Internal-link kind histogram — flatten internal_links_json.
    kind_counter: Counter[str] = Counter()
    for link_list in ok_rows.values_list("internal_links_json", flat=True):
        for link in link_list or []:
            kind = (link or {}).get("kind") or "other"
            kind_counter[kind] += 1
    top_link_kinds = kind_counter.most_common(10)

    # Top headings — flatten headings_json text.
    heading_counter: Counter[str] = Counter()
    for hl in ok_rows.values_list("headings_json", flat=True):
        for h in hl or []:
            t = ((h or {}).get("text") or "").strip()
            if t:
                heading_counter[t[:100]] += 1
    top_headings = [t for t, _ in heading_counter.most_common(20)]

    # CWV — median across mobile metrics (operator-visible default).
    avg_psi = ok_rows.aggregate(avg=Avg("mobile_pagespeed_score"))["avg"]
    median_lcp = _safe_median(ok_rows, "mobile_lcp_ms")
    median_cls = _safe_median_float(ok_rows, "mobile_cls")
    median_inp = _safe_median(ok_rows, "mobile_inp_ms")

    return {
        "page_count": page_count,
        "ok_page_count": ok_page_count,
        "median_word_count": median_word,
        "avg_word_count": avg_word,
        "has_schema_pct": schema_pct,
        "avg_pagespeed_score": (
            round(float(avg_psi), 1) if avg_psi is not None else None
        ),
        "median_lcp_ms": median_lcp,
        "median_cls": (round(median_cls, 3) if median_cls is not None else None),
        "median_inp_ms": median_inp,
        "page_types": page_types,
        "schema_types": schema_types,
        "top_internal_link_kinds": top_link_kinds,
        "top_headings": top_headings,
    }


# ── public API ──────────────────────────────────────────────────────


def summarise_our_domain(*, domain: str = "bajajlifeinsurance.com") -> DomainSummary:
    """OurDataCustodian — everything we know about our own domain.

    Pulls from the latest non-empty BAJAJ-kind CrawlSnapshot. Future
    work layers GSC + Adobe joins on top (the Adobe agent will
    contribute traffic data; the GSC adapter contributes query/impression
    data) — for now this returns the crawler-side picture only because
    that's the data the ContentWriter + SiteDiffer agents need.
    """
    snap = _latest_snapshot(kind="bajaj")
    if snap is None:
        return DomainSummary(
            domain=domain, is_ours=True,
            snapshot_id=None, snapshot_date=None,
        )
    rollup = _summarise_snapshot_pages(snap)
    return DomainSummary(
        domain=domain,
        is_ours=True,
        snapshot_id=str(snap.id),
        snapshot_date=snap.started_at.isoformat() if snap.started_at else None,
        **rollup,
    )


def summarise_competitor(domain: str) -> DomainSummary:
    """TheirDataCustodian — everything we know about one competitor.

    Joins the latest non-empty competitor CrawlSnapshot for ``domain``
    with the cross-snapshot ChangeWatcher feed. ``recent_changes`` is
    the operator's "what flipped this week" panel; ``recent_change_urls``
    seeds the SiteDifferAgent's evidence dict so it can cite specific
    URLs that have changed when narrating the diff.
    """
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    from ..models import CompetitorChangeEvent as CCE

    norm = (domain or "").strip().lower().lstrip("www.")
    snap = _latest_snapshot(kind="competitor", target_domain=norm)
    if snap is None:
        # No crawl yet — surface change events even without a snapshot.
        out = DomainSummary(
            domain=norm, is_ours=False,
            snapshot_id=None, snapshot_date=None,
        )
    else:
        rollup = _summarise_snapshot_pages(snap)
        out = DomainSummary(
            domain=norm,
            is_ours=False,
            snapshot_id=str(snap.id),
            snapshot_date=snap.started_at.isoformat() if snap.started_at else None,
            **rollup,
        )

    # ChangeWatcher rollup — last 7 days, grouped by kind.
    cutoff = dj_tz.now() - timedelta(days=7)
    events_qs = CCE.objects.filter(
        competitor_domain=norm, detected_at__gte=cutoff,
    )
    out.recent_changes = dict(
        Counter(events_qs.values_list("kind", flat=True))
    )
    out.recent_change_urls = [
        {
            "url": ev.url,
            "kind": ev.kind,
            "detected_at": ev.detected_at.isoformat() if ev.detected_at else None,
            "delta": ev.delta or {},
        }
        for ev in events_qs.order_by("-detected_at")[:20]
    ]
    return out


def summarise_roster(*, our_domain: str = "bajajlifeinsurance.com") -> dict[str, Any]:
    """Convenience: run OurDataCustodian + TheirDataCustodian for every
    domain in ``settings.COMPETITOR["roster"]``. One call powers the
    Custodians dashboard page.
    """
    from django.conf import settings

    roster = list(getattr(settings, "COMPETITOR", {}).get("roster") or [])
    ours = summarise_our_domain(domain=our_domain)
    theirs = [summarise_competitor(d) for d in roster]
    return {
        "our": ours.__dict__,
        "competitors": [t.__dict__ for t in theirs],
        "roster_size": len(roster),
    }


# ── SiteDiffer ───────────────────────────────────────────────────────


def compute_site_diff(
    our: DomainSummary,
    theirs: list[DomainSummary],
) -> DiffReport:
    """SiteDiffer — structural deltas between our domain and N competitors.

    No LLM, no fuzzy matching — pure set operations on the custodian
    summaries. The LLM-driven SiteDifferAgent will narrate this report
    later; this function is the underlying math.
    """
    out = DiffReport(
        our_domain=our.domain,
        their_domains=[t.domain for t in theirs],
    )

    out.page_count_delta = {
        t.domain: (our.ok_page_count - t.ok_page_count) for t in theirs
    }

    our_schemas = set(our.schema_types or [])
    out.schema_only_theirs = {
        t.domain: sorted(set(t.schema_types or []) - our_schemas)
        for t in theirs
    }
    all_theirs_schemas = set().union(*(set(t.schema_types or []) for t in theirs))
    out.schema_only_ours = sorted(our_schemas - all_theirs_schemas)

    our_kinds = {k for k, _ in (our.top_internal_link_kinds or [])}
    out.link_kind_gaps = {
        t.domain: sorted(
            {k for k, _ in (t.top_internal_link_kinds or [])} - our_kinds
        )
        for t in theirs
    }

    out.page_type_gaps = {
        t.domain: {
            ptype: (t.page_types.get(ptype, 0) - our.page_types.get(ptype, 0))
            for ptype in set(t.page_types) | set(our.page_types)
        }
        for t in theirs
    }

    out.cwv_deltas = {
        t.domain: {
            "pagespeed": _delta(
                our.avg_pagespeed_score, t.avg_pagespeed_score,
            ),
            "lcp_ms": _delta(our.median_lcp_ms, t.median_lcp_ms),
            "cls": _delta(our.median_cls, t.median_cls),
            "inp_ms": _delta(our.median_inp_ms, t.median_inp_ms),
        }
        for t in theirs
    }

    return out


def _delta(a, b):
    """Compact "ours vs theirs" delta for a single CWV metric."""
    if a is None and b is None:
        return None
    return {
        "ours": a,
        "theirs": b,
        "diff": (a - b) if (a is not None and b is not None) else None,
    }


# ── Hierarchical heading tree (Phase I) ───────────────────────────────


def headings_to_tree(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert a flat headings list (``[{level, text, idx, zone}, ...]``)
    into the page-outline tree the Inspector UI renders.

    Algorithm: stack-based "outline" walker. h1 → root; h2 → child of
    nearest preceding h1; h3 → child of nearest preceding h2; etc.
    Out-of-order headings (h3 with no preceding h2) attach to the
    nearest preceding ancestor of lower level. Robust to typical
    real-world heading-hierarchy mistakes — the tree is structural,
    not an audit.

    Each node shape::

        {"level": int, "text": str, "idx": int, "zone": str,
         "children": [<recursive>, ...]}
    """
    if not headings:
        return []
    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []   # current ancestor chain

    for h in headings:
        if not isinstance(h, dict):
            continue
        node = {
            "level": int(h.get("level") or 1),
            "text": h.get("text") or "",
            "idx": int(h.get("idx") or 0),
            "zone": h.get("zone") or "other",
            "children": [],
        }
        # Pop the stack until we find an ancestor with level <
        # this heading's level.
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1]["children"].append(node)
        stack.append(node)
    return roots


# ── StructureAgent — internal-link pattern analyser ───────────────────


@dataclass
class LinkPattern:
    """One observed source-kind → target-kind connection.

    Read as: "On pages of type ``source_page_type`` and section
    ``section`` (the nearest preceding heading), N% of pages link out
    to a URL classified as ``target_kind``."

    Operator question this answers: "Which kinds of internal links are
    competitors *systematically* placing, that we aren't?"
    """

    source_page_type: str
    target_kind: str
    section: str
    pages_with_link: int
    pages_total: int
    pct: float


def analyse_link_patterns(
    *,
    snapshot_id: str,
    min_pct: float = 30.0,
    top_n: int = 50,
) -> list[LinkPattern]:
    """Pull internal-link patterns from one CrawlSnapshot.

    For every (page_type, section, link_kind) tuple, count the
    fraction of pages of that page_type whose internal_links_json
    contains at least one link of that kind in that section.

    Returns the top ``top_n`` patterns where coverage exceeds
    ``min_pct``. These are the "load-bearing" structural patterns —
    anything below 30 % is a one-off or a long-tail artefact.
    """
    from apps.crawler.models import CrawlerPageResult

    rows = CrawlerPageResult.objects.filter(snapshot_id=snapshot_id).values(
        "url", "page_type", "internal_links_json",
    )
    # (page_type, section, kind) -> set of URLs that had at least
    # one link matching this signature.
    sig_urls: dict[tuple[str, str, str], set[str]] = {}
    pages_by_type: dict[str, set[str]] = {}
    for r in rows:
        url = r["url"]
        ptype = r["page_type"] or "unknown"
        pages_by_type.setdefault(ptype, set()).add(url)
        seen_sigs: set[tuple[str, str, str]] = set()
        for link in r["internal_links_json"] or []:
            section = ((link or {}).get("section") or "")[:80].strip()
            kind = (link or {}).get("kind") or "other"
            sig = (ptype, section, kind)
            if sig in seen_sigs:
                continue
            seen_sigs.add(sig)
            sig_urls.setdefault(sig, set()).add(url)

    patterns: list[LinkPattern] = []
    for (ptype, section, kind), urls in sig_urls.items():
        total = len(pages_by_type.get(ptype, set()))
        if total == 0:
            continue
        pct = round(100.0 * len(urls) / total, 1)
        if pct < min_pct:
            continue
        patterns.append(LinkPattern(
            source_page_type=ptype,
            target_kind=kind,
            section=section or "(no section)",
            pages_with_link=len(urls),
            pages_total=total,
            pct=pct,
        ))
    patterns.sort(key=lambda p: (-p.pct, -p.pages_with_link))
    return patterns[:top_n]


def link_pattern_gaps(
    our_snapshot_id: str,
    competitor_snapshot_ids: list[str],
    *,
    min_pct: float = 50.0,
) -> list[dict[str, Any]]:
    """StructureAgent's headline output: structural patterns competitors
    use that we DON'T.

    For each (page_type, target_kind) pattern that appears with ≥
    ``min_pct`` coverage on at least one competitor snapshot, check
    whether our snapshot has it. If not → it's a gap and the operator
    should ask "should we have this too?".

    Returns up to 30 gaps, ranked by the strongest competitor signal
    (highest coverage % on any single competitor).
    """
    our_patterns = analyse_link_patterns(
        snapshot_id=our_snapshot_id, min_pct=0.0, top_n=10_000,
    )
    # Index our patterns by (page_type, target_kind) for fast lookup.
    our_index: dict[tuple[str, str], float] = {}
    for p in our_patterns:
        key = (p.source_page_type, p.target_kind)
        our_index[key] = max(our_index.get(key, 0.0), p.pct)

    competitor_index: dict[tuple[str, str], dict[str, float]] = {}
    for snap_id in competitor_snapshot_ids:
        try:
            from apps.crawler.models import CrawlSnapshot
            snap = CrawlSnapshot.objects.filter(id=snap_id).first()
        except Exception:  # noqa: BLE001
            snap = None
        domain = (snap.target_domain or snap_id) if snap else snap_id
        for p in analyse_link_patterns(
            snapshot_id=snap_id, min_pct=min_pct, top_n=10_000,
        ):
            key = (p.source_page_type, p.target_kind)
            competitor_index.setdefault(key, {})[domain] = max(
                competitor_index.get(key, {}).get(domain, 0.0), p.pct,
            )

    gaps: list[dict[str, Any]] = []
    for key, per_domain in competitor_index.items():
        ours = our_index.get(key, 0.0)
        # Gap if competitors have it at ≥ min_pct AND we have it at < min_pct/2.
        max_theirs = max(per_domain.values())
        if max_theirs < min_pct or ours >= min_pct / 2:
            continue
        gaps.append({
            "source_page_type": key[0],
            "target_kind": key[1],
            "our_pct": ours,
            "their_pct_by_domain": per_domain,
            "max_their_pct": max_theirs,
            "domains_with_pattern": len(per_domain),
        })
    gaps.sort(key=lambda g: (-g["domains_with_pattern"], -g["max_their_pct"]))
    return gaps[:30]


# ── AdobeAgent — traffic-aware summariser ─────────────────────────────


def summarise_adobe_traffic(*, lookback_days: int = 30) -> dict[str, Any]:
    """AdobeAgent: pull the Adobe Analytics dashboard payload and shape
    it as a custodian-input summary.

    Wraps :class:`AdobeAnalyticsAdapter` so the orchestrator + UI never
    have to know about IMS auth, RSID, or REST quirks. Returns a
    plain dict — the LLM-driven AdobeAgent layer (future) wraps this
    with narration.

    Failures are non-fatal: returns ``{available: False, error: ...}``
    so the dashboard page degrades gracefully when Adobe credentials
    aren't configured yet.
    """
    try:
        from ..adapters.adobe_analytics import (
            AdapterDisabledError,
            AdobeAnalyticsAdapter,
            AdobeAnalyticsError,
        )
    except Exception as exc:  # noqa: BLE001 - adapter import failed
        return {"available": False, "error": f"adapter import failed: {exc}"}

    try:
        adapter = AdobeAnalyticsAdapter()
    except AdapterDisabledError as exc:
        return {"available": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"adapter init failed: {exc}"}

    try:
        dash = adapter.dashboard(lookback_days=lookback_days)
    except AdobeAnalyticsError as exc:
        return {"available": False, "error": f"adobe api: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)}

    # Map to a flat dict so this composes cleanly with the rest of
    # the custodian output. Top 10 pages + 10 entries + channels.
    return {
        "available": True,
        "lookback_days": dash.lookback_days,
        "rsid": dash.rsid,
        "totals": dict(dash.totals or {}),
        "top_pages": [
            {
                "page": p.page,
                "page_views": p.page_views,
            }
            for p in (dash.top_pages or [])[:10]
        ],
        "entry_pages": [
            {
                "page": e.page,
                "entries": e.entries,
                "bounce_rate": e.bounce_rate,
                "time_on_page_sec": e.time_on_page_sec,
            }
            for e in (dash.entry_pages or [])[:10]
        ],
        "channels": [
            {"channel": c.channel, "visits": c.visits, "share_pct": c.share_pct}
            for c in (dash.channels or [])
        ],
        "devices": [
            {"device_type": d.device_type, "visits": d.visits, "share_pct": d.share_pct}
            for d in (dash.devices or [])
        ],
    }


# ── LayoutAgent — landmark-zone aggregator ────────────────────────────


def summarise_layout(*, snapshot_id: str) -> dict[str, Any]:
    """LayoutAgent: aggregate where things sit in each page's DOM.

    Reads the ``zone`` tag that ``_extract_structured`` stamps onto
    each heading/link/image entry (added Phase H). For each
    landmark zone (header / nav / hero / main / aside / footer /
    other) we emit:

      * ``links``   — count + top kinds + sample anchors
      * ``headings`` — count + top texts
      * ``images``   — count + alt-coverage %

    Operator question this answers: "Where do competitors put their
    calculator CTAs? Where do they put their footer disclosure copy?
    Where do they expose related-products links?"

    Note: existing pre-Phase-H rows have no ``zone`` field — those
    entries fall into the ``unknown`` bucket. Re-crawl (the daily
    beat job at 03:00 IST) repopulates with proper zones.
    """
    from collections import Counter

    from apps.crawler.models import CrawlerPageResult

    rows = CrawlerPageResult.objects.filter(snapshot_id=snapshot_id).values(
        "internal_links_json", "external_links_json",
        "headings_json", "images_json",
    )

    zones: dict[str, dict[str, Any]] = {}

    def _bucket(zone: str) -> dict[str, Any]:
        return zones.setdefault(zone, {
            "link_count": 0,
            "link_kinds": Counter(),
            "link_anchors": Counter(),
            "heading_count": 0,
            "heading_texts": Counter(),
            "image_count": 0,
            "images_with_alt": 0,
        })

    for r in rows:
        for link in (r["internal_links_json"] or []):
            zone = (link or {}).get("zone") or "unknown"
            b = _bucket(zone)
            b["link_count"] += 1
            b["link_kinds"][link.get("kind") or "other"] += 1
            anchor = (link.get("anchor") or "").strip()[:60]
            if anchor:
                b["link_anchors"][anchor] += 1
        for link in (r["external_links_json"] or []):
            zone = (link or {}).get("zone") or "unknown"
            b = _bucket(zone)
            b["link_count"] += 1
            b["link_kinds"]["external"] += 1
        for h in (r["headings_json"] or []):
            zone = (h or {}).get("zone") or "unknown"
            b = _bucket(zone)
            b["heading_count"] += 1
            t = (h.get("text") or "").strip()[:80]
            if t:
                b["heading_texts"][t] += 1
        for img in (r["images_json"] or []):
            zone = (img or {}).get("zone") or "unknown"
            b = _bucket(zone)
            b["image_count"] += 1
            if (img.get("alt") or "").strip():
                b["images_with_alt"] += 1

    # Materialise Counters → list[tuple] for JSON serialisation.
    out: dict[str, Any] = {}
    for zone, b in zones.items():
        out[zone] = {
            "link_count": b["link_count"],
            "top_link_kinds": b["link_kinds"].most_common(8),
            "top_link_anchors": b["link_anchors"].most_common(8),
            "heading_count": b["heading_count"],
            "top_heading_texts": b["heading_texts"].most_common(8),
            "image_count": b["image_count"],
            "image_alt_pct": (
                round(100.0 * b["images_with_alt"] / b["image_count"], 1)
                if b["image_count"] > 0 else 0.0
            ),
        }
    return {
        "snapshot_id": str(snapshot_id),
        "zones": out,
    }


def layout_diff(
    our_snapshot_id: str,
    competitor_snapshot_ids: list[str],
) -> dict[str, Any]:
    """LayoutAgent's "what do competitors do in zone X that we don't"
    diff.

    For each zone (header/nav/hero/main/aside/footer), compare top
    link kinds across us + each competitor and surface kinds the
    competitor surfaces in a zone but we don't.
    """
    ours = summarise_layout(snapshot_id=our_snapshot_id).get("zones", {})
    diffs: dict[str, list[dict[str, Any]]] = {}
    for snap_id in competitor_snapshot_ids:
        their = summarise_layout(snapshot_id=snap_id).get("zones", {})
        from apps.crawler.models import CrawlSnapshot
        snap = CrawlSnapshot.objects.filter(id=snap_id).first()
        domain = (snap.target_domain or snap_id) if snap else snap_id
        per_zone: list[dict[str, Any]] = []
        for zone in ("header", "nav", "hero", "main", "aside", "footer"):
            ours_kinds = {
                k: c for k, c in (ours.get(zone, {}).get("top_link_kinds") or [])
            }
            their_kinds = {
                k: c for k, c in (their.get(zone, {}).get("top_link_kinds") or [])
            }
            only_theirs = sorted(
                set(their_kinds) - set(ours_kinds),
                key=lambda k: -their_kinds[k],
            )
            if only_theirs:
                per_zone.append({
                    "zone": zone,
                    "kinds_only_in_competitor": only_theirs,
                    "their_link_count": their.get(zone, {}).get("link_count", 0),
                    "our_link_count": ours.get(zone, {}).get("link_count", 0),
                })
        diffs[domain] = per_zone
    return {
        "our_snapshot_id": our_snapshot_id,
        "diffs_by_competitor": diffs,
    }
