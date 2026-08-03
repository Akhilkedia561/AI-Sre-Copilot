"""
The agent loop — where the interesting engineering lives.

Design:
- Uses OpenAI SDK because it works with OpenAI, Groq, DeepSeek, Together, etc.
  Point `LLM_BASE_URL` at whichever provider you like.
- Function calling / tool use: the LLM picks which tool to call and what
  arguments. We execute it, feed the result back, loop until it emits a report.
- Cost + latency tracked on every iteration and exported as Prometheus metrics.
- Hard iteration cap and per-call timeout to prevent runaway costs.
- All untrusted content wrapped in <untrusted_input> before reaching the LLM.
- Structured JSON output for the final report; validated against Pydantic.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import OpenAI, APIError

from app.config import Settings
from app.models import Alert, IncidentReport, ToolCallLog
from app.prompts import SYSTEM_PROMPT, format_initial_user_message, format_tool_result
from app.metrics import (
    llm_tokens_total,
    llm_cost_usd_total,
    tool_call_duration_seconds,
    hypothesis_confidence_total,
)
from app.tools.prometheus_tool import PrometheusTool
from app.tools.loki_tool import LokiTool
from app.tools.runbook_tool import RunbookTool
from app.tools.deployment_tool import DeploymentTool

log = logging.getLogger(__name__)


# Rough per-1K-token pricing for cost estimation. Adjust per your provider.
# Values below match GPT-4o-mini's public pricing as of late 2024. If you use
# Groq (free tier) these become 0. Kept as a lookup so you can override per model.
MODEL_PRICING_PER_1K_TOKENS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.00060},
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "llama-3.3-70b-versatile": {"input": 0.0, "output": 0.0},  # Groq free
    "claude-3-5-sonnet-latest": {"input": 0.003, "output": 0.015},
    "default": {"input": 0.001, "output": 0.003},  # conservative fallback
}


class SRECopilotAgent:
    """Autonomous investigation agent bound to a single incident."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_seconds,
        )
        # Tools are shared across investigations; they hold connection pools.
        self.tools = {
            "query_metrics": PrometheusTool(settings.prometheus_url),
            "query_logs": LokiTool(settings.loki_url),
            "search_runbooks": RunbookTool(
                settings.runbook_dir,
                settings.chroma_persist_dir,
                settings.embeddings_model,
            ),
            "get_recent_deployments": DeploymentTool(),
        }

    # ------------------------------------------------------------------ tools
    def _tool_schemas(self) -> list[dict[str, Any]]:
        """OpenAI function-calling schemas describing each tool to the LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "query_metrics",
                    "description": (
                        "Execute a PromQL query against Prometheus and return the "
                        "result. Use this for metric-level investigation: request "
                        "rates, error ratios, latency percentiles, host CPU/mem, etc."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "promql": {
                                "type": "string",
                                "description": "The PromQL expression to evaluate.",
                            },
                            "time_range_minutes": {
                                "type": "integer",
                                "description": "Optional lookback window in minutes.",
                                "default": 5,
                            },
                        },
                        "required": ["promql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_logs",
                    "description": (
                        "Execute a LogQL query against Loki and return matching "
                        "log lines. Use to see actual error text, stack traces, or "
                        "specific request patterns."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "logql": {
                                "type": "string",
                                "description": "The LogQL query to execute.",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max lines to return (default 30).",
                                "default": 30,
                            },
                            "time_range_minutes": {
                                "type": "integer",
                                "description": "Lookback window in minutes.",
                                "default": 15,
                            },
                        },
                        "required": ["logql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_runbooks",
                    "description": (
                        "Semantic search over indexed runbooks and past incident "
                        "reports. Use FIRST for any known alertname — an existing "
                        "runbook often has the fastest path to diagnosis."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural language query.",
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "How many runbooks to return.",
                                "default": 3,
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_recent_deployments",
                    "description": (
                        "Return recent deployment history for a service. Many "
                        "alerts fire within minutes of a recent deploy."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "service": {
                                "type": "string",
                                "description": "Service or job name (e.g. 'demoapp').",
                            },
                            "lookback_hours": {
                                "type": "integer",
                                "default": 2,
                            },
                        },
                        "required": ["service"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "emit_report",
                    "description": (
                        "Emit the final structured incident report. Call this "
                        "exactly ONCE at the end of your investigation."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "hypothesis": {"type": "string"},
                            "confidence": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                            "evidence": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "suggested_actions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "similar_incidents": {
                                "type": "array",
                                "items": {"type": "string"},
                                "default": [],
                            },
                        },
                        "required": [
                            "hypothesis",
                            "confidence",
                            "evidence",
                            "suggested_actions",
                        ],
                    },
                },
            },
        ]

    # -------------------------------------------------------------- execution
    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Dispatch a tool call. All exceptions are caught and returned as
        error strings so the LLM can react rather than us crashing."""
        started = time.perf_counter()
        try:
            tool = self.tools[name]
            result = tool.run(**arguments)
        except KeyError:
            result = f"ERROR: unknown tool '{name}'"
        except Exception as exc:  # pragma: no cover — defensive
            log.exception("tool_error tool=%s", name)
            result = f"ERROR executing {name}: {exc}"
        finally:
            duration = time.perf_counter() - started
            tool_call_duration_seconds.labels(tool=name).observe(duration)
        return str(result)

    def _estimate_cost(self, model: str, usage: Any) -> float:
        """Estimate USD cost from token counts."""
        pricing = MODEL_PRICING_PER_1K_TOKENS.get(
            model, MODEL_PRICING_PER_1K_TOKENS["default"]
        )
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        return (
            (input_tokens / 1000) * pricing["input"]
            + (output_tokens / 1000) * pricing["output"]
        )

    # ----------------------------------------------------------- main loop
    def investigate(self, alert: Alert) -> IncidentReport:
        """Run the full agent loop for one alert. Returns an IncidentReport."""
        started = time.perf_counter()

        alert_json = alert.model_dump_json(indent=2)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": format_initial_user_message(alert.summary, alert_json),
            },
        ]

        tool_call_history: list[ToolCallLog] = []
        total_tokens = 0
        total_cost = 0.0
        final_report_args: dict[str, Any] | None = None

        for iteration in range(self.settings.llm_max_iterations):
            try:
                response = self.client.chat.completions.create(
                    model=self.settings.llm_model,
                    messages=messages,
                    tools=self._tool_schemas(),
                    tool_choice="auto",
                    temperature=0.1,
                )
            except APIError as exc:
                log.error("llm_api_error iter=%d err=%s", iteration, exc)
                raise

            usage = response.usage
            if usage:
                total_tokens += usage.total_tokens or 0
                llm_tokens_total.labels(direction="input").inc(
                    usage.prompt_tokens or 0
                )
                llm_tokens_total.labels(direction="output").inc(
                    usage.completion_tokens or 0
                )
                cost = self._estimate_cost(self.settings.llm_model, usage)
                total_cost += cost
                llm_cost_usd_total.inc(cost)

            choice = response.choices[0]
            assistant_msg = choice.message

            # Append the assistant turn to the running conversation so subsequent
            # calls see the full history.
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.content,
                    "tool_calls": (
                        [tc.model_dump() for tc in assistant_msg.tool_calls]
                        if assistant_msg.tool_calls
                        else None
                    ),
                }
            )

            # If the model just wrote text without a tool call, gently nudge it.
            if not assistant_msg.tool_calls:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Please continue the investigation by calling a tool, "
                            "or emit the final report with emit_report."
                        ),
                    }
                )
                continue

            # Handle every tool call in this turn.
            for tool_call in assistant_msg.tool_calls:
                fn = tool_call.function
                try:
                    args = json.loads(fn.arguments)
                except json.JSONDecodeError:
                    args = {}

                if fn.name == "emit_report":
                    final_report_args = args
                    # Once a report is emitted we stop even if other tool
                    # calls were requested in the same turn.
                    break

                started_tool = time.perf_counter()
                tool_result = self._execute_tool(fn.name, args)
                tool_duration_ms = int((time.perf_counter() - started_tool) * 1000)

                # Truncate huge results so we don't blow up the context window.
                result_for_llm = tool_result[:4000]
                if len(tool_result) > 4000:
                    result_for_llm += "\n\n[truncated]"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": format_tool_result(fn.name, result_for_llm),
                    }
                )

                tool_call_history.append(
                    ToolCallLog(
                        tool=fn.name,
                        arguments=args,
                        result_summary=result_for_llm[:400],
                        duration_ms=tool_duration_ms,
                    )
                )

            if final_report_args is not None:
                break

        if final_report_args is None:
            # Model never emitted a report — synthesise a low-confidence one so
            # the pipeline never returns None.
            final_report_args = {
                "hypothesis": (
                    "Agent exhausted its iteration budget without reaching a "
                    "conclusion. Manual triage required."
                ),
                "confidence": "low",
                "evidence": [
                    f"Made {len(tool_call_history)} tool calls without converging."
                ],
                "suggested_actions": [
                    "Open Grafana and investigate the alert manually.",
                ],
                "similar_incidents": [],
            }

        report = IncidentReport(
            alertname=alert.alertname,
            severity=alert.severity,
            hypothesis=final_report_args.get("hypothesis", ""),
            confidence=final_report_args.get("confidence", "low"),
            evidence=final_report_args.get("evidence", []),
            suggested_actions=final_report_args.get("suggested_actions", []),
            similar_incidents=final_report_args.get("similar_incidents", []),
            tool_calls=tool_call_history,
            total_tokens=total_tokens,
            cost_usd=round(total_cost, 6),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

        hypothesis_confidence_total.labels(confidence=report.confidence).inc()
        return report
