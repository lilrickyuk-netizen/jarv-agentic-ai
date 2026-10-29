"""
JARV Backend - Analytics API (Repair 14a)

How JARV itself is performing in a workspace, from its own records: missions
by status (normalised to the mission lifecycle) and per day, success rate,
duration and tokens; tool runs by tool and by agent, failures and approval
pauses; and the estimated monthly cost against the budget. Product traffic
lives on /api/revenue/{workspace}/analytics.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/{workspace_id}/overview")
async def overview(workspace_id: UUID, user_id: CurrentUserId, days: int = Query(30, ge=1, le=365),
                   db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    from app.core.runtime import lifecycle
    from app.models.agent import Agent
    from app.models.task import Task
    from app.models.tool_system import Tool, ToolRun

    owned = (await db.execute(select(Workspace.id).where(Workspace.id == workspace_id,
                                                         Workspace.owner_id == UUID(str(user_id))))).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    since = datetime.now(timezone.utc) - timedelta(days=days)

    tasks = (await db.execute(select(Task).where(Task.workspace_id == workspace_id, Task.created_at >= since))
             ).scalars().all()
    statuses = Counter(lifecycle.normalise(t.status) for t in tasks)
    per_day: Dict[str, Dict[str, int]] = defaultdict(lambda: {"created": 0, "completed": 0, "failed": 0})
    durations = []
    for t in tasks:
        created = _aware(t.created_at)
        if created is not None:
            per_day[created.date().isoformat()]["created"] += 1
        state = lifecycle.normalise(t.status)
        if state in (lifecycle.COMPLETED, lifecycle.FAILED):
            finished = _aware(t.completed_at) or _aware(t.updated_at) or created
            if finished is not None:
                per_day[finished.date().isoformat()]["completed" if state == lifecycle.COMPLETED else "failed"] += 1
        if t.execution_duration_seconds:
            durations.append(int(t.execution_duration_seconds))
    finished = statuses.get(lifecycle.COMPLETED, 0) + statuses.get(lifecycle.FAILED, 0) + statuses.get(lifecycle.PARTIAL, 0)

    runs = (await db.execute(
        select(ToolRun.status, ToolRun.success, ToolRun.required_approval, ToolRun.duration_ms, Tool.tool_name, Agent.agent_type)
        .join(Agent, ToolRun.agent_id == Agent.id).join(Tool, ToolRun.tool_id == Tool.id)
        .where(Agent.workspace_id == workspace_id, ToolRun.started_at >= since))).all()
    by_tool: Dict[str, Dict[str, int]] = defaultdict(lambda: {"runs": 0, "failed": 0})
    by_agent: Counter = Counter()
    paused = failed = 0
    for status, success, approval, _ms, tool_name, agent_type in runs:
        by_tool[tool_name]["runs"] += 1
        by_agent[agent_type] += 1
        if success is False:
            by_tool[tool_name]["failed"] += 1
            failed += 1
        if approval or status == "blocked":
            paused += 1
    run_ms = [r[3] for r in runs if r[3]]

    cost: Dict[str, Any]
    try:
        from app.core.infra.configs import estimate_monthly

        cost = await estimate_monthly(db, workspace_id)
    except ValueError as exc:
        cost = {"error": str(exc)}
    return {
        "period_days": days,
        "missions": {
            "total": len(tasks), "by_status": dict(statuses),
            "success_rate": round(statuses.get(lifecycle.COMPLETED, 0) / finished, 3) if finished else None,
            "average_seconds": round(sum(durations) / len(durations), 1) if durations else None,
            "tokens": sum(int(t.tokens_used or 0) for t in tasks),
            "per_day": dict(sorted(per_day.items())),
        },
        "tools": {
            "runs": len(runs), "failed": failed, "approval_pauses": paused,
            "average_ms": round(sum(run_ms) / len(run_ms)) if run_ms else None,
            "top": sorted(({"tool": k, **v} for k, v in by_tool.items()), key=lambda x: -x["runs"])[:12],
            "by_agent": dict(by_agent.most_common(12)),
        },
        "cost": cost,
    }
