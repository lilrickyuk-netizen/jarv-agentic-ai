"""
JARV Backend - Swarm API

Authenticated, owner-scoped swarm management backed by the database: runs,
sub-agents, their tasks and output, limits, costs, metrics, and activity.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.core.swarm.limits import SwarmLimitManager, SwarmLimitPolicy
from app.core.swarm.manager import SubAgentStatus, SwarmManager, SwarmRunCreate, SwarmRunResult, SwarmStatus
from app.core.swarm.sub_agent import SubAgentManager, SubAgentResult, SubAgentTaskCreate
from app.core.swarm.tracking import SwarmCostRecord, SwarmMetrics, SwarmTracker
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/swarm", tags=["swarm"])

swarm_manager = SwarmManager()
sub_agent_manager = SubAgentManager()
limit_manager = SwarmLimitManager()
tracker = SwarmTracker()


class SwarmResponse(BaseModel):
    id: UUID
    message: str
    swarm: Optional[SwarmRunResult] = None


class SubAgentResponse(BaseModel):
    id: UUID
    message: str
    sub_agent: Optional[SubAgentResult] = None


class SpawnRequest(BaseModel):
    agent_template: str
    task_description: str
    authority_level: int = Field(ge=0, le=10)
    allowed_tools: List[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class ReasonRequest(BaseModel):
    reason: str = Field("completed", min_length=1, max_length=1000)


class CancelRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=1000)


class SetLimitRequest(BaseModel):
    workspace_id: UUID
    max_concurrent_swarms: Optional[int] = Field(None, ge=1)
    max_sub_agents_per_swarm: Optional[int] = Field(None, ge=1)
    max_total_sub_agents: Optional[int] = Field(None, ge=1)
    max_cost_per_swarm: Optional[float] = Field(None, gt=0)


class AttachLogsRequest(BaseModel):
    parent_task_id: UUID


async def _owned_workspace(db: AsyncSession, user_id: str, workspace_id: UUID) -> Workspace:
    workspace = (await db.execute(select(Workspace).where(
        Workspace.id == workspace_id, Workspace.owner_id == UUID(str(user_id))))).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def _owned_workspace_ids(db: AsyncSession, user_id: str) -> List[UUID]:
    return list((await db.execute(select(Workspace.id).where(
        Workspace.owner_id == UUID(str(user_id))))).scalars().all())


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ----- runs --------------------------------------------------------------------------------

@router.post("/runs", response_model=SwarmResponse)
async def create_swarm_run_endpoint(swarm: SwarmRunCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    try:
        swarm_id = await swarm_manager.create_swarm_run(swarm, db=db, authenticated_user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)
    return SwarmResponse(id=swarm_id, message="Swarm run created")


@router.get("/runs", response_model=List[SwarmRunResult])
async def list_swarm_runs_endpoint(user_id: CurrentUserId, workspace_id: Optional[UUID] = Query(None),
                                   status: Optional[SwarmStatus] = Query(None),
                                   active_only: bool = Query(False), db: AsyncSession = Depends(get_db)):
    return await swarm_manager.list_swarms(db, user_id, workspace_id, status.value if status else None, active_only)


@router.get("/runs/stats/{workspace_id}", response_model=dict)
async def get_swarm_stats_endpoint(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _owned_workspace(db, user_id, workspace_id)
    return await swarm_manager.get_swarm_stats(db, workspace_id)


@router.get("/runs/{swarm_run_id}", response_model=SwarmResponse)
async def get_swarm_run_endpoint(swarm_run_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    swarm = await swarm_manager.get_swarm_run(db, swarm_run_id, user_id)
    if swarm is None:
        raise HTTPException(status_code=404, detail="Swarm run not found")
    return SwarmResponse(id=swarm_run_id, message="Swarm run retrieved", swarm=swarm)


async def _transition(action, db, swarm_run_id, user_id, *args) -> Dict[str, Any]:
    try:
        swarm = await action(db, swarm_run_id, user_id, *args)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)
    return {"swarm_run_id": str(swarm.id), "status": swarm.status}


@router.post("/runs/{swarm_run_id}/pause", response_model=dict)
async def pause_swarm_endpoint(swarm_run_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    return await _transition(swarm_manager.pause_swarm, db, swarm_run_id, user_id)


@router.post("/runs/{swarm_run_id}/resume", response_model=dict)
async def resume_swarm_endpoint(swarm_run_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    return await _transition(swarm_manager.resume_swarm, db, swarm_run_id, user_id)


@router.post("/runs/{swarm_run_id}/complete", response_model=dict)
async def complete_swarm_endpoint(swarm_run_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    return await _transition(swarm_manager.complete_swarm, db, swarm_run_id, user_id)


@router.post("/runs/{swarm_run_id}/cancel", response_model=dict)
async def cancel_swarm_endpoint(swarm_run_id: UUID, request: CancelRequest, user_id: CurrentUserId,
                                db: AsyncSession = Depends(get_db)):
    """Operator cancel from the dashboard. Agents use cancel_swarm_with_boundary, which needs approval."""
    result = await _transition(swarm_manager.cancel_swarm, db, swarm_run_id, user_id, request.reason)
    return {**result, "reason": request.reason}


# ----- sub-agents ---------------------------------------------------------------------------

@router.post("/runs/{swarm_run_id}/sub-agents", response_model=SubAgentResponse)
async def spawn_sub_agent_endpoint(swarm_run_id: UUID, request: SpawnRequest, user_id: CurrentUserId,
                                   db: AsyncSession = Depends(get_db)):
    try:
        sub_agent_id = await swarm_manager.spawn_sub_agent(
            swarm_run_id, request.agent_template, request.task_description, request.authority_level,
            request.allowed_tools, request.timeout_seconds, db=db, authenticated_user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)
    return SubAgentResponse(id=sub_agent_id, message="Sub-agent spawned and run",
                            sub_agent=await sub_agent_manager.get_sub_agent(db, sub_agent_id, user_id))


@router.get("/sub-agents", response_model=List[SubAgentResult])
async def list_sub_agents_endpoint(user_id: CurrentUserId, swarm_run_id: Optional[UUID] = Query(None),
                                   status: Optional[SubAgentStatus] = Query(None),
                                   active_only: bool = Query(False), db: AsyncSession = Depends(get_db)):
    return await sub_agent_manager.list_sub_agents(db, user_id, swarm_run_id, status.value if status else None,
                                                   active_only)


@router.post("/sub-agents/{sub_agent_id}/dissolve", response_model=dict)
async def dissolve_sub_agent_endpoint(sub_agent_id: UUID, request: ReasonRequest, user_id: CurrentUserId,
                                      db: AsyncSession = Depends(get_db)):
    try:
        child = await swarm_manager.dissolve_sub_agent(db, sub_agent_id, user_id, request.reason)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)
    return {"sub_agent_id": str(child.id), "status": child.status, "reason": request.reason}


@router.post("/sub-agents/{sub_agent_id}/tasks", response_model=dict)
async def assign_task_endpoint(sub_agent_id: UUID, task: SubAgentTaskCreate, user_id: CurrentUserId,
                               db: AsyncSession = Depends(get_db)):
    if task.sub_agent_id != sub_agent_id:
        raise HTTPException(status_code=400, detail="sub_agent_id in the body must match the URL")
    try:
        task_id = await sub_agent_manager.assign_task(db, task, user_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)
    return {"task_id": str(task_id), **(await sub_agent_manager.get_status(db, sub_agent_id, user_id))}


@router.get("/sub-agents/{sub_agent_id}/status", response_model=dict)
async def get_sub_agent_status_endpoint(sub_agent_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    try:
        return await sub_agent_manager.get_status(db, sub_agent_id, user_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


@router.get("/sub-agents/{sub_agent_id}/output", response_model=dict)
async def collect_output_endpoint(sub_agent_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    try:
        return await sub_agent_manager.collect_output(db, sub_agent_id, user_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


@router.post("/sub-agents/{sub_agent_id}/attach-logs", response_model=dict)
async def attach_logs_endpoint(sub_agent_id: UUID, request: AttachLogsRequest, user_id: CurrentUserId,
                               db: AsyncSession = Depends(get_db)):
    try:
        return await sub_agent_manager.attach_logs_to_parent_task(db, sub_agent_id, user_id, request.parent_task_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)


# ----- limits ---------------------------------------------------------------------------------

@router.post("/limits", response_model=SwarmLimitPolicy)
async def set_swarm_limit_endpoint(request: SetLimitRequest, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _owned_workspace(db, user_id, request.workspace_id)
    try:
        await limit_manager.set_swarm_limit(
            db, request.workspace_id, max_concurrent_swarms=request.max_concurrent_swarms,
            max_sub_agents_per_swarm=request.max_sub_agents_per_swarm,
            max_total_sub_agents=request.max_total_sub_agents, max_cost_per_swarm=request.max_cost_per_swarm,
            changed_by=UUID(str(user_id)))
    except Exception as exc:  # noqa: BLE001
        raise _http(exc)
    return await limit_manager.get_limit_policy(db, request.workspace_id)


@router.get("/limits", response_model=List[SwarmLimitPolicy])
async def list_limit_policies_endpoint(user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    return await limit_manager.list_limit_policies(db, await _owned_workspace_ids(db, user_id))


@router.get("/limits/stats/{workspace_id}", response_model=dict)
async def get_limit_stats_endpoint(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _owned_workspace(db, user_id, workspace_id)
    return await limit_manager.get_limit_stats(db, workspace_id)


# ----- tracking -----------------------------------------------------------------------------

async def _owned_run(db, swarm_run_id, user_id):
    try:
        return await swarm_manager.owned_swarm(db, swarm_run_id, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/runs/{swarm_run_id}/costs", response_model=dict)
async def get_swarm_costs_endpoint(swarm_run_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _owned_run(db, swarm_run_id, user_id)
    return {"swarm_run_id": str(swarm_run_id), "costs": await tracker.calculate_swarm_cost(db, swarm_run_id)}


@router.get("/runs/{swarm_run_id}/metrics", response_model=SwarmMetrics)
async def get_swarm_metrics_endpoint(swarm_run_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _owned_run(db, swarm_run_id, user_id)
    return await tracker.get_swarm_metrics(db, swarm_run_id)


@router.get("/runs/{swarm_run_id}/activity", response_model=dict)
async def get_swarm_activity_endpoint(swarm_run_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _owned_run(db, swarm_run_id, user_id)
    return await tracker.report_swarm_activity(db, swarm_run_id)


@router.get("/costs", response_model=List[SwarmCostRecord])
async def list_cost_records_endpoint(user_id: CurrentUserId, swarm_run_id: Optional[UUID] = Query(None),
                                     limit: int = Query(100, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    return await tracker.list_cost_records(db, await _owned_workspace_ids(db, user_id), swarm_run_id, limit)


@router.get("/costs/workspace/{workspace_id}", response_model=dict)
async def get_workspace_costs_endpoint(workspace_id: UUID, user_id: CurrentUserId,
                                       start_date: Optional[str] = Query(None), end_date: Optional[str] = Query(None),
                                       db: AsyncSession = Depends(get_db)):
    await _owned_workspace(db, user_id, workspace_id)
    try:
        start = datetime.fromisoformat(start_date.replace("Z", "+00:00")) if start_date else None
        end = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {exc}")
    return await tracker.get_workspace_swarm_costs(db, workspace_id, start, end)


@router.get("/dashboard/{workspace_id}")
async def get_swarm_dashboard(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _owned_workspace(db, user_id, workspace_id)
    stats = await swarm_manager.get_swarm_stats(db, workspace_id)
    limits = await limit_manager.get_limit_stats(db, workspace_id)
    active = await swarm_manager.list_active_swarms(db, user_id, workspace_id)
    finished = stats["succeeded_sub_agents"]
    judged = stats["total_sub_agents_spawned"] - stats["active_sub_agents"]
    return {
        "workspace_id": str(workspace_id), "stats": stats, "limits": limits,
        "active_swarms": [s.model_dump(mode="json") for s in active],
        "health": {
            "swarm_capacity_used": round(limits["current_usage"]["active_swarms"]
                                         / max(1, limits["limits"]["max_concurrent_swarms"]), 3),
            "sub_agent_capacity_used": round(limits["current_usage"]["active_sub_agents"]
                                             / max(1, limits["limits"]["max_total_sub_agents"]), 3),
            "success_rate": round(finished / judged, 3) if judged else 0.0,
            "total_cost": stats["total_cost"],
        },
    }
