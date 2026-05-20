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


@api_view(["POST"])
def gsc_coverage_build_view(request):
    """Derive a fresh coverage CSV from already-pulled GSC performance data
    plus a live sitemap fetch. Returns counts so the UI can show a toast.
    """
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
    """
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
