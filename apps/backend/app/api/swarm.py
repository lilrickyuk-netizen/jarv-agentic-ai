"""
JARV Backend - Swarm API Endpoints

REST API for swarm management.
"""
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.swarm.manager import (
    SwarmManager,
    SwarmRunCreate,
    SwarmRunResult,
    SwarmStatus,
    SubAgentStatus,
)
from app.core.swarm.sub_agent import (
    SubAgentManager,
    SubAgentCreate,
    SubAgentResult,
    SubAgentTaskCreate,
    SubAgentTaskResult,
)
from app.core.swarm.limits import (
    SwarmLimitManager,
    SwarmLimitPolicy,
    LimitScope,
)
from app.core.swarm.tracking import (
    SwarmTracker,
    SwarmCostRecord,
    SwarmMetrics,
)

router = APIRouter(prefix="/api/swarm", tags=["swarm"])

# Initialize managers
swarm_manager = SwarmManager()
sub_agent_manager = SubAgentManager()
limit_manager = SwarmLimitManager()
tracker = SwarmTracker()


# Response models
class SwarmResponse(BaseModel):
    """Swarm response"""
    id: UUID
    message: str
    swarm: Optional[SwarmRunResult] = None


class SubAgentResponse(BaseModel):
    """Sub-agent response"""
    id: UUID
    message: str
    sub_agent: Optional[SubAgentResult] = None


class TaskResponse(BaseModel):
    """Task response"""
    id: UUID
    message: str
    task: Optional[SubAgentTaskResult] = None


class StatusResponse(BaseModel):
    """Status response"""
    status: dict


class LimitResponse(BaseModel):
    """Limit response"""
    id: UUID
    message: str
    policy: Optional[SwarmLimitPolicy] = None


class CostResponse(BaseModel):
    """Cost response"""
    swarm_run_id: UUID
    costs: dict


class MetricsResponse(BaseModel):
    """Metrics response"""
    swarm_run_id: UUID
    metrics: SwarmMetrics


class ActivityResponse(BaseModel):
    """Activity response"""
    swarm_run_id: UUID
    report: dict


# Swarm operation requests
class SpawnRequest(BaseModel):
    """Spawn sub-agent request"""
    agent_template: str
    task_description: str
    authority_level: int = Field(ge=0, le=10)
    allowed_tools: List[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)


class DissolveRequest(BaseModel):
    """Dissolve sub-agent request"""
    reason: str = "completed"


class CancelRequest(BaseModel):
    """Cancel swarm request"""
    reason: str


class SetLimitRequest(BaseModel):
    """Set limit request"""
    scope: LimitScope
    scope_id: Optional[UUID] = None
    max_concurrent_swarms: Optional[int] = None
    max_sub_agents_per_swarm: Optional[int] = None
    max_total_sub_agents: Optional[int] = None
    max_sub_agent_depth: Optional[int] = None


# =============================================================================
# SWARM RUN ENDPOINTS
# =============================================================================

@router.post("/runs", response_model=SwarmResponse)
async def create_swarm_run_endpoint(swarm: SwarmRunCreate):
    """
    Create swarm run.

    Initializes a new swarm for parallel execution.
    """
    try:
        swarm_id = await swarm_manager.create_swarm_run(swarm)
        return SwarmResponse(
            id=swarm_id,
            message="Swarm run created successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{swarm_run_id}", response_model=SwarmResponse)
async def get_swarm_run_endpoint(swarm_run_id: UUID):
    """Get swarm run by ID"""
    swarm = await swarm_manager.get_swarm_run(swarm_run_id)
    if not swarm:
        raise HTTPException(status_code=404, detail="Swarm run not found")
    return SwarmResponse(
        id=swarm_run_id,
        message="Swarm run retrieved",
        swarm=swarm
    )


@router.get("/runs", response_model=List[SwarmRunResult])
async def list_swarm_runs_endpoint(
    workspace_id: Optional[UUID] = Query(None),
    status: Optional[SwarmStatus] = Query(None),
):
    """List swarm runs with filters"""
    # In production: Query with filters
    return await swarm_manager.list_active_swarms(workspace_id)


