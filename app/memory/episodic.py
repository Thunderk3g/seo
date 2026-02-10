from typing import List, Dict, Any
from datetime import datetime

class EpisodicMemory:
    """
    Tracks interaction history (episodes) for long-term coherence.
    """
    def __init__(self):
        self.episodes: List[Dict[str, Any]] = []

    def record_episode(self, input_prompt: str, output_response: str, metadata: Dict[str, Any]):
        self.episodes.append({
            "timestamp": datetime.utcnow().isoformat(),
            "input": input_prompt,
            "output": output_response,
            "metadata": metadata
        })

    def get_recent_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        return self.episodes[-limit:]
