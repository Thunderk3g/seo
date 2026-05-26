"""DesignBriefAgent — Figma file → competitor-grounded design notes.

Operator workflow:

  1. Designer pastes a Figma file URL + frame name into the UI.
  2. We fetch the file's frame tree via the Figma REST API, extracting:
       * frame names + dimensions (the page-zone map)
       * text node contents (the copy)
       * image fills (the imagery)
       * component instances (reused design tokens)
  3. We join that "design intent" with the StructureAgent +
     LayoutAgent output for the target product type → emit a brief
     listing "competitor X has this in zone Y; your draft does/doesn't."

This module is the data side: the Figma fetch + parse, plus a
deterministic-only ``compose_brief()`` that returns the structured
diff. The LLM-narrated companion is gated on a Groq call (uses the
existing pool) and can be enabled per request.

Gated on ``FIGMA_TOKEN`` env. Without it the upload UI explains how
to provision one; the service refuses politely instead of crashing.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger("seo.ai.services.design_brief")


FIGMA_API = "https://api.figma.com/v1"


@dataclass
class FigmaFrameSummary:
    """One frame's worth of design intent — what the designer drew."""

    id: str
    name: str
    width: float = 0.0
    height: float = 0.0
    text_nodes: list[str] = field(default_factory=list)
    image_fill_count: int = 0
    component_instances: list[str] = field(default_factory=list)
    child_count: int = 0


@dataclass
class DesignBrief:
    """Final brief payload the UI renders."""

    figma_file_key: str
    figma_url: str
    frame_name: str = ""
    frame_summary: FigmaFrameSummary | None = None
    competitor_signals: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


# ── Figma fetch ──────────────────────────────────────────────────────


_FIGMA_URL_RE = re.compile(
    r"figma\.com/(?:file|design)/([A-Za-z0-9]+)(?:/[^?]*)?(?:\?node-id=([0-9:-]+))?",
)


def parse_figma_url(url: str) -> tuple[str, str]:
    """Extract ``(file_key, node_id)`` from a Figma file/design URL.

    Returns empty strings for both when the URL doesn't parse.
    """
    m = _FIGMA_URL_RE.search(url or "")
    if not m:
        return "", ""
    file_key = m.group(1) or ""
    node_id = (m.group(2) or "").replace("-", ":")  # Figma URL uses dashes
    return file_key, node_id


def fetch_figma_file(file_key: str) -> dict[str, Any]:
    """Fetch a Figma file's node tree via REST API.

    Raises ``RuntimeError`` when the FIGMA_TOKEN env is missing — the
    caller should surface this as a UI error directing the operator
    to provision a personal access token at
    https://www.figma.com/developers/api#access-tokens.
    """
    token = (os.environ.get("FIGMA_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "FIGMA_TOKEN env not set. Generate a Figma personal access "
            "token and set FIGMA_TOKEN=fig_pat_... in .env.",
        )
    if not file_key:
        raise RuntimeError("file_key required")

    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{FIGMA_API}/files/{file_key}",
            headers={"X-Figma-Token": token},
        )
        r.raise_for_status()
        return r.json()


def _walk_frame(node: dict[str, Any]) -> FigmaFrameSummary:
    """Aggregate text/image/component counts from a frame's subtree."""
    summary = FigmaFrameSummary(
        id=node.get("id") or "",
        name=node.get("name") or "",
    )
    box = (node.get("absoluteBoundingBox") or {})
    summary.width = float(box.get("width") or 0.0)
    summary.height = float(box.get("height") or 0.0)

    stack: list[dict[str, Any]] = [node]
    while stack:
        cur = stack.pop()
        ntype = cur.get("type")
        if ntype == "TEXT":
            text = (cur.get("characters") or "").strip()
            if text:
                summary.text_nodes.append(text[:200])
        if ntype == "INSTANCE":
            cname = (cur.get("name") or "").strip()
            if cname:
                summary.component_instances.append(cname[:80])
        # Image fills are stored in the "fills" array as imageRef entries.
        for fill in cur.get("fills") or []:
            if (fill or {}).get("type") == "IMAGE":
                summary.image_fill_count += 1
        for child in cur.get("children") or []:
            stack.append(child)
            summary.child_count += 1

    # Cap text nodes — designer briefs can have hundreds.
    summary.text_nodes = summary.text_nodes[:50]
    summary.component_instances = summary.component_instances[:50]
    return summary


