"""
JARV Backend - Experience API

RESTful API endpoints for agent experience records and learning insights.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.models.self_evolution import ExperienceRecord

router = APIRouter(prefix="/api/experience", tags=["experience"])


class ExperienceInfo(BaseModel):
    id: str
    agent_id: str
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
    applicable_contexts: List[str]
    confidence_score: float
    times_applied: int
    success_rate: float | None
    is_validated: bool
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ExperienceStats(BaseModel):
    total_experiences: int
    validated_experiences: int
    active_experiences: int
    by_type: dict[str, int]
    by_outcome: dict[str, int]
    average_confidence: float
    average_success_rate: float
    most_applied_experience_id: str | None


@router.get("/list", response_model=List[ExperienceInfo])
async def list_experiences(
    agent_id: Optional[UUID] = None,
    experience_type: Optional[str] = None,
    outcome: Optional[str] = None,
    is_validated: Optional[bool] = None,
    is_active: Optional[bool] = True,
    min_confidence: Optional[float] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    List experience records with optional filtering.

    Args:
        agent_id: Filter by agent
        experience_type: Filter by experience type
        outcome: Filter by outcome (success, failure, partial)
        is_validated: Filter by validation status
        is_active: Filter by active status
        min_confidence: Minimum confidence score
        limit: Maximum number of experiences to return

    Returns:
        List of experience records
    """
    query = select(ExperienceRecord)

    if agent_id:
        query = query.where(ExperienceRecord.agent_id == agent_id)
    if experience_type:
        query = query.where(ExperienceRecord.experience_type == experience_type)
    if outcome:
        query = query.where(ExperienceRecord.outcome == outcome)
    if is_validated is not None:
        query = query.where(ExperienceRecord.is_validated == is_validated)
    if is_active is not None:
        query = query.where(ExperienceRecord.is_active == is_active)
    if min_confidence is not None:
        query = query.where(ExperienceRecord.confidence_score >= min_confidence)

    query = query.order_by(ExperienceRecord.confidence_score.desc(), ExperienceRecord.created_at.desc()).limit(limit)

    result = await db.execute(query)
    experiences = result.scalars().all()

    return [
        ExperienceInfo(
            id=str(exp.id),
            agent_id=str(exp.agent_id),
            session_id=str(exp.session_id) if exp.session_id else None,
            task_id=str(exp.task_id) if exp.task_id else None,
            experience_type=exp.experience_type,
            title=exp.title,
            description=exp.description,
            situation=exp.situation,
            action_taken=exp.action_taken,
            result=exp.result,
            outcome=exp.outcome,
            lesson_learned=exp.lesson_learned,
            applicable_contexts=exp.applicable_contexts or [],
            confidence_score=exp.confidence_score,
            times_applied=exp.times_applied,
            success_rate=exp.success_rate,
            is_validated=exp.is_validated,
            is_active=exp.is_active,
            created_at=exp.created_at.isoformat() if exp.created_at else datetime.now().isoformat(),
            updated_at=exp.updated_at.isoformat() if exp.updated_at else datetime.now().isoformat(),
        )
        for exp in experiences
    ]


