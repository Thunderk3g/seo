from typing import Dict, Callable, Any
from pydantic import BaseModel

class ToolRegistry:
    """
    Central registry for all tools available to the agents.
    """
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register_tool(self, name: str, func: Callable, schema: Any):
        self._tools[name] = {
            "func": func,
            "schema": schema
        }

    def get_tool(self, name: str):
        return self._tools.get(name)

    def list_tools(self):
        return list(self._tools.keys())

tool_registry = ToolRegistry()
