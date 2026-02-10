from typing import Literal
from app.graph.state import AgentState

def should_continue(state: AgentState) -> Literal["continue", "end", "error"]:
    """
    Determines the next path in the graph based on the current state.
    """
    if state.get("errors"):
        return "error"
    
    if state.get("output_response"):
        return "end"
    
    return "continue"

def orchestrate_routing(state: AgentState) -> Literal["adapters", "analysis"]:
    """
    Advanced routing logic for the Orchestrator node.
    """
    intent = state.get("intent", "").lower()
    if any(keyword in intent for keyword in ["search", "fetch", "data", "lookup"]):
        return "adapters"
    return "analysis"
