from typing import Dict, Any
from app.graph.state import AgentState
from app.models.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate

async def reporting_agent(state: AgentState) -> Dict[str, Any]:
    llm = get_llm()
    analysis = state.get("analysis_results", {}).get("content", "")
    intent = state.get("intent", "")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Generate an executive-level report with sharp insights and professional language."),
        ("human", "Intent: {intent}\nAnalysis: {analysis}")
    ])
    
    chain = prompt | llm
    result = await chain.ainvoke({"intent": intent, "analysis": analysis})
    
    return {
        "narrative_output": result.content,
        "output_response": result.content,
        "current_node": "reporting"
    }
