# Intent & Routing

Phase 1 of the agentic flow focuses on understanding the user's objective and preparing the task queue.

## Components

### User Intent Agent
- **Description**: The first point of contact for any user request.
- **Responsibilities**:
    - Analyzes the natural language prompt.
    - Determines the "Depth" of analysis required (Quick vs. Deep).
    - Identifies the response modality (Text, Visual, or Interactive).

### Orchestrator
- **Description**: The operational dispatcher of the system.
- **Responsibilities**:
    - Takes validated intent and breaks it into parallel tasks.
    - Routes specific queries to the appropriate API Adapters.
    - Note: This agent does NOT perform reasoning; it ensures workflow efficiency.
