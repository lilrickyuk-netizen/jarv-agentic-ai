"""
JARV Backend - Swarm Manager

Manages swarm runs and sub-agent lifecycle.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
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
        Create swarm run.

        In production: Insert into SwarmRun table.

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
                raise ValueError("Sub-agents can only be added to an active swarm")

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

            from app.core.security import redact_secrets, redact_text
            from app.core.agents.runner import AgentRunner

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

            execution = await AgentRunner(model=lead.model_name).run_agent(
                agent_name=agent_template,
                task=task_description,
                workspace_id=workspace.id,
                user_id=owner_id,
                db=db,
                agent_id=child_agent.id,
                task_id=task_row.id,
                session_id=swarm.session_id,
                authority_ceiling=int(authority_level),
                allowed_tools_ceiling=sorted(requested_tools),
                parent_agent_id=lead.id,
            )
            success = bool(execution.get("success") and execution.get("output_text"))
            completed_at = datetime.now(timezone.utc)
            outcome = redact_secrets({
                "agent": agent_template,
                "success": success,
                "output_text": execution.get("output_text"),
                "result_data": execution.get("result_data") or {},
                "error": execution.get("error"),
                "tokens": int(execution.get("tokens") or 0),
            })
            child.status = (SubAgentStatus.COMPLETED.value if success
                            else SubAgentStatus.FAILED.value)
            child.started_at = now
            child.completed_at = completed_at
            child.success = success
            child.tokens_used = int(execution.get("tokens") or 0)
            child.result = outcome
            child.meta_data = {**(child.meta_data or {}), "verified_output": success}
            child_agent.current_state = "completed" if success else "failed"
            child_agent.last_active_at = completed_at
            child_agent.total_executions += 1
            child_agent.successful_executions += int(success)
            child_agent.failed_executions += int(not success)
            child_agent.total_tokens_used += int(execution.get("tokens") or 0)
            task_row.status = "completed" if success else "failed"
            task_row.completed_at = completed_at
            task_row.result = {"verified": success, "subagent_id": str(child.id)}
            task_row.error_message = redact_text(str(execution.get("error") or "")) or None
            child_task.status = "completed" if success else "failed"
            child_task.completed_at = completed_at
            child_task.success = success
            child_task.result = outcome
            db.add_all([
                SubAgentLog(
                    subagent_id=child.id,
                    log_level="info" if success else "error",
                    log_message=redact_text(
                        f"Child execution {'completed' if success else 'failed'}: "
                        f"{execution.get('error') or execution.get('output_text') or 'no output'}"),
                    log_category="execution_result",
                    context={"parent_agent_id": str(lead.id), "task_id": str(task_row.id)},
                ),
            ])
            await db.flush()
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

    async def dissolve_sub_agent(
        self,
        sub_agent_id: UUID,
        reason: str = "completed",
    ) -> bool:
        """
        Dissolve sub-agent.

        In production: Mark sub-agent as dissolved and cleanup.

        Args:
            sub_agent_id: Sub-agent ID
            reason: Dissolution reason

        Returns:
            Success status
        """
        try:
            # In production:
            # 1. Load sub-agent
            # 2. Collect final output
            # 3. Update status to DISSOLVED
            # 4. Record dissolution reason and timestamp
            # 5. Decrement swarm active_sub_agents count
            # 6. Archive logs
            # 7. Cleanup resources

            self.logger.info(
                f"Dissolved sub-agent: {reason}",
                extra={"sub_agent_id": str(sub_agent_id)}
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to dissolve sub-agent: {e}",
                extra={"sub_agent_id": str(sub_agent_id)},
                exc_info=True
            )
            return False

    async def pause_swarm(
        self,
        swarm_run_id: UUID,
    ) -> bool:
        """
        Pause swarm execution.

        In production: Pause all active sub-agents.

        Args:
            swarm_run_id: Swarm run ID

        Returns:
            Success status
        """
        try:
            # In production:
            # 1. Load swarm run
            # 2. Update status to PAUSED
            # 3. Send pause signal to all active sub-agents
            # 4. Wait for sub-agents to acknowledge pause
            # 5. Record pause timestamp

            self.logger.info(
                f"Paused swarm",
                extra={"swarm_run_id": str(swarm_run_id)}
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to pause swarm: {e}",
                extra={"swarm_run_id": str(swarm_run_id)},
                exc_info=True
            )
            return False

    async def resume_swarm(
        self,
        swarm_run_id: UUID,
    ) -> bool:
        """
        Resume paused swarm.

        In production: Resume all paused sub-agents.

        Args:
            swarm_run_id: Swarm run ID

        Returns:
            Success status
        """
        try:
            # In production:
            # 1. Load swarm run
            # 2. Verify status is PAUSED
            # 3. Update status to RUNNING
            # 4. Send resume signal to all paused sub-agents
            # 5. Record resume timestamp

            self.logger.info(
                f"Resumed swarm",
                extra={"swarm_run_id": str(swarm_run_id)}
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to resume swarm: {e}",
                extra={"swarm_run_id": str(swarm_run_id)},
                exc_info=True
            )
            return False

    async def cancel_swarm(
        self,
        swarm_run_id: UUID,
        reason: str,
    ) -> bool:
        """
        Cancel swarm with boundary enforcement.

        In production: Cancel swarm and dissolve all sub-agents.

        Args:
            swarm_run_id: Swarm run ID
            reason: Cancellation reason

        Returns:
            Success status
        """
        try:
            # In production:
            # 1. Load swarm run
            # 2. Update status to CANCELLED
            # 3. Send cancel signal to all active sub-agents
            # 4. Dissolve all sub-agents
            # 5. Record cancellation reason and timestamp
            # 6. Create boundary violation if needed
            # 7. Notify lead agent

            self.logger.info(
                f"Cancelled swarm: {reason}",
                extra={"swarm_run_id": str(swarm_run_id)}
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to cancel swarm: {e}",
                extra={"swarm_run_id": str(swarm_run_id)},
                exc_info=True
            )
            return False

    async def get_swarm_run(
        self,
        swarm_run_id: UUID,
    ) -> Optional[SwarmRunResult]:
        """Get swarm run by ID"""
        # In production: Query database
        return None

    async def list_active_swarms(
        self,
        workspace_id: Optional[UUID] = None,
    ) -> List[SwarmRunResult]:
        """List active swarm runs"""
        # In production: Query active swarms
        return []

    async def get_swarm_stats(
        self,
        workspace_id: UUID,
    ) -> Dict[str, Any]:
        """Get swarm statistics"""
        return {
            "total_swarms": 0,
            "active_swarms": 0,
            "total_sub_agents_spawned": 0,
            "active_sub_agents": 0,
            "total_tokens_used": 0,
            "total_cost": 0.0,
        }


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


async def dissolve_sub_agent(sub_agent_id: UUID, reason: str = "completed") -> bool:
    """Global function to dissolve sub-agent"""
    return await _swarm_manager.dissolve_sub_agent(sub_agent_id, reason)
