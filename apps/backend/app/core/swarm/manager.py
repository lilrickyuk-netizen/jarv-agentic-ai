"""
JARV Backend - Swarm Manager

Manages swarm runs and sub-agent lifecycle.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum
import logging

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
            # Validate swarm limits
            from app.core.swarm.limits import check_swarm_limits
            can_create, reason = await check_swarm_limits(
                swarm.workspace_id,
                swarm.max_sub_agents,
            )

            if not can_create:
                raise ValueError(f"Cannot create swarm: {reason}")

            # In production: Insert into database
            # from app.models.swarm import SwarmRun as DBSwarmRun
            # from app.core.database import get_db
            # async with get_db() as db:
            #     db_swarm = DBSwarmRun(
            #         workspace_id=swarm.workspace_id,
            #         lead_agent_id=swarm.lead_agent_id,
            #         lead_agent_name=swarm.lead_agent_name,
            #         parent_task_id=swarm.parent_task_id,
            #         swarm_purpose=swarm.swarm_purpose,
            #         status=SwarmStatus.INITIALIZING,
            #         max_sub_agents=swarm.max_sub_agents,
            #         timeout_seconds=swarm.timeout_seconds,
            #         started_at=datetime.utcnow(),
            #         metadata=swarm.metadata,
            #     )
            #     db.add(db_swarm)
            #     await db.commit()
            #     swarm_id = db_swarm.id

            swarm_id = uuid4()

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
    ) -> UUID:
        """
        Spawn sub-agent for swarm run.

        In production: Create SubAgent record and dispatch to worker.

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
            # In production:
            # 1. Load swarm run
            # 2. Verify swarm is active
            # 3. Check sub-agent count < max_sub_agents
            # 4. Verify authority_level <= lead_agent_authority
            # 5. Create SubAgent record
            # 6. Dispatch to worker queue
            # 7. Update swarm active_sub_agents count
            # 8. Return sub-agent ID

            from app.core.swarm.sub_agent import SubAgentManager
            sub_agent_manager = SubAgentManager()

            from app.core.swarm.sub_agent import SubAgentCreate
            sub_agent_data = SubAgentCreate(
                swarm_run_id=swarm_run_id,
                agent_template=agent_template,
                task_description=task_description,
                authority_level=authority_level,
                allowed_tools=allowed_tools,
                timeout_seconds=timeout_seconds,
            )

            sub_agent_id = await sub_agent_manager.create_sub_agent(sub_agent_data)

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


async def create_swarm_run(swarm: SwarmRunCreate) -> UUID:
    """Global function to create swarm run"""
    return await _swarm_manager.create_swarm_run(swarm)


async def spawn_sub_agent(
    swarm_run_id: UUID,
    agent_template: str,
    task_description: str,
    authority_level: int,
    allowed_tools: List[str],
    **kwargs
) -> UUID:
    """Global function to spawn sub-agent"""
    return await _swarm_manager.spawn_sub_agent(
        swarm_run_id,
        agent_template,
        task_description,
        authority_level,
        allowed_tools,
        **kwargs
    )


async def dissolve_sub_agent(sub_agent_id: UUID, reason: str = "completed") -> bool:
    """Global function to dissolve sub-agent"""
    return await _swarm_manager.dissolve_sub_agent(sub_agent_id, reason)
