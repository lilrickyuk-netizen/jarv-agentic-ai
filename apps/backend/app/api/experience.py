"""
JARV Backend - Experience API

Authenticated access to experience records and the verified-learning
lifecycle (candidate -> verified -> retired, or rejected). Every call is
limited to the caller's own workspaces.
"""
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.core.learning import learning_service
from app.models.agent import Agent
from app.models.self_evolution import ExperienceRecord, SelfEvolutionRecord
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/experience", tags=["experience"])


class ExperienceInfo(BaseModel):
    id: str
    agent_id: str
    agent_name: str | None
    workspace_id: str | None
    session_id: str | None
    task_id: str | None
    experience_type: str
    title: str
    description: str
    situation: str
    action_taken: str
    result: str
    outcome: str
    lesson_learned: str
    lesson_status: str
    lesson_key: str | None
    applicable_contexts: List[str]
    confidence_score: float
    times_applied: int
    success_rate: float | None
    is_validated: bool
    is_active: bool
    meta_data: dict | None
    created_at: str
    updated_at: str


class ExperienceStats(BaseModel):
    total_experiences: int
    validated_experiences: int
    active_experiences: int
    by_type: dict[str, int]
    by_outcome: dict[str, int]
    by_lesson_status: dict[str, int]
    average_confidence: float
    average_success_rate: float
    most_applied_experience_id: str | None


class EvolutionInfo(BaseModel):
    id: str
    evolution_type: str
    title: str
    description: str
    status: str
    verification_status: str
    is_applied: bool
    is_rolled_back: bool
    rollback_reason: str | None
    version: int | None
    lesson_key: str | None
    created_at: str


