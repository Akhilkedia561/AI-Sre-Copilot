# Runbook: HostMemoryPressure

## Summary
Fires when host memory used > 90% for two minutes (available memory close to
running out). Often precedes OOM kills.

## Common causes
1. **Container memory leak** — one container's `container_memory_usage_bytes`
   is climbing while others are flat.
2. **Cache pressure** — legitimate but high working set. Look at
   `node_memory_Cached_bytes` share vs `node_memory_Anon_bytes`.
3. **Too many replicas** on one host — a scheduling mistake in production.

## Diagnostic PromQL
- Overall used %:
  `(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100`
- Top containers by memory:
  `topk(5, sum by (name) (container_memory_usage_bytes{name!=""}))`

## Remediation
- Restart the leaking container as a stopgap.
- Increase host memory in the short term.
- File a bug for the leak; consider setting container memory limits so a
  single container can't take down the whole host.
