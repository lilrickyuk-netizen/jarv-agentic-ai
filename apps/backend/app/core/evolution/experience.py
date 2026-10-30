"""
JARV Backend - Experience Management

Database-backed experience capture for the self-evolution API. Records are
stored as ``ExperienceRecord`` rows through the verified-learning service, so
experiences captured here feed the same lesson verification, application, and
rollback lifecycle as agent runs.

Summaries and lessons are taken from the stored record. Nothing is generated
that the record does not support.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

import logging
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.learning import learning_service
from app.models.agent import Agent
from app.models.self_evolution import ExperienceRecord

logger = logging.getLogger(__name__)


class ExperienceType(str, Enum):
    """Type of experience"""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ExperienceCreate(BaseModel):
    """Schema for creating experience record"""
    workspace_id: UUID
    agent_id: Optional[UUID] = None
    agent_name: str
    task_description: str
    experience_type: ExperienceType
    tools_used: List[str] = Field(default_factory=list)
    actions_taken: List[str] = Field(default_factory=list)
    outcome: str
    duration_seconds: float = 0.0
    tokens_used: Dict[str, int] = Field(default_factory=dict)
    cost_estimate: float = 0.0
    context: Dict[str, Any] = Field(default_factory=dict)
    error_details: Optional[str] = None
    lesson: Optional[str] = Field(None, description="Lesson stated by the caller; derived from the record if omitted")


class LessonExtract(BaseModel):
    """Lesson held by an experience record"""
    lesson_text: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    applicable_to: List[str] = Field(default_factory=list)
    improvement_areas: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExperienceResult(BaseModel):
    """Experience record result"""
    id: UUID
    workspace_id: Optional[UUID]
    agent_id: UUID
    agent_name: str
    task_description: str
    experience_type: ExperienceType
    tools_used: List[str]
    actions_taken: List[str]
    outcome: str
    duration_seconds: float
    tokens_used: Dict[str, int]
    cost_estimate: float
    context: Dict[str, Any]
    error_details: Optional[str]
    summary: Optional[str]
    lessons: List[LessonExtract]
    created_at: datetime
    updated_at: datetime


def _type(record: ExperienceRecord) -> ExperienceType:
    try:
        return ExperienceType(record.experience_type)
    except ValueError:
        return {"success": ExperienceType.SUCCESS, "failure": ExperienceType.FAILURE}.get(
            record.outcome, ExperienceType.PARTIAL)


def _lesson(record: ExperienceRecord) -> LessonExtract:
    meta = record.meta_data or {}
    return LessonExtract(
        lesson_text=record.lesson_learned,
        confidence_score=max(0.0, min(1.0, record.confidence_score or 0.0)),
        applicable_to=list(record.applicable_contexts or []),
        improvement_areas=[],
        metadata={"status": record.lesson_status, "source": meta.get("lesson_source"),
                  "times_applied": record.times_applied, "success_rate": record.success_rate},
    )


def _summary(record: ExperienceRecord) -> str:
    return f"{record.agent_name or 'agent'} {record.outcome}: {record.situation} -> {record.result}"[:1000]


def to_result(record: ExperienceRecord, workspace_id: Optional[UUID] = None) -> ExperienceResult:
    meta = record.meta_data or {}
    now = datetime.now(timezone.utc)
    return ExperienceResult(
        id=record.id,
        workspace_id=record.workspace_id or workspace_id,
        agent_id=record.agent_id,
        agent_name=record.agent_name or "agent",
        task_description=record.situation,
        experience_type=_type(record),
        tools_used=list(meta.get("tools_used") or []),
        actions_taken=[record.action_taken],
        outcome=record.result,
        duration_seconds=float(meta.get("duration_seconds") or 0.0),
        tokens_used=dict(meta.get("tokens_used") or {}),
        cost_estimate=float(meta.get("cost_estimate") or 0.0),
        context=dict(meta.get("context") or {}),
        error_details=record.result if record.outcome == "failure" else None,
        summary=_summary(record),
        lessons=[_lesson(record)],
        created_at=record.created_at or now,
        updated_at=record.updated_at or now,
    )


class ExperienceManager:
    """Experience capture and retrieval scoped to the caller's workspaces."""

    def _scoped(self, workspace_ids: Sequence[UUID]):
        ids = list(workspace_ids)
        return (
            select(ExperienceRecord, Agent.workspace_id)
            .join(Agent, Agent.id == ExperienceRecord.agent_id)
            .where(or_(ExperienceRecord.workspace_id.in_(ids),
                       (ExperienceRecord.workspace_id.is_(None)) & Agent.workspace_id.in_(ids)))
        )

    async def capture_experience(self, db: AsyncSession, experience: ExperienceCreate) -> UUID:
        agent_id = None
        if experience.agent_id is not None:
            agent_id = (await db.execute(select(Agent.id).where(
                Agent.id == experience.agent_id, Agent.workspace_id == experience.workspace_id,
            ))).scalar_one_or_none()
            if agent_id is None:
                raise PermissionError("Agent does not belong to this workspace")
        record = await learning_service.record_experience(
            db,
            workspace_id=experience.workspace_id,
            agent_name=experience.agent_name,
            situation=experience.task_description,
            action="; ".join(experience.actions_taken) or "(not recorded)",
            result=experience.error_details or experience.outcome,
            outcome=experience.experience_type.value,
            experience_type=experience.experience_type.value,
            tools_used=experience.tools_used,
            agent_id=agent_id,
            lesson=experience.lesson,
            meta={"duration_seconds": experience.duration_seconds,
                  "tokens_used": experience.tokens_used,
                  "cost_estimate": experience.cost_estimate,
                  "context": experience.context},
        )
        return record.id

    async def get_experience(
        self, db: AsyncSession, experience_id: UUID, workspace_ids: Sequence[UUID],
    ) -> Optional[ExperienceResult]:
        row = (await db.execute(
            self._scoped(workspace_ids).where(ExperienceRecord.id == experience_id)
        )).first()
        return to_result(row[0], row[1]) if row else None

    async def summarize_experience(
        self, db: AsyncSession, experience_id: UUID, workspace_ids: Sequence[UUID],
    ) -> Optional[str]:
        result = await self.get_experience(db, experience_id, workspace_ids)
        return result.summary if result else None

    async def extract_lesson(
        self, db: AsyncSession, experience_id: UUID, workspace_ids: Sequence[UUID],
    ) -> Optional[List[LessonExtract]]:
        result = await self.get_experience(db, experience_id, workspace_ids)
        return result.lessons if result else None

    async def list_experiences(
        self,
        db: AsyncSession,
        workspace_ids: Sequence[UUID],
        *,
        agent_id: Optional[UUID] = None,
        experience_type: Optional[ExperienceType] = None,
        limit: int = 100,
    ) -> List[ExperienceResult]:
        query = self._scoped(workspace_ids)
        if agent_id:
            query = query.where(ExperienceRecord.agent_id == agent_id)
        if experience_type:
            query = query.where(ExperienceRecord.experience_type == experience_type.value)
        rows = (await db.execute(
            query.order_by(ExperienceRecord.created_at.desc()).limit(limit)
        )).all()
        return [to_result(record, workspace) for record, workspace in rows]

    async def get_experience_stats(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        return await learning_service.stats(db, [workspace_id])
