# JARV Monitoring and Logging

Complete monitoring and logging setup for JARV production deployment.

## Overview

JARV monitoring stack includes:
- **Prometheus**: Metrics collection and storage
- **Grafana**: Metrics visualization and dashboards
- **Alertmanager**: Alert management and notifications
- **Loki**: Log aggregation
- **Promtail**: Log collection agent

## Quick Start (Optional - for Oracle Cloud deployment)

### Add to docker-compose.prod.yml

```yaml
  prometheus:
    image: prom/prometheus:latest
    container_name: jarv-prometheus
    volumes:
      - ./infra/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./infra/monitoring/alerting-rules.yml:/etc/prometheus/rules/alerting-rules.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    ports:
      - "9090:9090"
    networks:
      - jarv-network
    restart: always

  grafana:
    image: grafana/grafana:latest
    container_name: jarv-grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./infra/monitoring/grafana-dashboard.json:/etc/grafana/provisioning/dashboards/jarv.json:ro
    ports:
      - "3001:3000"
    networks:
      - jarv-network
    depends_on:
      - prometheus
    restart: always

volumes:
  prometheus_data:
  grafana_data:
```

## Application Metrics

### Add Prometheus metrics to backend

Install prometheus_client:

```python
# In apps/backend/pyproject.toml dependencies
prometheus-client = "^0.19.0"
```

Add metrics endpoint in `apps/backend/app/main.py`:

```python
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

# Metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'path', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'path']
)

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.middleware("http")
async def track_metrics(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    http_requests_total.labels(
        method=request.method,
        path=request.url.path,
        status=response.status_code
    ).inc()

    http_request_duration_seconds.labels(
        method=request.method,
        path=request.url.path
    ).observe(duration)

    return response
```

## Log Aggregation with Loki (Optional)

### Add Loki and Promtail to docker-compose.prod.yml

```yaml
  loki:
    image: grafana/loki:latest
    container_name: jarv-loki
    ports:
      - "3100:3100"
    volumes:
      - loki_data:/loki
    networks:
      - jarv-network
    restart: always

  promtail:
    image: grafana/promtail:latest
    container_name: jarv-promtail
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/log:/var/log:ro
      - ./infra/monitoring/promtail-config.yml:/etc/promtail/config.yml:ro
    command: -config.file=/etc/promtail/config.yml
    networks:
      - jarv-network
    restart: always

volumes:
  loki_data:
```

## Simple Monitoring (Without Prometheus/Grafana)

For simpler deployments, use built-in health checks and log aggregation:

### Health Check Monitoring Script

Create `scripts/health-check.sh`:

```bash
#!/bin/bash
# Simple health check script for cron jobs

API_URL="${1:-http://localhost/health}"
WEBHOOK_URL="$2"

response=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL")

if [ "$response" -ne 200 ]; then
    echo "ALERT: API health check failed with status $response"

    # Send notification (optional)
    if [ -n "$WEBHOOK_URL" ]; then
        curl -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"text\":\"JARV API health check failed with status $response\"}"
    fi

    exit 1
fi

echo "API health check passed"
exit 0
```

Add to crontab:

```bash
# Check health every 5 minutes
*/5 * * * * /path/to/jarv/scripts/health-check.sh http://localhost/health >> /var/log/jarv-health.log 2>&1
```

## Log Management

### View logs from all services

```bash
# All logs
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f backend

# Last 100 lines
docker compose -f docker-compose.prod.yml logs --tail=100 backend

# Filter by time
docker compose -f docker-compose.prod.yml logs --since 2024-01-01T00:00:00 backend
```

### Rotate logs to prevent disk fill

Create `/etc/logrotate.d/docker-containers`:

```
/var/lib/docker/containers/*/*.log {
    rotate 7
    daily
    compress
    missingok
    delaycompress
    copytruncate
    maxsize 100M
}
```

## Error Tracking with Sentry

### Add Sentry to Backend

Install sentry-sdk:

```python
# In apps/backend/pyproject.toml
sentry-sdk = {extras = ["fastapi"], version = "^1.40.0"}
```

Initialize in `apps/backend/app/main.py`:

```python
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
        environment=os.getenv("ENVIRONMENT", "production"),
    )
```

Add `SENTRY_DSN` to `.env.production`:

```
SENTRY_DSN=https://xxxxx@xxxxx.ingest.sentry.io/xxxxx
```

Sign up for free Sentry account at sentry.io.

## Cloud Provider Monitoring

### Oracle Cloud

Use Oracle Cloud's built-in monitoring:
1. Go to **Observability & Management > Monitoring**
2. Create alarm for:
   - CPU utilization > 80%
   - Memory utilization > 90%
   - Disk utilization > 85%

### Render

Render includes built-in metrics:
1. Go to service dashboard
2. Click **Metrics** tab
3. View CPU, Memory, Request metrics
4. Set up alerts in **Settings > Notifications**

### Railway

Railway includes built-in monitoring:
1. Go to service page
2. View **Metrics** section
3. Check CPU, Memory, Network usage
4. Configure alerts in project settings

## Uptime Monitoring (External)

Use external uptime monitoring services (free options):

1. **UptimeRobot** (uptimerobot.com) - Free for 50 monitors
2. **StatusCake** (statuscake.com) - Free for 10 monitors
3. **Pingdom** (pingdom.com) - Free trial

Configure to check:
- Dashboard URL every 5 minutes
- API health endpoint every 5 minutes
- Alert via email/SMS/webhook on downtime

## Key Metrics to Monitor

### Application Health
- HTTP response time (p50, p95, p99)
- Error rate (4xx, 5xx)
- Request throughput
- Active connections

### Infrastructure
- CPU usage
- Memory usage
- Disk space
- Network bandwidth

### Database
- Active connections
- Query duration
- Cache hit rate
- Deadlocks

### Workers
- Queue length
- Task processing time
- Failed tasks
- Active workers

## Alerting Best Practices

1. **Alert on symptoms, not causes**: Alert on high error rates, not on CPU usage
2. **Set appropriate thresholds**: Avoid alert fatigue
3. **Use multiple channels**: Email, SMS, Slack, PagerDuty
4. **Group related alerts**: Reduce noise during incidents
5. **Document runbooks**: Include resolution steps in alerts

## Cost Considerations

### Free Options
- Sentry (10k errors/month free)
- UptimeRobot (50 monitors free)
- Grafana Cloud (10k metrics free)

### Self-Hosted (Oracle Cloud)
- $0/month on Oracle Always Free tier
- Includes Prometheus + Grafana + Loki
- Full control and unlimited metrics

### Managed Options
- Datadog: ~$15/host/month
- New Relic: ~$25/month
- Better Stack: ~$10/month
