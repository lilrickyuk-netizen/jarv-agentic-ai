"""
JARV Backend - Command API

Dashboard command control. A command (typed, or produced by speech-to-text) is
safety-classified and recorded as a mission, then handed to the mission
runtime (the worker queue by default). The response returns immediately with
the mission id; the dashboard follows progress through
``GET /command/tasks/{task_id}`` until the mission finishes.

Commands that need Richard's approval are recorded as ``blocked`` and are not
dispatched until they are approved.
"""
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId, get_current_user_id
from app.core.command import CommandService
from app.core.database import get_db
from app.core.runtime import lifecycle
from app.core.runtime.dispatcher import dispatch_mission
from app.core.runtime.missions import cancel_mission, retry_mission
from app.models.company_operations import LiveOperationsFeedItem
from app.models.task import Task
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/command", tags=["command"])


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=4000)
    workspace_id: Optional[UUID] = None


class CommandResponse(BaseModel):
    task_id: str
    command: str
    status: str
    requires_approval: bool
    response_text: str
    plan_steps: List[str]
    selected_agents: List[str]
    provider: Optional[str]
    model: Optional[str]
    execution_time: float
    tokens_used: int
    approval_reason: Optional[str] = None
    error: Optional[str] = None
    finished: bool = False
    dispatch_mode: Optional[str] = None


class MissionEvent(BaseModel):
    at: str
    title: str
    message: str
    severity: str


class MissionStatusResponse(CommandResponse):
    workspace_id: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    attempts: int = 0
    status_history: List[Dict[str, Any]] = []
    events: List[MissionEvent] = []


class CommandHistoryItem(BaseModel):
    task_id: str
    command: str
    status: str
    response_text: Optional[str]
    selected_agents: List[str]
    created_at: str
    completed_at: Optional[str]
    error: Optional[str]


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


async def _owned_task(db: AsyncSession, operator: str, task_id: UUID) -> Task:
    task = (await db.execute(
        select(Task).join(Workspace, Workspace.id == Task.workspace_id)
        .where(Task.id == task_id, Task.task_type == "command",
               Workspace.owner_id == UUID(str(operator)))
    )).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    return task


def _mission_view(task: Task, events: List[LiveOperationsFeedItem]) -> MissionStatusResponse:
    res = task.result if isinstance(task.result, dict) else {}
    meta = task.meta_data or {}
    status = lifecycle.normalise(task.status)
    if status in lifecycle.IN_FLIGHT:
        text = "Mission accepted and queued for execution." if status == lifecycle.QUEUED else \
            "JARV is working on this mission."
    elif status == lifecycle.BLOCKED:
        text = ("This command requires your approval before JARV will execute it.\n\n"
                f"Reason: {meta.get('blocked_reason') or (task.context or {}).get('safety_reason')}")
    else:
        text = res.get("response") or task.error_message or ""
    return MissionStatusResponse(
        task_id=str(task.id), command=task.description or task.title, status=status,
        requires_approval=status in (lifecycle.BLOCKED, lifecycle.WAITING_ON_APPROVAL),
        response_text=text, plan_steps=list(res.get("plan_steps") or []),
        selected_agents=list(res.get("selected_agents") or []),
        provider=res.get("provider") or meta.get("provider"), model=res.get("model") or meta.get("model"),
        execution_time=float(task.execution_duration_seconds or 0), tokens_used=int(task.tokens_used or 0),
        approval_reason=meta.get("blocked_reason"),
        error=task.error_message if status in (lifecycle.FAILED, lifecycle.PARTIAL) else None,
        finished=status in lifecycle.TERMINAL or status in (lifecycle.BLOCKED, lifecycle.WAITING_ON_APPROVAL),
        dispatch_mode=meta.get("dispatch_mode"),
        workspace_id=str(task.workspace_id), created_at=_iso(task.created_at),
        started_at=_iso(task.started_at), updated_at=_iso(task.updated_at),
        heartbeat_at=_iso(task.heartbeat_at), attempts=int(task.retry_count or 0) + 1,
        status_history=list(meta.get("status_history") or []),
        events=[MissionEvent(at=_iso(e.created_at) or "", title=e.title, message=e.message or "",
                             severity=e.severity or "info") for e in events],
    )


