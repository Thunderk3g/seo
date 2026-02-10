from typing import Dict, Any
from app.graph.state import AgentState
from app.models.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

class IntentResponse(BaseModel):
    intent: str = Field(description="The primary intent of the user")
    depth: str = Field(description="Level of depth required: shallow or deep")
    modality: str = Field(description="Format desired: text, chart, or report")

async def intent_agent(state: AgentState) -> Dict[str, Any]:
    llm = get_llm().with_structured_output(IntentResponse)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Analyze the user input and determine intent, depth, and modality."),
        ("human", "{input}")
    ])
    
    chain = prompt | llm
    result = await chain.ainvoke({"input": state["input_prompt"]})
    
    return {
        "intent": result.intent,
        "depth": result.depth,
        "modality": result.modality,
        "current_node": "intent"
    }
