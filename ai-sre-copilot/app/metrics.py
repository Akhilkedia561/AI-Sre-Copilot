"""
Prometheus metrics exposing the copilot's own health.

Exported at /metrics. Your existing Prometheus already scrapes this if you add
`copilot:8000` to prometheus.yml — the copilot monitors itself.
"""

from prometheus_client import Counter, Histogram, Gauge

# ---- Business metrics ------------------------------------------------------

incidents_processed_total = Counter(
    "copilot_incidents_processed_total",
    "Total incidents received and processed",
    ["alertname", "outcome"],  # outcome: success | llm_failure | rate_limited
)

hypothesis_confidence_total = Counter(
    "copilot_hypothesis_confidence_total",
    "Distribution of hypothesis confidence levels",
    ["confidence"],
)

feedback_reactions_total = Counter(
    "copilot_feedback_reactions_total",
    "Emoji feedback reactions collected from Slack",
    ["reaction"],  # thumbs_up | thumbs_down
)

# ---- Cost + latency --------------------------------------------------------

llm_tokens_total = Counter(
    "copilot_llm_tokens_total",
    "Total LLM tokens consumed",
    ["direction"],  # input | output
)

llm_cost_usd_total = Counter(
    "copilot_llm_cost_usd_total",
    "Estimated cumulative LLM cost in USD",
)

incident_duration_seconds = Histogram(
    "copilot_incident_duration_seconds",
    "Wall-clock time from webhook receipt to Slack post",
    buckets=(0.5, 1, 2, 5, 10, 15, 20, 30, 60),
)

tool_call_duration_seconds = Histogram(
    "copilot_tool_call_duration_seconds",
    "Latency of individual tool calls",
    ["tool"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

# ---- Operational state -----------------------------------------------------

active_investigations = Gauge(
    "copilot_active_investigations",
    "Number of investigations currently in flight",
)
