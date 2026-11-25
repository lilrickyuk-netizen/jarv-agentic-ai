"""
JAI Backend - Command API

Dashboard command control. A command (typed, or produced by speech-to-text) is
safety-classified and recorded as a mission, then handed to the mission
runtime (the worker queue by default). The response returns immediately with
the mission id; the dashboard follows progress through
``GET /command/tasks/{task_id}`` until the mission finishes.

Commands that need Richard's approval are recorded as ``blocked`` and are not
dispatched until they are approved.
"""
import logging
from datetime import datetime, timezone
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
    # The model each role ran on, when the roles differ (from the engines' own run reports).
    models_by_role: Dict[str, str] = {}


class MissionEvent(BaseModel):
    at: str
    title: str
    message: str
    severity: str


class MissionStatusResponse(CommandResponse):
    workspace_id: str
    folder: Optional[str] = None
    archived: bool = False
    resumable: bool = False
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
    folder: Optional[str] = None
    archived: bool = False


def _folder(task: Task) -> Optional[str]:
    """The folder the mission works in: the one its result records, or while it runs, the one its brief names.
    18 November: every running mission's card said "no folder" until it finished, because only the result had it."""
    res = task.result if isinstance(task.result, dict) else {}
    if res.get("workspace_path"):
        return res["workspace_path"]
    return CommandService._extract_path(task.description or task.title or "")


def _archived(task: Task) -> bool:
    return bool((task.meta_data or {}).get("archived_at"))


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


def _so_far(task: Task, status: str, live: Optional[Dict[str, Any]]) -> tuple:
    """Time and tokens for the card: the recorded totals once a mission has finished; while it works, the time
    since it started and the tokens its live progress record has counted (22 November: running cards said
    "0s · 0 tokens" until the end)."""
    seconds, tokens = float(task.execution_duration_seconds or 0), int(task.tokens_used or 0)
    if status in lifecycle.IN_FLIGHT:
        if task.started_at:
            started = task.started_at if task.started_at.tzinfo else task.started_at.replace(tzinfo=timezone.utc)
            seconds = max(seconds, round((datetime.now(timezone.utc) - started).total_seconds()))
        tokens = max(tokens, int((live or {}).get("tokens_so_far") or 0))
    return seconds, tokens


def _ran_on(task: Task, status: str, live: Optional[Dict[str, Any]]) -> tuple:
    """(provider, model, models by role) for the card: what the engines reported running this mission, never a
    setting or the Orchestrator's model read now (25 November: VIDEO_MODEL went back to Sonnet and the cards still
    said Opus, the Orchestrator's model recorded when the mission was queued). While it works: the models its runs
    have reported so far; once it has ended: the ones its result recorded (service.worked_on)."""
    from app.core.command.service import worked_on

    res = task.result if isinstance(task.result, dict) else {}
    if status in lifecycle.IN_FLIGHT:
        did = worked_on(live or {}) if live else None
        if did is None and res.get("models_used"):
            return res.get("provider"), res.get("model"), dict(res.get("models_by_role") or {})
        if did is None:
            return None, None, {}
        return did["provider"], did["model"], dict(did.get("by_role") or {})
    return res.get("provider"), res.get("model"), dict(res.get("models_by_role") or {})


