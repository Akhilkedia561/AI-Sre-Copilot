"""
FastAPI application entrypoint — the HTTP surface.

Routes:
    POST /webhook/alertmanager  Alertmanager POSTs here on alert fire/resolve.
    GET  /healthz               Liveness probe.
    GET  /metrics               Prometheus scrape endpoint (self-monitoring).
    GET  /                      Human-friendly index.

Design:
- Webhooks respond IMMEDIATELY (accepted, will process). Investigation runs in
  a background task so Alertmanager isn't blocked by our LLM latency.
- Rate limiter caps investigations per minute; overflow forwards the raw alert.
- LLM failures fall through to the same raw-forward path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.agent import SRECopilotAgent
from app.config import get_settings
from app.metrics import (
    active_investigations,
    incident_duration_seconds,
    incidents_processed_total,
)
from app.models import Alert, AlertmanagerWebhook
from app.slack.formatter import format_incident_message, format_raw_alert_message
from app.slack.formatter import post_to_slack

logging.basicConfig(
    level=get_settings().log_level,
    format="ts=%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s",
)
log = logging.getLogger("copilot")


app = FastAPI(
    title="AI SRE Copilot",
    description="Autonomous incident investigation agent",
    version="0.1.0",
)


class TokenBucket:
    """Very small in-process sliding-window rate limiter."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.window: deque[float] = deque()

    def acquire(self) -> bool:
        now = time.time()
        cutoff = now - 60.0
        while self.window and self.window[0] < cutoff:
            self.window.popleft()
        if len(self.window) >= self.per_minute:
            return False
        self.window.append(now)
        return True


_settings = get_settings()
_agent = SRECopilotAgent(_settings)
_limiter = TokenBucket(_settings.max_incidents_per_minute)


def _process_alert_sync(alert: Alert) -> None:
    """Investigate one alert. Runs in a background thread."""
    active_investigations.inc()
    started = time.perf_counter()
    try:
        if not _limiter.acquire():
            log.warning("rate_limited alertname=%s", alert.alertname)
            incidents_processed_total.labels(
                alertname=alert.alertname, outcome="rate_limited"
            ).inc()
            post_to_slack(
                _settings.slack_webhook_url,
                format_raw_alert_message(
                    alert, reason="rate_limited — AI analysis skipped"
                ),
            )
            return

        try:
            report = _agent.investigate(alert)
        except Exception as exc:
            log.exception("investigation_failed alertname=%s", alert.alertname)
            if _settings.fallback_on_llm_failure:
                incidents_processed_total.labels(
                    alertname=alert.alertname, outcome="llm_failure"
                ).inc()
                post_to_slack(
                    _settings.slack_webhook_url,
                    format_raw_alert_message(
                        alert, reason=f"AI analysis failed: {type(exc).__name__}"
                    ),
                )
            return

        incidents_processed_total.labels(
            alertname=alert.alertname, outcome="success"
        ).inc()
        post_to_slack(
            _settings.slack_webhook_url,
            format_incident_message(alert, report),
        )
        log.info(
            "investigation_complete alertname=%s confidence=%s tokens=%d cost=$%.4f duration_ms=%d",
            alert.alertname,
            report.confidence,
            report.total_tokens,
            report.cost_usd,
            report.duration_ms,
        )
    finally:
        active_investigations.dec()
        incident_duration_seconds.observe(time.perf_counter() - started)


@app.post("/webhook/alertmanager")
async def alertmanager_webhook(
    payload: AlertmanagerWebhook, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Receive an Alertmanager webhook payload and schedule investigations."""
    firing = [a for a in payload.alerts if a.status == "firing"]
    log.info(
        "webhook_received receiver=%s firing_count=%d",
        payload.receiver,
        len(firing),
    )
    for alert in firing:
        background_tasks.add_task(
            asyncio.to_thread, _process_alert_sync, alert
        )
    return JSONResponse({"accepted": len(firing)})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def index() -> dict[str, str]:
    return {
        "service": "ai-sre-copilot",
        "version": "0.1.0",
        "docs": "/docs",
        "metrics": "/metrics",
        "webhook": "/webhook/alertmanager",
    }
