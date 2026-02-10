from prometheus_client import Counter, Histogram

# Agent performance metrics
AGENT_LATENCY = Histogram(
    "agent_execution_latency_seconds",
    "Latency of agent node execution",
    ["agent_type"]
)

AGENT_SUCCESS_COUNT = Counter(
    "agent_execution_success_total",
    "Total successful agent executions",
    ["agent_type"]
)

AGENT_FAILURE_COUNT = Counter(
    "agent_execution_failure_total",
    "Total failed agent executions",
    ["agent_type"]
)
