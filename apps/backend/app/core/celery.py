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
celery_app = Celery(
    "jarv",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
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

    # Beat schedule (for periodic tasks)
    beat_schedule={},
)


@after_setup_logger.connect
def setup_celery_logging(logger, *args, **kwargs):
    """Configure Celery logging to match application logging"""
    from app.core.logging import setup_logging
    setup_logging()


# Autodiscover tasks (will look for tasks.py in registered apps)
celery_app.autodiscover_tasks()


if __name__ == "__main__":
    celery_app.start()
