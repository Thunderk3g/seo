import json
from datetime import datetime
from app.logging import logger

class AuditLogger:
    """
    Records immutable logs of agent decisions and data access.
    """
    @staticmethod
    def log_decision(agent_type: str, decision: dict, metadata: dict):
        audit_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent_type,
            "decision": decision,
            "metadata": metadata
        }
        # In production, this would be written to a secure, tamper-proof database
        logger.info("AUDIT_LOG", **audit_entry)

audit_logger = AuditLogger()
