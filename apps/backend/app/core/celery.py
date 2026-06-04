"""
JARV Backend - Celery Configuration

Celery worker queue for background tasks and scheduled jobs.
"""
import logging
from celery import Celery
from celery.signals import after_setup_logger

from app.core.config import settings

logger = logging.getLogger(__name__)

# Create Celery app
# Coerce the broker/result-backend URL to a plain string — Celery/Kombu cannot
# consume the Pydantic RedisDsn object that settings.REDIS_URL exposes.
celery_app = Celery(
    "jarv",
    broker=str(settings.REDIS_URL),
    backend=str(settings.REDIS_URL),
    include=[
        "app.workers.tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    result_backend_transport_options={
        "master_name": "mymaster",
        "socket_keepalive": True,
        "retry_on_timeout": True,
    },

    # Worker settings
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,

    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,

    # Beat schedule (for periodic tasks). JARV self-triggers these — no operator
    # command required. Enable/disable is controlled by SCHEDULED_JOBS below.
    beat_schedule={
        "daily-status-loop": {
            "task": "scheduled_status_loop",
            "schedule": float(getattr(settings, "SCHEDULER_STATUS_INTERVAL_SECONDS", 120)),
            "options": {"expires": 110},
        },
    },
)

# Declarative registry of scheduled jobs (surfaced via /api/scheduler/jobs).
SCHEDULED_JOBS = [
    {
        "name": "daily_status_check",
        "task": "scheduled_status_loop",
        "interval_seconds": float(getattr(settings, "SCHEDULER_STATUS_INTERVAL_SECONDS", 120)),
        "enabled": True,
        "type": "health/daily-loop",
        "description": "Autonomous read-only system status check (daily operating loop heartbeat).",
    },
    {
        "name": "self_healing_check",
        "task": "scheduled_status_loop",
        "interval_seconds": float(getattr(settings, "SCHEDULER_STATUS_INTERVAL_SECONDS", 120)),
        "enabled": bool(getattr(settings, "SELF_HEALING_ENABLED", True)),
        "type": "self-healing",
        "description": "Self-healing health probe (uses the status loop as its check).",
    },
    {
        "name": "workspace_maintenance",
        "task": "scheduled_status_loop",
        "interval_seconds": 3600.0,
        "enabled": False,
        "type": "maintenance",
        "description": "Workspace maintenance sweep (disabled by default; enable per workspace).",
    },
]


@after_setup_logger.connect
def setup_celery_logging(logger, *args, **kwargs):
    """Configure Celery logging to match application logging"""
    from app.core.logging import setup_logging
    setup_logging()


# Autodiscover tasks (will look for tasks.py in registered apps)
celery_app.autodiscover_tasks()


if __name__ == "__main__":
    celery_app.start()
