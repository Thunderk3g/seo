# Agentic Flow Diagram

This document illustrates the high-level workflow of the multi-agent system, from user input to final report generation.

## Visual Flow

```mermaid
graph TD
    User([User Prompt]) --> UIA[User Intent Agent]
    
    subgraph Intent & Routing
        UIA --> ORCH[Orchestrator]
    end

    subgraph Data Acquisition (Parallel)
        ORCH --> API_A[API A Adapter]
        ORCH --> API_B[API B Adapter]
        ORCH --> API_C[API C Adapter]
        ORCH --> API_D[API D Adapter]
    end

    subgraph Data Normalization
        API_A --> SO{Semantic Observations JSON}
        API_B --> SO
        API_C --> SO
        API_D --> SO
    end

    subgraph Intelligent Synthesis
        SO --> SUA[Semantic Umbrella Agent]
        SUA --> ARA[Analysis / Reasoning Agent]
    end

    subgraph Output Generation
        ARA --> VA[Visualization Agent]
        VA --> RNA[Report / Narrative Agent]
    end

    RNA --> Final([Final Engineering Insights])

    %% Styling
    style User fill:#e1f5fe,stroke:#01579b
    style ORCH fill:#fff9c4,stroke:#fbc02d,stroke-width:2px
    style SO fill:#f5f5f5,stroke:#616161,stroke-dasharray: 5 5
    style Final fill:#e8f5e9,stroke:#2e7d32
    style UIA fill:#f3e5f5,stroke:#7b1fa2
    style SUA fill:#ede7f6,stroke:#512da8
    style ARA fill:#e0f2f1,stroke:#00796b
    style VA fill:#fff3e0,stroke:#e65100
    style RNA fill:#fbe9e7,stroke:#d84315
```

## Workflow Components

1. [**Intent & Routing**](./INTENT_ROUTING.md)
2. [**Data Acquisition**](./DATA_ACQUISITION.md)
3. [**Data Normalization**](./DATA_NORMALIZATION.md)
4. [**Intelligent Synthesis**](./INTELLIGENT_SYNTHESIS.md)
5. [**Output Generation**](./OUTPUT_GENERATION.md)
