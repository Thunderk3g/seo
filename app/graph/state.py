from typing import TypedDict, List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AgentMessage(BaseModel):
    role: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class AgentState(TypedDict):
    # Input/Output
    input_prompt: str
    output_response: Optional[str]
    
    # Core Metadata
    intent: Optional[str]
    depth: str  # shallow, deep
    modality: str # text, chart, report
    
    # Execution Tracking
    current_node: str
    history: List[AgentMessage]
    
    # Data Repositories (Shared Memory)
    collected_data: List[Dict[str, Any]]
    semantic_context: Dict[str, Any]
    missing_fields: List[str]
    
    # Reasoning Results
    analysis_results: Dict[str, Any]
    visualization_config: Dict[str, Any]
    narrative_output: str
    
    # Control Flow
    next_action: str
    errors: List[str]
    retries: int