@router.post("/runs/{swarm_run_id}/pause", response_model=dict)
async def pause_swarm_endpoint(swarm_run_id: UUID):
    """
    Pause swarm execution.

    Pauses all active sub-agents.
    """
    try:
        success = await swarm_manager.pause_swarm(swarm_run_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to pause swarm")
        return {
            "swarm_run_id": str(swarm_run_id),
            "status": "paused",
            "message": "Swarm paused successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runs/{swarm_run_id}/resume", response_model=dict)
async def resume_swarm_endpoint(swarm_run_id: UUID):
    """
    Resume paused swarm.

    Resumes all paused sub-agents.
    """
    try:
        success = await swarm_manager.resume_swarm(swarm_run_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to resume swarm")
        return {
            "swarm_run_id": str(swarm_run_id),
            "status": "running",
            "message": "Swarm resumed successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runs/{swarm_run_id}/cancel", response_model=dict)
async def cancel_swarm_endpoint(swarm_run_id: UUID, request: CancelRequest):
    """
    Cancel swarm with boundary enforcement.

    Cancels swarm and dissolves all sub-agents.
    """
    try:
        success = await swarm_manager.cancel_swarm(swarm_run_id, request.reason)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to cancel swarm")
        return {
            "swarm_run_id": str(swarm_run_id),
            "status": "cancelled",
            "reason": request.reason,
            "message": "Swarm cancelled successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/stats/{workspace_id}", response_model=dict)
async def get_swarm_stats_endpoint(workspace_id: UUID):
    """Get swarm statistics for workspace"""
    return await swarm_manager.get_swarm_stats(workspace_id)


# =============================================================================
# SUB-AGENT ENDPOINTS
# =============================================================================

@router.post("/runs/{swarm_run_id}/sub-agents", response_model=SubAgentResponse)
async def spawn_sub_agent_endpoint(swarm_run_id: UUID, request: SpawnRequest):
    """
    Spawn sub-agent.

    Creates and spawns a new sub-agent for the swarm.
    """
    try:
        sub_agent_id = await swarm_manager.spawn_sub_agent(
            swarm_run_id,
            request.agent_template,
            request.task_description,
            request.authority_level,
            request.allowed_tools,
            request.timeout_seconds,
        )
        return SubAgentResponse(
            id=sub_agent_id,
            message="Sub-agent spawned successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sub-agents/{sub_agent_id}/dissolve", response_model=dict)
async def dissolve_sub_agent_endpoint(sub_agent_id: UUID, request: DissolveRequest):
    """
    Dissolve sub-agent.

    Terminates sub-agent and cleans up resources.
    """
    try:
        success = await swarm_manager.dissolve_sub_agent(sub_agent_id, request.reason)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to dissolve sub-agent")
        return {
            "sub_agent_id": str(sub_agent_id),
            "status": "dissolved",
            "reason": request.reason,
            "message": "Sub-agent dissolved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sub-agents/{sub_agent_id}/tasks", response_model=TaskResponse)
async def assign_task_endpoint(sub_agent_id: UUID, task: SubAgentTaskCreate):
    """
    Assign task to sub-agent.

    Creates and assigns a task to the specified sub-agent.
    """
    try:
        task_id = await sub_agent_manager.assign_task(task)
        return TaskResponse(
            id=task_id,
            message="Task assigned successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sub-agents/{sub_agent_id}/status", response_model=StatusResponse)
async def get_sub_agent_status_endpoint(sub_agent_id: UUID):
    """
    Get sub-agent status.

    Returns current status and progress information.
    """
    try:
        status = await sub_agent_manager.get_status(sub_agent_id)
        return StatusResponse(status=status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sub-agents/{sub_agent_id}/output", response_model=dict)
async def collect_output_endpoint(sub_agent_id: UUID):
    """
    Collect sub-agent output.

    Retrieves all completed task outputs.
    """
    try:
        output = await sub_agent_manager.collect_output(sub_agent_id)
        return output
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sub-agents", response_model=List[SubAgentResult])
async def list_sub_agents_endpoint(
    swarm_run_id: Optional[UUID] = Query(None),
    status: Optional[SubAgentStatus] = Query(None),
):
    """List active sub-agents with filters"""
    return await sub_agent_manager.list_active_sub_agents(swarm_run_id)


# =============================================================================
# LIMIT ENDPOINTS
# =============================================================================

@router.post("/limits", response_model=LimitResponse)
async def set_swarm_limit_endpoint(request: SetLimitRequest):
    """
    Set swarm limit policy.

    Creates or updates swarm limits for a scope.
    """
    try:
        policy_id = await limit_manager.set_swarm_limit(
            request.scope,
            request.scope_id,
            request.max_concurrent_swarms,
            request.max_sub_agents_per_swarm,
            request.max_total_sub_agents,
            request.max_sub_agent_depth,
        )
        return LimitResponse(
            id=policy_id,
            message="Swarm limits set successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/limits/{scope}", response_model=LimitResponse)
async def get_limit_policy_endpoint(
    scope: LimitScope,
    scope_id: Optional[UUID] = Query(None),
):
    """Get limit policy for scope"""
    policy = await limit_manager.get_limit_policy(scope, scope_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Limit policy not found")
    return LimitResponse(
        id=policy.id,
        message="Limit policy retrieved",
        policy=policy
    )


@router.get("/limits", response_model=List[SwarmLimitPolicy])
async def list_limit_policies_endpoint(
    scope: Optional[LimitScope] = Query(None),
):
    """List limit policies with filters"""
    return await limit_manager.list_limit_policies(scope)


@router.get("/limits/stats/{workspace_id}", response_model=dict)
async def get_limit_stats_endpoint(workspace_id: UUID):
    """Get limit usage statistics"""
    return await limit_manager.get_limit_stats(workspace_id)


# =============================================================================
# TRACKING ENDPOINTS
# =============================================================================

@router.get("/runs/{swarm_run_id}/costs", response_model=CostResponse)
async def get_swarm_costs_endpoint(swarm_run_id: UUID):
    """
    Get swarm cost breakdown.

    Returns detailed cost information for the swarm.
    """
    try:
        costs = await tracker.calculate_swarm_cost(swarm_run_id)
        return CostResponse(
            swarm_run_id=swarm_run_id,
            costs=costs
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{swarm_run_id}/metrics", response_model=MetricsResponse)
async def get_swarm_metrics_endpoint(swarm_run_id: UUID):
    """
    Get swarm metrics.

    Returns performance and completion metrics.
    """
    try:
        metrics = await tracker.get_swarm_metrics(swarm_run_id)
        return MetricsResponse(
            swarm_run_id=swarm_run_id,
            metrics=metrics
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{swarm_run_id}/activity", response_model=ActivityResponse)
async def get_swarm_activity_endpoint(swarm_run_id: UUID):
    """
    Get swarm activity report.

    Returns comprehensive activity summary.
    """
    try:
        report = await tracker.report_swarm_activity(swarm_run_id)
        return ActivityResponse(
            swarm_run_id=swarm_run_id,
            report=report
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/costs", response_model=List[SwarmCostRecord])
async def list_cost_records_endpoint(
    swarm_run_id: Optional[UUID] = Query(None),
    workspace_id: Optional[UUID] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """List cost records with filters"""
    return await tracker.list_cost_records(swarm_run_id, workspace_id, limit)


@router.get("/costs/workspace/{workspace_id}", response_model=dict)
async def get_workspace_costs_endpoint(
    workspace_id: UUID,
    start_date: Optional[str] = Query(None, description="ISO format datetime"),
    end_date: Optional[str] = Query(None, description="ISO format datetime"),
):
    """Get workspace swarm costs over time"""
    try:
        start = datetime.fromisoformat(start_date.replace('Z', '+00:00')) if start_date else None
        end = datetime.fromisoformat(end_date.replace('Z', '+00:00')) if end_date else None

        return await tracker.get_workspace_swarm_costs(workspace_id, start, end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DASHBOARD ENDPOINT
# =============================================================================

@router.get("/dashboard/{workspace_id}")
async def get_swarm_dashboard(workspace_id: UUID):
    """
    Get swarm dashboard data.

    Returns comprehensive swarm metrics and status.
    """
    try:
        swarm_stats = await swarm_manager.get_swarm_stats(workspace_id)
        limit_stats = await limit_manager.get_limit_stats(workspace_id)
        active_swarms = await swarm_manager.list_active_swarms(workspace_id)

        # Get costs for active swarms
        swarm_costs = []
        for swarm in active_swarms[:5]:  # Limit to 5 most recent
            costs = await tracker.calculate_swarm_cost(swarm.id)
            swarm_costs.append(costs)

        return {
            "workspace_id": str(workspace_id),
            "stats": swarm_stats,
            "limits": limit_stats,
            "active_swarms": [swarm.dict() for swarm in active_swarms],
            "recent_costs": swarm_costs,
            "health": {
                "swarm_capacity_used": 0.0,
                "sub_agent_capacity_used": 0.0,
                "avg_success_rate": 0.0,
                "total_cost_today": 0.0,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
