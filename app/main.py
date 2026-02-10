import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import health, agents, stream
from app.config import settings
from app.logging import configure_logging

# Initialize logging
configure_logging()

app = FastAPI(
    title="Multi-Agent AI Backend",
    description="Production-ready multi-agent pipeline with LangGraph and FastAPI",
    version="1.0.0",
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(health.router, prefix="/api/v1/health", tags=["Health"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["Agents"])
app.include_router(stream.router, prefix="/api/v1/stream", tags=["Streaming"])

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
