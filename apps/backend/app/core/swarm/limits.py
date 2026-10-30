"""
JARV Backend - Swarm limits

Limits come from three places, the tightest winning:
- global defaults (settings: SWARM_MAX_CONCURRENT, SWARM_MAX_SUBAGENTS_PER_SWARM,
  SWARM_MAX_TOTAL_SUBAGENTS capped by MAX_SUBAGENTS_GLOBAL, SWARM_MAX_COST_PER_SWARM);
- the workspace's own ``max_subagents``;
- the workspace's active SwarmLimitPolicy row, when one exists.

Sub-agents never spawn sub-agents (depth 1), whatever the policy says.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.swarm import SubAgent, SwarmLimitPolicy as LimitPolicyRow, SwarmRun
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

ACTIVE_SWARM_STATES = ("initializing", "running", "paused")
FINISHED_SUBAGENT_STATES = ("completed", "failed", "timed_out", "dissolved")
MAX_DEPTH = 1


class LimitScope(str, Enum):
    GLOBAL = "global"
    WORKSPACE = "workspace"


class SwarmLimitPolicy(BaseModel):
    id: UUID
    scope: LimitScope
    scope_id: Optional[UUID]
    max_concurrent_swarms: int
    max_sub_agents_per_swarm: int
    max_total_sub_agents: int
    max_sub_agent_depth: int = MAX_DEPTH
    max_cost_per_swarm: Optional[float] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def global_limits() -> Dict[str, Any]:
    return {
        "max_concurrent_swarms": int(getattr(settings, "SWARM_MAX_CONCURRENT", 5)),
        "max_sub_agents_per_swarm": int(getattr(settings, "SWARM_MAX_SUBAGENTS_PER_SWARM", 10)),
        "max_total_sub_agents": min(int(getattr(settings, "SWARM_MAX_TOTAL_SUBAGENTS", 50)),
                                    int(getattr(settings, "MAX_SUBAGENTS_GLOBAL", 50))),
        "max_cost_per_swarm": float(getattr(settings, "SWARM_MAX_COST_PER_SWARM", 5.0)),
        "max_sub_agent_depth": MAX_DEPTH,
    }


def _policy_model(row: LimitPolicyRow) -> SwarmLimitPolicy:
    meta = row.meta_data or {}
    return SwarmLimitPolicy(
        id=row.id, scope=LimitScope.WORKSPACE, scope_id=row.workspace_id,
        max_concurrent_swarms=row.max_concurrent_swarms, max_sub_agents_per_swarm=row.max_subagents,
        max_total_sub_agents=int(meta.get("max_total_sub_agents") or row.max_subagents),
        max_cost_per_swarm=float(row.max_cost_per_swarm) if row.max_cost_per_swarm is not None else None,
        is_active=row.is_active, created_at=row.created_at, updated_at=row.updated_at)


class SwarmLimitManager:
    """Reads, enforces, and sets swarm limits in the database."""

    def __init__(self):
        self.default_limits = global_limits()

    async def policy_row(self, db: AsyncSession, workspace_id: UUID) -> Optional[LimitPolicyRow]:
        return (await db.execute(
            select(LimitPolicyRow).where(LimitPolicyRow.workspace_id == workspace_id,
                                         LimitPolicyRow.is_active.is_(True))
            .order_by(LimitPolicyRow.updated_at.desc()).limit(1))).scalar_one_or_none()

    async def effective_limits(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        limits = global_limits()
        workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
        if workspace is not None and workspace.max_subagents:
            limits["max_sub_agents_per_swarm"] = min(limits["max_sub_agents_per_swarm"], int(workspace.max_subagents))
        row = await self.policy_row(db, workspace_id)
        if row is not None:
            policy = _policy_model(row)
            limits["max_concurrent_swarms"] = min(limits["max_concurrent_swarms"], policy.max_concurrent_swarms)
            limits["max_sub_agents_per_swarm"] = min(limits["max_sub_agents_per_swarm"], policy.max_sub_agents_per_swarm)
            limits["max_total_sub_agents"] = min(limits["max_total_sub_agents"], policy.max_total_sub_agents)
            if policy.max_cost_per_swarm is not None:
                limits["max_cost_per_swarm"] = min(limits["max_cost_per_swarm"], policy.max_cost_per_swarm)
            limits["policy_id"] = str(row.id)
        return limits

    async def usage(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, int]:
        active_swarms = (await db.execute(select(func.count()).select_from(SwarmRun).where(
            SwarmRun.workspace_id == workspace_id, SwarmRun.status.in_(ACTIVE_SWARM_STATES)))).scalar_one()
        active_subagents = (await db.execute(
            select(func.count()).select_from(SubAgent).join(SwarmRun, SubAgent.swarm_run_id == SwarmRun.id)
            .where(SwarmRun.workspace_id == workspace_id, SubAgent.status.notin_(FINISHED_SUBAGENT_STATES)))
        ).scalar_one()
        return {"active_swarms": int(active_swarms), "active_sub_agents": int(active_subagents)}

    async def check_swarm_limits(self, db: AsyncSession, workspace_id: UUID,
                                 requested_sub_agents: int) -> Tuple[bool, Optional[str]]:
        limits = await self.effective_limits(db, workspace_id)
        usage = await self.usage(db, workspace_id)
        if usage["active_swarms"] >= limits["max_concurrent_swarms"]:
            return False, f"{usage['active_swarms']} swarms are already active (limit {limits['max_concurrent_swarms']})"
        if requested_sub_agents > limits["max_sub_agents_per_swarm"]:
            return False, (f"Requested {requested_sub_agents} sub-agents; the limit per swarm is "
                           f"{limits['max_sub_agents_per_swarm']}")
        if usage["active_sub_agents"] + requested_sub_agents > limits["max_total_sub_agents"]:
            return False, f"Would exceed the workspace limit of {limits['max_total_sub_agents']} active sub-agents"
        return True, None

    async def set_swarm_limit(self, db: AsyncSession, workspace_id: UUID, *,
                              max_concurrent_swarms: Optional[int] = None,
                              max_sub_agents_per_swarm: Optional[int] = None,
                              max_total_sub_agents: Optional[int] = None,
                              max_cost_per_swarm: Optional[float] = None,
                              changed_by: Optional[UUID] = None) -> LimitPolicyRow:
        """Create or update the workspace's policy. Values above the global limits are capped to them."""
        caps = global_limits()
        row = await self.policy_row(db, workspace_id)
        now = datetime.now(timezone.utc)
        current = _policy_model(row) if row is not None else None

        def pick(value, existing, cap):
            chosen = value if value is not None else (existing if existing is not None else cap)
            if chosen < 1:
                raise ValueError("Limits must be at least 1")
            return min(int(chosen), int(cap))

        concurrent = pick(max_concurrent_swarms, current.max_concurrent_swarms if current else None,
                          caps["max_concurrent_swarms"])
        per_swarm = pick(max_sub_agents_per_swarm, current.max_sub_agents_per_swarm if current else None,
                         caps["max_sub_agents_per_swarm"])
        total = pick(max_total_sub_agents, current.max_total_sub_agents if current else None,
                     caps["max_total_sub_agents"])
        cost = max_cost_per_swarm if max_cost_per_swarm is not None else (
            current.max_cost_per_swarm if current and current.max_cost_per_swarm is not None
            else caps["max_cost_per_swarm"])
        cost = min(float(cost), float(caps["max_cost_per_swarm"]))
        if row is None:
            row = LimitPolicyRow(id=uuid4(), workspace_id=workspace_id, policy_name="workspace swarm limits",
                                 policy_type="workspace", max_subagents=per_swarm,
                                 max_concurrent_swarms=concurrent, max_cost_per_swarm=Decimal(str(round(cost, 2))),
                                 is_active=True, created_by=changed_by,
                                 meta_data={"max_total_sub_agents": total}, created_at=now, updated_at=now)
            db.add(row)
        else:
            row.max_subagents, row.max_concurrent_swarms = per_swarm, concurrent
            row.max_cost_per_swarm = Decimal(str(round(cost, 2)))
            row.meta_data = {**(row.meta_data or {}), "max_total_sub_agents": total}
            row.updated_at = now
        await db.flush()
        return row

    async def get_limit_policy(self, db: AsyncSession, workspace_id: UUID) -> Optional[SwarmLimitPolicy]:
        row = await self.policy_row(db, workspace_id)
        return _policy_model(row) if row is not None else None

    async def list_limit_policies(self, db: AsyncSession, workspace_ids: List[UUID]) -> List[SwarmLimitPolicy]:
        rows = (await db.execute(select(LimitPolicyRow).where(LimitPolicyRow.workspace_id.in_(workspace_ids))
                                 .order_by(LimitPolicyRow.updated_at.desc()))).scalars().all()
        return [_policy_model(r) for r in rows]

    async def get_limit_stats(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        limits = await self.effective_limits(db, workspace_id)
        usage = await self.usage(db, workspace_id)
        return {"workspace_id": str(workspace_id), "limits": limits, "current_usage": usage,
                "remaining": {"swarms": max(0, limits["max_concurrent_swarms"] - usage["active_swarms"]),
                              "sub_agents": max(0, limits["max_total_sub_agents"] - usage["active_sub_agents"])}}


_limit_manager = SwarmLimitManager()


async def check_swarm_limits(db: AsyncSession, workspace_id: UUID,
                             requested_sub_agents: int) -> Tuple[bool, Optional[str]]:
    return await _limit_manager.check_swarm_limits(db, workspace_id, requested_sub_agents)


async def set_swarm_limit(db: AsyncSession, workspace_id: UUID, **kwargs) -> LimitPolicyRow:
    return await _limit_manager.set_swarm_limit(db, workspace_id, **kwargs)
