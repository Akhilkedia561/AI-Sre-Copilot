# Runbook: HighCPUUsage

## Summary
Fires when the average CPU across all cores exceeds 80% for two minutes.

## Common causes
1. **Load spike** — legitimate traffic increase.
2. **Runaway process** — one container is dominating; check
   `sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[5m]))`.
3. **Infinite retry loop** — an alert-adjacent metric to look at is request
   rate; if it's very high without matching upstream, a client is retrying
   too aggressively.
4. **Background job** running unexpectedly — cron, backup, indexer.

## Diagnostic PromQL
- Per-container CPU %:
  `sum by (name) (rate(container_cpu_usage_seconds_total{name!=""}[5m])) * 100`
- Per-mode CPU on the host:
  `avg by (mode) (rate(node_cpu_seconds_total[5m]))`

## Remediation
- Scale horizontally if load-related.
- Restart the offending container if it's a bug.
- Coordinate with whoever owns any unexpected background job.
