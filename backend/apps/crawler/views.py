"""DRF views — Django port of crawler-engine FastAPI routes.

Endpoint map (all under ``/api/v1/crawler/``):

  GET  /status            — current crawl state + stats
  POST /start             — kick off a new crawl in a background thread
  POST /stop              — signal the running crawl to drain & stop
  GET  /summary           — high-level counters for dashboard cards
  GET  /tables            — list of CSV-backed tables with row counts
  GET  /tables/<key>      — full headers + rows of one table
  GET  /download/<key>    — raw CSV download
  GET  /reports/xlsx      — multi-sheet styled XLSX report download
  GET  /tree              — hierarchical site graph derived from discovered edges
  GET  /logs              — polling log feed (replaces FastAPI WebSocket)
"""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from django.http import FileResponse, JsonResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import log_bus
from .conf import settings
from .services import crawler_service, report_service
from .state import STATE
from .storage import repository as repo


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
def tables_list_view(_request):
    items = []
    for key, meta in repo.CATALOG.items():
        count = repo.read_csv(key)["count"]
        items.append({
            "key": key,
            "label": meta["label"],
            "icon": meta["icon"],
            "description": meta["description"],
            "count": count,
        })
    return Response({"tables": items})


@api_view(["GET"])
def table_detail_view(_request, key: str):
    meta = repo.CATALOG.get(key)
    if not meta:
        return Response({"error": "Unknown table"}, status=404)
    data = repo.read_csv(key)
    return Response({
        "key": key,
        "label": meta["label"],
        "icon": meta["icon"],
        "description": meta["description"],
        "headers": data["headers"],
        "rows": data["rows"],
        "count": data["count"],
    })


@api_view(["GET"])
def download_csv_view(_request, key: str):
    meta = repo.CATALOG.get(key)
    if not meta:
        return JsonResponse({"error": "Unknown file"}, status=404)
    path: Path = settings.data_path / meta["file"]
    if not path.exists():
        return JsonResponse({"error": "File not yet generated"}, status=404)
    # FileResponse opens the file in binary mode and streams it.
    return FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=meta["file"],
        content_type="text/csv",
    )


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
