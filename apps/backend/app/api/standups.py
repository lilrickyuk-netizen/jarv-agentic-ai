"""
JARV Backend - AI Standups API

RESTful API endpoints for AI team standups and daily updates.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import date, datetime

from app.core.database import get_db
from app.models.company_operations import AIStandup

router = APIRouter(prefix="/api/standups", tags=["standups"])


class StandupInfo(BaseModel):
    id: str
    workspace_id: str
    agent_id: str | None
    standup_date: str
    yesterday_accomplishments: List[str]
    today_plans: List[str]
    blockers: List[str]
    needs_help_with: List[str] | None
    tasks_completed: int
    tasks_in_progress: int
    tasks_planned: int
    mood: str | None
    confidence_level: float | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class StandupStats(BaseModel):
    total_standups: int
    standups_today: int
    total_accomplishments: int
    total_blockers: int
    total_tasks_completed: int
    total_tasks_in_progress: int
    average_confidence: float
    agents_reporting: int
    common_blockers: List[str]


class DailyStandupSummary(BaseModel):
    standup_date: str
    total_standups: int
    total_accomplishments: int
    total_blockers: int
    tasks_completed: int
    tasks_in_progress: int
    average_confidence: float


@router.get("/list", response_model=List[StandupInfo])
async def list_standups(
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    has_blockers: Optional[bool] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    List AI standups with optional filtering.

    Args:
        workspace_id: Filter by workspace
        agent_id: Filter by specific agent
        start_date: Filter standups from this date onwards
        end_date: Filter standups up to this date
        has_blockers: Filter standups with/without blockers
        limit: Maximum number of standups to return

    Returns:
        List of standup records
    """
    query = select(AIStandup)

    if workspace_id:
        query = query.where(AIStandup.workspace_id == workspace_id)
    if agent_id:
        query = query.where(AIStandup.agent_id == agent_id)
    if start_date:
        query = query.where(AIStandup.standup_date >= start_date)
    if end_date:
        query = query.where(AIStandup.standup_date <= end_date)
    if has_blockers is not None:
        if has_blockers:
            query = query.where(func.json_array_length(AIStandup.blockers) > 0)
        else:
            query = query.where(func.json_array_length(AIStandup.blockers) == 0)

    query = query.order_by(AIStandup.standup_date.desc(), AIStandup.created_at.desc()).limit(limit)

    result = await db.execute(query)
    standups = result.scalars().all()

    return [
        StandupInfo(
            id=str(standup.id),
            workspace_id=str(standup.workspace_id),
            agent_id=str(standup.agent_id) if standup.agent_id else None,
            standup_date=standup.standup_date.isoformat(),
            yesterday_accomplishments=standup.yesterday_accomplishments or [],
            today_plans=standup.today_plans or [],
            blockers=standup.blockers or [],
            needs_help_with=standup.needs_help_with,
            tasks_completed=standup.tasks_completed,
            tasks_in_progress=standup.tasks_in_progress,
            tasks_planned=standup.tasks_planned,
            mood=standup.mood,
            confidence_level=standup.confidence_level,
            created_at=standup.created_at.isoformat() if standup.created_at else datetime.now().isoformat(),
            updated_at=standup.updated_at.isoformat() if standup.updated_at else datetime.now().isoformat(),
        )
        for standup in standups
    ]


