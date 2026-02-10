from typing import Dict, Any
from langgraph.graph import StateGraph, END
from app.graph.state import AgentState

from app.agents.intent.agent import intent_agent
from app.agents.orchestrator.agent import orchestrator_agent
from app.agents.adapters.agent import adapters_agent
from app.agents.semantic_umbrella.agent import semantic_umbrella_agent
from app.agents.analysis.agent import analysis_agent
from app.agents.visualization.agent import visualization_agent
from app.agents.reporting.agent import reporting_agent

# Use the imported agents in the nodes
async def intent_node(state: AgentState) -> Dict[str, Any]:
    return await intent_agent(state)

async def orchestrator_node(state: AgentState) -> Dict[str, Any]:
    return await orchestrator_agent(state)

async def adapter_node(state: AgentState) -> Dict[str, Any]:
    return await adapters_agent(state)

async def semantic_umbrella_node(state: AgentState) -> Dict[str, Any]:
    return await semantic_umbrella_agent(state)

async def analysis_node(state: AgentState) -> Dict[str, Any]:
    return await analysis_agent(state)

async def visualization_node(state: AgentState) -> Dict[str, Any]:
    return await visualization_agent(state)

async def reporting_node(state: AgentState) -> Dict[str, Any]:
    return await reporting_agent(state)

# Conditional routing logic
def router_logic(state: AgentState) -> str:
    if state.get("errors"):
        return "error_handler"
    return state.get("next_action", "analysis")

def create_graph():
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("intent", intent_node)
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("adapters", adapter_node)
    workflow.add_node("semantic_umbrella", semantic_umbrella_node)
    workflow.add_node("analysis", analysis_node)
    workflow.add_node("visualization", visualization_node)
    workflow.add_node("reporting", reporting_node)

    # Set Entry Point
    workflow.set_entry_point("intent")

    # Define Edges
    workflow.add_edge("intent", "orchestrator")
    workflow.add_edge("orchestrator", "adapters")
    workflow.add_edge("adapters", "semantic_umbrella")
    workflow.add_edge("semantic_umbrella", "analysis")
    
    # Simple sequential flow for now, can be complex branching
    workflow.add_edge("analysis", "visualization")
    workflow.add_edge("visualization", "reporting")
    workflow.add_edge("reporting", END)

    return workflow.compile()

master_app = create_graph()
