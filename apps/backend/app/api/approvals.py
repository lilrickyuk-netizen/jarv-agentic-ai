"""
JARV Backend - Approvals API

RESTful API endpoints for approval requests and boundary approvals.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID, uuid4
from datetime import datetime, timezone
import logging

from app.core.database import get_db
from app.core.auth import CurrentUserId
from app.models.approval import Approval
from app.models.task import Task
from app.models.operations import AuditLog
from app.models.company_operations import LiveOperationsFeedItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


# ===== Command-boundary approvals =====
# When the command pipeline hits a Richard hard boundary it pauses the action by
# setting the Task status to "blocked" and recording a boundary feed item. These
# blocked command tasks ARE the approval queue the operator actions here:
# confirm (approve) continues only the approved action, cancel (reject) drops it.
# Destructive actions are never auto-executed; Richard confirms, cancels, or
# intervenes.

_BLOCKED_STATES = ("blocked",)


class CommandApprovalItem(BaseModel):
    task_id: str
    command: str
    status: str
    reason: Optional[str]
    boundary_type: Optional[str]
    workspace_id: str
    created_at: Optional[str]
    updated_at: Optional[str]


class ApprovalDecision(BaseModel):
    note: Optional[str] = None


async def _write_audit(db, workspace_id, action, description, success, target_id, operator, required_approval=False):
    try:
        db.add(AuditLog(
            id=uuid4(), workspace_id=workspace_id, actor_type="operator",
            action=action, action_category="approval", description=description,
            target_type="command", target_id=target_id,
            after_state={"operator": operator}, success=success,
            required_approval=required_approval,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"approval audit write failed: {exc}")


async def _write_feed(db, workspace_id, task_id, severity, title, message):
    try:
        db.add(LiveOperationsFeedItem(
            id=uuid4(), workspace_id=workspace_id, item_type="approval",
            severity=severity, title=title, message=message,
            related_task_id=task_id, requires_action=False,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"approval feed write failed: {exc}")


@router.get("/command-blocks", response_model=List[CommandApprovalItem])
async def list_command_blocks(db: Session = Depends(get_db)):
    """List blocked command actions awaiting Richard's confirmation."""
    rows = (
        await db.execute(
            select(Task)
            .where(Task.status.in_(_BLOCKED_STATES))
            .order_by(Task.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    items: List[CommandApprovalItem] = []
    for t in rows:
        meta = t.meta_data if isinstance(t.meta_data, dict) else {}
        ctx = t.context if isinstance(t.context, dict) else {}
        items.append(CommandApprovalItem(
            task_id=str(t.id),
            command=t.description or t.title,
            status=t.status,
            reason=meta.get("blocked_reason") or ctx.get("safety_reason"),
            boundary_type=meta.get("boundary_type"),
            workspace_id=str(t.workspace_id),
            created_at=t.created_at.isoformat() if t.created_at else None,
            updated_at=t.updated_at.isoformat() if t.updated_at else None,
        ))
    return items


@router.post("/command-blocks/{task_id}/approve", response_model=CommandApprovalItem)
async def approve_command_block(
    task_id: UUID,
    operator: CurrentUserId,
    decision: ApprovalDecision = ApprovalDecision(),
    db: Session = Depends(get_db),
):
    """Confirm a blocked command. Records the approval; destructive actions are
    not auto-run — Richard remains in control and can intervene."""
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Blocked command not found")
    if task.status not in _BLOCKED_STATES:
        raise HTTPException(status_code=400, detail=f"Task is not awaiting approval (status={task.status})")

    task.status = "approved"
    meta = dict(task.meta_data or {})
    meta.update({"approved_by": operator, "approval_note": decision.note,
                 "approved_at": datetime.now(timezone.utc).isoformat()})
    task.meta_data = meta
    task.updated_at = datetime.now(timezone.utc)

    await _write_audit(
        db, task.workspace_id, "approval_granted",
        f"Operator {operator} approved blocked command: {(task.description or task.title)[:300]}",
        True, str(task.id), operator, required_approval=True,
    )
    await _write_feed(
        db, task.workspace_id, task.id, "success", "Approval granted",
        f"Operator approved the blocked action. {decision.note or ''}".strip(),
    )
    await db.commit()
    return CommandApprovalItem(
        task_id=str(task.id), command=task.description or task.title, status=task.status,
        reason=meta.get("blocked_reason"), boundary_type=meta.get("boundary_type"),
        workspace_id=str(task.workspace_id),
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


@router.post("/command-blocks/{task_id}/reject", response_model=CommandApprovalItem)
async def reject_command_block(
    task_id: UUID,
    operator: CurrentUserId,
    decision: ApprovalDecision = ApprovalDecision(),
    db: Session = Depends(get_db),
):
    """Cancel a blocked command. The action is dropped and logged."""
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Blocked command not found")
    if task.status not in _BLOCKED_STATES:
        raise HTTPException(status_code=400, detail=f"Task is not awaiting approval (status={task.status})")

    task.status = "cancelled"
    meta = dict(task.meta_data or {})
    meta.update({"rejected_by": operator, "rejection_note": decision.note,
                 "rejected_at": datetime.now(timezone.utc).isoformat()})
    task.meta_data = meta
    task.updated_at = datetime.now(timezone.utc)

    await _write_audit(
        db, task.workspace_id, "approval_rejected",
        f"Operator {operator} rejected blocked command: {(task.description or task.title)[:300]}",
        True, str(task.id), operator, required_approval=True,
    )
    await _write_feed(
        db, task.workspace_id, task.id, "warning", "Approval rejected",
        f"Operator cancelled the blocked action. {decision.note or ''}".strip(),
    )
    await db.commit()
    return CommandApprovalItem(
        task_id=str(task.id), command=task.description or task.title, status=task.status,
        reason=meta.get("blocked_reason"), boundary_type=meta.get("boundary_type"),
        workspace_id=str(task.workspace_id),
        created_at=task.created_at.isoformat() if task.created_at else None,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


class ApprovalInfo(BaseModel):
    id: str
    user_id: str
    session_id: str
    approval_type: str
    action_description: str
    action_details: dict
    authority_level_required: int
    status: str
    approved: bool | None
    approved_at: str | None
    rejected_at: str | None
    response_message: str | None
    executed: bool
    executed_at: str | None
    execution_result: dict | None
    execution_error: str | None
    expires_at: str | None
    is_expired: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ApprovalStats(BaseModel):
    total_approvals: int
    pending_approvals: int
    approved_approvals: int
    rejected_approvals: int
    executed_approvals: int
    expired_approvals: int
    by_type: dict[str, int]
    by_authority_level: dict[str, int]
    average_response_time_minutes: float


@router.get("/list", response_model=List[ApprovalInfo])
async def list_approvals(
    status: Optional[str] = None,
    approval_type: Optional[str] = None,
    user_id: Optional[UUID] = None,
    is_expired: Optional[bool] = None,
    min_authority: Optional[int] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    List approval requests with optional filtering.

    Args:
        status: Filter by status (pending, approved, rejected)
        approval_type: Filter by approval type
        user_id: Filter by user
        is_expired: Filter by expiration status
        min_authority: Minimum authority level
        limit: Maximum number of approvals to return

    Returns:
        List of approval records
    """
    query = select(Approval)

    if status:
        query = query.where(Approval.status == status)
    if approval_type:
        query = query.where(Approval.approval_type == approval_type)
    if user_id:
        query = query.where(Approval.user_id == user_id)
    if is_expired is not None:
        query = query.where(Approval.is_expired == is_expired)
    if min_authority is not None:
        query = query.where(Approval.authority_level_required >= min_authority)

    query = query.order_by(Approval.created_at.desc()).limit(limit)

    result = await db.execute(query)
    approvals = result.scalars().all()

    return [
        ApprovalInfo(
            id=str(approval.id),
            user_id=str(approval.user_id),
            session_id=str(approval.session_id),
            approval_type=approval.approval_type,
            action_description=approval.action_description,
            action_details=approval.action_details,
            authority_level_required=approval.authority_level_required,
            status=approval.status,
            approved=approval.approved,
            approved_at=approval.approved_at.isoformat() if approval.approved_at else None,
            rejected_at=approval.rejected_at.isoformat() if approval.rejected_at else None,
            response_message=approval.response_message,
            executed=approval.executed,
            executed_at=approval.executed_at.isoformat() if approval.executed_at else None,
            execution_result=approval.execution_result,
            execution_error=approval.execution_error,
            expires_at=approval.expires_at.isoformat() if approval.expires_at else None,
            is_expired=approval.is_expired,
            created_at=approval.created_at.isoformat() if approval.created_at else datetime.now().isoformat(),
            updated_at=approval.updated_at.isoformat() if approval.updated_at else datetime.now().isoformat(),
        )
        for approval in approvals
    ]


@router.get("/stats", response_model=ApprovalStats)
async def get_approval_stats(
    user_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    Get aggregated statistics for approvals.

    Args:
        user_id: Optional user filter

    Returns:
        Approval statistics including counts and metrics
    """
    query = select(Approval)
    if user_id:
        query = query.where(Approval.user_id == user_id)

    result = await db.execute(query)
    all_approvals = result.scalars().all()

    # Calculate statistics
    total_approvals = len(all_approvals)
    pending_approvals = sum(1 for a in all_approvals if a.status == 'pending')
    approved_approvals = sum(1 for a in all_approvals if a.approved == True)
    rejected_approvals = sum(1 for a in all_approvals if a.approved == False)
    executed_approvals = sum(1 for a in all_approvals if a.executed)
    expired_approvals = sum(1 for a in all_approvals if a.is_expired)

    # By type
    by_type: dict[str, int] = {}
    for approval in all_approvals:
        by_type[approval.approval_type] = by_type.get(approval.approval_type, 0) + 1

    # By authority level
    by_authority_level: dict[str, int] = {}
    for approval in all_approvals:
        level_key = f"Level {approval.authority_level_required}"
        by_authority_level[level_key] = by_authority_level.get(level_key, 0) + 1

    # Average response time
    response_times = []
    for approval in all_approvals:
        if approval.approved_at and approval.created_at:
            delta = (approval.approved_at - approval.created_at).total_seconds() / 60
            response_times.append(delta)
        elif approval.rejected_at and approval.created_at:
            delta = (approval.rejected_at - approval.created_at).total_seconds() / 60
            response_times.append(delta)

    average_response_time = sum(response_times) / len(response_times) if response_times else 0.0

    return ApprovalStats(
        total_approvals=total_approvals,
        pending_approvals=pending_approvals,
        approved_approvals=approved_approvals,
        rejected_approvals=rejected_approvals,
        executed_approvals=executed_approvals,
        expired_approvals=expired_approvals,
        by_type=by_type,
        by_authority_level=by_authority_level,
        average_response_time_minutes=round(average_response_time, 2),
    )


@router.get("/{approval_id}", response_model=ApprovalInfo)
async def get_approval(
    approval_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific approval.

    Args:
        approval_id: UUID of the approval

    Returns:
        Approval information
    """
    query = select(Approval).where(Approval.id == approval_id)
    result = await db.execute(query)
    approval = result.scalar_one_or_none()

    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    return ApprovalInfo(
        id=str(approval.id),
        user_id=str(approval.user_id),
        session_id=str(approval.session_id),
        approval_type=approval.approval_type,
        action_description=approval.action_description,
        action_details=approval.action_details,
        authority_level_required=approval.authority_level_required,
        status=approval.status,
        approved=approval.approved,
        approved_at=approval.approved_at.isoformat() if approval.approved_at else None,
        rejected_at=approval.rejected_at.isoformat() if approval.rejected_at else None,
        response_message=approval.response_message,
        executed=approval.executed,
        executed_at=approval.executed_at.isoformat() if approval.executed_at else None,
        execution_result=approval.execution_result,
        execution_error=approval.execution_error,
        expires_at=approval.expires_at.isoformat() if approval.expires_at else None,
        is_expired=approval.is_expired,
        created_at=approval.created_at.isoformat() if approval.created_at else datetime.now().isoformat(),
        updated_at=approval.updated_at.isoformat() if approval.updated_at else datetime.now().isoformat(),
    )