@router.get("/stats", response_model=ExperienceStats)
async def get_experience_stats(
    agent_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    Get aggregated statistics for experiences.

    Args:
        agent_id: Optional agent filter

    Returns:
        Experience statistics including counts and metrics
    """
    query = select(ExperienceRecord)
    if agent_id:
        query = query.where(ExperienceRecord.agent_id == agent_id)

    result = await db.execute(query)
    all_experiences = result.scalars().all()

    # Calculate statistics
    total_experiences = len(all_experiences)
    validated_experiences = sum(1 for exp in all_experiences if exp.is_validated)
    active_experiences = sum(1 for exp in all_experiences if exp.is_active)

    # By type
    by_type: dict[str, int] = {}
    for exp in all_experiences:
        by_type[exp.experience_type] = by_type.get(exp.experience_type, 0) + 1

    # By outcome
    by_outcome: dict[str, int] = {}
    for exp in all_experiences:
        by_outcome[exp.outcome] = by_outcome.get(exp.outcome, 0) + 1

    # Average confidence
    confidence_values = [exp.confidence_score for exp in all_experiences]
    average_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0

    # Average success rate
    success_rates = [exp.success_rate for exp in all_experiences if exp.success_rate is not None]
    average_success_rate = sum(success_rates) / len(success_rates) if success_rates else 0.0

    # Most applied experience
    most_applied = max(all_experiences, key=lambda exp: exp.times_applied) if all_experiences else None
    most_applied_experience_id = str(most_applied.id) if most_applied else None

    return ExperienceStats(
        total_experiences=total_experiences,
        validated_experiences=validated_experiences,
        active_experiences=active_experiences,
        by_type=by_type,
        by_outcome=by_outcome,
        average_confidence=round(average_confidence, 2),
        average_success_rate=round(average_success_rate, 2),
        most_applied_experience_id=most_applied_experience_id,
    )


@router.get("/agent/{agent_id}/top", response_model=List[ExperienceInfo])
async def get_agent_top_experiences(
    agent_id: UUID,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Get top experiences for a specific agent by confidence and success rate.

    Args:
        agent_id: UUID of the agent
        limit: Number of top experiences to return

    Returns:
        List of top experience records
    """
    query = (
        select(ExperienceRecord)
        .where(ExperienceRecord.agent_id == agent_id)
        .where(ExperienceRecord.is_active == True)
        .order_by(ExperienceRecord.confidence_score.desc(), ExperienceRecord.times_applied.desc())
        .limit(limit)
    )

    result = await db.execute(query)
    experiences = result.scalars().all()

    return [
        ExperienceInfo(
            id=str(exp.id),
            agent_id=str(exp.agent_id),
            session_id=str(exp.session_id) if exp.session_id else None,
            task_id=str(exp.task_id) if exp.task_id else None,
            experience_type=exp.experience_type,
            title=exp.title,
            description=exp.description,
            situation=exp.situation,
            action_taken=exp.action_taken,
            result=exp.result,
            outcome=exp.outcome,
            lesson_learned=exp.lesson_learned,
            applicable_contexts=exp.applicable_contexts or [],
            confidence_score=exp.confidence_score,
            times_applied=exp.times_applied,
            success_rate=exp.success_rate,
            is_validated=exp.is_validated,
            is_active=exp.is_active,
            created_at=exp.created_at.isoformat() if exp.created_at else datetime.now().isoformat(),
            updated_at=exp.updated_at.isoformat() if exp.updated_at else datetime.now().isoformat(),
        )
        for exp in experiences
    ]


@router.get("/{experience_id}", response_model=ExperienceInfo)
async def get_experience(
    experience_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific experience.

    Args:
        experience_id: UUID of the experience

    Returns:
        Experience information
    """
    query = select(ExperienceRecord).where(ExperienceRecord.id == experience_id)
    result = await db.execute(query)
    exp = result.scalar_one_or_none()

    if not exp:
        raise HTTPException(status_code=404, detail="Experience not found")

    return ExperienceInfo(
        id=str(exp.id),
        agent_id=str(exp.agent_id),
        session_id=str(exp.session_id) if exp.session_id else None,
        task_id=str(exp.task_id) if exp.task_id else None,
        experience_type=exp.experience_type,
        title=exp.title,
        description=exp.description,
        situation=exp.situation,
        action_taken=exp.action_taken,
        result=exp.result,
        outcome=exp.outcome,
        lesson_learned=exp.lesson_learned,
        applicable_contexts=exp.applicable_contexts or [],
        confidence_score=exp.confidence_score,
        times_applied=exp.times_applied,
        success_rate=exp.success_rate,
        is_validated=exp.is_validated,
        is_active=exp.is_active,
        created_at=exp.created_at.isoformat() if exp.created_at else datetime.now().isoformat(),
        updated_at=exp.updated_at.isoformat() if exp.updated_at else datetime.now().isoformat(),
    )
