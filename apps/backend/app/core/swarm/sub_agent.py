"""
JARV Backend - Sub-agents

Follow-up work for sub-agents a swarm has already spawned, all persisted and
owner-scoped: assign another task (run through the real AgentRunner inside
the same authority and tool ceilings the sub-agent was spawned with), status,
collected output, attaching a sub-agent's log to its parent task, and timing
out sub-agents whose run stopped without finishing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.operations import AuditLog
from app.models.swarm import SubAgent, SubAgentLog, SubAgentTask, SwarmRun
from app.models.task import Task

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SubAgentCreate(BaseModel):
    swarm_run_id: UUID
    agent_template: str
    task_description: str
    authority_level: int = Field(ge=0, le=10)
    allowed_tools: List[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SubAgentResult(BaseModel):
    id: UUID
    swarm_run_id: UUID
    agent_template: str
    task_description: str
    status: str
    authority_level: int
    allowed_tools: List[str]
    assigned_tasks: List[UUID]
    completed_tasks: int
    failed_tasks: int
    tokens_used: Dict[str, int]
    cost_estimate: float
    output: Optional[Dict[str, Any]]
    timeout_seconds: int
    spawned_at: datetime
    dissolved_at: Optional[datetime]
    metadata: Dict[str, Any]


class SubAgentTaskCreate(BaseModel):
    sub_agent_id: UUID
    task_title: str
    task_description: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class SubAgentTaskResult(BaseModel):
    id: UUID
    sub_agent_id: UUID
    swarm_run_id: UUID
    task_title: str
    task_description: str
    status: TaskStatus
    input_data: Dict[str, Any]
    output_data: Optional[Dict[str, Any]]
    error_message: Optional[str]
    tools_used: List[str]
    tokens_used: Dict[str, int]
    cost_estimate: float
    timeout_seconds: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


async def _tasks(db: AsyncSession, child_id: UUID) -> List[SubAgentTask]:
    return list((await db.execute(select(SubAgentTask).where(SubAgentTask.subagent_id == child_id)
                                  .order_by(SubAgentTask.created_at))).scalars().all())


async def to_result(db: AsyncSession, child: SubAgent) -> SubAgentResult:
    tasks = await _tasks(db, child.id)
    meta = child.meta_data or {}
    dissolved = meta.get("dissolved_at")
    return SubAgentResult(
        id=child.id, swarm_run_id=child.swarm_run_id, agent_template=child.subagent_type,
        task_description=child.system_prompt or "", status=child.status,
        authority_level=int(meta.get("authority_level") or 0), allowed_tools=list(meta.get("allowed_tools") or []),
        assigned_tasks=[t.id for t in tasks], completed_tasks=sum(1 for t in tasks if t.status == "completed"),
        failed_tasks=sum(1 for t in tasks if t.status == "failed"),
        tokens_used={child.model_name: int(child.tokens_used or 0)}, cost_estimate=float(child.cost or 0),
        output=child.result, timeout_seconds=int(meta.get("timeout_seconds") or 1800),
        spawned_at=child.created_at or child.started_at or datetime.now(timezone.utc),
        dissolved_at=datetime.fromisoformat(dissolved) if dissolved else None, metadata=meta)


class SubAgentManager:
    def __init__(self):
        from app.core.swarm.manager import SwarmManager

        self.swarms = SwarmManager()

    async def assign_task(self, db: AsyncSession, task: SubAgentTaskCreate, owner: UUID | str) -> UUID:
        """Run another task on an existing sub-agent, within its spawn-time ceilings."""
        from app.core.security import redact_text
        from app.core.swarm.manager import _run_child

        child = await self.swarms.owned_sub_agent(db, task.sub_agent_id, owner)
        if child.status in ("dissolved", "timed_out"):
            raise ValueError(f"The sub-agent is {child.status}; spawn a new one")
        if child.status in ("working", "spawning"):
            raise ValueError("The sub-agent is still working on its current task")
        swarm = (await db.execute(select(SwarmRun).where(SwarmRun.id == child.swarm_run_id))).scalar_one()
        if swarm.status not in ("initializing", "running"):
            raise ValueError(f"The swarm is {swarm.status}; no new tasks start")
        meta = child.meta_data or {}
        lead = (await db.execute(select(Agent).where(Agent.id == swarm.parent_agent_id))).scalar_one()
        agent = (await db.execute(select(Agent).where(Agent.id == UUID(meta["agent_id"])))).scalar_one()
        if not agent.is_active:
            raise ValueError("The sub-agent's agent record is inactive")
        now = datetime.now(timezone.utc)
        description = f"{task.task_title}\n\n{task.task_description}".strip()
        row = Task(id=uuid4(), workspace_id=swarm.workspace_id, assigned_agent_id=agent.id,
                   title=f"Swarm task: {task.task_title}"[:500], description=redact_text(description),
                   task_type="subagent_task", status="running", priority=5,
                   context={"swarm_run_id": str(swarm.id), "subagent_id": str(child.id),
                            "parent_agent_id": str(lead.id), "authority_level": meta.get("authority_level"),
                            "allowed_tools": meta.get("allowed_tools"), "input": task.input_data})
        db.add(row)
        child_task = SubAgentTask(subagent_id=child.id, task_description=redact_text(description),
                                  task_type=child.subagent_type, status="in_progress", started_at=now,
                                  meta_data={"parent_agent_id": str(lead.id), "task_id": str(row.id),
                                             "title": task.task_title, "input": task.input_data})
        db.add(child_task)
        child.status = "working"
        await db.flush()
        await _run_child(db, swarm, lead, child, agent, row, child_task, description, UUID(str(owner)),
                         int(meta.get("authority_level") or 0), list(meta.get("allowed_tools") or []))
        return child_task.id

    async def get_status(self, db: AsyncSession, sub_agent_id: UUID, owner: UUID | str) -> Dict[str, Any]:
        child = await self.swarms.owned_sub_agent(db, sub_agent_id, owner)
        tasks = await _tasks(db, child.id)
        current = next((t for t in reversed(tasks) if t.status == "in_progress"), None)
        started = child.started_at or child.created_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        end = child.completed_at or datetime.now(timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return {"sub_agent_id": str(child.id), "agent": child.subagent_type, "status": child.status,
                "success": child.success, "assigned_tasks": len(tasks),
                "completed_tasks": sum(1 for t in tasks if t.status == "completed"),
                "failed_tasks": sum(1 for t in tasks if t.status == "failed"),
                "current_task": str(current.id) if current else None,
                "tokens_used": int(child.tokens_used or 0), "cost_estimate": float(child.cost or 0),
                "uptime_seconds": int((end - started).total_seconds()) if started else 0,
                "error": child.error_message}

    async def collect_output(self, db: AsyncSession, sub_agent_id: UUID, owner: UUID | str) -> Dict[str, Any]:
        child = await self.swarms.owned_sub_agent(db, sub_agent_id, owner)
        tasks = await _tasks(db, child.id)
        outputs = [{"task_id": str(t.id), "status": t.status, "success": t.success,
                    "output_text": (t.result or {}).get("output_text"), "result_data": (t.result or {}).get("result_data"),
                    "error": (t.result or {}).get("error"),
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None} for t in tasks]
        done = [o for o in outputs if o["success"]]
        return {"sub_agent_id": str(child.id), "agent": child.subagent_type, "status": child.status,
                "completed_tasks": [o["task_id"] for o in done], "outputs": outputs,
                "summary": "\n\n".join(str(o["output_text"]) for o in done if o["output_text"])[:20000],
                "total_tokens": int(child.tokens_used or 0), "total_cost": float(child.cost or 0)}

    async def attach_logs_to_parent_task(self, db: AsyncSession, sub_agent_id: UUID, owner: UUID | str,
                                         parent_task_id: UUID) -> Dict[str, Any]:
        """Copy the sub-agent's log into its parent task's record and the audit trail."""
        child = await self.swarms.owned_sub_agent(db, sub_agent_id, owner)
        swarm = (await db.execute(select(SwarmRun).where(SwarmRun.id == child.swarm_run_id))).scalar_one()
        parent = (await db.execute(select(Task).where(Task.id == parent_task_id,
                                                      Task.workspace_id == swarm.workspace_id))).scalar_one_or_none()
        if parent is None:
            raise LookupError("Parent task not found in the swarm's workspace")
        logs = (await db.execute(select(SubAgentLog).where(SubAgentLog.subagent_id == child.id)
                                 .order_by(SubAgentLog.logged_at))).scalars().all()
        entries = [{"at": l.logged_at.isoformat() if l.logged_at else None, "level": l.log_level,
                    "category": l.log_category, "message": l.log_message[:2000]} for l in logs]
        context = dict(parent.context or {})
        attached = dict(context.get("subagent_logs") or {})
        attached[str(child.id)] = {"agent": child.subagent_type, "status": child.status, "entries": entries}
        context["subagent_logs"] = attached
        parent.context = context
        now = datetime.now(timezone.utc)
        db.add(AuditLog(id=uuid4(), workspace_id=swarm.workspace_id, actor_type="swarm",
                        action="subagent_logs_attached", action_category="swarm",
                        description=f"{len(entries)} log entries of sub-agent {child.subagent_type} attached to task",
                        target_type="task", target_id=str(parent.id),
                        after_state={"subagent_id": str(child.id), "parent_agent_id": (child.meta_data or {}).get("parent_agent_id"),
                                     "entries": len(entries)},
                        success=True, created_at=now, updated_at=now))
        await db.flush()
        return {"parent_task_id": str(parent.id), "sub_agent_id": str(child.id), "entries": len(entries)}

    async def time_out_stale(self, db: AsyncSession, now: Optional[datetime] = None) -> List[UUID]:
        """Sub-agents still marked working past their timeout (their run died) become timed_out."""
        now = now or datetime.now(timezone.utc)
        rows = (await db.execute(select(SubAgent).where(SubAgent.status.in_(("working", "spawning"))))).scalars().all()
        timed_out: List[UUID] = []
        for child in rows:
            started = child.started_at or child.created_at
            if started is None:
                continue
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            limit = int((child.meta_data or {}).get("timeout_seconds") or 1800)
            if now - started < timedelta(seconds=limit):
                continue
            child.status, child.success, child.completed_at = "timed_out", False, now
            child.error_message = f"No result within {limit}s; the run stopped."
            for task in await _tasks(db, child.id):
                if task.status == "in_progress":
                    task.status, task.success, task.completed_at = "failed", False, now
            db.add(SubAgentLog(subagent_id=child.id, log_level="error", log_category="timeout",
                               log_message=child.error_message,
                               context={"parent_agent_id": (child.meta_data or {}).get("parent_agent_id")}))
            timed_out.append(child.id)
        await db.flush()
        return timed_out

    async def list_sub_agents(self, db: AsyncSession, owner: UUID | str, swarm_run_id: Optional[UUID] = None,
                              status: Optional[str] = None, active_only: bool = False) -> List[SubAgentResult]:
        from app.models.workspace import Workspace

        query = (select(SubAgent).join(SwarmRun, SubAgent.swarm_run_id == SwarmRun.id)
                 .join(Workspace, SwarmRun.workspace_id == Workspace.id)
                 .where(Workspace.owner_id == UUID(str(owner))))
        if swarm_run_id is not None:
            query = query.where(SubAgent.swarm_run_id == swarm_run_id)
        if status is not None:
            query = query.where(SubAgent.status == status)
        elif active_only:
            query = query.where(SubAgent.status.in_(("spawning", "idle", "working")))
        rows = (await db.execute(query.order_by(SubAgent.created_at.desc()).limit(200))).scalars().all()
        return [await to_result(db, row) for row in rows]

    async def get_sub_agent(self, db: AsyncSession, sub_agent_id: UUID, owner: UUID | str) -> Optional[SubAgentResult]:
        try:
            return await to_result(db, await self.swarms.owned_sub_agent(db, sub_agent_id, owner))
        except LookupError:
            return None


_sub_agent_manager = SubAgentManager()


async def assign_sub_agent_task(db: AsyncSession, task: SubAgentTaskCreate, owner: UUID | str) -> UUID:
    return await _sub_agent_manager.assign_task(db, task, owner)


async def get_sub_agent_status(db: AsyncSession, sub_agent_id: UUID, owner: UUID | str) -> Dict[str, Any]:
    return await _sub_agent_manager.get_status(db, sub_agent_id, owner)


async def collect_sub_agent_output(db: AsyncSession, sub_agent_id: UUID, owner: UUID | str) -> Dict[str, Any]:
    return await _sub_agent_manager.collect_output(db, sub_agent_id, owner)
