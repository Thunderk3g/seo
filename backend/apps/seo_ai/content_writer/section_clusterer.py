"""Cluster one page's content into named topical sections via LLM.

Thin wrapper over the existing
``apps.seo_ai.services.page_topic_sections.build_page_topic_sections``
which already:

* groups consecutive headings into LLM-named topic blocks
  ("Tax Benefits", "Premium Calculator", "Eligibility", "FAQ", ...);
* caches the clustering on disk per (snapshot_id, url) for 24 h so
  re-running a revamp the same day is free of LLM cost;
* surfaces internal-link → section ties so the writer can reason about
  what each section is supposed to link out to.

The wrapper exists so this package owns a stable input/output shape and
the orchestrator never reaches into ``services``. If we ever swap the
underlying clusterer for a different approach (embedding-based, denser
LLM call, ...), only this file changes.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("seo.ai.content_writer.section_clusterer")


def cluster_page_sections(page_row, *, provider=None, model: str | None = None) -> dict[str, Any]:
    """Cluster ``page_row`` (a ``CrawlerPageResult``) into named sections.

    Returns the section payload dict from
    ``services.page_topic_sections.build_page_topic_sections`` → ``_to_dict``.

    ``provider``/``model`` route the LLM call through the content_writer's
    Claude provider (Haiku) without disturbing the global provider. On any
    failure returns a minimal payload with ``error`` populated so the rest
    of the pipeline (gap engine, writer) still runs.
    """
    if page_row is None:
        return {"sections": [], "error": "no page row to cluster"}
    try:
        from ..services.page_topic_sections import (
            _to_dict as _section_to_dict,
            build_page_topic_sections,
        )
        result = build_page_topic_sections(
            page=page_row, provider=provider, model=model,
        )
        return _section_to_dict(result)
    except Exception as exc:  # noqa: BLE001 — non-fatal for the orchestrator
        logger.warning(
            "section clustering failed for %s: %s",
            getattr(page_row, "url", "?"), exc,
        )
        return {"sections": [], "error": f"{type(exc).__name__}: {exc}"}


def cluster_many_by_url(
    rows_by_url: dict[str, Any],
    *,
    provider=None,
    model: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Cluster a dict of ``{url: page_row}`` and return ``{url: payload}``.

    Sequential by design — parallelising N more LLM calls on top of N
    SERP crawls invites rate-limit trouble.
    """
    out: dict[str, dict[str, Any]] = {}
    for url, row in rows_by_url.items():
        out[url] = cluster_page_sections(row, provider=provider, model=model)
    return out
