"""Agent for URL classification explanation and GSC state mapping."""

from apps.common import constants
from apps.crawl_sessions.models import CrawlSession, Page


class ClassificationExplainerAgent:
    """Maps URLs to GSC states and provides human-readable context."""

    # Explanation templates as defined in AI Agent Structure spec
    EXPLANATION_TEMPLATES = {
        constants.LIFECYCLE_STATE_DISCOVERED: "Googlebot found the URL but hasn't crawled it yet. Usually due to crawl budget constraints.",
        constants.LIFECYCLE_STATE_CRAWLED: "Googlebot crawled the page but decided not to index it. This often points to quality issues or thin content.",
        constants.LIFECYCLE_STATE_INDEX_ELIGIBLE: "Page was successfully crawled and is eligible for indexing.",
        constants.LIFECYCLE_STATE_ALTERNATE_CANONICAL: "This is a duplicate of another page, and correctly points to the canonical version. No action needed.",
        constants.LIFECYCLE_STATE_DUPLICATE_NOT_SELECTED: "This is a duplicate page, but lacks a canonical tag. Google picked a different canonical than what you likely want.",
        constants.LIFECYCLE_STATE_NOT_FOUND: "The page returned a 404. If this page moved, add a 301 redirect. If it's permanently gone, a 404 is correct.",
        constants.LIFECYCLE_STATE_SOFT_404: "Page returns a 200 OK, but looks like an error page (e.g. 'Not Found' text). Return a real 404 or 410.",
        constants.LIFECYCLE_STATE_BLOCKED_ROBOTS: "Access is blocked by robots.txt. The page won't be crawled unless you update the rules.",
        constants.LIFECYCLE_STATE_NOINDEX: "Page has a 'noindex' tag. It was crawled but intentionally excluded from the index.",
        constants.LIFECYCLE_STATE_SERVER_ERROR: "The server returned a 5xx error. Check server logs for crashes or capacity issues.",
        constants.LIFECYCLE_STATE_REDIRECT: "The URL redirects to another page. The target URL will be evaluated for indexing.",
        constants.LIFECYCLE_STATE_ANOMALY: "An unspecified crawl error occurred (e.g., DNS issue, timeout).",
    }

    @classmethod
    def explain_url(cls, page: Page) -> dict:
        """Provide a human-readable explanation for a single URL's state."""
        state = page.url_lifecycle_state
        explanation = cls.EXPLANATION_TEMPLATES.get(
            state,
            "Unknown classification state."
        )

        return {
            "url": page.url,
            "lifecycle_state": state,
            "explanation": explanation,
        }

    @classmethod
    def explain_session_distribution(cls, session_id: str) -> dict:
        """Generate explanations for the overall coverage state of a session."""
        try:
            session = CrawlSession.objects.get(id=session_id)
        except CrawlSession.DoesNotExist:
            return {"error": "Session not found"}

        pages = Page.objects.filter(crawl_session=session)
        
        distribution = {}
        for state_val, state_label in constants.LIFECYCLE_STATE_CHOICES:
            count = pages.filter(url_lifecycle_state=state_val).count()
            if count > 0:
                distribution[state_val] = {
                    "label": state_label,
                    "count": count,
                    "explanation": cls.EXPLANATION_TEMPLATES.get(state_val, ""),
                }

        return {
            "session_id": str(session.id),
            "distribution": distribution,
            "status": "success",
        }
