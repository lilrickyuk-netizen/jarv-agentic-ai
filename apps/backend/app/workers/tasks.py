"""
JARV Backend - Worker Tasks

Background tasks for async operations.
"""
import logging
import asyncio
from typing import Any
from celery import Task

from app.core.celery import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)


class AsyncTask(Task):
    """Base task class with async support"""

    def __call__(self, *args, **kwargs):
        """Execute task with async support"""
        return asyncio.run(self.run_async(*args, **kwargs))

    async def run_async(self, *args, **kwargs):
        """Override this method in subclasses"""
        raise NotImplementedError


@celery_app.task(name="test_task", bind=True)
def test_task(self: Task, message: str = "Hello from JARV worker") -> dict[str, Any]:
    """Test task to verify worker queue is functioning"""
    logger.info(f"Test task started: {message}")

    task_info = {
        "task_id": self.request.id,
        "task_name": self.name,
        "message": message,
        "status": "completed",
        "environment": settings.ENVIRONMENT,
    }

    logger.info(f"Test task completed: {task_info}")
    return task_info


@celery_app.task(name="async_test_task", bind=True, base=AsyncTask)
async def async_test_task(self: AsyncTask, message: str = "Hello from async JARV worker") -> dict[str, Any]:
    """Async test task to verify async worker support"""
    logger.info(f"Async test task started: {message}")

    # Simulate async work
    await asyncio.sleep(1)

    task_info = {
        "task_id": self.request.id,
        "task_name": self.name,
        "message": message,
        "status": "completed",
        "async": True,
        "environment": settings.ENVIRONMENT,
    }

    logger.info(f"Async test task completed: {task_info}")
    return task_info


@celery_app.task(name="health_check_task", bind=True)
def health_check_task(self: Task) -> dict[str, Any]:
    """Health check task for worker monitoring"""
    return {
        "task_id": self.request.id,
        "status": "healthy",
        "worker": self.request.hostname,
    }
