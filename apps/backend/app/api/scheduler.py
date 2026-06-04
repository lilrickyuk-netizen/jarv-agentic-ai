"""
JARV Backend - Scheduler API

Surfaces the autonomous scheduler: registered scheduled jobs, their enable/
disable state, and recent scheduled runs (read from the tasks the scheduler
itself created). Lets the dashboard prove JARV self-triggers work.
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.task import Task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status() -> Dict[str, Any]:
    """Scheduler service status + configured beat schedule summary."""
    try:
        from app.core.celery import SCHEDULED_JOBS, celery_app
        beat = list(celery_app.conf.beat_schedule.keys())
        enabled = [j for j in SCHEDULED_JOBS if j["enabled"]]
        return {
            "scheduler": "celery-beat",
            "running": True,
            "beat_entries": beat,
            "jobs_total": len(SCHEDULED_JOBS),
            "jobs_enabled": len(enabled),
        }
    except Exception as exc:  # noqa: BLE001
        return {"scheduler": "celery-beat", "running": False, "error": str(exc)}


@router.get("/jobs")
async def scheduler_jobs() -> List[Dict[str, Any]]:
    """List configured scheduled jobs (name, type, interval, enabled)."""
    from app.core.celery import SCHEDULED_JOBS
    return SCHEDULED_JOBS


@router.get("/runs")
async def scheduler_runs(limit: int = 20, db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """Recent autonomous scheduled runs (tasks the scheduler created)."""
    rows = (
        await db.execute(
            select(Task).where(Task.task_type == "scheduled")
            .order_by(Task.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "task_id": str(t.id),
            "title": t.title,
            "status": t.status,
            "summary": (t.result or {}).get("response") if isinstance(t.result, dict) else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in rows
    ]
