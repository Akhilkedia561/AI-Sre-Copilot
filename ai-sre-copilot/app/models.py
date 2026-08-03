"""
Pydantic models for Alertmanager's webhook payload and the internal incident
report the agent produces.

The Alertmanager schema is documented at:
https://prometheus.io/docs/alerting/latest/configuration/#webhook_config
"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class Alert(BaseModel):
    """One alert entry inside the Alertmanager webhook payload."""

    status: str = Field(..., description='"firing" or "resolved"')
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    generatorURL: str | None = None
    fingerprint: str | None = None

    # Convenience accessors ------------------------------------------------
    @property
    def alertname(self) -> str:
        return self.labels.get("alertname", "UnknownAlert")

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "unknown")

    @property
    def summary(self) -> str:
        return self.annotations.get("summary", self.alertname)

    @property
    def description(self) -> str:
        return self.annotations.get("description", "")

    @property
    def instance(self) -> str:
        return self.labels.get("instance", "")

    @property
    def job(self) -> str:
        return self.labels.get("job", "")


class AlertmanagerWebhook(BaseModel):
    """Top-level payload Alertmanager POSTs to a webhook receiver."""

    version: str
    groupKey: str
    status: str
    receiver: str
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[Alert]


class ToolCallLog(BaseModel):
    """Record of one tool call the agent made during investigation."""

    tool: str
    arguments: dict[str, Any]
    result_summary: str
    duration_ms: int


class IncidentReport(BaseModel):
    """The structured output the agent produces per alert."""

    alertname: str
    severity: str
    hypothesis: str = Field(..., description="Plain-English root-cause hypothesis")
    confidence: str = Field(..., description="low | medium | high")
    evidence: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    similar_incidents: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallLog] = Field(default_factory=list)
    total_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    generated_at: datetime = Field(default_factory=datetime.utcnow)
