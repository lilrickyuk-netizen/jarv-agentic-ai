"""
JARV Backend - Approvals API

RESTful API endpoints for approval requests and boundary approvals.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.models.approval import Approval

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


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
