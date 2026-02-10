import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.graph.master_graph import master_app

router = APIRouter()

class StreamRequest(BaseModel):
    prompt: str

@router.post("/")
async def stream_request(request: StreamRequest):
    async def event_generator():
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
        
        # Stream events from LangGraph
        async for event in master_app.astream(initial_state):
            # Format event for SSE
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
