from typing import Dict, Any, List

class SemanticMemory:
    """
    Manages semantic knowledge extracted during the session.
    Typically backed by a vector store or a document store.
    """
    def __init__(self):
        self.kb: Dict[str, Any] = {}

    def store_fact(self, key: str, value: Any):
        self.kb[key] = value

    def query(self, query: str) -> List[Any]:
        # Simple keyword matching for now
        return [v for k, v in self.kb.items() if query.lower() in k.lower()]
