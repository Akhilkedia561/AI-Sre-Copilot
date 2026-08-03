# Runbook: AppHighErrorRate

## Summary
This alert fires when the ratio of 5xx responses to total responses for the
`demoapp` service exceeds 5% over any 5-minute window and stays above the
threshold for 2 minutes.

## Common causes (in order of frequency)
1. **Recent deploy** introduced a regression — check `get_recent_deployments`
   for anything in the last 30 minutes. Roll back if a suspicious change is
   correlated.
2. **Downstream dependency failure** — the app's own logs typically contain
   the upstream error text. Filter with `{container="demoapp"} |= "error"`.
3. **Cardinality explosion** in a caller — one client sending malformed
   requests. Break down error rate by endpoint using
   `sum by (endpoint) (rate(app_requests_total{status="500"}[5m]))`.
4. **Resource starvation** on the host — CPU / memory pressure causing
   timeouts. Check `node_cpu_seconds_total` and `container_memory_usage_bytes`.

## Diagnostic checklist
- Break down error rate per endpoint (PromQL above).
- Correlate spike time with deployment history.
- Look at raw error log lines from Loki.
- Check whether host CPU/memory is under pressure.

## Remediation
- If deploy-correlated: roll back the last deploy for `demoapp`.
- If dependency: page the owning team for the failing dependency.
- If load-related: scale the service and/or add a rate-limit at the edge.

## Ownership
- Primary: demoapp on-call
- Escalation: platform on-call after 15 minutes without progress.
