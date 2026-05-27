"""DRF views — Django port of crawler-engine FastAPI routes.

Endpoint map (all under ``/api/v1/crawler/``):

  GET  /status                    — current crawl state + stats
  POST /start                     — kick off a new crawl in a background thread
  POST /stop                      — signal the running crawl to drain & stop
  GET  /summary                   — high-level counters for dashboard cards
  GET  /summary/breakdown         — per-subdomain / per-category counts
  GET  /tables                    — list of CSV-backed tables with row counts
  GET  /tables/<key>              — full headers + rows of one table (filterable)
  GET  /download/<key>            — raw CSV download (filterable)
  GET  /reports/xlsx              — multi-sheet styled XLSX report download
  POST /gsc/coverage/refresh      — flush the GSC coverage cache
  GET  /tree                      — hierarchical site graph derived from discovered edges
  GET  /logs                      — polling log feed (replaces FastAPI WebSocket)
"""
from __future__ import annotations

import csv as _csv
from collections import defaultdict, deque
from pathlib import Path

from django.http import FileResponse, JsonResponse, StreamingHttpResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import log_bus
from .conf import settings
from .services import crawler_service, report_service
from .state import STATE
from .storage import gsc_loader, repository as repo
from .storage import url_classifier


# ── Filter param parsing ────────────────────────────────────────────────────


_FILTER_KEYS = ("subdomain", "category", "category_key", "page_type",
                "indexed", "indexed_status", "from_sitemap")


def _extract_filters(request) -> dict:
    """Pull the supported filter query params off a DRF request."""
    out: dict[str, str | bool] = {}
    for k in _FILTER_KEYS:
        v = request.query_params.get(k)
        if v:
            out[k] = v
    if request.query_params.get("hide_branch_404_noise") in {"1", "true", "yes"}:
        out["hide_branch_404_noise"] = True
    return out


# ── Crawler lifecycle ───────────────────────────────────────────


@api_view(["GET"])
def status_view(_request):
    with STATE.lock:
        stats = STATE.stats.as_dict()
        visited_count = len(STATE.visited)
        queue_count = len(STATE.queue)
    return Response({
        "is_running": STATE.is_running,
        "should_stop": STATE.should_stop,
        "seed": settings.seed_url,
        "allowed_domains": sorted(settings.allowed_domains),
        "stats": stats,
        "visited_count": visited_count,
        "queue_count": queue_count,
    })


@api_view(["POST"])
def start_view(_request):
    ok, msg = crawler_service.start()
    if not ok:
        return Response({"ok": False, "message": msg}, status=409)
    return Response({"ok": True, "message": msg})


@api_view(["POST"])
def stop_view(_request):
    ok, msg = crawler_service.request_stop()
    return Response({"ok": ok, "message": msg}, status=200 if ok else 409)


# ── Data access ─────────────────────────────────────────────────


@api_view(["GET"])
def summary_view(_request):
    return Response(repo.summary())


@api_view(["GET"])
def summary_breakdown_view(_request):
    """Per-subdomain / per-category aggregates for the Reports landing page."""
    return Response(repo.summary_breakdown())


@api_view(["GET"])
def tables_list_view(_request):
    """List every catalog entry; categorised entries include a per-category breakdown."""
    breakdown = repo.summary_breakdown()
    by_subdomain = breakdown.get("by_subdomain", {})
    categories_meta = {c["key"]: c for c in breakdown.get("categories", [])}
    items = []
    for key, meta in repo.CATALOG.items():
        total = repo.read_csv(key)["count"]
        entry = {
            "key": key,
            "label": meta["label"],
            "icon": meta["icon"],
            "description": meta["description"],
            "count": total,
            "categorized": bool(meta.get("categorized")),
        }
        if meta.get("categorized"):
            # Build per-category badges from the same breakdown — saves the
            # frontend an extra round-trip.
            entry["categories"] = [
                {
                    "key": c["key"],
                    "label": c["label"],
                    "subdomain": c["subdomain"],
                    "icon": c["icon"],
                    "counts": categories_meta.get(c["key"], {}).get(
                        "counts", c.get("counts", {})
                    ),
                }
                for c in url_classifier.CATEGORY_DEFS
            ]
            entry["by_subdomain"] = by_subdomain
        items.append(entry)
    return Response({
        "tables": items,
        "noise_404_branch_not_indexed": breakdown.get(
            "noise_404_branch_not_indexed", 0
        ),
    })


@api_view(["GET"])
def table_detail_view(request, key: str):
    meta = repo.CATALOG.get(key)
    if not meta:
        return Response({"error": "Unknown table"}, status=404)
    filters = _extract_filters(request)
    data = repo.read_csv(key, filters=filters or None)
    return Response({
        "key": key,
        "label": meta["label"],
        "icon": meta["icon"],
        "description": meta["description"],
        "headers": data["headers"],
        "rows": data["rows"],
        "count": data["count"],
        "filters": filters,
    })


