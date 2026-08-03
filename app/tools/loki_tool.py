"""
`query_logs` — execute a LogQL query and return matching log lines.

Uses Loki's HTTP API:
  GET /loki/api/v1/query_range

We enforce a limit and truncate line contents so context stays sane.
"""

from __future__ import annotations

import json
import time
import httpx


class LokiTool:
    def __init__(self, base_url: str, timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def run(self, logql: str, limit: int = 30, time_range_minutes: int = 15) -> str:
        now_ns = int(time.time() * 1e9)
        start_ns = now_ns - int(time_range_minutes * 60 * 1e9)
        params = {
            "query": logql,
            "start": start_ns,
            "end": now_ns,
            "limit": limit,
            "direction": "backward",  # newest first
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                r = client.get(
                    f"{self.base_url}/loki/api/v1/query_range", params=params
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            return json.dumps({"error": f"loki_http_error: {exc}"})

        if data.get("status") != "success":
            return json.dumps(
                {"error": "loki_query_error", "detail": data.get("error", "")}
            )

        streams = data.get("data", {}).get("result", [])
        if not streams:
            return json.dumps({"result": "no_matching_lines", "query": logql})

        lines: list[dict] = []
        for stream in streams:
            labels = stream.get("stream", {})
            for ts_ns, line in stream.get("values", []):
                lines.append(
                    {
                        "ts": ts_ns,
                        "labels": {
                            k: v for k, v in labels.items() if k in ("container", "level")
                        },
                        "line": line[:300],  # truncate individual line
                    }
                )
        lines = sorted(lines, key=lambda x: x["ts"], reverse=True)[:limit]

        return json.dumps({"query": logql, "count": len(lines), "lines": lines}, indent=2)
