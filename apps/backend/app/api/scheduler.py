"""
JARV Backend - Scheduler API

Surfaces the autonomous scheduler: registered scheduled jobs, their enable/
disable state, and recent scheduled runs (read from the audit entry each run
writes). Lets the dashboard prove JARV self-triggers work.
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.operations import AuditLog

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
    """Recent autonomous scheduled runs (one audit entry per run)."""
    rows = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "scheduled_run")
            .order_by(AuditLog.created_at.desc()).limit(max(1, min(limit, 200)))
        )
    ).scalars().all()
    return [
        {
            "run_id": str(r.id),
            "job": r.target_id,
            "status": "ok" if r.success else "degraded",
            "summary": r.description,
            "details": r.after_state,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
