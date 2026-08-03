# Runbook: AppHighLatency

## Summary
Fires when the 95th-percentile latency of demoapp exceeds 1 second for
more than 2 minutes.

## Common causes
1. **CPU throttling** — cAdvisor's `container_cpu_cfs_throttled_seconds_total`
   is increasing. Bump container CPU limits.
2. **Slow downstream** — check the slow endpoint's own logs; look for slow
   query patterns or timeouts to upstreams.
3. **GC pressure** in a Java/Python app — for demoapp look at
   `process_gc_seconds_total` if instrumented.
4. **Cold cache** after restart — first requests are slow until the cache
   warms. Should self-resolve in 5–10 minutes.

## Diagnostic PromQL
- Per-endpoint p95:
  `histogram_quantile(0.95, sum by (le, endpoint) (rate(app_request_duration_seconds_bucket[5m])))`
- CPU throttle:
  `rate(container_cpu_cfs_throttled_seconds_total{name="demoapp"}[5m])`
- Request rate (to correlate with load spike):
  `sum(rate(app_requests_total[5m]))`

## Remediation
- If throttled: raise CPU limit in docker-compose or k8s manifest.
- If dependency-slow: escalate to owner of that dependency.
- If cache-cold: monitor for 10 minutes before intervening.