@api_view(["GET"])
def download_csv_view(request, key: str):
    meta = repo.CATALOG.get(key)
    if not meta:
        return JsonResponse({"error": "Unknown file"}, status=404)
    path: Path = settings.data_path / meta["file"]
    if not path.exists():
        return JsonResponse({"error": "File not yet generated"}, status=404)
    filters = _extract_filters(request)
    if not filters:
        # No filters — stream the raw file untouched (fastest path, no parse).
        return FileResponse(
            open(path, "rb"),
            as_attachment=True,
            filename=meta["file"],
            content_type="text/csv",
        )
    # Filtered download — stream rows one-at-a-time through repo.iter_rows().
    data = repo.read_csv(key, filters=filters)
    headers = data["headers"]

    def _stream():
        # Each row is yielded as a CSV-encoded string with proper escaping.
        buf = _StringBuffer()
        writer = _csv.writer(buf)
        writer.writerow(headers)
        yield buf.flush()
        rows = repo.iter_rows(key, filters=filters)
        for row in rows:
            writer.writerow([row.get(h, "") for h in headers])
            yield buf.flush()

    suffix_parts = []
    for k, v in filters.items():
        if k == "hide_branch_404_noise" and v:
            suffix_parts.append("nonoise")
        elif v:
            suffix_parts.append(f"{k}-{v}")
    suffix = "_" + "_".join(suffix_parts) if suffix_parts else ""
    fname = meta["file"].replace(".csv", f"{suffix}.csv")
    resp = StreamingHttpResponse(_stream(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@api_view(["POST"])
def gsc_coverage_refresh_view(_request):
    """Flush the in-memory GSC coverage cache; the next read picks up the latest CSV."""
    gsc_loader.invalidate_cache()
    cov = gsc_loader.load_coverage_map()
    return Response({"ok": True, "loaded_urls": len(cov)})


# ── GSC freeze switch ─────────────────────────────────────────────
# When GSC_FROZEN=true in env, the two endpoints below that can issue
# live Search Console API calls (sitemap backfill + URL Inspection)
# short-circuit with a 503 and leave the on-disk CSV cache untouched.
# Used when the operator has temporarily lost GSC access — overnight
# crawls must keep working off the existing csv coverage map rather
# than failing on an OAuth refresh.
def _gsc_is_frozen() -> bool:
    import os
    return os.environ.get("GSC_FROZEN", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


@api_view(["POST"])
def gsc_coverage_build_view(request):
    """Derive a fresh coverage CSV from already-pulled GSC performance data
    plus a live sitemap fetch. Returns counts so the UI can show a toast.

    Gated by ``GSC_FROZEN`` env — when set, returns 503 instead of
    touching the network (operator has lost GSC access).
    """
    if _gsc_is_frozen():
        return Response(
            {
                "ok": False,
                "error": "GSC is frozen (GSC_FROZEN=true). Using cached "
                         "coverage CSV only — no live API calls until the "
                         "operator restores Search Console access.",
            },
            status=503,
        )
    from .storage import gsc_coverage_builder
    sitemap = request.query_params.get("sitemap") or gsc_coverage_builder.DEFAULT_SITEMAP
    backfill = request.query_params.get("backfill") in {"1", "true", "yes"}
    try:
        coverage = gsc_coverage_builder.build_coverage(sitemap_seed=sitemap)
        result = {"ok": True, "coverage": coverage}
        if backfill:
            result["backfill"] = gsc_coverage_builder.backfill_from_sitemap(
                sitemap_seed=sitemap,
            )
        return Response(result)
    except Exception as exc:  # noqa: BLE001
        return Response({"ok": False, "error": str(exc)}, status=500)


@api_view(["POST"])
def console_capture_start_view(request):
    """Kick off a Playwright console-capture run in a background thread.

    Returns immediately with `{ok, message}`; clients poll
    /console/capture/status for progress. Refuses to start if a run is
    already in progress.
    """
    import threading
    from .engine import browser_console
    if browser_console.CAPTURE_STATE.is_running:
        return Response(
            {"ok": False, "message": "A capture is already running."},
            status=409,
        )
    try:
        limit = int(request.query_params.get("limit", "200"))
    except (TypeError, ValueError):
        limit = 200
    subdomain = request.query_params.get("subdomain", "www")
    only_status = request.query_params.get("status", "200")
    levels_raw = request.query_params.get("levels", "error,warning")
    levels = (("error", "warning", "info", "log", "debug")
              if levels_raw == "all"
              else tuple(x.strip() for x in levels_raw.split(",") if x.strip()))
    urls = browser_console.select_target_urls(
        limit=limit, subdomain=subdomain, only_status=only_status,
    )
    if not urls:
        return Response(
            {"ok": False,
             "message": "No URLs match the filter — run the crawler first."},
            status=400,
        )

    def _run():
        browser_console.capture(urls, levels=levels)

    t = threading.Thread(target=_run, daemon=True, name="console-capture")
    t.start()
    return Response({
        "ok": True,
        "message": f"Capture started for {len(urls)} URL(s).",
        "target_count": len(urls),
    })


@api_view(["GET"])
def console_capture_status_view(_request):
    from .engine import browser_console
    return Response(browser_console.CAPTURE_STATE.as_dict())


@api_view(["POST"])
def console_capture_stop_view(_request):
    from .engine import browser_console
    if not browser_console.CAPTURE_STATE.is_running:
        return Response({"ok": False, "message": "No active capture."}, status=409)
    browser_console.request_stop()
    return Response({"ok": True, "message": "Stop signal sent."})


@api_view(["GET"])
def psi_progress_view(_request):
    """Live snapshot of the inline PSI scheduler while a crawl is running.

    Returns an empty object when no scheduler is registered (no crawl in
    flight, or PSI is disabled). When active, returns the scheduler's
    progress dict::

        {
          "is_running": bool,
          "started_at": float | null,
          "finished_at": float | null,
          "submitted": int,
          "in_flight": int,
          "completed": int,
          "failed": int,
          "queue_size": int,
          "last_url": str,
          "workers": int,
          "strategies": ["mobile", "desktop"],
          "primary_strategy": "mobile",
          "disabled": bool,
          "disabled_reason": str   (only when disabled)
        }
    """
    from .engine import psi_scheduler
    sched = psi_scheduler.get_current()
    if sched is None:
        return Response({})
    return Response(sched.progress())


@api_view(["GET"])
def psi_status_view(_request):
    """Return the last-persisted PSI run outcome. Powers the
    "PSI capture skipped because <reason>" banner on the Reports page.

    Shape (when a run has happened):
        {
          "ok": bool,
          "started_at": ISO8601,
          "finished_at": ISO8601,
          "urls_inspected": int,
          "rows_written": int,
          "failed": int,
          "strategies": ["mobile", "desktop"],
          "primary_strategy": "mobile",
          "error": "..."   (only present when ok=false)
        }

    Returns ``{}`` when no PSI run has happened yet.
    """
    from .engine import psi_capture
    return Response(psi_capture.read_status())


@api_view(["POST"])
def gsc_inspect_unknowns_view(request):
    """Upgrade `unknown` rows to definitive verdicts via URL Inspection API.

    Rate-limited (~2000/day per property). Idempotent — already-inspected
    URLs are skipped because they're no longer ``unknown``.

    Gated by ``GSC_FROZEN`` env — when set, returns 503 instead of
    issuing a live URL Inspection API request.
    """
    if _gsc_is_frozen():
        return Response(
            {
                "ok": False,
                "error": "GSC is frozen (GSC_FROZEN=true). URL Inspection "
                         "calls disabled until the operator restores "
                         "Search Console access.",
            },
            status=503,
        )
    from .storage import gsc_coverage_builder
    site = request.query_params.get("site") or "https://www.bajajlifeinsurance.com/"
    try:
        max_urls = int(request.query_params.get("max", "1900"))
    except (TypeError, ValueError):
        max_urls = 1900
    try:
        res = gsc_coverage_builder.upgrade_with_url_inspection(
            site_url=site, max_urls=max_urls,
        )
        if not res.get("ok"):
            return Response(res, status=400)
        return Response(res)
    except Exception as exc:  # noqa: BLE001
        return Response({"ok": False, "error": str(exc)}, status=500)


class _StringBuffer:
    """Minimal write-then-flush buffer for csv.writer in a generator."""

    def __init__(self) -> None:
        self._chunks: list[str] = []

    def write(self, s: str) -> int:  # csv.writer calls this
        self._chunks.append(s)
        return len(s)

    def flush(self) -> str:
        out = "".join(self._chunks)
        self._chunks.clear()
        return out


# ── Report download ─────────────────────────────────────────────


@api_view(["GET"])
def report_xlsx_view(_request):
    try:
        path = report_service.generate_xlsx()
    except Exception as exc:  # noqa: BLE001
        return JsonResponse(
            {"error": f"Report generation failed: {exc}"}, status=500,
        )
    return FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=path.name,
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


# ── Site tree ───────────────────────────────────────────────────


def _build_tree(max_depth: int, max_nodes: int) -> dict:
    results = repo.read_csv("results")
    status_map: dict[str, dict] = {}
    if results["headers"]:
        h = results["headers"]
        idx_url = h.index("url") if "url" in h else 0
        idx_code = h.index("status_code") if "status_code" in h else 1
        idx_title = h.index("title") if "title" in h else 3
        for row in results["rows"]:
            if len(row) <= idx_url:
                continue
            status_map[row[idx_url]] = {
                "status_code": row[idx_code] if len(row) > idx_code else "",
                "title": row[idx_title] if len(row) > idx_title else "",
            }

    discovered = repo.read_csv("discovered")
    first_parent: dict[str, str] = {}
    depth_map: dict[str, int] = {}
    for row in discovered["rows"]:
        if len(row) < 3:
            continue
        child, parent, depth = row[0].strip(), row[1].strip(), row[2].strip()
        if not child or not parent or child == parent:
            continue
        try:
            d = int(depth)
        except ValueError:
            d = 0
        if child not in first_parent:
            first_parent[child] = parent
            depth_map[child] = d

    children_of: dict[str, list[str]] = defaultdict(list)
    all_children: set[str] = set()
    all_parents: set[str] = set()
    for child, parent in first_parent.items():
        children_of[parent].append(child)
        all_children.add(child)
        all_parents.add(parent)
    for lst in children_of.values():
        lst.sort()

    top_level = sorted(p for p in all_parents if p not in all_children)

    seed = settings.seed_url
    root_url = seed
    if seed in top_level:
        other_orphans = [u for u in top_level if u != seed]
        children_of[seed] = sorted(set(children_of.get(seed, [])) | set(other_orphans))
    else:
        children_of[seed] = sorted(set(children_of.get(seed, [])) | set(top_level))

    def node_payload(url: str, depth: int, _total: int) -> dict:
        info = status_map.get(url, {})
        return {
            "url": url,
            "title": info.get("title", ""),
            "status_code": info.get("status_code", ""),
            "depth": depth,
            "total_children": len(children_of.get(url, [])),
            "children": [],
        }

    emitted = 0
    truncated = False
    root_node = node_payload(root_url, 0, 0)
    queue: deque = deque([(root_url, root_node, 0)])
    emitted += 1

    while queue:
        url, node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for child_url in children_of.get(url, []):
            if emitted >= max_nodes:
                truncated = True
                break
            child_node = node_payload(child_url, depth + 1, 0)
            node["children"].append(child_node)
            queue.append((child_url, child_node, depth + 1))
            emitted += 1
        if truncated:
            break

    return {
        "root": root_node,
        "total_edges": len(first_parent),
        "total_nodes_returned": emitted,
        "max_depth": max_depth,
        "truncated": truncated,
    }


@api_view(["GET"])
def tree_view(request):
    try:
        max_depth = int(request.query_params.get("max_depth", 4))
        max_nodes = int(request.query_params.get("max_nodes", 3000))
    except (TypeError, ValueError):
        return Response({"error": "max_depth/max_nodes must be integers"}, status=400)
    max_depth = max(1, min(20, max_depth))
    max_nodes = max(10, min(20000, max_nodes))
    return Response(_build_tree(max_depth, max_nodes))


# ── Logs (polling replaces WebSocket) ───────────────────────────


@api_view(["GET"])
def logs_view(request):
    """Return every log message after the caller's last cursor.

    Replaces ``/ws/logs`` from the FastAPI service. The crawler frontend
    polls this endpoint with the previously-returned ``cursor`` value,
    receives only new messages, and updates its UI — matching the live
    WebSocket UX without requiring Django Channels.

    Query params:
      * cursor (optional int) — last seq id seen by this client. Omit on
        first call to seed with the most recent ``limit`` messages.
      * limit  (optional int) — cap on messages returned (default 500).
    """
    raw_cursor = request.query_params.get("cursor")
    try:
        cursor = int(raw_cursor) if raw_cursor not in (None, "") else None
    except (TypeError, ValueError):
        cursor = None
    try:
        limit = int(request.query_params.get("limit", 500))
    except (TypeError, ValueError):
        limit = 500
    limit = max(1, min(2000, limit))

    messages, new_cursor = log_bus.poll(cursor=cursor, limit=limit)

    with STATE.lock:
        stats = STATE.stats.as_dict()
        is_running = STATE.is_running

    return Response({
        "cursor": new_cursor,
        "messages": messages,
        "is_running": is_running,
        "stats": stats,
    })


# ── Audit engine — Health Score + Issues ────────────────────────────────


@api_view(["GET"])
def health_score_view(_request):
    """Single-KPI overview of crawl health.

    Computes the Ahrefs-formula Health Score from the current crawl
    results CSV. Returns score (0-100), tier (Excellent/Good/Fair/Weak),
    per-severity issue-type counts, per-category counts, and top-5 error
    occurrences. Powers the dashboard widget and the chat ``get_health_score``
    tool.
    """
    from .services.health_score import compute as compute_health_score

    return Response(compute_health_score().as_dict())


@api_view(["GET"])
def competitor_health_score_view(_request, domain: str):
    """Per-competitor Health Score.

    Reads the most-recent COMPLETED CrawlSnapshot whose
    ``target_domain`` matches the URL path arg and computes the
    Health Score over that snapshot's CrawlerPageResult rows. Returns
    404 if no competitor crawl has run yet for that domain.

    Powers the per-competitor Health Score card the dashboard renders
    in the competitor detail view, and the chat
    ``get_competitor_health_score`` tool.
    """
    from .models import CrawlSnapshot
    from .services.health_score import compute_for_snapshot

    domain = (domain or "").strip().lower().lstrip("www.")
    if not domain:
        return Response({"error": "domain required"}, status=400)

    snap = (
        CrawlSnapshot.objects
        .filter(
            kind=CrawlSnapshot.Kind.COMPETITOR,
            target_domain=domain,
            status=CrawlSnapshot.Status.COMPLETE,
        )
        .order_by("-started_at")
        .first()
    )
    if snap is None:
        return Response(
            {
                "error": "no completed competitor crawl for this domain",
                "domain": domain,
            },
            status=404,
        )
    hs = compute_for_snapshot(str(snap.id))
    if hs is None:
        return Response(
            {
                "error": "snapshot has no scorable rows",
                "domain": domain,
                "snapshot_id": str(snap.id),
            },
            status=404,
        )
    body = hs.as_dict()
    body.update({
        "domain": domain,
        "snapshot_id": str(snap.id),
        "snapshot_started_at": snap.started_at.isoformat() if snap.started_at else "",
        "snapshot_finished_at": (
            snap.finished_at.isoformat() if snap.finished_at else ""
        ),
        "pages_attempted": snap.pages_attempted,
        "pages_ok": snap.pages_ok,
        "pages_errored": snap.pages_errored,
    })
    return Response(body)


@api_view(["GET"])
def issues_view(request):
    """List every issue type with its current occurrence count.

    Query params:
      * severity (optional) — comma-separated subset of
        ``error,warning,notice`` to filter the response. Default: all.
      * category (optional) — comma-separated subset of the 8 categories.

    Returns slim summaries (no per-URL lists) so the response stays small.
    Drill into a specific issue via ``/issues/<slug>`` for the affected URLs.
    """
    from .audits import run_all

    severity_filter = {
        s for s in (request.query_params.get("severity") or "").split(",") if s
    }
    category_filter = {
        c for c in (request.query_params.get("category") or "").split(",") if c
    }

    audit = run_all()
    occs = [o for o in audit.occurrences if o.count > 0]
    if severity_filter:
        occs = [o for o in occs if o.issue.severity in severity_filter]
    if category_filter:
        occs = [o for o in occs if o.issue.category in category_filter]
    # Sort by severity (errors first) then by count desc.
    severity_order = {"error": 0, "warning": 1, "notice": 2}
    occs.sort(key=lambda o: (severity_order[o.issue.severity], -o.count))

    return Response({
        "total_urls": audit.total_urls,
        "ok_urls": audit.ok_urls,
        "severity_counts": audit.severity_counts(),
        "issue_type_counts": audit.issue_type_counts(),
        "issues": [o.as_summary() for o in occs],
        "started_at": audit.started_at,
        "finished_at": audit.finished_at,
    })


@api_view(["GET"])
def themes_list_view(_request):
    """List every available thematic report (8 themes)."""
    from .services.themes import list_themes
    return Response({"themes": list_themes()})


@api_view(["GET"])
def theme_detail_view(_request, slug: str):
    """One thematic deep-dive report — issues curated for one concern
    (robots, crawlability, https, international, performance, linking,
    markup, cwv)."""
    from .services.themes import get
    theme = get(slug)
    if theme is None:
        return Response(
            {"error": f"unknown theme: {slug}"},
            status=404,
        )
    return Response(theme.as_dict())


@api_view(["GET"])
def compare_view(request):
    """SEMrush-style Compare Crawls — diff any two CrawlSnapshot rows.

    Query params:
      * a (UUID, optional) — older snapshot. Default: second-most-recent.
      * b (UUID, optional) — newer snapshot. Default: most-recent.

    Returns per-issue diffs (Fixed / New / Changed) + per-URL page-set
    diffs (added / removed / status-changed) + Health Score delta. If
    fewer than two snapshots exist, returns 404 with an explanation.

    Works across engines: an "a" from the legacy engine vs "b" from
    Scrapy lets the operator visually validate parity at any granularity
    during the 30-day migration soak.
    """
    from .services.crawl_diff import diff, latest_two_snapshots

    a_id = request.query_params.get("a")
    b_id = request.query_params.get("b")
    if not (a_id and b_id):
        pair = latest_two_snapshots()
        if pair is None:
            return Response(
                {
                    "error": "Need at least 2 CrawlSnapshot rows to compare.",
                    "hint": "Run python manage.py crawl twice (or once + crawl_scrapy).",
                },
                status=404,
            )
        a_id, b_id = pair

    try:
        result = diff(a_id, b_id)
    except Exception as exc:  # noqa: BLE001
        return Response(
            {"error": f"diff failed: {type(exc).__name__}: {exc}"},
            status=404,
        )
    return Response(result.as_dict())


@api_view(["GET"])
def trends_view(request):
    """Time-series of Health Score + per-category counts.

    Powers the /trends route (Health Score over 30/90/365 days).
    Reads MetricSnapshot rows written daily by the
    snapshot_runner.take_snapshot task (Celery beat) or manually via
    the snapshot_metrics management command.

    Query params:
      * window (int days, default 90, max 365)
      * engine (legacy | scrapy | empty for both)
    """
    from .services.snapshot_runner import latest

    engine = request.query_params.get("engine", "")
    try:
        window = int(request.query_params.get("window") or 90)
    except (TypeError, ValueError):
        window = 90
    rows = latest(engine=engine, limit=window)
    return Response({
        "engine": engine or "any",
        "window": window,
        "snapshot_count": len(rows),
        "snapshots": rows,
    })


@api_view(["GET"])
def pagerank_view(_request):
    """Top URLs by internal PageRank + summary aggregates.

    Powers the Health Dashboard "Top-linked pages" tile and the chat
    tool `get_pagerank_top`. Results are mtime-cached over
    crawl_discovered.csv so the first request pays the ~2s compute
    cost and subsequent requests are < 10 ms.
    """
    from .services.pagerank import summary, top_n

    return Response({
        "summary": summary(),
        "top": top_n(50),
    })


@api_view(["GET"])
def near_duplicates_view(request):
    """Near-duplicate URL clusters via MinHash + LSH.

    Query params:
      threshold (float 0.0-1.0, default 0.9 = Screaming Frog default)
      n (int, default 20, max 100)
    """
    from .services.near_dup import summary, top_clusters

    try:
        threshold = float(request.query_params.get("threshold") or 0.9)
    except (TypeError, ValueError):
        threshold = 0.9
    try:
        n = int(request.query_params.get("n") or 20)
    except (TypeError, ValueError):
        n = 20

    return Response({
        "summary": summary(threshold=threshold),
        "clusters": top_clusters(n, threshold=threshold),
    })


@api_view(["GET"])
def page_explorer_view(request):
    """Ahrefs-style sortable/filterable URL inventory over the latest
    crawl_results.csv.

    Query params (all optional; see services/page_explorer.py for the
    full contract):
      sort, status, subdomain, page_type, indexed, has_psi, q,
      limit (1-500, default 50), offset (default 0).

    Returns ``{total, returned, limit, offset, sort, rows, columns}``.
    Phase 3 will swap the data source to Postgres without changing
    this response shape.
    """
    from .services.page_explorer import query as run_query

    params = {
        k: request.query_params.get(k)
        for k in ("status", "subdomain", "page_type", "indexed",
                  "has_psi", "q")
    }
    sort = request.query_params.get("sort") or "url"
    limit = request.query_params.get("limit") or 50
    offset = request.query_params.get("offset") or 0
    return Response(run_query(params=params, sort=sort, limit=limit, offset=offset))


@api_view(["GET"])
def page_explorer_facets_view(_request):
    """Distinct values for the filterable enum columns. Populates the
    Page Explorer filter dropdowns."""
    from .services.page_explorer import facets

    return Response(facets())


@api_view(["GET"])
def issue_detail_view(_request, slug: str):
    """Per-issue drill-in: metadata + affected URLs.

    Caps at 1000 affected URLs to keep the response bounded. Returns 404
    for unknown slugs.
    """
    from .audits import ISSUES_BY_SLUG, run_all

    issue = ISSUES_BY_SLUG.get(slug)
    if issue is None:
        return Response({"error": f"unknown issue slug: {slug}"}, status=404)

    audit = run_all()
    occ = next((o for o in audit.occurrences if o.issue.slug == slug), None)
    if occ is None:
        return Response({"error": f"issue {slug} not present in audit"}, status=404)

    affected = [
        {
            "url": (r.get("url") or "").strip(),
            "title": (r.get("title") or "").strip(),
            "status_code": r.get("status_code") or "",
            "subdomain": r.get("subdomain") or "",
            "page_type": r.get("page_type") or "",
            "word_count": r.get("word_count") or "",
            "response_time_ms": r.get("response_time_ms") or "",
            "indexed_status": r.get("indexed_status") or "",
        }
        for r in occ.affected_urls
    ]

    return Response({
        **occ.as_summary(),
        "affected_urls": affected,
        "started_at": audit.started_at,
    })


# ── Content map / similarity (Phase 2 + 3) ─────────────────────────────────


@api_view(["GET"])
def content_map_3d_view(request):
    """GET /api/v1/crawler/content/map/3d

    Returns 3D scatter points from a snapshot's PageEmbedding rows. The
    snapshot is selected by (in priority order):
      1. ?snapshot=<uuid>  — exact match
      2. ?domain=<host>    — latest non-empty COMPLETE competitor
                             snapshot for that target_domain
      3. (default)         — latest snapshot of any kind

    Each competitor gets its own content map because every
    PageEmbedding row carries snapshot_id; there's no cross-domain
    bleed. Returns 404 only when no snapshot at all can be resolved.
    """
    from django.db.models import Count

    from .models import CrawlSnapshot
    from .content.projection import get_3d_points

    snap_id = (request.GET.get("snapshot") or "").strip()
    domain = (request.GET.get("domain") or "").strip().lower()
    snap = None
    if snap_id:
        snap = CrawlSnapshot.objects.filter(id=snap_id).first()
    elif domain:
        snap = (
            CrawlSnapshot.objects.annotate(n=Count("pages"))
            .filter(
                kind="competitor",
                status="complete",
                target_domain__iexact=domain,
                n__gte=1,
            )
            .order_by("-started_at")
            .first()
        )
    else:
        snap = CrawlSnapshot.objects.order_by("-started_at").first()
    if snap is None:
        return Response(
            {"error": "no snapshot", "domain": domain or None},
            status=404,
        )
    points = get_3d_points(snap)
    return Response({
        "snapshot_id": str(snap.id),
        "snapshot_kind": snap.kind,
        "snapshot_domain": snap.target_domain or "",
        "snapshot_date": snap.started_at.isoformat() if snap.started_at else "",
        "total": len(points),
        "points": points,
    })


@api_view(["GET"])
def content_similar_view(request):
    """GET /api/v1/crawler/content/similar
    Params: url=<page_url> OR query=<free_text>,
            product=<label>, page_type=<label>, top_k=<int>.

    Returns top-k pages most semantically similar.
    """
    from .content.similarity import similar_to_url, similar_to_query

    top_k = max(1, min(50, int(request.GET.get("top_k", "10"))))
    product = request.GET.get("product") or None
    page_type = request.GET.get("page_type") or None
    url = request.GET.get("url") or ""
    query = request.GET.get("query") or ""
    if not (url or query):
        return Response(
            {"error": "must provide ?url= or ?query="}, status=400,
        )
    if url:
        results = similar_to_url(
            url, top_k=top_k, product=product, page_type=page_type,
        )
    else:
        results = similar_to_query(
            query, top_k=top_k, product=product, page_type=page_type,
        )
    return Response({"results": results})


@api_view(["GET"])
def snapshots_list_view(_request):
    """GET /api/v1/crawler/snapshots — pickable snapshots for cluster /
    map / inspector UIs.

    Returns the most recent ~30 non-empty snapshots across both
    Bajaj and competitor kinds, newest first. Each row is enough to
    populate a dropdown (id, started_at, kind, target_domain, page
    count) without hitting the per-snapshot detail endpoints.
    """
    from django.db.models import Count

    from .models import CrawlSnapshot

    rows = (
        CrawlSnapshot.objects.annotate(n=Count("pages"))
        .filter(n__gte=5)
        .order_by("-started_at")[:30]
    )
    return Response({
        "count": len(rows),
        "snapshots": [
            {
                "id": str(s.id),
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "kind": s.kind,
                "engine": s.engine,
                "target_domain": s.target_domain or "",
                "page_count": s.pages_attempted or 0,
                "ok_page_count": s.pages_ok or 0,
                "health_score": s.health_score,
                "status": s.status,
            }
            for s in rows
        ],
    })


@api_view(["GET"])
def content_clusters_view(request):
    """GET /api/v1/crawler/content/clusters
    Params: snapshot=<id> (optional, defaults to latest),
            mode=primary|multi (default primary).

    Returns the hierarchical Product → Page-type → pages tree, plus an
    `uncertain` bucket. Pure rule-based — no LLM, no embeddings required.
    """
    from .models import CrawlSnapshot
    from .content.clusters import build_clusters

    snap_id = request.GET.get("snapshot", "")
    snap = (
        CrawlSnapshot.objects.filter(id=snap_id).first()
        if snap_id else CrawlSnapshot.objects.order_by("-started_at").first()
    )
    if snap is None:
        return Response({"error": "no snapshot"}, status=404)

    mode = request.GET.get("mode", "primary").lower()
    if mode not in ("primary", "multi"):
        mode = "primary"

    return Response(build_clusters(snap, mode=mode))


# ── Compliance dashboard (WCAG / GDPR / OWASP) ─────────────────────────────


@api_view(["GET"])
def compliance_view(_request):
    """GET /api/v1/crawler/compliance — manager-facing compliance
    report aggregating WCAG accessibility, GDPR/DPDPA cookie, and
    OWASP security-header detectors with per-URL evidence.
    """
    from .compliance import build_compliance_payload
    return Response(build_compliance_payload())


def comprehensive_report_view(request):
    """GET /api/v1/crawler/report/comprehensive.xlsx — multi-sheet
    XLSX bundling Phase A-D audit data: Executive Summary,
    Compliance Overview, WCAG Findings, Privacy & Cookies, Security
    Headers, Structured Data, Hreflang Matrix, Technical SEO,
    Content Audit, Page Inventory, Detector Catalog.

    Query params:
      * sections — comma-separated subset of ALL_SECTIONS to emit.
        Defaults to all when absent.
    """
    from .storage.comprehensive_report import (
        ALL_SECTIONS, build_comprehensive_report,
    )

    requested = (request.GET.get("sections") or "").strip()
    sections = None
    if requested:
        sections = {s.strip() for s in requested.split(",") if s.strip()}
        sections = sections & set(ALL_SECTIONS)
        if not sections:
            sections = set(ALL_SECTIONS)

    out_path = build_comprehensive_report(sections=sections)
    return FileResponse(
        open(out_path, "rb"),
        as_attachment=True,
        filename="bajaj_seo_compliance_report.xlsx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )


def compliance_csv_view(_request):
    """GET /api/v1/crawler/compliance.csv — same data flattened to
    one row per (rule, URL) so it can be opened in Excel and shared
    with the engineering team for remediation."""
    from .compliance import build_compliance_csv
    body = build_compliance_csv()
    resp = StreamingHttpResponse(iter([body]), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="compliance_report.csv"'
    return resp


# ── Phase 6 — GEO suite (llms.txt + IndexNow + AI-bot logs + backlinks) ─────


@api_view(["GET"])
def llms_txt_audit_view(request):
    """GET /api/v1/crawler/geo/llms-txt — audit llms.txt at site root.

    Query: ?domain=bajajlifeinsurance.com (defaults to Bajaj).
    """
    from .services.llms_txt import audit as audit_llms

    domain = request.query_params.get("domain") or "bajajlifeinsurance.com"
    result = audit_llms(domain)
    return Response(result.as_dict())


@api_view(["GET"])
def llms_txt_draft_view(request):
    """GET /api/v1/crawler/geo/llms-txt/draft — generate a draft body
    from the AEM sitemap + page-type data."""
    from .services.llms_txt import generate as gen_llms

    try:
        cap = int(request.query_params.get("max_pages_per_section") or 30)
    except (TypeError, ValueError):
        cap = 30
    draft = gen_llms(max_pages_per_section=max(1, min(cap, 200)))
    return Response(draft.as_dict())


@api_view(["POST"])
def indexnow_ping_view(request):
    """POST /api/v1/crawler/geo/indexnow/ping — submit URLs to the
    IndexNow protocol (Bing + Yandex). Body: {"urls": [...]}.

    Hardcoded allow-prefix prevents accidental staging pings.
    """
    from .adapters.indexnow import ping_urls

    raw = request.data if hasattr(request, "data") else {}
    urls = raw.get("urls") if isinstance(raw, dict) else None
    if not urls or not isinstance(urls, list):
        return Response({"ok": False, "error": "missing 'urls' list in body"}, status=400)
    result = ping_urls(urls)
    return Response(result)


@api_view(["GET"])
def ai_bot_hits_view(request):
    """GET /api/v1/crawler/geo/ai-bots — recent verified AI-bot hits.

    Reads from the AIBotLog model populated by bot_log_parser. Returns
    an aggregate (per-bot counts) plus the most recent ``limit`` hits.
    """
    from .adapters.bot_log_parser import recent_hits, hits_by_bot

    try:
        limit = int(request.query_params.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    return Response({
        "totals": hits_by_bot(),
        "recent": recent_hits(max(1, min(limit, 500))),
    })


@api_view(["GET"])
def backlinks_view(request):
    """GET /api/v1/crawler/geo/backlinks — Common Crawl-derived backlinks
    pointing at Bajaj URLs.

    Phase 6 ships the model + adapter stub; the monthly WAT pull is
    operator-side. Endpoint returns whatever rows are loaded.
    """
    from .adapters.commoncrawl_backlinks import recent_backlinks, summary

    try:
        limit = int(request.query_params.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    return Response({
        "summary": summary(),
        "backlinks": recent_backlinks(max(1, min(limit, 500))),
    })
