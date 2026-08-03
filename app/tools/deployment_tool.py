"""
`get_recent_deployments` — return recent deployment events for a service.

Currently returns synthetic data because deployment sources vary widely
(GitOps, Jenkins, ArgoCD, Spinnaker, plain git tags). In production you'd
wire this to whatever your CI/CD system exposes.

To swap in a real source: subclass and override `_fetch_deployments`.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta


class DeploymentTool:
    def __init__(self):
        # A tiny fake deployment "database" so demos are deterministic-ish.
        # Replace with an API call to your CI system in production.
        self._known_services = {
            "demoapp": [
                {
                    "commit": "a1b2c3d",
                    "author": "alice",
                    "message": "bump payment lib to 2.4.0",
                    "minutes_ago": 12,
                },
                {
                    "commit": "9f8e7d6",
                    "author": "bob",
                    "message": "add /error endpoint for chaos testing",
                    "minutes_ago": 240,
                },
            ],
            "ec2-host": [],
        }

    def _fetch_deployments(self, service: str, lookback_hours: int) -> list[dict]:
        deployments = self._known_services.get(service, [])
        cutoff_minutes = lookback_hours * 60
        return [d for d in deployments if d["minutes_ago"] <= cutoff_minutes]

    def run(self, service: str, lookback_hours: int = 2) -> str:
        deployments = self._fetch_deployments(service, lookback_hours)
        now = datetime.utcnow()
        formatted = [
            {
                "commit": d["commit"],
                "author": d["author"],
                "message": d["message"],
                "deployed_at": (now - timedelta(minutes=d["minutes_ago"])).isoformat()
                + "Z",
                "minutes_ago": d["minutes_ago"],
            }
            for d in deployments
        ]
        if not formatted:
            return json.dumps(
                {
                    "service": service,
                    "result": "no_recent_deployments",
                    "lookback_hours": lookback_hours,
                }
            )
        return json.dumps(
            {"service": service, "count": len(formatted), "deployments": formatted},
            indent=2,
        )
