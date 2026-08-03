"""
`query_metrics` — execute a PromQL query and return the result.

Uses Prometheus's HTTP API:
  GET /api/v1/query        instant query
  GET /api/v1/query_range  range query

We return a compact JSON string so the LLM sees something small and parseable.
"""

from __future__ import annotations

import json
import time
from typing import Any
import httpx


class PrometheusTool:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def run(self, promql: str, time_range_minutes: int = 5) -> str:
        """
        Execute an instant query at time=now. We keep it simple — instant queries
        with rate([window]) implicitly cover the range_minutes window through
        the PromQL itself, so we don't need to use query_range for typical
        investigation. This keeps output small.
        """
        params: dict[str, Any] = {
            "query": promql,
            "time": time.time(),
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(f"{self.base_url}/api/v1/query", params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            return json.dumps({"error": f"prometheus_http_error: {exc}"})

        if data.get("status") != "success":
            return json.dumps(
                {"error": "prometheus_query_error", "detail": data.get("error", "")}
            )

        # Compact the result: metric labels + last value per series.
        result = data.get("data", {}).get("result", [])
        if not result:
            return json.dumps({"result": "no_data", "query": promql})

        compact = []
        for series in result[:25]:  # cap series count to protect context
            metric = series.get("metric", {})
            value = series.get("value") or series.get("values", [[0, "0"]])[-1]
            compact.append({"labels": metric, "value": value[1]})

        return json.dumps(
            {"query": promql, "count": len(result), "series": compact},
            indent=2,
        )