class ReasonBody(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


def _iso(value: Optional[datetime]) -> str:
    return (value or datetime.now(timezone.utc)).isoformat()


def _info(exp: ExperienceRecord) -> ExperienceInfo:
    return ExperienceInfo(
        id=str(exp.id), agent_id=str(exp.agent_id), agent_name=exp.agent_name,
        workspace_id=str(exp.workspace_id) if exp.workspace_id else None,
        session_id=str(exp.session_id) if exp.session_id else None,
        task_id=str(exp.task_id) if exp.task_id else None,
        experience_type=exp.experience_type, title=exp.title, description=exp.description,
        situation=exp.situation, action_taken=exp.action_taken, result=exp.result,
        outcome=exp.outcome, lesson_learned=exp.lesson_learned,
        lesson_status=exp.lesson_status or "candidate", lesson_key=exp.lesson_key,
        applicable_contexts=exp.applicable_contexts or [], confidence_score=exp.confidence_score,
        times_applied=exp.times_applied, success_rate=exp.success_rate,
        is_validated=exp.is_validated, is_active=exp.is_active, meta_data=exp.meta_data,
        created_at=_iso(exp.created_at), updated_at=_iso(exp.updated_at),
    )


async def _owned(db: AsyncSession, user_id: str) -> List[UUID]:
    return list((await db.execute(
        select(Workspace.id).where(Workspace.owner_id == UUID(str(user_id)))
    )).scalars().all())


def _scoped(owned: List[UUID]):
    """Experiences in the caller's workspaces, including rows written before
    experiences carried their own workspace_id (scoped through the owning agent)."""
    return (
        select(ExperienceRecord)
        .join(Agent, Agent.id == ExperienceRecord.agent_id)
        .where(or_(ExperienceRecord.workspace_id.in_(owned),
                   (ExperienceRecord.workspace_id.is_(None)) & Agent.workspace_id.in_(owned)))
    )


async def _owned_experience(db: AsyncSession, user_id: str, experience_id: UUID) -> ExperienceRecord:
    owned = await _owned(db, user_id)
    exp = (await db.execute(_scoped(owned).where(ExperienceRecord.id == experience_id))).scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    if exp.workspace_id is None:
        raise HTTPException(status_code=409, detail="Legacy experience has no workspace; it cannot be verified")
    return exp


@router.get("/list", response_model=List[ExperienceInfo])
async def list_experiences(
    user_id: CurrentUserId,
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    agent_name: Optional[str] = None,
    experience_type: Optional[str] = None,
    outcome: Optional[str] = None,
    lesson_status: Optional[str] = None,
    is_validated: Optional[bool] = None,
    is_active: Optional[bool] = None,
    min_confidence: Optional[float] = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned(db, user_id)
    query = _scoped(owned)
    if workspace_id:
        if workspace_id not in owned:
            raise HTTPException(status_code=404, detail="Workspace not found")
        query = query.where(ExperienceRecord.workspace_id == workspace_id)
    if agent_id:
        query = query.where(ExperienceRecord.agent_id == agent_id)
    if agent_name:
        query = query.where(ExperienceRecord.agent_name == agent_name)
    if experience_type:
        query = query.where(ExperienceRecord.experience_type == experience_type)
    if outcome:
        query = query.where(ExperienceRecord.outcome == outcome)
    if lesson_status:
        query = query.where(ExperienceRecord.lesson_status == lesson_status)
    if is_validated is not None:
        query = query.where(ExperienceRecord.is_validated == is_validated)
    if is_active is not None:
        query = query.where(ExperienceRecord.is_active == is_active)
    if min_confidence is not None:
        query = query.where(ExperienceRecord.confidence_score >= min_confidence)
    query = query.order_by(ExperienceRecord.created_at.desc()).limit(limit)
    return [_info(e) for e in (await db.execute(query)).scalars().all()]


@router.get("/stats", response_model=ExperienceStats)
async def get_experience_stats(
    user_id: CurrentUserId,
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned(db, user_id)
    query = _scoped(owned)
    if workspace_id:
        if workspace_id not in owned:
            raise HTTPException(status_code=404, detail="Workspace not found")
        query = query.where(ExperienceRecord.workspace_id == workspace_id)
    if agent_id:
        query = query.where(ExperienceRecord.agent_id == agent_id)
    rows = (await db.execute(query)).scalars().all()
    by_type: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for e in rows:
        by_type[e.experience_type] = by_type.get(e.experience_type, 0) + 1
        by_outcome[e.outcome] = by_outcome.get(e.outcome, 0) + 1
        status = e.lesson_status or "candidate"
        by_status[status] = by_status.get(status, 0) + 1
    rates = [e.success_rate for e in rows if e.success_rate is not None]
    most = max(rows, key=lambda e: e.times_applied or 0) if rows else None
    return ExperienceStats(
        total_experiences=len(rows),
        validated_experiences=sum(1 for e in rows if e.is_validated),
        active_experiences=sum(1 for e in rows if e.is_active),
        by_type=by_type, by_outcome=by_outcome, by_lesson_status=by_status,
        average_confidence=round(sum(e.confidence_score for e in rows) / len(rows), 3) if rows else 0.0,
        average_success_rate=round(sum(rates) / len(rates), 3) if rates else 0.0,
        most_applied_experience_id=str(most.id) if most and most.times_applied else None,
    )


@router.get("/lessons", response_model=List[ExperienceInfo])
async def list_verified_lessons(
    user_id: CurrentUserId, workspace_id: UUID, agent_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Lessons currently given to agents in this workspace."""
    if workspace_id not in await _owned(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    query = select(ExperienceRecord).where(
        ExperienceRecord.workspace_id == workspace_id,
        ExperienceRecord.lesson_status == "verified",
        ExperienceRecord.is_active.is_(True),
    )
    if agent_name:
        query = query.where(ExperienceRecord.agent_name == agent_name)
    rows = (await db.execute(query.order_by(ExperienceRecord.updated_at.desc()))).scalars().all()
    return [_info(e) for e in rows]


@router.get("/evolution", response_model=List[EvolutionInfo])
async def list_lesson_evolution(
    user_id: CurrentUserId, workspace_id: UUID, limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Versioned activation, retirement, and proposal records for this workspace."""
    if workspace_id not in await _owned(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    rows = (await db.execute(
        select(SelfEvolutionRecord)
        .join(Agent, Agent.id == SelfEvolutionRecord.agent_id)
        .where(Agent.workspace_id == workspace_id,
               SelfEvolutionRecord.evolution_type.in_(
                   ("lesson_activation", "lesson_retirement", "workflow_proposal")))
        .order_by(SelfEvolutionRecord.created_at.desc()).limit(limit)
    )).scalars().all()
    return [EvolutionInfo(
        id=str(r.id), evolution_type=r.evolution_type, title=r.title, description=r.description,
        status=r.status, verification_status=r.verification_status, is_applied=r.is_applied,
        is_rolled_back=r.is_rolled_back, rollback_reason=r.rollback_reason,
        version=(r.meta_data or {}).get("version"), lesson_key=(r.meta_data or {}).get("lesson_key"),
        created_at=_iso(r.created_at),
    ) for r in rows if (r.meta_data or {}).get("workspace_id") in (None, str(workspace_id))]


@router.post("/{experience_id}/approve", response_model=ExperienceInfo)
async def approve_lesson(experience_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    """Human verification of a candidate lesson. Unsafe lessons are refused."""
    exp = await _owned_experience(db, user_id, experience_id)
    try:
        await learning_service.approve_lesson(db, exp.id, exp.workspace_id, approver=f"user:{user_id}")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return _info(exp)


@router.post("/{experience_id}/reject", response_model=ExperienceInfo)
async def reject_lesson(
    experience_id: UUID, body: ReasonBody, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    exp = await _owned_experience(db, user_id, experience_id)
    await learning_service.reject_lesson(db, exp.id, exp.workspace_id, reason=body.reason)
    return _info(exp)


@router.post("/{experience_id}/retire", response_model=ExperienceInfo)
async def retire_lesson(
    experience_id: UUID, body: ReasonBody, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    """Roll back a verified lesson."""
    exp = await _owned_experience(db, user_id, experience_id)
    if not await learning_service.retire(db, exp.workspace_id, exp.lesson_key,
                                         reason=f"manual rollback by user:{user_id}: {body.reason}"):
        raise HTTPException(status_code=409, detail="Lesson is not currently verified")
    return _info(exp)


@router.get("/agent/{agent_id}/top", response_model=List[ExperienceInfo])
async def get_agent_top_experiences(
    agent_id: UUID, user_id: CurrentUserId, limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned(db, user_id)
    rows = (await db.execute(
        _scoped(owned).where(ExperienceRecord.agent_id == agent_id, ExperienceRecord.is_active.is_(True))
        .order_by(ExperienceRecord.confidence_score.desc(), ExperienceRecord.times_applied.desc())
        .limit(limit)
    )).scalars().all()
    return [_info(e) for e in rows]


# Dynamic single-segment route declared last so it does not shadow the static routes.
@router.get("/{experience_id}", response_model=ExperienceInfo)
async def get_experience(experience_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    owned = await _owned(db, user_id)
    exp = (await db.execute(_scoped(owned).where(ExperienceRecord.id == experience_id))).scalar_one_or_none()
    if exp is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return _info(exp)
