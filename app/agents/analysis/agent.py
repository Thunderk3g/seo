from typing import Dict, Any
from app.graph.state import AgentState
from app.models.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate

async def analysis_agent(state: AgentState) -> Dict[str, Any]:
    llm = get_llm()
    context = state.get("semantic_context", {}).get("merged_summary", "")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Perform deep analysis, identify trends, correlations, and root causes based on the context provided."),
        ("human", "Context: {context}")
    ])
    
    chain = prompt | llm
    result = await chain.ainvoke({"context": context})
    
    return {
        "analysis_results": {"content": result.content},
        "current_node": "analysis"
    }