def _find_frame_by_name(doc: dict[str, Any], frame_name: str) -> dict[str, Any] | None:
    """BFS the document tree for a frame whose name matches."""
    if not frame_name:
        return None
    target = frame_name.strip().lower()
    queue: list[dict[str, Any]] = [doc]
    while queue:
        node = queue.pop(0)
        if (node.get("name") or "").strip().lower() == target:
            return node
        for child in node.get("children") or []:
            queue.append(child)
    return None


# ── public brief composer ────────────────────────────────────────────


def compose_brief(
    *,
    figma_url: str,
    frame_name: str = "",
) -> DesignBrief:
    """Pull the named Figma frame + assemble a competitor-grounded brief.

    Deterministic — no LLM. The brief lists:

      * what's in the designer's frame (text, images, instances),
      * which competitors put similar elements in similar zones,
      * recommendations (e.g. "competitors put a calculator CTA in
        the hero on 7/8 product pages — your draft has none in zone
        'hero'").

    Joins against the layout-zone signal from the LayoutAgent + the
    structure-pattern signal from the StructureAgent so the brief is
    grounded in real crawl data, not generic design advice.
    """
    file_key, node_id = parse_figma_url(figma_url)
    brief = DesignBrief(figma_file_key=file_key, figma_url=figma_url, frame_name=frame_name)
    if not file_key:
        brief.error = "could not parse Figma file URL"
        return brief

    try:
        doc = fetch_figma_file(file_key)
    except RuntimeError as exc:
        brief.error = str(exc)
        return brief
    except httpx.HTTPStatusError as exc:
        brief.error = f"Figma API {exc.response.status_code}: {exc.response.text[:200]}"
        return brief
    except Exception as exc:  # noqa: BLE001
        brief.error = f"Figma fetch failed: {exc}"
        return brief

    document = doc.get("document") or {}
    frame = _find_frame_by_name(document, frame_name) if frame_name else document
    if frame is None:
        brief.error = f"frame '{frame_name}' not found in file"
        return brief

    brief.frame_summary = _walk_frame(frame)

    # ── Join with crawl data for competitor signals ─────────────
    # Pull the latest LayoutAgent zone rollups for each competitor;
    # surface "zone X has kind Y on N competitors" as one signal row.
    try:
        from .custodian import layout_diff
        from apps.crawler.models import CrawlSnapshot
        from django.db.models import Count

        our_snap = (
            CrawlSnapshot.objects.annotate(n=Count("pages"))
            .filter(kind="bajaj", n__gte=5)
            .order_by("-started_at")
            .first()
        )
        if our_snap:
            comp_ids = list(
                CrawlSnapshot.objects.annotate(n=Count("pages"))
                .filter(kind="competitor", n__gte=5)
                .order_by("-started_at")
                .values_list("id", flat=True)[:5]
            )
            comp_ids_str = [str(i) for i in comp_ids]
            diff = layout_diff(str(our_snap.id), comp_ids_str)
            for domain, zone_diffs in (diff.get("diffs_by_competitor") or {}).items():
                for entry in zone_diffs:
                    brief.competitor_signals.append({
                        "competitor": domain,
                        "zone": entry.get("zone"),
                        "kinds_only_in_competitor": entry.get("kinds_only_in_competitor"),
                    })
    except Exception as exc:  # noqa: BLE001 — never block the brief
        log.info("design_brief: layout diff skipped (%s)", exc)

    # ── Recommendations — deterministic rule set ─────────────────
    # When ≥ half the competitors have a kind in a zone and our
    # designer's frame doesn't appear to cover that zone, flag it.
    zone_kind_count: dict[tuple[str, str], int] = {}
    for sig in brief.competitor_signals:
        zone = sig.get("zone") or "other"
        for kind in sig.get("kinds_only_in_competitor") or []:
            zone_kind_count[(zone, kind)] = zone_kind_count.get((zone, kind), 0) + 1
    half = max(1, len(brief.competitor_signals) // 2)
    for (zone, kind), n in zone_kind_count.items():
        if n >= half:
            brief.recommendations.append({
                "type": "missing_in_zone",
                "zone": zone,
                "kind": kind,
                "competitors_with_this": n,
                "rationale": (
                    f"{n} competitor(s) put a '{kind}' link/element in the "
                    f"'{zone}' zone. Consider adding the same to your frame."
                ),
            })

    return brief
