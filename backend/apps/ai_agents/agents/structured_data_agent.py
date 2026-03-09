"""Agent for structured data analysis."""

from apps.common import constants
from apps.crawl_sessions.models import CrawlSession, StructuredData


class StructuredDataAgent:
    """Analyzes schema implementation and validation states."""

    @staticmethod
    def analyze_session(session_id: str) -> dict:
        """Analyze structured data validation states across a session."""
        try:
            session = CrawlSession.objects.get(id=session_id)
        except CrawlSession.DoesNotExist:
            return {"error": "Session not found"}

        schemas = StructuredData.objects.filter(page__crawl_session=session)
        total_schemas = schemas.count()

        if total_schemas == 0:
            return {"status": "no_data", "message": "No structured data found."}

        # ── Group by Schema Type and Validation State ──────────
        summary = {}
        # Count by state
        state_counts = {
            constants.VALIDATION_STATE_VALID: 0,
            constants.VALIDATION_STATE_WARNING: 0,
            constants.VALIDATION_STATE_INVALID: 0,
        }

        for schema_type in schemas.values_list("schema_type", flat=True).distinct():
            type_schemas = schemas.filter(schema_type=schema_type)
            
            valid = type_schemas.filter(validation_state=constants.VALIDATION_STATE_VALID).count()
            warning = type_schemas.filter(validation_state=constants.VALIDATION_STATE_WARNING).count()
            invalid = type_schemas.filter(validation_state=constants.VALIDATION_STATE_INVALID).count()
            
            summary[schema_type] = {
                "total": type_schemas.count(),
                "valid": valid,
                "warning": warning,
                "invalid": invalid,
            }
            
            state_counts[constants.VALIDATION_STATE_VALID] += valid
            state_counts[constants.VALIDATION_STATE_WARNING] += warning
            state_counts[constants.VALIDATION_STATE_INVALID] += invalid

        return {
            "session_id": str(session.id),
            "total_schemas": total_schemas,
            "overall_health": {
                "valid_count": state_counts[constants.VALIDATION_STATE_VALID],
                "warning_count": state_counts[constants.VALIDATION_STATE_WARNING],
                "invalid_count": state_counts[constants.VALIDATION_STATE_INVALID],
                "percent_valid": round((state_counts[constants.VALIDATION_STATE_VALID] / total_schemas) * 100, 2),
            },
            "type_summary": summary,
            "status": "success",
        }
