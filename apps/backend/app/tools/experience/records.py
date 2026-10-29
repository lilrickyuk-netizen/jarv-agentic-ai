"""
JARV Backend - Experience record tools (Repair 12e-3c)

create_experience_record, summarise_experience, extract_lesson,
link_experience_to_workspace, link_experience_to_task,
list_experience_records.

They work through the verified-learning service (app.core.learning): every
record is redacted, its lesson passes the self-evolution safety guard,
lessons only become guidance once verified, and experiences never mix
between workspaces (linking to another workspace makes a guarded copy there).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.agents.base import AuthorityLevel
from app.core.learning import learning_service
from app.models.agent import Agent
from app.models.self_evolution import ExperienceRecord
from app.models.task import Task
from app.tools._scoped import ScopedTool, as_uuid


class _ExperienceTool(ScopedTool):
    _category = "experience"
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS


def view(row: ExperienceRecord) -> Dict[str, Any]:
    return {"id": str(row.id), "workspace_id": str(row.workspace_id) if row.workspace_id else None,
            "task_id": str(row.task_id) if row.task_id else None, "agent": row.agent_name,
            "type": row.experience_type, "title": row.title, "situation": row.situation,
            "action": row.action_taken, "result": row.result, "outcome": row.outcome,
            "lesson": row.lesson_learned, "lesson_status": row.lesson_status, "lesson_key": row.lesson_key,
            "confidence": row.confidence_score, "times_applied": row.times_applied,
            "success_rate": row.success_rate, "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _in_workspace(workspace_id: UUID):
    """Records of this workspace, including older rows that only carry the workspace's agent."""
    agents = select(Agent.id).where(Agent.workspace_id == workspace_id)
    return or_(ExperienceRecord.workspace_id == workspace_id,
               (ExperienceRecord.workspace_id.is_(None)) & ExperienceRecord.agent_id.in_(agents))


