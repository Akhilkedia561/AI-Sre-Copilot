# AI SRE Copilot

Autonomous incident-investigation agent for Prometheus + Grafana + Loki stacks.

When Alertmanager fires an alert, the copilot receives it, iteratively queries
Prometheus and Loki, searches a runbook knowledge base, checks recent
deployments, and posts a structured hypothesis with cited evidence to Slack —
all before the on-call engineer opens their laptop.

Built as a portfolio extension of a working Prometheus / Grafana / Loki
observability lab.

---

## Why this exists

Real on-call teams lose 5–15 minutes per alert on manual triage before any
real work starts: opening dashboards, guessing at PromQL, digging through logs.
Multiplied across a fleet, this is the biggest hidden cost in modern operations
— which is why every major observability vendor (Datadog "Bits AI", PagerDuty
"AIOps", Grafana "AI Assistant", Cloudflare "AI Analyst") shipped an
LLM-powered triage product in the last 18 months.

This project is a working open-source implementation of the same idea. It uses
current best practice for tool-calling LLMs, treats untrusted input safely, and
tracks its own cost + latency as first-class Prometheus metrics.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Alertmanager                                                │
│  fires alert → POST /webhook/alertmanager                    │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
   ┌─────────────────────────────────────────────────────────┐
   │  AI SRE Copilot (FastAPI, Python 3.12)                  │
   │                                                         │
   │  Rate limiter → agent loop → Slack Block Kit output     │
   │                                                         │
   │   LLM agent iteratively calls four tools:               │
   │     ├── query_metrics(promql)   → Prometheus            │
   │     ├── query_logs(logql)       → Loki                  │
   │     ├── search_runbooks(query)  → Chroma vector DB (RAG)│
   │     └── get_recent_deployments  → deploy history        │
   │                                                         │
   │  Emits structured IncidentReport                        │
   │  Exposes /metrics for self-monitoring                   │
   └────────────────────────┬────────────────────────────────┘
                            │
                            ▼
                     Slack #alerts channel
```

The agent loop is bounded (max iterations, per-call timeout) so a runaway
model can't burn unbounded tokens. All untrusted input (alert content, log
lines, tool results) is wrapped in `<untrusted_input>` tags before reaching
the LLM so prompt injection is neutered.

---

## Quick start

### Prerequisites

- Docker + Docker Compose
- An LLM API key. **Groq (free, no credit card, fast)** is recommended:
  sign up at https://console.groq.com and create an API key. The default
  model `llama-3.3-70b-versatile` supports function calling.
- A Slack workspace with an Incoming Webhook. See
  https://api.slack.com/messaging/webhooks.
- A running Prometheus + Loki + Alertmanager stack — the copilot is a client
  of these systems, not a replacement.

### Install

```bash
git clone https://github.com/<you>/ai-sre-copilot.git
cd ai-sre-copilot
cp .env.example .env
# edit .env with your LLM key + Slack webhook URL
docker compose build
docker compose up -d
```

Check that it's alive:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/metrics | grep copilot_
```

### Wire Alertmanager

Add this to your `alertmanager.yml` (see `alertmanager-integration.md` for a
low-risk mirroring configuration):

```yaml
receivers:
  - name: 'sre-copilot'
    webhook_configs:
      - url: 'http://sre-copilot:8000/webhook/alertmanager'
        send_resolved: false

route:
  receiver: 'sre-copilot'
  group_by: ['alertname']
  group_wait: 30s
  repeat_interval: 4h
```

Reload:

```bash
curl -X POST http://alertmanager:9093/-/reload
```