@router.get("/{standup_id}", response_model=StandupInfo)
async def get_standup(
    standup_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific standup.

    Args:
        standup_id: UUID of the standup

    Returns:
        Standup information
    """
    query = select(AIStandup).where(AIStandup.id == standup_id)
    result = await db.execute(query)
    standup = result.scalar_one_or_none()

    if not standup:
        raise HTTPException(status_code=404, detail="Standup not found")

    return StandupInfo(
        id=str(standup.id),
        workspace_id=str(standup.workspace_id),
        agent_id=str(standup.agent_id) if standup.agent_id else None,
        standup_date=standup.standup_date.isoformat(),
        yesterday_accomplishments=standup.yesterday_accomplishments or [],
        today_plans=standup.today_plans or [],
        blockers=standup.blockers or [],
        needs_help_with=standup.needs_help_with,
        tasks_completed=standup.tasks_completed,
        tasks_in_progress=standup.tasks_in_progress,
        tasks_planned=standup.tasks_planned,
        mood=standup.mood,
        confidence_level=standup.confidence_level,
        created_at=standup.created_at.isoformat() if standup.created_at else datetime.now().isoformat(),
        updated_at=standup.updated_at.isoformat() if standup.updated_at else datetime.now().isoformat(),
    )


@router.get("/stats", response_model=StandupStats)
async def get_standup_stats(
    workspace_id: Optional[UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """
    Get aggregated statistics for standups.

    Args:
        workspace_id: Optional workspace filter
        start_date: Optional start date filter
        end_date: Optional end date filter

    Returns:
        Standup statistics including counts and metrics
    """
    query = select(AIStandup)
    if workspace_id:
        query = query.where(AIStandup.workspace_id == workspace_id)
    if start_date:
        query = query.where(AIStandup.standup_date >= start_date)
    if end_date:
        query = query.where(AIStandup.standup_date <= end_date)

    result = await db.execute(query)
    all_standups = result.scalars().all()

    # Calculate statistics
    total_standups = len(all_standups)
    today = date.today()
    standups_today = sum(1 for s in all_standups if s.standup_date == today)

    total_accomplishments = sum(len(s.yesterday_accomplishments or []) for s in all_standups)
    total_blockers = sum(len(s.blockers or []) for s in all_standups)
    total_tasks_completed = sum(s.tasks_completed for s in all_standups)
    total_tasks_in_progress = sum(s.tasks_in_progress for s in all_standups)

    # Average confidence
    confidence_values = [s.confidence_level for s in all_standups if s.confidence_level is not None]
    average_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0

    # Unique agents reporting
    agents_reporting = len(set(s.agent_id for s in all_standups if s.agent_id))

    # Common blockers (extract unique blockers and count frequency)
    all_blockers = []
    for s in all_standups:
        all_blockers.extend(s.blockers or [])

    # Get top 5 common blockers
    blocker_counts = {}
    for blocker in all_blockers:
        blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1

    common_blockers = sorted(blocker_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    common_blockers = [blocker for blocker, count in common_blockers]

    return StandupStats(
        total_standups=total_standups,
        standups_today=standups_today,
        total_accomplishments=total_accomplishments,
        total_blockers=total_blockers,
        total_tasks_completed=total_tasks_completed,
        total_tasks_in_progress=total_tasks_in_progress,
        average_confidence=round(average_confidence, 2),
        agents_reporting=agents_reporting,
        common_blockers=common_blockers,
    )


@router.get("/daily-summary", response_model=List[DailyStandupSummary])
async def get_daily_summary(
    workspace_id: Optional[UUID] = None,
    days: int = 7,
    db: Session = Depends(get_db)
):
    """
    Get daily standup summary for the past N days.

    Args:
        workspace_id: Optional workspace filter
        days: Number of days to include (default 7)

    Returns:
        List of daily standup summaries
    """
    query = select(AIStandup)
    if workspace_id:
        query = query.where(AIStandup.workspace_id == workspace_id)

    # Filter by date range
    end_date = date.today()
    start_date = date.fromordinal(end_date.toordinal() - days)
    query = query.where(AIStandup.standup_date >= start_date)
    query = query.where(AIStandup.standup_date <= end_date)

    result = await db.execute(query)
    all_standups = result.scalars().all()

    # Group by date
    daily_groups = {}
    for standup in all_standups:
        date_key = standup.standup_date.isoformat()
        if date_key not in daily_groups:
            daily_groups[date_key] = []
        daily_groups[date_key].append(standup)

    # Create summaries
    summaries = []
    for date_key, standups in sorted(daily_groups.items(), reverse=True):
        confidence_values = [s.confidence_level for s in standups if s.confidence_level is not None]
        avg_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0

        summaries.append(DailyStandupSummary(
            standup_date=date_key,
            total_standups=len(standups),
            total_accomplishments=sum(len(s.yesterday_accomplishments or []) for s in standups),
            total_blockers=sum(len(s.blockers or []) for s in standups),
            tasks_completed=sum(s.tasks_completed for s in standups),
            tasks_in_progress=sum(s.tasks_in_progress for s in standups),
            average_confidence=round(avg_confidence, 2),
        ))

    return summaries
