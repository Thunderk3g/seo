from typing import List

class ToolPermissions:
    """
    Manages access control for tools.
    """
    def __init__(self):
        # Example role-based access
        self.role_permissions = {
            "admin": ["*"],
            "user": ["general_search", "weather_api"],
            "analyst": ["general_search", "finance_api", "chart_engine"]
        }

    def can_access(self, role: str, tool_name: str) -> bool:
        allowed = self.role_permissions.get(role, [])
        return "*" in allowed or tool_name in allowed
