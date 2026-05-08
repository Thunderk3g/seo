"""AI insights service — Day 5 + cache extension.

Builds a session-scoped natural-language summary using the Anthropic SDK.

Behaviour:
  - When ``ANTHROPIC_API_KEY`` is unset (or the SDK is not importable), the
    service returns a stub payload with ``available=False``. The frontend uses
    this flag to render "AI insights are not configured" copy.
  - When the key is present, the service composes a request with two blocks:
      * ``system`` — static persona + output contract, marked
        ``cache_control: {type: "ephemeral"}`` so subsequent calls hit the
        prompt cache.
      * ``messages[0]`` — the per-session derived stats. NOT cached; this is
        the dynamic input.
  - Strict-JSON reply (``{"summary", "highlights"}``) is parsed; on any error
    we degrade gracefully to a "fallback" payload that still satisfies the
    InsightsResponse shape so the UI does not break.

Cache layer (spec §4.3, §4.4, §6 step 5):
  - Anthropic calls cost real money; every drawer-open used to re-issue.
  - ``regenerate(session)`` performs the live call and persists the result on
    ``CrawlSession.ai_insights`` (+ generated_at, + model). It is invoked
    once at the end of a crawl by ``tasks.run_on_demand_crawl`` and again on
    explicit POST to ``/sessions/<id>/insights/``.
  - ``get_insights(session)`` is the cheap GET path: returns the cached row
    when present, otherwise falls back to ``regenerate`` so the UI never
    sees an empty drawer.

The model defaults to ``claude-sonnet-4-6`` and is overridable via the
``ANTHROPIC_MODEL`` env var.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from django.utils import timezone as dj_timezone

from apps.ai_agents.agents.indexing_agent import IndexingIntelligenceAgent
from apps.crawl_sessions.models import CrawlSession
from apps.crawl_sessions.services.issue_service import IssueService

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "claude-sonnet-4-6"

# Persona + output contract. Static: kept lexicographically frozen and free of
# any per-request data so the prefix is cacheable.
_SYSTEM_PROMPT = (
    "You are Lattice, an SEO insights analyst. You receive a JSON payload "
    "describing a single crawl session: indexability state distribution, "
    "canonical cluster diagnostics, and a 12-category issue summary. "
    "Produce an executive-level read-out for an SEO marketing operator.\n\n"
    "Reply ONLY with strict JSON in this exact shape, no prose, no code "
    "fence:\n"
    "{\n"
    '  "summary": "<2-3 plain-text sentences describing the most important '
    'finding>",\n'
    '  "highlights": [\n'
    "    {\n"
    '      "title": "<short label>",\n'
    '      "severity": "info" | "warning" | "critical",\n'
    '      "body": "<1-2 sentences explaining what to do>"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    " - Aim for 3-5 highlights, ordered by severity (critical first).\n"
    " - Severity must be one of info, warning, critical.\n"
    " - Keep wording specific to the data; avoid generic SEO platitudes.\n"
    " - Never invent metrics that are not in the input."
)


def _is_anthropic_available() -> bool:
    """True iff the API key is set in the environment at call time."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _build_session_payload(session: CrawlSession) -> dict[str, Any]:
    """Gather per-session derived stats — the dynamic (uncached) input."""
    indexing = IndexingIntelligenceAgent.analyze_session(str(session.id))
    canonical = IndexingIntelligenceAgent.analyze_canonical_clusters(str(session.id))
    issues = IssueService.derive_issues(session)
    return {
        "session_id": str(session.id),
        "website_domain": getattr(session.website, "domain", None),
        "status": session.status,
        "indexing": indexing,
        "canonical_clusters": canonical,
        "issue_summary": issues,
    }