async def _record(db, workspace_id: UUID, experience_id: Any) -> ExperienceRecord:
    row = (await db.execute(select(ExperienceRecord).where(
        ExperienceRecord.id == as_uuid(experience_id, "experience id"), _in_workspace(workspace_id)))
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("Experience record not found in this workspace")
    return row


async def _task(db, workspace_id: UUID, task_id: Any) -> Task:
    row = (await db.execute(select(Task).where(Task.id == as_uuid(task_id, "task id"),
                                               Task.workspace_id == workspace_id))).scalar_one_or_none()
    if row is None:
        raise LookupError("Task not found in this workspace")
    return row


# ----- inputs ------------------------------------------------------------------------------

class _Create(BaseModel):
    situation: str = Field(..., min_length=3)
    action: str = Field(..., min_length=3)
    result: str = Field(..., min_length=1)
    outcome: str = Field(..., description="success, failure, partial")
    lesson: Optional[str] = Field(None, description="Omit to derive it from the record")
    agent_name: Optional[str] = None
    task_id: Optional[str] = None
    tools_used: List[str] = Field(default_factory=list)


class _Summary(BaseModel):
    days: int = Field(30, ge=1, le=365)
    agent_name: Optional[str] = None
    task_id: Optional[str] = None


class _Extract(BaseModel):
    experience_id: Optional[str] = Field(None, description="Show an existing record's lesson and its evidence")
    task_id: Optional[str] = Field(None, description="Record a finished task as an experience and extract its lesson")
    lesson: Optional[str] = None


class _LinkWorkspace(BaseModel):
    experience_id: str
    workspace_id: str


class _LinkTask(BaseModel):
    experience_id: str
    task_id: str


class _List(BaseModel):
    outcome: Optional[str] = None
    agent_name: Optional[str] = None
    lesson_status: Optional[str] = Field(None, description="candidate, verified, rejected, retired")
    task_id: Optional[str] = None
    limit: int = Field(25, ge=1, le=200)


# ----- tools ------------------------------------------------------------------------------

class CreateExperienceRecordTool(_ExperienceTool):
    _name = "create_experience_record"
    _description = ("Record what happened (situation, action, result, outcome) with its lesson; the lesson is "
                    "safety-checked and only becomes guidance once verified.")
    _input = _Create

    async def act(self, db, context, owner, data):
        task_id = (await _task(db, context.workspace_id, data["task_id"])).id if data.get("task_id") else context.task_id
        row = await learning_service.record_experience(
            db, workspace_id=context.workspace_id, agent_name=data.get("agent_name") or "orchestrator",
            situation=data["situation"], action=data["action"], result=data["result"], outcome=data["outcome"],
            task_id=task_id, lesson=data.get("lesson"), tools_used=data["tools_used"], agent_id=context.agent_id,
            meta={"source": "create_experience_record"})
        return view(row), f"Experience recorded ({row.outcome}); lesson {row.lesson_status}"


class SummariseExperienceTool(_ExperienceTool):
    _name = "summarise_experience"
    _description = "Summarise the workspace's experience: outcomes, agents, lesson status, verified lessons, recent failures."
    _input = _Summary
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        since = datetime.now(timezone.utc) - timedelta(days=data["days"])
        query = select(ExperienceRecord).where(_in_workspace(context.workspace_id),
                                               ExperienceRecord.created_at >= since)
        if data.get("agent_name"):
            query = query.where(ExperienceRecord.agent_name == data["agent_name"])
        if data.get("task_id"):
            query = query.where(ExperienceRecord.task_id == as_uuid(data["task_id"], "task id"))
        rows = list((await db.execute(query.order_by(ExperienceRecord.created_at.desc()))).scalars().all())
        outcomes = Counter(r.outcome for r in rows)
        judged = outcomes.get("success", 0) + outcomes.get("failure", 0)
        verified = [r for r in rows if r.lesson_status == "verified" and r.is_active]
        summary = {
            "period_days": data["days"], "total": len(rows), "by_outcome": dict(outcomes),
            "success_rate": round(outcomes.get("success", 0) / judged, 3) if judged else None,
            "by_agent": dict(Counter(r.agent_name or "unknown" for r in rows).most_common(10)),
            "by_lesson_status": dict(Counter(r.lesson_status for r in rows)),
            "verified_lessons": [{"lesson": r.lesson_learned, "agent": r.agent_name, "applied": r.times_applied,
                                  "success_rate": r.success_rate} for r in verified[:10]],
            "recent_failures": [{"title": r.title, "result": r.result[:300], "lesson": r.lesson_learned}
                                for r in rows if r.outcome == "failure"][:5],
        }
        text = (f"{len(rows)} experience(s) in {data['days']} days; {len(verified)} verified lesson(s)"
                + (f"; success rate {summary['success_rate']:.0%}" if summary["success_rate"] is not None else ""))
        return summary, text


class ExtractLessonTool(_ExperienceTool):
    _name = "extract_lesson"
    _description = ("Extract the lesson from a finished task (recording it as an experience) or show an existing "
                    "record's lesson with the evidence behind it.")
    _input = _Extract

    async def act(self, db, context, owner, data):
        if data.get("task_id"):
            task = await _task(db, context.workspace_id, data["task_id"])
            if task.status not in ("completed", "failed", "partial", "cancelled"):
                raise ValueError(f"The task is still {task.status}; lessons come from finished work")
            result = task.result if isinstance(task.result, dict) else {}
            outcome = {"completed": "success", "failed": "failure"}.get(task.status, "partial")
            agent = (task.context or {}).get("agent") or result.get("agent")
            produced = task.error_message or result.get("output_text") or result.get("summary") or result.get("answer")
            row = await learning_service.record_experience(
                db, workspace_id=context.workspace_id, agent_name=agent or "orchestrator",
                situation=task.title, action=task.description or task.title,
                result=str(produced or f"task {task.status}")[:4000],
                outcome=outcome, task_id=task.id, lesson=data.get("lesson"), meta={"source": "extract_lesson"})
        elif data.get("experience_id"):
            row = await _record(db, context.workspace_id, data["experience_id"])
        else:
            raise ValueError("Give a task_id or an experience_id")
        evidence = []
        if row.lesson_key:
            cluster = (await db.execute(select(ExperienceRecord).where(
                ExperienceRecord.lesson_key == row.lesson_key, _in_workspace(context.workspace_id)))).scalars().all()
            evidence = [{"id": str(r.id), "outcome": r.outcome, "status": r.lesson_status} for r in cluster]
        return ({"experience": view(row), "lesson": row.lesson_learned, "status": row.lesson_status,
                 "evidence": evidence},
                f"Lesson ({row.lesson_status}, {len(evidence)} supporting record(s)): {row.lesson_learned[:160]}")


class LinkExperienceToWorkspaceTool(_ExperienceTool):
    _name = "link_experience_to_workspace"
    _description = ("Link an experience to a workspace: an unscoped record is scoped to it; a record from another "
                    "of the owner's workspaces is copied there (safety-checked) so workspaces never mix.")
    _input = _LinkWorkspace

    async def act(self, db, context, owner, data):
        from app.core.workspaces.lifecycle import workspace_lifecycle

        target = await workspace_lifecycle.owned(db, data["workspace_id"], owner)
        row = await _record(db, context.workspace_id, data["experience_id"])
        if row.workspace_id is None:
            if target.id != context.workspace_id:
                raise PermissionError("An unscoped record can only be scoped to the workspace that owns its agent")
            row.workspace_id = target.id
            await db.flush()
            return view(row), "Experience scoped to this workspace"
        if row.workspace_id == target.id:
            return view(row), "Experience already belongs to that workspace"
        copy = await learning_service.record_experience(
            db, workspace_id=target.id, agent_name=row.agent_name or "orchestrator", situation=row.situation,
            action=row.action_taken, result=row.result, outcome=row.outcome, lesson=row.lesson_learned,
            meta={"copied_from": str(row.id), "source_workspace": str(row.workspace_id)})
        return {"source": view(row), "copy": view(copy)}, f"Experience copied to '{target.name}' as {copy.lesson_status}"


class LinkExperienceToTaskTool(_ExperienceTool):
    _name = "link_experience_to_task"
    _description = "Link an experience record to a task in the same workspace."
    _input = _LinkTask

    async def act(self, db, context, owner, data):
        row = await _record(db, context.workspace_id, data["experience_id"])
        task = await _task(db, row.workspace_id or context.workspace_id, data["task_id"])
        row.task_id = task.id
        row.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return view(row), f"Experience linked to task '{task.title}'"


class ListExperienceRecordsTool(_ExperienceTool):
    _name = "list_experience_records"
    _description = "List this workspace's experience records, filtered by outcome, agent, lesson status or task."
    _input = _List
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        query = select(ExperienceRecord).where(_in_workspace(context.workspace_id))
        if data.get("outcome"):
            query = query.where(ExperienceRecord.outcome == data["outcome"])
        if data.get("agent_name"):
            query = query.where(ExperienceRecord.agent_name == data["agent_name"])
        if data.get("lesson_status"):
            query = query.where(ExperienceRecord.lesson_status == data["lesson_status"])
        if data.get("task_id"):
            query = query.where(ExperienceRecord.task_id == as_uuid(data["task_id"], "task id"))
        rows = (await db.execute(query.order_by(ExperienceRecord.created_at.desc()).limit(data["limit"]))).scalars().all()
        return {"records": [view(r) for r in rows], "count": len(rows)}, f"{len(rows)} experience record(s)"


EXPERIENCE_RECORD_TOOLS = [
    CreateExperienceRecordTool, SummariseExperienceTool, ExtractLessonTool, LinkExperienceToWorkspaceTool,
    LinkExperienceToTaskTool, ListExperienceRecordsTool,
]
