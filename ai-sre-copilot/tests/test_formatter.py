"""Slack formatter unit tests."""

from datetime import datetime
from app.models import Alert, IncidentReport, ToolCallLog
from app.slack.formatter import format_incident_message, format_raw_alert_message


def _alert() -> Alert:
    return Alert(
        status="firing",
        labels={"alertname": "AppHighErrorRate", "severity": "warning", "job": "ec2-app"},
        annotations={"summary": "Error rate spiked", "description": "5xx at 8/s"},
        startsAt=datetime.utcnow(),
    )


def test_format_incident_message_has_expected_blocks():
    report = IncidentReport(
        alertname="AppHighErrorRate",
        severity="warning",
        hypothesis="Recent deploy caused regression",
        confidence="high",
        evidence=["Error rate 22%", "Deploy 12 minutes ago"],
        suggested_actions=["Roll back last deploy"],
        similar_incidents=["AppHighErrorRate.md"],
        tool_calls=[
            ToolCallLog(
                tool="query_metrics", arguments={"promql": "up"}, result_summary="ok", duration_ms=50
            )
        ],
        total_tokens=1234,
        cost_usd=0.005,
        duration_ms=1500,
    )
    msg = format_incident_message(_alert(), report)
    assert "blocks" in msg
    text_all = str(msg["blocks"])
    assert "Recent deploy caused regression" in text_all
    assert "Error rate 22%" in text_all
    assert "Roll back last deploy" in text_all
    assert "AppHighErrorRate" in text_all


def test_format_raw_alert_message_includes_reason():
    msg = format_raw_alert_message(_alert(), reason="LLM API timeout")
    assert "LLM API timeout" in str(msg["blocks"])
    assert "AppHighErrorRate" in msg["text"]
