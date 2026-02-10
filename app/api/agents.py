from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.graph.master_graph import master_app
from app.graph.state import AgentState

router = APIRouter()

class ProcessRequest(BaseModel):
    prompt: str

class ProcessResponse(BaseModel):
    response: str
    metadata: dict

@router.post("/process", response_model=ProcessResponse)
async def process_request(request: ProcessRequest):
    try:
        # Initial State
        initial_state = {
            "input_prompt": request.prompt,
            "history": [],
            "collected_data": [],
            "semantic_context": {},
            "missing_fields": [],
            "errors": [],
            "retries": 0,
            "depth": "shallow",
            "modality": "text"
        }
        
        # Run Graph
        result = await master_app.ainvoke(initial_state)
        
        return ProcessResponse(
            response=result.get("output_response", "No response generated."),
            metadata={
                "intent": result.get("intent"),
                "node_history": result.get("current_node")
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
