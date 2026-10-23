# JARV Monitoring

Prometheus, Alertmanager, and Grafana, plus exporters for PostgreSQL, Redis,
and the host. Defined in `docker-compose.monitoring.yml` at the repository root.

## Start

Set `GRAFANA_ADMIN_PASSWORD` in `.env.production` (or `.env`) at the repository root. Grafana reads only that variable from those files, then:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
# production
docker compose -f docker-compose.prod.yml -f docker-compose.monitoring.yml up -d
```

| Service      | URL                    | Notes                                       |
|--------------|------------------------|---------------------------------------------|
| Grafana      | http://localhost:3001  | user `admin`; opens on the JARV Overview dashboard |
| Prometheus   | http://localhost:9090  | Status → Targets shows every scrape target  |
| Alertmanager | http://localhost:9093  |                                             |

All three listen on localhost only. Reach them remotely through an SSH tunnel
or an authenticated reverse proxy.

## What is measured

The backend's `GET /metrics` exports:

- HTTP: `http_requests_total`, `http_request_duration_seconds` (histogram, by
  route template), `http_requests_in_flight`, process CPU and memory.
- Missions (read from the database, so they cover work done on any worker):
  `jarv_missions{status}`, `jarv_missions_stale`,
  `jarv_mission_queue_oldest_seconds`, `jarv_mission_recoveries`,
  `jarv_mission_outcomes_24h{status}`, `jarv_mission_duration_seconds`,
  `jarv_tokens_used_24h`, `jarv_approvals_waiting`.
- Agents and tools: `jarv_agent_runs_24h{agent,result}`,
  `jarv_tool_calls_24h{tool,result}`.
- Memory and learning: `jarv_memories{category}`, `jarv_lessons{status}`.
- Workers and queue: `jarv_workers_up`, `celery_queue_length`.
- `jarv_metrics_database_up` is 0 when the database could not be read.

The exporters add `pg_*`, `redis_*`, and `node_*` metrics.

## Alerts

Rules are in `alerting-rules.yml`. Alertmanager delivers every alert to
`POST /api/observability/alerts` on the backend. JARV opens an incident per
alert (one per alert fingerprint, so a repeating alert updates the same
incident), posts it to the Live Operations Feed, and resolves the incident when
the alert clears. Critical alerts are flagged as needing action.

## Logs

Every backend and worker log line carries `request_id` and `mission_id`. A
mission submitted through the API logs with its request id, then with its
mission id on whichever worker runs it. In production the logs are JSON with
these as fields; in development they appear as `[req=… mission=…]`.

## Tokens (optional)

To require authentication on `/metrics` and the alert webhook:

1. Set `METRICS_TOKEN` and `ALERT_WEBHOOK_TOKEN` in `apps/backend/.env`.
2. Write the same values to `infra/monitoring/secrets/metrics_token` and
   `infra/monitoring/secrets/alert_webhook_token` (one line each; git ignores them).
3. Uncomment the `authorization` blocks in `prometheus.yml` and `alertmanager.yml`.

Without `ALERT_WEBHOOK_TOKEN`, the webhook only accepts private-network callers.