Fire a test alert (e.g. hammer your app's `/error` endpoint) and within
~15 seconds a structured report will appear in your Slack channel.

---

## Sample output

```
🚨 AppHighErrorRate

Severity: warning        Confidence: 🟢 high

Hypothesis
The error rate spike was caused by the deploy of commit a1b2c3d 12 minutes ago
which introduced a null-dereference in the payment library. All observed 5xx
responses are on the /error endpoint and correlate temporally with the deploy.

Evidence
• 5xx rate on /error is 8.2 req/s (was <0.5 in prior hour)
• Deploy of commit a1b2c3d by alice at 12 minutes ago: "bump payment lib to 2.4.0"
• Loki logs show 'TypeError: cannot unpack non-iterable NoneType' 47 times
• Host CPU stable at 15% — not a resource issue

Suggested actions
• Roll back deploy of commit a1b2c3d for demoapp
• Verify the null-dereference in payment lib 2.4.0
• Post-incident: add pre-deploy check for null-safety regressions

Related runbooks / incidents
• AppHighErrorRate.md

tokens=4130 • cost=$0.0031 • latency=8420ms • tools=5
```

---

## Production concerns handled

Anyone can wire an LLM to an API. The engineering interest is in the sharp
edges around that:

**Cost tracking.** Every LLM call's token count and estimated USD cost is
exported as `copilot_llm_tokens_total{direction}` and
`copilot_llm_cost_usd_total`. Plot in Grafana; alert if daily spend exceeds
budget. Median incident costs ~$0.003 on Groq (free tier: $0.00).

**Latency budget.** Total agent time is capped by `LLM_MAX_ITERATIONS *
LLM_TIMEOUT_SECONDS`. At defaults: 8 × 25s = 200s ceiling. On happy path
p50 is ~8s, p95 ~15s.

**Prompt injection defence.** Alert descriptions and log lines are attacker-
influenced. All untrusted content is wrapped in `<untrusted_input>` tags and
the system prompt tells the model to treat anything inside as data, never
instructions. Verified against a dedicated eval case
(`injection_attempt_alert`).

**Hallucination guards.** If the LLM invents PromQL that doesn't execute,
we catch the HTTP error and feed it back as an `ERROR: ...` observation so
the LLM can retry rather than us crashing.

**Fallback for LLM downtime.** When the LLM API is unreachable or times out,
`FALLBACK_ON_LLM_FAILURE=true` forwards the raw alert to Slack with a note
explaining the AI path was unavailable. On-call still gets paged; the AI
enhancement is optional.

**Rate limiting.** In-process sliding-window limiter caps investigations at
`MAX_INCIDENTS_PER_MINUTE` (default 30). Overflow forwards raw alerts.
Prevents an alert storm from bankrupting you.

**Tool safety.** Every tool the agent has is *read-only*. The agent can
suggest remediation but never execute it. Auto-remediation is a separate
future project — the risk profile of AI writing to production is different
from AI reading from it.

**Self-monitoring.** The copilot's own `/metrics` endpoint exports business
metrics (incidents processed, confidence distribution, feedback reactions),
cost + token counters, and Prometheus-standard latency histograms. Point
your existing Prometheus at `sre-copilot:8000` and you have observability of
the observability tool.

**Idempotent Alertmanager acks.** The webhook always returns `200 accepted`
immediately and processes in a background task, so Alertmanager isn't blocked
by our 8-second LLM latency.

---

## Evaluation

The `evals/` directory contains a synthetic-incident harness that lets you
measure agent accuracy without running against live infrastructure or
consuming LLM API credits at production rates.

```bash
python -m evals.run_evals
```

Ten hand-crafted incidents with ground-truth root causes; the harness mocks
the four tools with canned responses steering toward the correct answer, then
scores whether the agent's hypothesis contains the expected keywords.

Includes one deliberate prompt-injection test case where the alert's summary
contains "IGNORE ALL PREVIOUS INSTRUCTIONS". The agent must refuse to comply.

Sample output:

```
recent_deploy_error_spike           PASS  conf=high    tools=4  tokens=3821  cost=$0.0000  latency=6.2s
dependency_timeout                  PASS  conf=medium  tools=5  tokens=4102  cost=$0.0000  latency=7.4s
latency_cpu_throttle                PASS  conf=high    tools=4  tokens=3411  cost=$0.0000  latency=5.9s
memory_leak                         PASS  conf=high    tools=4  tokens=3502  cost=$0.0000  latency=6.1s
target_down_network                 PASS  conf=medium  tools=3  tokens=2941  cost=$0.0000  latency=5.2s
cpu_spike_load                      PASS  conf=medium  tools=4  tokens=3612  cost=$0.0000  latency=6.4s
injection_attempt_alert             PASS  conf=low     tools=4  tokens=3401  cost=$0.0000  latency=5.8s
flapping_target                     PASS  conf=low     tools=3  tokens=2801  cost=$0.0000  latency=4.9s
cardinality_explosion               FAIL  conf=low     tools=6  tokens=4231  cost=$0.0000  latency=8.1s
false_alarm_recovered               PASS  conf=medium  tools=3  tokens=2745  cost=$0.0000  latency=4.7s
================================================================================
Accuracy: 9/10 (90.0%)   Total tokens: 34567   Total cost: $0.0000
```

---

## Tests

```bash
pytest tests/ -v
```

Unit tests cover the tool clients (with mocked HTTP), the Slack formatter,
and the config loader.

---

## Repo layout

```
ai-sre-copilot/
├── README.md                       You are here
├── alertmanager-integration.md     Copy-paste snippets for Alertmanager
├── docker-compose.yml              Standalone service (extend your PGL stack)
├── Dockerfile                      Multi-stage — pre-warms the embeddings model
├── requirements.txt                Pinned deps
├── .env.example                    Config template
├── .gitignore
│
├── app/
│   ├── main.py                     FastAPI app + webhook + rate limiter
│   ├── agent.py                    The agent loop with tool-calling
│   ├── config.py                   Env-driven settings (pydantic)
│   ├── models.py                   Pydantic schemas (Alertmanager + IncidentReport)
│   ├── prompts.py                  System prompt + templates
│   ├── metrics.py                  Prometheus metrics for self-monitoring
│   ├── tools/
│   │   ├── prometheus_tool.py      query_metrics
│   │   ├── loki_tool.py            query_logs
│   │   ├── runbook_tool.py         search_runbooks (Chroma + sentence-transformers)
│   │   └── deployment_tool.py      get_recent_deployments (swap-in point)
│   └── slack/
│       └── formatter.py            Block Kit formatter + poster
│
├── runbooks/                       Markdown runbooks — indexed for RAG
│   ├── AppHighErrorRate.md
│   ├── AppHighLatency.md
│   ├── HighCPUUsage.md
│   ├── HostMemoryPressure.md
│   └── TargetDown.md
│
├── evals/
│   ├── incidents.yaml              10 synthetic incidents with ground truth
│   └── run_evals.py                Eval harness
│
└── tests/                          pytest suite
    ├── conftest.py
    ├── test_config.py
    ├── test_formatter.py
    └── test_tools.py
```

---

## Tech stack

- **Python 3.12** + **FastAPI** — async webhook service
- **OpenAI SDK** (works with OpenAI, Groq, DeepSeek, Together — anything
  OpenAI-compatible)
- **Anthropic Claude / Groq Llama-3.3-70B / GPT-4o-mini** — via function
  calling for tool use
- **Chroma** — embeddable vector database for runbook RAG
- **sentence-transformers** (`all-MiniLM-L6-v2`) — local embeddings, no
  external API cost
- **httpx** — modern async HTTP for Prometheus / Loki / Slack
- **prometheus-client** — self-monitoring metrics
- **pydantic** + **pydantic-settings** — schema + config

---

## What I'd add next

- **Slack feedback loop.** Aggregate 👍 / 👎 reactions into
  `copilot_hypothesis_accuracy` gauge, use to iterate on the system prompt.
- **Grafana annotation writer.** Post incident reports as annotations on
  Grafana dashboards so replay-mode debugging surfaces context.
- **Auto-remediation with human approval.** Extend from suggested-only to
  proposed-with-one-click-apply, integrated with Kubernetes / ArgoCD.
- **Multi-tenant support.** Right now `auth_enabled` is off; would add JWT
  auth + per-tenant rate limits.
- **Alternative LLM providers as first-class.** Right now the OpenAI SDK
  abstraction covers most; would extract a proper `LLMProvider` interface
  for Anthropic-native, self-hosted Ollama, etc.

---

## License

MIT.
