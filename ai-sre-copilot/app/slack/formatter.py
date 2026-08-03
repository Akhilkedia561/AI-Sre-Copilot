"""
Slack Block Kit formatting + posting.

The formatter produces rich messages with:
- Alert header with severity emoji
- Hypothesis + confidence badge
- Evidence bullets
- Suggested actions
- Cited runbooks
- Cost + latency footer

Also includes a fallback plain-alert formatter for when the LLM fails or the
rate limiter fires.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.models import Alert, IncidentReport

log = logging.getLogger(__name__)

_SEVERITY_EMOJI = {
    "critical": ":rotating_light:",
    "page": ":rotating_light:",
    "warning": ":warning:",
    "info": ":information_source:",
    "unknown": ":grey_question:",
}
_CONFIDENCE_EMOJI = {"high": ":green_circle:", "medium": ":large_yellow_circle:", "low": ":red_circle:"}


def _bullet_list(items: list[str], max_chars: int = 1500) -> str:
    """Bullet-point join with total length cap. Slack complains past ~3000 chars."""
    result = ""
    for item in items:
        line = f"• {item}\n"
        if len(result) + len(line) > max_chars:
            result += "…(truncated)\n"
            break
        result += line
    return result.rstrip() or "(none)"


def format_incident_message(alert: Alert, report: IncidentReport) -> dict[str, Any]:
    severity_emoji = _SEVERITY_EMOJI.get(alert.severity, _SEVERITY_EMOJI["unknown"])
    confidence_emoji = _CONFIDENCE_EMOJI.get(
        report.confidence, _CONFIDENCE_EMOJI["low"]
    )

    header = f"{severity_emoji} {alert.alertname}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header, "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Severity:*\n{alert.severity}"},
                {
                    "type": "mrkdwn",
                    "text": f"*Confidence:*\n{confidence_emoji} {report.confidence}",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Hypothesis*\n{report.hypothesis}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Evidence*\n{_bullet_list(report.evidence)}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Suggested actions*\n{_bullet_list(report.suggested_actions)}",
            },
        },
    ]

    if report.similar_incidents:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Related runbooks / incidents*\n{_bullet_list(report.similar_incidents)}",
                },
            }
        )

    # Footer with cost + latency stats (visible to on-call, helps calibrate).
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"tokens={report.total_tokens} • "
                        f"cost=${report.cost_usd:.4f} • "
                        f"latency={report.duration_ms}ms • "
                        f"tools={len(report.tool_calls)}"
                    ),
                }
            ],
        }
    )

    return {"blocks": blocks, "text": f"{header}: {report.hypothesis[:150]}"}


def format_raw_alert_message(alert: Alert, reason: str) -> dict[str, Any]:
    """Fallback formatter used when the AI path can't run."""
    severity_emoji = _SEVERITY_EMOJI.get(alert.severity, _SEVERITY_EMOJI["unknown"])
    return {
        "text": f"{severity_emoji} {alert.alertname} ({reason})",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{severity_emoji} {alert.alertname}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Reason:* {reason}\n"
                        f"*Summary:* {alert.summary}\n"
                        f"*Description:* {alert.description}\n"
                        f"*Started at:* {alert.startsAt.isoformat()}"
                    ),
                },
            },
        ],
    }


def post_to_slack(webhook_url: str, message: dict[str, Any]) -> None:
    """POST a Block Kit message to the given webhook URL."""
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(webhook_url, json=message)
            r.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("slack_post_failed err=%s body=%s", exc, json.dumps(message)[:500])