def _stub_payload(session: CrawlSession) -> dict[str, Any]:
    """Return a deterministic offline payload when the SDK is unavailable.

    The summary still references real session counters so the UI is not
    completely blank during local development.
    """
    return {
        "available": False,
        "session_id": str(session.id),
        "summary": (
            "AI insights are not configured. Set ANTHROPIC_API_KEY to enable "
            "natural-language analysis of this crawl session."
        ),
        "highlights": [],
        "model": "stub",
        "cached": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _parse_model_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Parse the model's JSON-shaped reply.

    Returns (summary, highlights). On parse failure, falls back to using the
    raw text as the summary with an empty highlights list.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text.strip(), []

    summary = data.get("summary") if isinstance(data, dict) else None
    highlights = data.get("highlights") if isinstance(data, dict) else None
    if not isinstance(summary, str):
        summary = text.strip()
    if not isinstance(highlights, list):
        highlights = []

    # Defensive shape coercion — the model may emit extra keys.
    cleaned: list[dict[str, Any]] = []
    for h in highlights:
        if not isinstance(h, dict):
            continue
        title = h.get("title")
        severity = h.get("severity")
        body = h.get("body")
        if severity not in ("info", "warning", "critical"):
            severity = "info"
        cleaned.append(
            {
                "title": str(title or "")[:120],
                "severity": severity,
                "body": str(body or "")[:600],
            }
        )
    return summary, cleaned


def _real_anthropic_payload(session: CrawlSession) -> dict[str, Any]:
    """Issue the cached Anthropic call and shape the response."""
    # Imported lazily so test environments without the package can still import
    # this module to exercise the stub branch.
    import anthropic  # type: ignore

    model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)
    payload = _build_session_payload(session)

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=0.3,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                # Mark the static persona/contract block as cacheable. The
                # per-session payload below is NOT cached — it is the dynamic
                # input that varies on every request.
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": json.dumps(payload, default=str, sort_keys=True),
            }
        ],
    )

    # Extract the text content from the first text block.
    text = ""
    for block in response.content or []:
        if getattr(block, "type", None) == "text":
            text = block.text
            break

    summary, highlights = _parse_model_text(text)

    # Note: ``cached`` here is the row-cache flag (spec §4.4), not the
    # Anthropic prompt-cache flag. Any fresh compute always emits
    # cached=False; regenerate() overrides this anyway. We deliberately
    # discard ``response.usage.cache_read_input_tokens`` — the
    # cache_control on the system block still works to reduce token cost,
    # but the frontend signal "cached" must reflect "served from
    # session.ai_insights without an Anthropic round-trip".

    return {
        "available": True,
        "session_id": str(session.id),
        "summary": summary,
        "highlights": highlights,
        "model": model,
        "cached": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _compute_payload(session: CrawlSession) -> dict[str, Any]:
    """Run the full compute path (stub, real-SDK, or fallback).

    This is the *uncached* path used by ``regenerate``. ``cached`` here
    refers to Anthropic's prompt cache (cache_read_input_tokens > 0), not
    the row-level cache on ``session.ai_insights``.
    """
    if not _is_anthropic_available():
        return _stub_payload(session)
    try:
        return _real_anthropic_payload(session)
    except Exception:  # noqa: BLE001 — we want to catch SDK + parse errors.
        logger.exception("AI insights call failed for session %s", session.id)
        stub = _stub_payload(session)
        stub["summary"] = "AI insights temporarily unavailable."
        stub["model"] = "fallback"
        return stub


class InsightsService:
    """Public entry point for the AI insights endpoint.

    Two methods:
      * :meth:`get_insights` — cache-aware. Cheap GET. Returns the cached
        ``session.ai_insights`` payload when present; otherwise falls back
        to a one-time :meth:`regenerate` so the drawer never opens empty.
      * :meth:`regenerate` — calls Anthropic (or stub/fallback) and writes
        the payload to the session row. Invoked at end-of-crawl and on
        explicit POST to ``/sessions/<id>/insights/``.
    """

    @staticmethod
    def get_insights(session: CrawlSession) -> dict[str, Any]:
        """Return the InsightsResponse shape for *session* (cache-first).

        Cache hit detection: if ``session.ai_insights`` is a non-empty
        dict AND ``session.ai_insights_generated_at`` is set, the row is
        considered fresh and returned with ``cached=True`` (no SDK call).
        Otherwise we call :meth:`regenerate` synchronously so the UI gets
        a populated drawer on first open.

        Note: a fallback payload (``model="fallback"``) persisted by
        ``regenerate`` will be returned by every subsequent GET until the
        user explicitly POSTs to force a fresh compute. This is
        intentional — best-effort means "don't bill Anthropic just
        because the drawer opened"; the user can hit Regenerate to retry.
        """
        cached = session.ai_insights
        if isinstance(cached, dict) and cached and session.ai_insights_generated_at:
            payload = dict(cached)
            payload["cached"] = True
            payload["model"] = session.ai_insights_model or payload.get("model", "")
            payload["generated_at"] = session.ai_insights_generated_at.isoformat()
            payload["session_id"] = str(session.id)
            return payload
        # Cache miss → compute + persist so subsequent GETs are cheap.
        return InsightsService.regenerate(session)

    @staticmethod
    def regenerate(session: CrawlSession) -> dict[str, Any]:
        """Force a fresh compute and persist the result to the session row.

        Best-effort: never raises. If Anthropic errors, the fallback payload
        is still persisted so subsequent GETs return the friendly message.
        Always returns ``cached=False`` (this is the live compute path).
        """
        payload = _compute_payload(session)
        # Fresh compute is, by definition, not a row-cache hit.
        payload["cached"] = False
        try:
            session.ai_insights = payload
            session.ai_insights_generated_at = dj_timezone.now()
            session.ai_insights_model = payload.get("model", "") or ""
            session.save(update_fields=[
                "ai_insights",
                "ai_insights_generated_at",
                "ai_insights_model",
                "updated_at",
            ])
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to persist AI insights cache for session %s", session.id,
            )
        return payload