def _mission_view(task: Task, events: List[LiveOperationsFeedItem],
                  live: Optional[Dict[str, Any]] = None) -> MissionStatusResponse:
    res = task.result if isinstance(task.result, dict) else {}
    meta = task.meta_data or {}
    status = lifecycle.normalise(task.status)
    seconds, tokens = _so_far(task, status, live)
    ran_on = _ran_on(task, status, live)
    from app.core.creative import render_jobs

    job = render_jobs.rendering(meta) if status in lifecycle.IN_FLIGHT else None
    if job is not None:
        text = render_jobs.card_line(job)  # "Rendering (no AI cost), 4m 12s so far."
    elif status in lifecycle.IN_FLIGHT:
        text = "Mission accepted and queued for execution." if status == lifecycle.QUEUED else \
            "JAI is working on this mission."
    elif status == lifecycle.BLOCKED:
        text = ("This command requires your approval before JAI will execute it.\n\n"
                f"Reason: {meta.get('blocked_reason') or (task.context or {}).get('safety_reason')}")
    else:
        text = res.get("response") or task.error_message or ""
    return MissionStatusResponse(
        task_id=str(task.id), command=task.description or task.title, status=status,
        requires_approval=status in (lifecycle.BLOCKED, lifecycle.WAITING_ON_APPROVAL),
        response_text=text, plan_steps=list(res.get("plan_steps") or []),
        selected_agents=list(res.get("selected_agents") or []),
        provider=ran_on[0], model=ran_on[1],
        models_by_role=ran_on[2] if len(set(ran_on[2].values())) > 1 else {},
        execution_time=float(seconds), tokens_used=int(tokens),
        approval_reason=meta.get("blocked_reason"),
        error=task.error_message if status in (lifecycle.FAILED, lifecycle.PARTIAL) else None,
        finished=status in lifecycle.TERMINAL or status in (lifecycle.BLOCKED, lifecycle.WAITING_ON_APPROVAL),
        dispatch_mode=meta.get("dispatch_mode"),
        workspace_id=str(task.workspace_id), folder=_folder(task), archived=_archived(task),
        resumable=status in (lifecycle.NEEDS_CONTINUATION, lifecycle.PARTIAL) and not _archived(task),
        created_at=_iso(task.created_at),
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
    from app.core.command import progress

    task = await _owned_task(db, operator, task_id)
    live = await progress.load(task.id) if lifecycle.normalise(task.status) in lifecycle.IN_FLIGHT else None
    return _mission_view(task, await _events(db, task.id), live)


@router.post("/tasks/{task_id}/cancel", response_model=MissionStatusResponse)
async def cancel_command(
    task_id: UUID, operator: CurrentUserId, db: AsyncSession = Depends(get_db),
) -> MissionStatusResponse:
    task = await _owned_task(db, operator, task_id)
    if not await cancel_mission(db, task, actor=str(operator)):
        raise HTTPException(status_code=409, detail=f"Mission is {task.status}; it cannot be cancelled")
    await db.commit()
    return _mission_view(task, await _events(db, task.id))


@router.post("/tasks/{task_id}/archive", response_model=MissionStatusResponse)
async def archive_command(
    task_id: UUID, operator: CurrentUserId, db: AsyncSession = Depends(get_db),
) -> MissionStatusResponse:
    """Hide a mission that is no longer running from the mission list (nothing is deleted)."""
    task = await _owned_task(db, operator, task_id)
    status = lifecycle.normalise(task.status)
    if status in lifecycle.IN_FLIGHT and status != lifecycle.NEEDS_CONTINUATION:
        raise HTTPException(status_code=409, detail=f"Mission is {status}; cancel it before archiving")
    if status == lifecycle.NEEDS_CONTINUATION:
        # An archived mission must never be continued automatically.
        lifecycle.transition(task, lifecycle.CANCELLED, actor=str(operator), reason="archived by operator")
    from datetime import datetime, timezone

    task.meta_data = {**(task.meta_data or {}), "archived_at": datetime.now(timezone.utc).isoformat(),
                      "archived_by": str(operator)}
    await db.commit()
    # updated_at is set by the database on write, so it is reloaded before the view reads it.
    await db.refresh(task)
    return _mission_view(task, await _events(db, task.id))


@router.post("/tasks/{task_id}/unarchive", response_model=MissionStatusResponse)
async def unarchive_command(
    task_id: UUID, operator: CurrentUserId, db: AsyncSession = Depends(get_db),
) -> MissionStatusResponse:
    task = await _owned_task(db, operator, task_id)
    task.meta_data = {k: v for k, v in (task.meta_data or {}).items() if k not in ("archived_at", "archived_by")}
    await db.commit()
    # updated_at is set by the database on write, so it is reloaded before the view reads it.
    await db.refresh(task)
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
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db),
) -> List[CommandHistoryItem]:
    """The caller's recent missions (archived ones only when asked for)."""
    tasks = (await db.execute(
        select(Task).join(Workspace, Workspace.id == Task.workspace_id)
        .where(Task.task_type == "command", Workspace.owner_id == UUID(str(operator)))
        .order_by(Task.created_at.desc()).limit(limit * 4 if not include_archived else limit)
    )).scalars().all()
    if not include_archived:
        tasks = [t for t in tasks if not _archived(t)][:limit]
    items: List[CommandHistoryItem] = []
    for t in tasks:
        res = t.result if isinstance(t.result, dict) else {}
        items.append(CommandHistoryItem(
            task_id=str(t.id), command=t.title, status=lifecycle.normalise(t.status),
            response_text=res.get("response"), selected_agents=res.get("selected_agents", []),
            created_at=_iso(t.created_at) or "", completed_at=_iso(t.completed_at),
            error=t.error_message, folder=_folder(t), archived=_archived(t),
        ))
    return items


class WorkingAgent(BaseModel):
    id: str
    role: str
    status: str
    doing: Optional[str] = None


class WorkingMission(BaseModel):
    task_id: str
    title: str
    status: str
    agents: List[WorkingAgent] = []


_WORKING_STATES = ("running", "queued", "recovering", "needs_continuation", "waiting_on_approval")


@router.get("/working", response_model=List[WorkingMission])
async def working_now(operator: CurrentUserId, db: AsyncSession = Depends(get_db)) -> List[WorkingMission]:
    """The caller's missions in progress and, for each, the agents on it with what each is doing now, from the
    mission's live progress record: the Command Center shows them around the orb."""
    from app.core.command import progress

    tasks = (await db.execute(
        select(Task).join(Workspace, Workspace.id == Task.workspace_id)
        .where(Task.task_type == "command", Workspace.owner_id == UUID(str(operator)),
               Task.status.in_(_WORKING_STATES))
        .order_by(Task.created_at.desc()).limit(3)
    )).scalars().all()
    out: List[WorkingMission] = []
    for task in tasks:
        record = await progress.load(task.id) or {}
        packages = ((record.get("team") or {}).get("packages")) or []
        agents = [WorkingAgent(id=str(p.get("id") or ""), role=str(p.get("role") or p.get("title") or "Agent")[:60],
                               status=str(p.get("status") or "planned"),
                               doing=(str(p.get("doing_now"))[:140] if p.get("doing_now") else None))
                  for p in packages if isinstance(p, dict) and p.get("status") in ("working", "planned")]
        from app.core.creative import render_jobs

        job = render_jobs.rendering(task.meta_data)
        if job is not None:  # a render with no AI on it: the card says so, with the time so far
            agents = [WorkingAgent(id="RENDER", role="Renderer", status="working",
                                   doing=render_jobs.card_line(job)[:140])]
        if not agents and lifecycle.normalise(task.status) == "running":
            said = record.get("agent_said") or record.get("phase")
            agents = [WorkingAgent(id="JAI", role="JAI", status="working", doing=str(said)[:140] if said else None)]
        out.append(WorkingMission(task_id=str(task.id), title=task.title[:160], status=lifecycle.normalise(task.status),
                                  agents=agents[:6]))
    return out


@router.get("/info", dependencies=[Depends(get_current_user_id)])
async def command_info() -> dict:
    """Active provider and model for the command UI (no secrets). Authenticated."""
    service = CommandService()
    return {"provider": service.provider_name, "model": service.model}
