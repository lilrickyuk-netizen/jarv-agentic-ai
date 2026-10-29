"""
JARV Backend - Swarm Manager

Manages swarm runs and sub-agent lifecycle.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from decimal import Decimal
from pydantic import BaseModel, Field
from enum import Enum
import logging
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.swarm import SubAgent, SubAgentLog, SubAgentTask, SwarmRun
from app.models.task import Task
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


class SwarmStatus(str, Enum):
    """Swarm run status"""
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SubAgentStatus(str, Enum):
    """Sub-agent status"""
    SPAWNING = "spawning"
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    DISSOLVED = "dissolved"


class SwarmRunCreate(BaseModel):
    """Schema for creating swarm run"""
    workspace_id: UUID
    lead_agent_id: UUID
    lead_agent_name: str
    parent_task_id: Optional[UUID] = None
    swarm_purpose: str
    max_sub_agents: int = Field(default=10, ge=1, le=100)
    timeout_seconds: int = Field(default=3600, ge=60, le=86400)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SwarmRunResult(BaseModel):
    """Swarm run result"""
    id: UUID
    workspace_id: UUID
    lead_agent_id: UUID
    lead_agent_name: str
    parent_task_id: Optional[UUID]
    swarm_purpose: str
    status: SwarmStatus
    max_sub_agents: int
    active_sub_agents: int
    completed_sub_agents: int
    failed_sub_agents: int
    total_tasks_completed: int
    total_tokens_used: Dict[str, int]
    total_cost: float
    timeout_seconds: int
    started_at: datetime
    completed_at: Optional[datetime]
    metadata: Dict[str, Any]


class SwarmManager:
    """
    Manages swarm runs and sub-agent lifecycle.

    Handles swarm creation, sub-agent spawning, and dissolution.
    """

    def __init__(self):
        """Initialize swarm manager"""
        self.logger = logging.getLogger("swarm.manager")

    async def create_swarm_run(
        self,
        swarm: SwarmRunCreate,
        *,
        db: AsyncSession,
        authenticated_user_id: UUID | str,
    ) -> UUID:
        """
        Create a swarm run owned by the authenticated user, within the limits.

        Args:
            swarm: Swarm creation data

        Returns:
            Swarm run ID
        """
        try:
            owner_id = UUID(str(authenticated_user_id))
            workspace = (await db.execute(
                select(Workspace).where(
                    Workspace.id == swarm.workspace_id,
                    Workspace.owner_id == owner_id,
                    Workspace.is_active.is_(True),
                )
            )).scalar_one_or_none()
            if workspace is None:
                raise PermissionError("Authenticated user does not own an active workspace")
            if not workspace.swarm_enabled:
                raise PermissionError("Swarm execution is disabled for this workspace")

            lead = (await db.execute(
                select(Agent).where(
                    Agent.id == swarm.lead_agent_id,
                    Agent.workspace_id == workspace.id,
                    Agent.is_active.is_(True),
                )
            )).scalar_one_or_none()
            if lead is None:
                raise ValueError("Lead agent must be active and belong to the workspace")
            if swarm.max_sub_agents > workspace.max_subagents:
                raise ValueError("Requested swarm size exceeds the workspace limit")
            if swarm.parent_task_id is not None:
                parent_task = (await db.execute(
                    select(Task.id).where(
                        Task.id == swarm.parent_task_id,
                        Task.workspace_id == workspace.id,
                    )
                )).scalar_one_or_none()
                if parent_task is None:
                    raise PermissionError("Parent task is outside the swarm workspace")

            # Validate swarm limits
            from app.core.swarm.limits import check_swarm_limits
            can_create, reason = await check_swarm_limits(
                db,
                swarm.workspace_id,
                swarm.max_sub_agents,
            )

            if not can_create:
                raise ValueError(f"Cannot create swarm: {reason}")

            db_swarm = SwarmRun(
                workspace_id=workspace.id,
                parent_agent_id=lead.id,
                swarm_type="delegated",
                objective=swarm.swarm_purpose,
                status=SwarmStatus.INITIALIZING.value,
                max_subagents=swarm.max_sub_agents,
                actual_subagents=0,
                coordination_strategy="parallel",
                started_at=datetime.now(timezone.utc),
                meta_data={
                    **swarm.metadata,
                    "authenticated_owner_id": str(owner_id),
                    "parent_task_id": str(swarm.parent_task_id) if swarm.parent_task_id else None,
                    "timeout_seconds": swarm.timeout_seconds,
                },
            )
            db.add(db_swarm)
            await db.flush()
            swarm_id = db_swarm.id

            self.logger.info(
                f"Created swarm run: {swarm.swarm_purpose}",
                extra={
                    "swarm_id": str(swarm_id),
                    "workspace_id": str(swarm.workspace_id),
                    "lead_agent": swarm.lead_agent_name,
                    "max_sub_agents": swarm.max_sub_agents,
                }
            )

            return swarm_id

        except Exception as e:
            self.logger.error(
                f"Failed to create swarm run: {e}",
                extra={"purpose": swarm.swarm_purpose},
                exc_info=True
            )
            raise

    async def spawn_sub_agent(
        self,
        swarm_run_id: UUID,
        agent_template: str,
        task_description: str,
        authority_level: int,
        allowed_tools: List[str],
        timeout_seconds: int = 1800,
        *,
        db: AsyncSession,
        authenticated_user_id: UUID | str,
    ) -> UUID:
        """
        Spawn sub-agent for swarm run.

        Persist and execute one scoped child through AgentRunner.

        Args:
            swarm_run_id: Swarm run ID
            agent_template: Agent template to use
            task_description: Sub-agent task
            authority_level: Authority level (cannot exceed lead agent)
            allowed_tools: Tools sub-agent can use
            timeout_seconds: Execution timeout

        Returns:
            Sub-agent ID
        """
        try:
            owner_id = UUID(str(authenticated_user_id))
            swarm = (await db.execute(
                select(SwarmRun).where(SwarmRun.id == swarm_run_id)
            )).scalar_one_or_none()
            if swarm is None:
                raise ValueError("Swarm run not found")
            workspace = (await db.execute(
                select(Workspace).where(
                    Workspace.id == swarm.workspace_id,
                    Workspace.owner_id == owner_id,
                    Workspace.is_active.is_(True),
                )
            )).scalar_one_or_none()
            if workspace is None:
                raise PermissionError("Authenticated user does not own the swarm workspace")
            if swarm.status not in (SwarmStatus.INITIALIZING.value, SwarmStatus.RUNNING.value):
                raise ValueError(f"Sub-agents can only be added to an active swarm (this one is {swarm.status})")
            from app.core.swarm.limits import SwarmLimitManager
            from app.core.swarm.tracking import SwarmTracker

            limits = await SwarmLimitManager().effective_limits(db, swarm.workspace_id)
            spent = (await SwarmTracker().calculate_swarm_cost(db, swarm.id))["totals"]["cost"]
            if spent >= float(limits["max_cost_per_swarm"]):
                raise ValueError(f"Swarm budget reached: ${spent:.4f} of ${limits['max_cost_per_swarm']:.2f}")

            lead = (await db.execute(
                select(Agent).where(
                    Agent.id == swarm.parent_agent_id,
                    Agent.workspace_id == swarm.workspace_id,
                    Agent.is_active.is_(True),
                )
            )).scalar_one_or_none()
            if lead is None:
                raise ValueError("Swarm lead agent is unavailable")
            if authority_level < 0 or authority_level > lead.authority_level:
                raise PermissionError("Sub-agent authority exceeds the lead agent")
            requested_tools = set(allowed_tools)
            if not requested_tools.issubset(set(lead.allowed_tools or [])):
                raise PermissionError("Sub-agent tools exceed the lead agent's allowed tools")

            from app.core.agents.registry import get_registry

            agent_registry = get_registry()
            if not agent_registry.is_implemented(agent_template):
                raise ValueError("Sub-agent template is not a registered implemented agent")
            agent_meta = agent_registry.get_metadata(agent_template)
            if agent_meta is None:
                raise ValueError("Sub-agent template metadata is unavailable")
            if authority_level < agent_meta.required_authority_level:
                raise PermissionError("Sub-agent authority is below the agent's registered minimum")
            if not requested_tools.issubset(set(agent_meta.default_tools or [])):
                raise PermissionError("Sub-agent requested tools are not declared by its agent")

            active_count = (await db.execute(
                select(func.count()).select_from(SubAgent).where(
                    SubAgent.swarm_run_id == swarm.id,
                    SubAgent.status.notin_((
                        SubAgentStatus.COMPLETED.value,
                        SubAgentStatus.FAILED.value,
                        SubAgentStatus.TIMED_OUT.value,
                        SubAgentStatus.DISSOLVED.value,
                    )),
                )
            )).scalar_one()
            if active_count >= swarm.max_subagents:
                raise ValueError("Swarm sub-agent capacity has been reached")

            from app.core.security import redact_text

            now = datetime.now(timezone.utc)
            safe_description = redact_text(task_description)

            child = SubAgent(
                swarm_run_id=swarm.id,
                subagent_name=agent_template[:255],
                subagent_type=agent_template[:50],
                role="scoped_subagent",
                specialization=agent_template[:255],
                model_provider=lead.model_provider,
                model_name=lead.model_name,
                system_prompt=safe_description,
                status=SubAgentStatus.WORKING.value,
                meta_data={
                    "parent_agent_id": str(lead.id),
                    "workspace_scope": "parent_swarm",
                    "authority_level": int(authority_level),
                    "allowed_tools": sorted(requested_tools),
                    "timeout_seconds": int(timeout_seconds),
                },
            )
            db.add(child)
            await db.flush()

            child_agent = Agent(
                id=uuid4(),
                name=agent_template,
                agent_type=agent_template,
                workspace_id=workspace.id,
                is_active=True,
                is_subagent=True,
                parent_agent_id=lead.id,
                config={
                    "swarm_run_id": str(swarm.id),
                    "subagent_id": str(child.id),
                    "workspace_scope": "parent_swarm",
                },
                system_prompt=safe_description,
                model_provider=lead.model_provider,
                model_name=lead.model_name,
                authority_level=int(authority_level),
                allowed_tools=sorted(requested_tools),
                blocked_tools=[],
                current_state="working",
            )
            db.add(child_agent)
            await db.flush()

            task_row = Task(
                id=uuid4(),
                workspace_id=workspace.id,
                assigned_agent_id=child_agent.id,
                title=f"Swarm task for {agent_template}"[:500],
                description=safe_description,
                task_type="subagent_task",
                status="running",
                priority=5,
                context={
                    "swarm_run_id": str(swarm.id),
                    "subagent_id": str(child.id),
                    "parent_agent_id": str(lead.id),
                    "authority_level": int(authority_level),
                    "allowed_tools": sorted(requested_tools),
                },
            )
            db.add(task_row)
            child.meta_data = {
                **(child.meta_data or {}),
                "agent_id": str(child_agent.id),
            }
            child_task = SubAgentTask(
                subagent_id=child.id,
                task_description=safe_description,
                task_type=agent_template,
                status="in_progress",
                started_at=now,
                meta_data={"parent_agent_id": str(lead.id), "task_id": str(task_row.id)},
            )
            db.add(child_task)
            child.meta_data = {**(child.meta_data or {}), "task_id": str(task_row.id)}
            swarm.actual_subagents = active_count + 1
            swarm.status = SwarmStatus.RUNNING.value
            await db.flush()

            await _run_child(db, swarm, lead, child, child_agent, task_row, child_task, task_description,
                             owner_id, int(authority_level), sorted(requested_tools))
            sub_agent_id = child.id

            self.logger.info(
                f"Spawned sub-agent: {agent_template}",
                extra={
                    "sub_agent_id": str(sub_agent_id),
                    "swarm_run_id": str(swarm_run_id),
                    "authority_level": authority_level,
                }
            )

            return sub_agent_id

        except Exception as e:
            self.logger.error(
                f"Failed to spawn sub-agent: {e}",
                extra={"swarm_run_id": str(swarm_run_id)},
                exc_info=True
            )
            raise

    # ----- lifecycle (all owner-scoped) -----------------------------------------------

    async def owned_swarm(self, db: AsyncSession, swarm_run_id: UUID | str, owner: UUID | str) -> SwarmRun:
        swarm = (await db.execute(
            select(SwarmRun).join(Workspace, SwarmRun.workspace_id == Workspace.id)
            .where(SwarmRun.id == UUID(str(swarm_run_id)), Workspace.owner_id == UUID(str(owner)))
        )).scalar_one_or_none()
        if swarm is None:
            raise LookupError("Swarm run not found")
        return swarm

    async def owned_sub_agent(self, db: AsyncSession, sub_agent_id: UUID | str, owner: UUID | str) -> SubAgent:
        child = (await db.execute(
            select(SubAgent).join(SwarmRun, SubAgent.swarm_run_id == SwarmRun.id)
            .join(Workspace, SwarmRun.workspace_id == Workspace.id)
            .where(SubAgent.id == UUID(str(sub_agent_id)), Workspace.owner_id == UUID(str(owner)))
        )).scalar_one_or_none()
        if child is None:
            raise LookupError("Sub-agent not found")
        return child

    async def dissolve_sub_agent(self, db: AsyncSession, sub_agent_id: UUID, owner: UUID | str,
                                 reason: str = "completed") -> SubAgent:
        """Dissolve one sub-agent: its agent record is deactivated, its outcome kept."""
        child = await self.owned_sub_agent(db, sub_agent_id, owner)
        if child.status == SubAgentStatus.DISSOLVED.value:
            return child
        now = datetime.now(timezone.utc)
        previous = child.status
        child.status = SubAgentStatus.DISSOLVED.value
        child.completed_at = child.completed_at or now
        if child.success is None:
            child.success = False
            child.error_message = child.error_message or f"dissolved before finishing: {reason}"
        child.meta_data = {**(child.meta_data or {}), "dissolved_at": now.isoformat(), "dissolve_reason": reason,
                           "status_before_dissolve": previous}
        agent_id = (child.meta_data or {}).get("agent_id")
        if agent_id:
            agent = (await db.execute(select(Agent).where(Agent.id == UUID(agent_id)))).scalar_one_or_none()
            if agent is not None:
                agent.is_active = False
                agent.current_state = "dissolved"
        db.add(SubAgentLog(subagent_id=child.id, log_level="info", log_category="dissolve",
                           log_message=f"Sub-agent dissolved ({reason}); status was {previous}.",
                           context={"parent_agent_id": (child.meta_data or {}).get("parent_agent_id")}))
        await db.flush()
        return child

    async def pause_swarm(self, db: AsyncSession, swarm_run_id: UUID, owner: UUID | str) -> SwarmRun:
        """No new sub-agents or tasks start while paused; finished work is kept."""
        swarm = await self.owned_swarm(db, swarm_run_id, owner)
        if swarm.status not in (SwarmStatus.INITIALIZING.value, SwarmStatus.RUNNING.value):
            raise ValueError(f"Only an active swarm can be paused (this one is {swarm.status})")
        swarm.meta_data = {**(swarm.meta_data or {}), "paused_at": datetime.now(timezone.utc).isoformat(),
                           "status_before_pause": swarm.status}
        swarm.status = SwarmStatus.PAUSED.value
        await db.flush()
        return swarm

    async def resume_swarm(self, db: AsyncSession, swarm_run_id: UUID, owner: UUID | str) -> SwarmRun:
        swarm = await self.owned_swarm(db, swarm_run_id, owner)
        if swarm.status != SwarmStatus.PAUSED.value:
            raise ValueError(f"Only a paused swarm can be resumed (this one is {swarm.status})")
        swarm.status = (swarm.meta_data or {}).get("status_before_pause") or SwarmStatus.RUNNING.value
        swarm.meta_data = {**(swarm.meta_data or {}), "resumed_at": datetime.now(timezone.utc).isoformat()}
        await db.flush()
        return swarm

    async def cancel_swarm(self, db: AsyncSession, swarm_run_id: UUID, owner: UUID | str, reason: str) -> SwarmRun:
        """Cancel the swarm, dissolve every unfinished sub-agent, and record the final cost."""
        from app.core.swarm.tracking import SwarmTracker

        swarm = await self.owned_swarm(db, swarm_run_id, owner)
        if swarm.status in (SwarmStatus.COMPLETED.value, SwarmStatus.CANCELLED.value, SwarmStatus.FAILED.value):
            raise ValueError(f"The swarm has already finished ({swarm.status})")
        for child in (await db.execute(select(SubAgent).where(SubAgent.swarm_run_id == swarm.id))).scalars().all():
            if child.status not in ("completed", "failed", "timed_out", "dissolved"):
                await self.dissolve_sub_agent(db, child.id, owner, reason=f"swarm cancelled: {reason}")
        await self._finish(db, swarm, SwarmStatus.CANCELLED, error=f"cancelled: {reason}")
        await SwarmTracker().record_final_cost(db, swarm)
        return swarm

    async def complete_swarm(self, db: AsyncSession, swarm_run_id: UUID, owner: UUID | str) -> SwarmRun:
        """Close a swarm whose sub-agents have all finished, dissolving them and recording cost."""
        from app.core.swarm.tracking import SwarmTracker

        swarm = await self.owned_swarm(db, swarm_run_id, owner)
        children = (await db.execute(select(SubAgent).where(SubAgent.swarm_run_id == swarm.id))).scalars().all()
        working = [c for c in children if c.status in ("spawning", "idle", "working")]
        if working:
            raise ValueError(f"{len(working)} sub-agent(s) are still working")
        for child in children:
            if child.status != SubAgentStatus.DISSOLVED.value:
                await self.dissolve_sub_agent(db, child.id, owner, reason="swarm completed")
        succeeded = any(c.success for c in children)
        swarm.result = {"sub_agents": len(children), "succeeded": sum(1 for c in children if c.success)}
        await self._finish(db, swarm, SwarmStatus.COMPLETED if succeeded else SwarmStatus.FAILED,
                           error=None if succeeded else "no sub-agent succeeded")
        await SwarmTracker().record_final_cost(db, swarm)
        return swarm

    async def _finish(self, db: AsyncSession, swarm: SwarmRun, status: SwarmStatus, error: Optional[str]) -> None:
        now = datetime.now(timezone.utc)
        swarm.status = status.value
        swarm.completed_at = now
        started = swarm.started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        swarm.duration_seconds = int((now - started).total_seconds()) if started else None
        swarm.success = status == SwarmStatus.COMPLETED
        swarm.error_message = error
        await db.flush()

    async def get_swarm_run(self, db: AsyncSession, swarm_run_id: UUID, owner: UUID | str) -> Optional[SwarmRunResult]:
        try:
            swarm = await self.owned_swarm(db, swarm_run_id, owner)
        except LookupError:
            return None
        return await _result(db, swarm)

    async def list_swarms(self, db: AsyncSession, owner: UUID | str, workspace_id: Optional[UUID] = None,
                          status: Optional[str] = None, active_only: bool = False,
                          limit: int = 50) -> List[SwarmRunResult]:
        query = (select(SwarmRun).join(Workspace, SwarmRun.workspace_id == Workspace.id)
                 .where(Workspace.owner_id == UUID(str(owner))))
        if workspace_id is not None:
            query = query.where(SwarmRun.workspace_id == workspace_id)
        if status is not None:
            query = query.where(SwarmRun.status == status)
        elif active_only:
            query = query.where(SwarmRun.status.in_(("initializing", "running", "paused")))
        rows = (await db.execute(query.order_by(SwarmRun.created_at.desc()).limit(limit))).scalars().all()
        return [await _result(db, row) for row in rows]

    async def list_active_swarms(self, db: AsyncSession, owner: UUID | str,
                                 workspace_id: Optional[UUID] = None) -> List[SwarmRunResult]:
        return await self.list_swarms(db, owner, workspace_id, active_only=True)

    async def get_swarm_stats(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        from app.core.swarm.tracking import SwarmTracker

        swarms = (await db.execute(select(SwarmRun).where(SwarmRun.workspace_id == workspace_id))).scalars().all()
        children = (await db.execute(select(SubAgent).join(SwarmRun, SubAgent.swarm_run_id == SwarmRun.id)
                                     .where(SwarmRun.workspace_id == workspace_id))).scalars().all()
        tracker = SwarmTracker()
        cost = 0.0
        for swarm in swarms:
            cost += (await tracker.calculate_swarm_cost(db, swarm.id))["totals"]["cost"]
        return {
            "total_swarms": len(swarms),
            "active_swarms": sum(1 for s in swarms if s.status in ("initializing", "running", "paused")),
            "total_sub_agents_spawned": len(children),
            "active_sub_agents": sum(1 for c in children if c.status in ("spawning", "idle", "working")),
            "succeeded_sub_agents": sum(1 for c in children if c.success),
            "total_tokens_used": sum(int(c.tokens_used or 0) for c in children),
            "total_cost": round(cost, 6), "cost_estimated": True,
        }


async def _active_children(db: AsyncSession, swarm_run_id: UUID) -> int:
    return int((await db.execute(select(func.count()).select_from(SubAgent).where(
        SubAgent.swarm_run_id == swarm_run_id,
        SubAgent.status.notin_(("completed", "failed", "timed_out", "dissolved"))))).scalar_one())


async def _result(db: AsyncSession, swarm: SwarmRun) -> SwarmRunResult:
    from app.core.swarm.tracking import SwarmTracker

    children = (await db.execute(select(SubAgent).where(SubAgent.swarm_run_id == swarm.id))).scalars().all()
    lead = (await db.execute(select(Agent).where(Agent.id == swarm.parent_agent_id))).scalar_one_or_none()
    tokens: Dict[str, int] = {}
    for child in children:
        tokens[child.model_name] = tokens.get(child.model_name, 0) + int(child.tokens_used or 0)
    meta = swarm.meta_data or {}
    parent_task = meta.get("parent_task_id")
    return SwarmRunResult(
        id=swarm.id, workspace_id=swarm.workspace_id, lead_agent_id=swarm.parent_agent_id,
        lead_agent_name=lead.name if lead else "", parent_task_id=UUID(parent_task) if parent_task else None,
        swarm_purpose=swarm.objective, status=SwarmStatus(swarm.status) if swarm.status in SwarmStatus._value2member_map_
        else SwarmStatus.RUNNING,
        max_sub_agents=swarm.max_subagents,
        active_sub_agents=sum(1 for c in children if c.status in ("spawning", "idle", "working")),
        completed_sub_agents=sum(1 for c in children if c.success),
        failed_sub_agents=sum(1 for c in children if c.success is False),
        total_tasks_completed=int((await db.execute(select(func.count()).select_from(SubAgentTask)
                                                    .join(SubAgent, SubAgentTask.subagent_id == SubAgent.id)
                                                    .where(SubAgent.swarm_run_id == swarm.id,
                                                           SubAgentTask.status == "completed"))).scalar_one()),
        total_tokens_used=tokens,
        total_cost=(await SwarmTracker().calculate_swarm_cost(db, swarm.id))["totals"]["cost"],
        timeout_seconds=int(meta.get("timeout_seconds") or 3600),
        started_at=swarm.started_at or swarm.created_at, completed_at=swarm.completed_at, metadata=meta)


async def _run_child(db: AsyncSession, swarm: SwarmRun, lead: Agent, child: SubAgent, child_agent: Agent,
                     task_row: Task, child_task: SubAgentTask, task_description: str, owner_id: UUID,
                     authority_level: int, tools: List[str]) -> bool:
    """Run one task on a sub-agent through the real AgentRunner, inside the
    lead's authority and tool ceilings, and record the verified outcome."""
    from app.core.agents.runner import AgentRunner
    from app.core.security import redact_secrets, redact_text
    from app.core.swarm.tracking import estimate_cost

    now = datetime.now(timezone.utc)
    execution = await AgentRunner(model=lead.model_name).run_agent(
        agent_name=child.subagent_type,
        task=task_description,
        workspace_id=swarm.workspace_id,
        user_id=owner_id,
        db=db,
        agent_id=child_agent.id,
        task_id=task_row.id,
        session_id=swarm.session_id,
        authority_ceiling=authority_level,
        allowed_tools_ceiling=tools,
        parent_agent_id=lead.id,
    )
    success = bool(execution.get("success") and execution.get("output_text"))
    completed_at = datetime.now(timezone.utc)
    tokens = int(execution.get("tokens") or 0)
    outcome = redact_secrets({
        "agent": child.subagent_type,
        "success": success,
        "output_text": execution.get("output_text"),
        "result_data": execution.get("result_data") or {},
        "error": execution.get("error"),
        "tokens": tokens,
    })
    child.status = SubAgentStatus.COMPLETED.value if success else SubAgentStatus.FAILED.value
    child.started_at = child.started_at or now
    child.completed_at = completed_at
    child.success = success
    child.tokens_used = int(child.tokens_used or 0) + tokens
    child.api_calls = int(child.api_calls or 0) + 1
    child.cost = Decimal(str(round(estimate_cost(child.model_name, child.tokens_used), 6)))
    child.result = outcome
    child.error_message = None if success else redact_text(str(execution.get("error") or "no output"))[:2000]
    child.meta_data = {**(child.meta_data or {}), "verified_output": success}
    child_agent.current_state = "completed" if success else "failed"
    child_agent.last_active_at = completed_at
    child_agent.total_executions += 1
    child_agent.successful_executions += int(success)
    child_agent.failed_executions += int(not success)
    child_agent.total_tokens_used += tokens
    task_row.status = "completed" if success else "failed"
    task_row.completed_at = completed_at
    task_row.result = {"verified": success, "subagent_id": str(child.id)}
    task_row.error_message = redact_text(str(execution.get("error") or "")) or None
    child_task.status = "completed" if success else "failed"
    child_task.completed_at = completed_at
    child_task.success = success
    child_task.result = outcome
    child_task.duration_seconds = int((completed_at - (child_task.started_at or now)).total_seconds())
    db.add(SubAgentLog(
        subagent_id=child.id,
        log_level="info" if success else "error",
        log_message=redact_text(
            f"Child execution {'completed' if success else 'failed'}: "
            f"{execution.get('error') or execution.get('output_text') or 'no output'}"),
        log_category="execution_result",
        context={"parent_agent_id": str(lead.id), "task_id": str(task_row.id)},
    ))
    await db.flush()
    return success


# Global swarm manager
_swarm_manager = SwarmManager()


async def create_swarm_run(
    swarm: SwarmRunCreate, *, db: AsyncSession, authenticated_user_id: UUID | str,
) -> UUID:
    """Global function to create swarm run"""
    return await _swarm_manager.create_swarm_run(
        swarm, db=db, authenticated_user_id=authenticated_user_id)


async def spawn_sub_agent(
    swarm_run_id: UUID,
    agent_template: str,
    task_description: str,
    authority_level: int,
    allowed_tools: List[str],
    *,
    db: AsyncSession,
    authenticated_user_id: UUID | str,
    **kwargs
) -> UUID:
    """Global function to spawn sub-agent"""
    return await _swarm_manager.spawn_sub_agent(
        swarm_run_id,
        agent_template,
        task_description,
        authority_level,
        allowed_tools,
        db=db,
        authenticated_user_id=authenticated_user_id,
        **kwargs
    )


async def dissolve_sub_agent(db: AsyncSession, sub_agent_id: UUID, owner: UUID | str,
                             reason: str = "completed") -> SubAgent:
    """Global function to dissolve a sub-agent"""
    return await _swarm_manager.dissolve_sub_agent(db, sub_agent_id, owner, reason)
