from prometheus_client import Counter, Histogram

tickets_total = Counter(
    "deskfleet_tickets_total",
    "Total tickets processed",
    ["decision", "category"],
)

ticket_latency_seconds = Histogram(
    "deskfleet_ticket_latency_seconds",
    "End-to-end ticket latency in seconds",
)

node_latency_seconds = Histogram(
    "deskfleet_node_latency_seconds",
    "Per-node latency in seconds",
    ["node"],
)

tool_calls_total = Counter(
    "deskfleet_tool_calls_total",
    "Tool calls by name and outcome",
    ["tool", "outcome"],
)

guardrail_blocks_total = Counter(
    "deskfleet_guardrail_blocks_total",
    "Guardrail block events by type",
    ["type"],
)

tokens_total = Counter(
    "deskfleet_tokens_total",
    "Cumulative token counts",
    ["kind"],
)

cost_usd_total = Counter(
    "deskfleet_cost_usd_total",
    "Cumulative cost in USD",
)

review_iterations = Histogram(
    "deskfleet_review_iterations",
    "Number of Reviewer iterations per ticket",
    buckets=[0, 1, 2, 3, 4, 5],
)
