# Multi-Agent AI Backend

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![LangGraph](https://img.shields.io/badge/LangGraph-0.0.26+-orange.svg)

An industrial-grade, production-ready backend implementing a sophisticated multi-agent pipeline using **LangGraph** and **FastAPI**.

## Features

- **Modular Agentic Pipeline**: Strict separation of concerns across specialized agents.
- **LangGraph Master DAG**: Advanced control flow, state transitions, and retries.
- **JSON-First Communication**: Standardized inter-agent data exchange using Pydantic.
- **Streaming Support**: Real-time agent updates via FastAPI Server-Sent Events (SSE).
- **Pro-grade Observability**: Integrated with LangSmith for tracing and Prometheus for metrics.
- **Hybrid Memory**: Built-in support for Working, Semantic, and Episodic memory.

## Architecture

The system follows a conceptual flow designed for high-depth reasoning and data-driven insights:

1. **Intent Agent**: Detects user goals and required depth.
2. **Orchestrator**: Routing without reasoning for performance and clarity.
3. **API Adapters**: Parallel data fetching.
4. **Semantic Umbrella**: Data merging and conflict resolution.
5. **Analysis**: Deep reasoning and trend detection.
6. **Visualization**: Automatic chart selection and data shaping.
7. **Narrative/Reporting**: Executive-level output generation.

For more details, see [ARCHITECTURE.md](./ARCHITECTURE.md) and the [Agentic Flow Overview](./doc/AGENTIC_FLOW.md).

## Getting Started

### Prerequisites
- Python 3.10+
- OpenAI API Key
- (Optional) LangSmith API Key for tracing

### Setup
```bash
./scripts/setup.sh
```

### Running the App
```bash
uvicorn app.main:app --reload
```

## API Endpoints

- `GET /api/v1/health`: Health status.
- `POST /api/v1/agents/process`: Synchronous agent processing.
- `POST /api/v1/stream`: Streaming agent updates.

## Docker Support

Run with Docker Compose:
```bash
docker-compose -f docker/docker-compose.yml up --build
```

## Security
- Role-based tool permissions.
- Immutable audit logging for autonomous agent decisions.