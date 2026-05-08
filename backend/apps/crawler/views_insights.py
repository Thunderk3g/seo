"""Standalone view for the AI insights endpoint (Day 5).

Lives outside ``views.py`` to avoid stepping on Agent B's edits to the
``CrawlSessionViewSet`` action surface. The router-bound ViewSet path and
this standalone path are non-overlapping at URL-resolve time:

    GET  /api/v1/sessions/<uuid>/insights/   → cached payload (cheap)
    POST /api/v1/sessions/<uuid>/insights/   → force-regenerate (Anthropic)

Both methods always return 200 with the full InsightsResponse shape
unless the session does not exist (404). The ``available`` flag tells
the frontend whether to render the live drawer or the "not configured"
placeholder copy.
"""

from __future__ import annotations

from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.ai_agents.services.insights_service import InsightsService
from apps.crawl_sessions.models import CrawlSession


@api_view(["GET", "POST"])
def insights_view(request, session_id):
    """Return AI-generated insights for a single crawl session.

    GET  → ``InsightsService.get_insights`` (cached row, no Anthropic call
           when the cache is warm).
    POST → ``InsightsService.regenerate`` (force-fresh; bills Anthropic and
           overwrites the cache).
    """
    try:
        session = CrawlSession.objects.get(pk=session_id)
    except CrawlSession.DoesNotExist:
        return Response({"detail": "Session not found"}, status=404)

    if request.method == "POST":
        return Response(InsightsService.regenerate(session))
    return Response(InsightsService.get_insights(session))
