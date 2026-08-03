# Wiring the Copilot into Alertmanager

Add this receiver + route to your `alertmanager.yml` alongside your existing
Slack config:

```yaml
receivers:
  - name: 'sre-copilot'
    webhook_configs:
      - url: 'http://sre-copilot:8000/webhook/alertmanager'
        send_resolved: false
        max_alerts: 10

route:
  # Route everything through the copilot first — it forwards to Slack itself.
  receiver: 'sre-copilot'
  group_by: ['alertname']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
```

For a low-blast-radius rollout, mirror alerts:

```yaml
route:
  receiver: 'slack-notifications'  # keep existing path
  routes:
    - receiver: 'sre-copilot'      # also send to copilot
      continue: true
      matchers:
        - severity =~ "warning|critical"
```

Reload Alertmanager:

```bash
curl -X POST http://alertmanager:9093/-/reload
```
