"""
JARV Backend - Checkpoints API

RESTful API endpoints for safe checkpoints and resume actions.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.models.boundary import SafeCheckpoint

router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"])


class CheckpointInfo(BaseModel):
    id: str
    session_id: str
    checkpoint_name: str
    checkpoint_type: str
    is_safe_state: bool
    state_snapshot: dict
    variables: dict
    verification_status: str
    safety_checks_passed: List[str]
    safety_warnings: List[str]
    can_resume_from: bool
    resume_actions_available: List[str]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CheckpointStats(BaseModel):
    total_checkpoints: int
    safe_checkpoints: int
    unsafe_checkpoints: int
    resumable_checkpoints: int
    by_type: dict[str, int]
    average_safety_checks: float


@router.get("/list", response_model=List[CheckpointInfo])
async def list_checkpoints(
    session_id: Optional[UUID] = None,
    is_safe_state: Optional[bool] = None,
    can_resume_from: Optional[bool] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    List checkpoints with optional filtering.
    """
    query = select(SafeCheckpoint)

    if session_id:
        query = query.where(SafeCheckpoint.session_id == session_id)
    if is_safe_state is not None:
        query = query.where(SafeCheckpoint.is_safe_state == is_safe_state)
    if can_resume_from is not None:
        query = query.where(SafeCheckpoint.can_resume_from == can_resume_from)

    query = query.order_by(SafeCheckpoint.created_at.desc()).limit(limit)

    result = db.execute(query)
    checkpoints = result.scalars().all()

    return [
        CheckpointInfo(
            id=str(checkpoint.id),
            session_id=str(checkpoint.session_id),
            checkpoint_name=checkpoint.checkpoint_name,
            checkpoint_type=checkpoint.checkpoint_type,
            is_safe_state=checkpoint.is_safe_state,
            state_snapshot=checkpoint.state_snapshot,
            variables=checkpoint.variables,
            verification_status=checkpoint.verification_status,
            safety_checks_passed=checkpoint.safety_checks_passed or [],
            safety_warnings=checkpoint.safety_warnings or [],
            can_resume_from=checkpoint.can_resume_from,
            resume_actions_available=checkpoint.resume_actions_available or [],
            created_at=checkpoint.created_at.isoformat() if checkpoint.created_at else datetime.now().isoformat(),
            updated_at=checkpoint.updated_at.isoformat() if checkpoint.updated_at else datetime.now().isoformat(),
        )
        for checkpoint in checkpoints
    ]


@router.get("/stats", response_model=CheckpointStats)
async def get_checkpoint_stats(db: Session = Depends(get_db)):
    """
    Get aggregated statistics for checkpoints.
    """
    result = db.execute(select(SafeCheckpoint))
    all_checkpoints = result.scalars().all()

    total_checkpoints = len(all_checkpoints)
    safe_checkpoints = sum(1 for c in all_checkpoints if c.is_safe_state)
    unsafe_checkpoints = total_checkpoints - safe_checkpoints
    resumable_checkpoints = sum(1 for c in all_checkpoints if c.can_resume_from)

    by_type: dict[str, int] = {}
    for checkpoint in all_checkpoints:
        by_type[checkpoint.checkpoint_type] = by_type.get(checkpoint.checkpoint_type, 0) + 1

    safety_check_counts = [len(c.safety_checks_passed or []) for c in all_checkpoints]
    average_safety_checks = sum(safety_check_counts) / len(safety_check_counts) if safety_check_counts else 0.0

    return CheckpointStats(
        total_checkpoints=total_checkpoints,
        safe_checkpoints=safe_checkpoints,
        unsafe_checkpoints=unsafe_checkpoints,
        resumable_checkpoints=resumable_checkpoints,
        by_type=by_type,
        average_safety_checks=round(average_safety_checks, 2),
    )
