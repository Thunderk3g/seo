# System Architecture - Multi-Agent AI Backend

## Overview
This system is an industry-grade multi-agent backend powered by **FastAPI** and **LangGraph**. It implements a sophisticated pipeline for processing user requests through specialized agents, ensuring a strict separation of concerns and scalable reasoning.

## Conceptual Flow
The request follows a modular DAG (Directed Acyclic Graph):

1.  **User Intent Agent**: Detects intent, required depth, and response modality.
2.  **Orchestrator Agent**: Routes tasks to specific sub-systems without performing reasoning itself.
3.  **API Adapter Agents**: Parallelized fetching of external/internal data.
4.  **Semantic Umbrella Agent**: Merges data, resolves semantic conflicts, and identifies missing information.
5.  **Analysis/Reasoning Agent**: Performs high-level analysis, trend detection, and root-cause identification.
6.  **Visualization Agent**: Selects appropriate charting types and shapes data for frontend consumption.
7.  **Report/Narrative Agent**: Generates executive-level summaries and insights.

## Master Graph (LangGraph)
The system uses LangGraph to manage state and execution flow. Each agent is a node in the graph, communicating via a shared `AgentState` object.

### State Management
- **Working Memory**: Short-term execution state.
- **Semantic Memory**: Contextual knowledge extracted during the session.
- **Episodic Memory**: History of interactions for long-term coherence.

## Observability & Reliable Engineering
- **Tracing**: Full integration with LangSmith.
- **Metrics**: Prometheus metrics for agent latency and success rates.
- **Audit**: Immutable audit logs for agent decisions.
- **JSON-First**: All inter-agent communication uses strict Pydantic-validated JSON schemas.

## Request Lifecycle
1. FastAPI receives request via `/api/v1/stream` or `/api/v1/agents/process`.
2. Master Graph is initialized with the user prompt.
3. Nodes execute in sequence or parallel depending on the Orchestrator's routing.
4. State is updated incrementally.
5. Final response is returned or streamed back to the client.
