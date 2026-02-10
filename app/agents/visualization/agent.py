from typing import Dict, Any
from app.graph.state import AgentState
from app.models.llm import get_llm
from pydantic import BaseModel, Field

class ChartConfig(BaseModel):
    chart_type: str = Field(description="Type of chart (bar, line, pie, etc.)")
    data_labels: list[str]
    data_values: list[float]
    title: str

async def visualization_agent(state: AgentState) -> Dict[str, Any]:
    # Check if modality requires a chart
    if state.get("modality") != "chart":
        return {"current_node": "visualization"}

    llm = get_llm().with_structured_output(ChartConfig)
    analysis = state.get("analysis_results", {}).get("content", "")
    
    prompt = "Based on this analysis: {analysis}, suggest a chart configuration."
    result = await llm.ainvoke(prompt.format(analysis=analysis))
    
    return {
        "visualization_config": result.model_dump(),
        "current_node": "visualization"
    }