async def _events(db: AsyncSession, task_id: UUID, limit: int = 40) -> List[LiveOperationsFeedItem]:
    rows = (await db.execute(
        select(LiveOperationsFeedItem).where(LiveOperationsFeedItem.related_task_id == task_id)
        .order_by(LiveOperationsFeedItem.created_at.desc()).limit(limit)
    )).scalars().all()
    return list(reversed(rows))


@router.post("/execute", response_model=CommandResponse)
async def execute_command(
    request: CommandRequest,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> CommandResponse:
    """Accept a command as a mission and dispatch it to the runtime.

    Returns at once with status ``queued`` (or ``blocked`` when approval is
    required). Follow the mission with ``GET /command/tasks/{task_id}``.
    """
    service = CommandService()
    try:
        submitted = await service.submit(
            command_text=request.command, db=db,
            workspace_id=request.workspace_id, operator=operator,
            user_id=UUID(str(operator)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    body = submitted.to_dict()
    if submitted.status == lifecycle.QUEUED:
        dispatched = await dispatch_mission(submitted.task_id, reason="command submitted")
        body["dispatch_mode"] = dispatched["mode"]
        result = dispatched.get("result")
        if isinstance(result, dict) and result.get("status"):
            body.update({k: v for k, v in result.items() if k in CommandResponse.model_fields})
    body["finished"] = body["status"] in lifecycle.TERMINAL or body["status"] in (
        lifecycle.BLOCKED, lifecycle.WAITING_ON_APPROVAL)
    return CommandResponse(**body)


@router.get("/tasks/{task_id}", response_model=MissionStatusResponse)
async def mission_status(
    task_id: UUID, operator: CurrentUserId, db: AsyncSession = Depends(get_db),
) -> MissionStatusResponse:
    """Current state, outcome, status history, and recent events of a mission."""
    task = await _owned_task(db, operator, task_id)
    return _mission_view(task, await _events(db, task.id))


@router.post("/tasks/{task_id}/cancel", response_model=MissionStatusResponse)
async def cancel_command(
    task_id: UUID, operator: CurrentUserId, db: AsyncSession = Depends(get_db),
) -> MissionStatusResponse:
    task = await _owned_task(db, operator, task_id)
    if not await cancel_mission(db, task, actor=str(operator)):
        raise HTTPException(status_code=409, detail=f"Mission is {task.status}; it cannot be cancelled")
    await db.commit()
    return _mission_view(task, await _events(db, task.id))


@router.post("/tasks/{task_id}/retry", response_model=MissionStatusResponse)
async def retry_command(
    task_id: UUID, operator: CurrentUserId, db: AsyncSession = Depends(get_db),
) -> MissionStatusResponse:
    """Run a failed or partial mission again."""
    task = await _owned_task(db, operator, task_id)
    if not await retry_mission(db, task, actor=str(operator)):
        raise HTTPException(status_code=409, detail=f"Mission is {task.status}; only failed or partial missions can be retried")
    await db.commit()
    await dispatch_mission(task.id, reason="retry")
    await db.refresh(task)
    return _mission_view(task, await _events(db, task.id))


@router.get("/history", response_model=List[CommandHistoryItem])
async def command_history(
    operator: CurrentUserId,
    limit: int = Query(25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> List[CommandHistoryItem]:
    """The caller's recent missions."""
    tasks = (await db.execute(
        select(Task).join(Workspace, Workspace.id == Task.workspace_id)
        .where(Task.task_type == "command", Workspace.owner_id == UUID(str(operator)))
        .order_by(Task.created_at.desc()).limit(limit)
    )).scalars().all()
    items: List[CommandHistoryItem] = []
    for t in tasks:
        res = t.result if isinstance(t.result, dict) else {}
        items.append(CommandHistoryItem(
            task_id=str(t.id), command=t.title, status=lifecycle.normalise(t.status),
            response_text=res.get("response"), selected_agents=res.get("selected_agents", []),
            created_at=_iso(t.created_at) or "", completed_at=_iso(t.completed_at),
            error=t.error_message,
        ))
    return items


@router.get("/info", dependencies=[Depends(get_current_user_id)])
async def command_info() -> dict:
    """Active provider and model for the command UI (no secrets). Authenticated."""
    service = CommandService()
    return {"provider": service.provider_name, "model": service.model}
