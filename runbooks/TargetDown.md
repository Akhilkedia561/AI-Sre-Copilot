# Runbook: TargetDown

## Summary
Fires when Prometheus fails to scrape a target for more than one minute
(`up == 0`).

## Common causes
1. **The target process crashed** — check its own container logs.
2. **Network partition** — security group changes, VPC route changes, or a
   home-network IP change (common with laptop-based Prometheus).
3. **Target restarted** — brief flap, will self-recover.
4. **Target moved / IP changed** — Prometheus scrape config is stale.

## Diagnostic checklist
- Query `up` grouped by job and instance to identify who is down.
- If the target is a container, check `container_last_seen` from cAdvisor.
- Check the container's own logs for a crash trace.
- SSH to the host and verify the target's port is listening
  (`ss -ltn | grep <port>`).

## Remediation
- If crash: restart, capture stack trace, file bug.
- If network: restore security group / verify inbound rules.
- If moved: update `prometheus.yml` targets and reload
  (`curl -X POST http://prometheus:9090/-/reload`).
