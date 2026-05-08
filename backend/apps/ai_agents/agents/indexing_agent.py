"""Agent for indexing potential assessment.

Consumes crawl data to identify indexability issues,
canonical mismatches, and overall coverage health.

Day 5 extension: ``analyze_session`` and ``analyze_canonical_clusters`` feed
:class:`apps.ai_agents.services.insights_service.InsightsService`, which
composes them with :class:`IssueService.derive_issues` and posts the result
to Anthropic with a prompt-cached system block. This module deliberately
keeps the LLM call out of the per-page pipeline — the agent stays a pure
analytics helper, and only the explicit insights endpoint pays the LLM cost.
"""

from apps.common import constants
from apps.crawl_sessions.models import CrawlSession, Page


class IndexingIntelligenceAgent:
    """Analyzes indexing health and canonical configurations."""

    @staticmethod
    def analyze_session(session_id: str) -> dict:
        """Analyze indexability state distribution for a session."""
        try:
            session = CrawlSession.objects.get(id=session_id)
        except CrawlSession.DoesNotExist:
            return {"error": "Session not found"}

        pages = Page.objects.filter(crawl_session=session)
        total_pages = pages.count()

        if total_pages == 0:
            return {"status": "no_data", "message": "No pages crawled in this session."}

        # ── Group by Lifecycle State ───────────────────────────
        state_distribution = {}
        for state_val, _ in constants.LIFECYCLE_STATE_CHOICES:
            count = pages.filter(url_lifecycle_state=state_val).count()
            if count > 0:
                state_distribution[state_val] = count

        return {
            "session_id": str(session.id),
            "total_pages": total_pages,
            "index_eligible": session.total_index_eligible,
            "excluded": session.total_excluded,
            "state_distribution": state_distribution,
            "status": "success",
        }

    @staticmethod
    def analyze_canonical_clusters(session_id: str) -> dict:
        """Analyze canonical configurations for mismatches and conflicts."""
        try:
            session = CrawlSession.objects.get(id=session_id)
        except CrawlSession.DoesNotExist:
            return {"error": "Session not found"}

        # Pages where the declared canonical doesn't match the resolved canonical
        mismatches = Page.objects.filter(
            crawl_session=session,
            canonical_match=False,
        ).only("url", "canonical_url", "canonical_resolved")

        # Missing canonicals
        missing = Page.objects.filter(
            crawl_session=session,
            canonical_url="",
        ).only("url")
        
        mismatch_details = []
        for page in mismatches:
            mismatch_details.append({
                "url": page.url,
                "declared": page.canonical_url,
                "resolved": page.canonical_resolved,
                "diagnostic": f"Duplicate, crawler chose {page.canonical_resolved} over user intent {page.canonical_url}",
            })

        return {
            "session_id": str(session.id),
            "total_mismatches": mismatches.count(),
            "total_missing": missing.count(),
            "mismatch_details": mismatch_details,
            "status": "success",
        }
