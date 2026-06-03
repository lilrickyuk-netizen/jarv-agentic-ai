# JARV Workers

Background workers for JARV Agentic AI System using Celery.

## Workers

The system includes multiple specialized workers:

- **Scheduler Worker**: Handles scheduled tasks and cron jobs
- **Operations Worker**: General operations and orchestration
- **Company Operator Worker**: Runs daily operating loops for workspaces
- **Self-Evolution Worker**: Processes experience and proposes improvements
- **Swarm Worker**: Manages sub-agent lifecycle and parallel execution
- **Support Worker**: Processes support tickets and feedback
- **Marketing Worker**: Executes marketing campaigns and content creation
- **Content Worker**: Generates technical content and documentation
- **Community Worker**: Handles community engagement and moderation
- **Partnership Worker**: Manages partnership pipeline and outreach
- **Revenue Worker**: Tracks revenue operations and experiments
- **Self-Healing Worker**: Monitors and fixes live platform issues
- **Approval/Resume Worker**: Manages approval checkpoints and resume actions

## Development

```bash
# Install dependencies
poetry install

# Run Celery worker
poetry run celery -A workers.celery_app worker --loglevel=info

# Run Celery beat (scheduler)
poetry run celery -A workers.celery_app beat --loglevel=info

# Run flower (monitoring)
poetry run celery -A workers.celery_app flower

# Run tests
poetry run pytest
```

## Environment Variables

Create a `.env` file:

```
DATABASE_URL=postgresql://user:password@localhost:5432/jarv
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
LOG_LEVEL=INFO
```

## Worker Configuration

Workers are configured with:
- Task routing based on queue names
- Retry policies for failed tasks
- Rate limiting where appropriate
- Task time limits
- Result expiration
- Prefetch multiplier for optimal throughput

## Monitoring

Use Flower to monitor worker status, task progress, and performance:

```
http://localhost:5555
```
