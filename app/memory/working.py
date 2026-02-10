from typing import Dict, Any

class WorkingMemory:
    """Manages short-term execution state within a single request cycle."""
    def __init__(self):
        self.state: Dict[str, Any] = {}

    def update(self, key: str, value: Any):
        self.state[key] = value

    def get(self, key: str):
        return self.state.get(key)
