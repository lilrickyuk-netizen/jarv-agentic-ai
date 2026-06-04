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


async def _run_scheduled_loop(job_name: str, description: str) -> dict[str, Any]:
    """
    Autonomous, operator-free loop run. Creates a real Task and writes audit +
    operations-feed entries so the dashboard shows JARV self-triggering work.
    Read-only: gathers DB counts; never modifies files.
    """
    from datetime import datetime, timezone
    from uuid import uuid4
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.task import Task as TaskModel
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.agent import Agent
    from app.models.operations import AuditLog
    from app.models.company_operations import LiveOperationsFeedItem

    async with AsyncSessionLocal() as db:
        ws_id = (await db.execute(select(Workspace.id).limit(1))).scalar_one_or_none()
        if ws_id is None:
            owner = (await db.execute(select(User.id).limit(1))).scalar_one_or_none()
            ws = Workspace(id=uuid4(), name="Command Center", slug=f"cc-{uuid4().hex[:6]}",
                           description="Default", owner_id=owner, workspace_type="general",
                           is_active=True, authority_level=5, config={},
                           created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
            db.add(ws); await db.flush(); ws_id = ws.id

        agents = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
        tasks = (await db.execute(select(func.count(TaskModel.id)))).scalar() or 0
        summary = f"Scheduled '{job_name}': DB connected, {agents} agents, {tasks} tasks."

        t = TaskModel(
            id=uuid4(), workspace_id=ws_id,
            title=f"[scheduled] {job_name}", description=description,
            task_type="scheduled", status="completed", priority=5,
            context={"source": "scheduler", "job": job_name},
            meta_data={"channel": "scheduler", "autonomous": True},
            result={"response": summary, "selected_agents": ["monitoring"],
                    "provider": "system", "model": "scheduler", "tool_calls": []},
            started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
            execution_duration_seconds=0, tokens_used=0,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        db.add(t)
        db.add(LiveOperationsFeedItem(
            id=uuid4(), workspace_id=ws_id, item_type="scheduled", severity="info",
            title=f"Scheduled run: {job_name}", message=summary, related_task_id=t.id,
            requires_action=False,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
        db.add(AuditLog(
            id=uuid4(), workspace_id=ws_id, actor_type="scheduler",
            action="scheduled_run", action_category="scheduler", description=summary,
            target_type="task", target_id=str(t.id), after_state={"job": job_name},
            success=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
        await db.commit()
        return {"job": job_name, "task_id": str(t.id), "summary": summary}


@celery_app.task(name="scheduled_status_loop", bind=True)
def scheduled_status_loop(self: Task) -> dict[str, Any]:
    """Daily operating / heartbeat loop — runs autonomously via Celery Beat."""
    return asyncio.run(_run_scheduled_loop(
        "daily_status_check",
        "Autonomous read-only system status check (no operator command)."))
