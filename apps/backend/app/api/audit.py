"""
JARV Backend - Audit Log API

Read-only access to the persistent audit trail (audit_logs table). Used by the
Operations page to show recent command/approval/execution/blocked events.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.operations import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditInfo:
    pass


@router.get("/list")
async def list_audit_logs(
    action_category: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return recent audit log entries (most recent first)."""
    query = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if action_category:
        query = query.where(AuditLog.action_category == action_category)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "actor_type": r.actor_type,
            "action": r.action,
            "action_category": r.action_category,
            "description": r.description,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "success": r.success,
            "required_approval": r.required_approval,
            "error_message": r.error_message,
            "metadata": r.after_state or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/stats")
async def audit_stats(db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Aggregate counts for the audit trail."""
    total = (await db.execute(select(func.count(AuditLog.id)))).scalar() or 0
    blocked = (
        await db.execute(
            select(func.count(AuditLog.id)).where(AuditLog.required_approval == True)  # noqa: E712
        )
    ).scalar() or 0
    failures = (
        await db.execute(
            select(func.count(AuditLog.id)).where(AuditLog.success == False)  # noqa: E712
        )
    ).scalar() or 0
    return {
        "total_events": int(total),
        "approval_required_events": int(blocked),
        "failed_events": int(failures),
    }
