from typing import Dict, Any
from app.graph.state import AgentState

async def orchestrator_agent(state: AgentState) -> Dict[str, Any]:
    # Pure routing logic based on state
    # Decides which adapters to call or if skipping to analysis
    intent = state.get("intent")
    
    # Logic to select external tools/APIs based on intent
    target_adapters = ["general_search"]
    if "market" in intent.lower():
        target_adapters.append("finance_api")
        
    return {
        "next_action": "adapters",
        "semantic_context": {"target_adapters": target_adapters},
        "current_node": "orchestrator"
    }
