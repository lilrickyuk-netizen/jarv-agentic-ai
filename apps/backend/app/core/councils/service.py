"""
JAI Backend - Running workflows: start, move on, gates, cancel

A workflow run moves forward in three ways, each through LangGraph (engine.advance) under a per-run lock:
  - start: Richard starts it ("run investor outreach for Plexecute"); the first mission starts.
  - tick: every minute (Celery beat, workflows_advance) each run waiting on a mission is checked; when the mission
    has finished, the run is resumed with how it went, and the next step starts.
  - gate: Richard approves or rejects a workflow gate on the Approvals page; the decision is kept on the run and the
    run is resumed.
A run never starts a step while another mission is working in the same workspace (two missions in one folder undo
each other's work): it waits for the next tick. Every change is written to the Live Operations feed.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.councils import engine, templates

logger = logging.getLogger(__name__)

GATE = "workflow_gate"
GATE_TASK_TYPE = "workflow_gate"
LOCK_SECONDS = 600
OPEN = ("running", "waiting_mission", "waiting_approval")


class WorkflowError(ValueError):
    """A workflow cannot be started or changed, with the reason in words Richard can act on."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _feed(db: AsyncSession, run: Any, title: str, message: str, *, severity: str = "info",
          task_id: Optional[UUID] = None, requires_action: bool = False) -> None:
    from app.models import LiveOperationsFeedItem

    db.add(LiveOperationsFeedItem(
        id=uuid4(), workspace_id=run.workspace_id, item_type="workflow", severity=severity,
        title=title[:200], message=message[:2000], related_task_id=task_id, requires_action=requires_action,
        created_at=_now(), updated_at=_now()))


# ----- the ports: what a step does in JAI ---------------------------------------------------------------------------

def _session_factory():
    from app.core.database import AsyncSessionLocal

    return AsyncSessionLocal


async def start_mission(state: Dict[str, Any], step: Dict[str, Any]) -> str:
    """Submit the step's mission in the run's workspace, as Richard, and send it to a worker."""
    from app.core.command import CommandService
    from app.core.runtime import lifecycle
    from app.models.task import Task

    async with _session_factory()() as db:
        submitted = await CommandService().submit(step["brief"], db, workspace_id=UUID(state["workspace_id"]),
                                                  user_id=UUID(state["user_id"]) if state.get("user_id") else None,
                                                  operator=state.get("user_id"))
        task = (await db.execute(select(Task).where(Task.id == UUID(submitted.task_id)))).scalar_one()
        task.meta_data = {**(task.meta_data or {}), "channel": "workflow", "workflow_run_id": state["run_id"],
                          "workflow_step": step["id"]}
        # Shown as the step's name ("Waiting-list growth for Plexecute: Find the audiences"), not its brief.
        title = _title(state)
        task.title = f"{title} for {state['product']}: {step['title']}"[:500]
        await db.commit()
    if submitted.status == lifecycle.QUEUED:
        from app.core.runtime.dispatcher import dispatch_mission

        await dispatch_mission(submitted.task_id, reason=f"workflow step {step['id']}")
    return str(submitted.task_id)


async def open_gate(state: Dict[str, Any], step: Dict[str, Any]) -> str:
    """An approval on the Approvals page: approving it lets the workflow go on, rejecting it stops it."""
    from app.models.task import Task

    title = _title(state)
    async with _session_factory()() as db:
        gate = Task(id=uuid4(), title=f"{title} for {state['product']}: {step['title']}"[:500],
                    description=step["ask"], task_type=GATE_TASK_TYPE, workspace_id=UUID(state["workspace_id"]),
                    status="blocked", context={},
                    meta_data={"boundary_type": GATE, "blocked_reason": step["ask"],
                               "workflow_run_id": state["run_id"], "workflow_step": step["id"]})
        db.add(gate)
        await db.commit()
        return str(gate.id)


PORTS = engine.Ports(start_mission=start_mission, open_gate=open_gate)


def _title(state: Dict[str, Any]) -> str:
    """The workflow's name: the Orchestrator's plan carries its own, a template's is looked up."""
    return str(state.get("title") or templates.TEMPLATES.get(state.get("template", ""), {}).get("title")
               or "Workflow")


def _info(run: Any) -> Dict[str, Any]:
    """What the run is following: the Orchestrator's plan kept on the run, or its template."""
    planned = (run.steps or {}).get("plan")
    if isinstance(planned, dict) and planned.get("steps"):
        return planned
    return templates.TEMPLATES.get(run.template, {"title": run.template, "steps": []})


def _steps(run: Any) -> List[Dict[str, Any]]:
    """The run's steps as the engine runs them."""
    planned = (run.steps or {}).get("plan")
    if isinstance(planned, dict) and planned.get("steps"):
        return list(planned["steps"])
    return templates.steps(run.template, product=run.product, folder=(run.steps or {}).get("folder", ""))


# ----- moving a run on ---------------------------------------------------------------------------------------------

@asynccontextmanager
async def _locked(run_id: Any) -> AsyncIterator[bool]:
    """One move of a run at a time, across workers; False when another holds it."""
    from app.core.redis import get_redis

    key = f"workflow:lock:{run_id}"
    redis = await get_redis()
    got = bool(await redis.set(key, "1", nx=True, ex=LOCK_SECONDS))
    try:
        yield got
    finally:
        if got:
            await redis.delete(key)


async def _busy(db: AsyncSession, workspace_id: UUID, except_task: Optional[UUID] = None) -> Optional[Any]:
    """A mission working in this workspace now (not the one the run waits for)."""
    from app.core.runtime import lifecycle
    from app.models.task import Task

    rows = (await db.execute(select(Task).where(
        Task.workspace_id == workspace_id, Task.task_type != GATE_TASK_TYPE,
        Task.status.in_([lifecycle.RUNNING, lifecycle.QUEUED, lifecycle.RECOVERING]))
    )).scalars().all()
    return next((t for t in rows if t.id != except_task and not (t.meta_data or {}).get("archived_at")), None)


def _apply(db: AsyncSession, run: Any, outcome: Dict[str, Any]) -> None:
    """Record where the run is after LangGraph moved it, and tell the feed."""
    state = outcome.get("state") or {}
    steps = dict(run.steps or {})
    steps.update({"tasks": state.get("tasks") or {}, "results": state.get("results") or {}})
    steps.pop("pending_resume", None)
    run.steps = steps
    paused = outcome.get("paused")
    titles = {s["id"]: s["title"] for s in _info(run)["steps"]}
    if paused:
        run.current_step = paused.get("step")
        run.waiting_task_id = UUID(paused["task_id"]) if paused.get("task_id") else None
        title = titles.get(run.current_step, run.current_step)
        if paused.get("kind") == "gate":
            run.status = "waiting_approval"
            _feed(db, run, f"{run.title}: waiting for you", f"“{title}” is on the Approvals page.",
                  severity="warning", task_id=run.waiting_task_id, requires_action=True)
        else:
            run.status = "waiting_mission"
            _feed(db, run, f"{run.title}: {title}", f"Step “{title}” has started as a mission.",
                  task_id=run.waiting_task_id)
    elif outcome.get("finished"):
        run.waiting_task_id = None
        run.finished_at = _now()
        if state.get("stopped"):
            run.status, run.stopped_reason = "stopped", str(state["stopped"])
            _feed(db, run, f"{run.title}: stopped", run.stopped_reason, severity="warning")
        else:
            run.status, run.current_step = "completed", None
            _feed(db, run, f"{run.title}: done", "Every step of the workflow is done.", severity="success")


async def _advance(db: AsyncSession, run: Any, *, start: Optional[Dict[str, Any]] = None,
                   resume: Optional[Dict[str, Any]] = None, saver_factory: Optional[Callable] = None,
                   ports: Optional[engine.Ports] = None) -> bool:
    """Move the run through LangGraph once, under its lock. False when another worker is moving it."""
    async with _locked(run.id) as got:
        if not got:
            return False
        steps = _steps(run)
        async with (saver_factory or engine.postgres_saver)() as saver:
            outcome = await engine.advance(steps, ports or PORTS, saver, str(run.id), start=start, resume=resume)
        _apply(db, run, outcome)
        await db.commit()
        return True


def _folder(workspace: Any) -> Optional[str]:
    config = workspace.config if isinstance(workspace.config, dict) else {}
    return config.get("root_path")


async def start(db: AsyncSession, *, user_id: UUID, workspace: Any, template: str,
                saver_factory: Optional[Callable] = None, ports: Optional[engine.Ports] = None,
                launched_by: Optional[UUID] = None) -> Any:
    """Start a workflow in Richard's workspace: the product is the workspace's name, the folder its folder.
    launched_by: the command task that asked for it, which is not a mission working in the folder."""
    from app.models import WorkflowRun

    if template not in templates.TEMPLATES:
        raise WorkflowError(f"There is no workflow called {template!r}. There are: "
                            + ", ".join(t["title"] for t in templates.TEMPLATES.values()) + ".")
    folder = _folder(workspace)
    if not folder:
        raise WorkflowError(f"The {workspace.name} workspace has no folder, so a workflow has nowhere to work.")
    running = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.workspace_id == workspace.id, WorkflowRun.status.in_(OPEN)))).scalars().first()
    if running is not None:
        raise WorkflowError(f"“{running.title}” is already running in {workspace.name}; one workflow per "
                            "workspace at a time.")
    busy = await _busy(db, workspace.id, except_task=launched_by)
    if busy is not None:
        raise WorkflowError(f"A mission (“{(busy.title or '')[:80]}”) is working in {workspace.name} now; "
                            "start the workflow when it has finished.")
    info = templates.TEMPLATES[template]
    run = WorkflowRun(id=uuid4(), workspace_id=workspace.id, user_id=user_id, template=template,
                      title=f"{info['title']} for {workspace.name}", product=workspace.name, status="running",
                      steps={"folder": folder, "order": [s["id"] for s in info["steps"]]})
    db.add(run)
    _feed(db, run, f"{run.title}: started", info["summary"].format(product=workspace.name))
    await db.commit()
    first = {"run_id": str(run.id), "template": template, "title": info["title"], "product": workspace.name,
             "folder": folder, "workspace_id": str(workspace.id), "user_id": str(user_id), "tasks": {},
             "results": {}, "stopped": None}
    await _advance(db, run, start=first, saver_factory=saver_factory, ports=ports)
    return run


async def start_planned(db: AsyncSession, *, user_id: UUID, workspace: Any, planned: Dict[str, Any],
                        saver_factory: Optional[Callable] = None, ports: Optional[engine.Ports] = None,
                        launched_by: Optional[UUID] = None) -> Any:
    """Start the Orchestrator's plan for a mission that needs several agents (councils/planner): the same engine,
    rules and gates as a template, with the plan kept on the run."""
    from app.core.councils import planner
    from app.models import WorkflowRun

    folder = _folder(workspace)
    if not folder:
        raise WorkflowError(f"The {workspace.name} workspace has no folder, so the plan has nowhere to work.")
    running = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.workspace_id == workspace.id, WorkflowRun.status.in_(OPEN)))).scalars().first()
    if running is not None:
        raise WorkflowError(f"\u201c{running.title}\u201d is already running in {workspace.name}; one workflow per "
                            "workspace at a time.")
    busy = await _busy(db, workspace.id, except_task=launched_by)
    if busy is not None:
        raise WorkflowError(f"A mission (\u201c{(busy.title or '')[:80]}\u201d) is working in {workspace.name} now.")
    steps = planner.fill(planned, product=workspace.name, folder=folder)
    agents = [s["specialist"] for s in steps if not s.get("gate")]
    plan = {"title": planned["title"], "council": list(dict.fromkeys(agents)), "steps": steps,
            "summary": "The Orchestrator split this mission across " + ", ".join(dict.fromkeys(agents)) + "."}
    run = WorkflowRun(id=uuid4(), workspace_id=workspace.id, user_id=user_id, template=planner.PLANNED,
                      title=f"{planned['title']} for {workspace.name}"[:200], product=workspace.name,
                      status="running", steps={"folder": folder, "order": [s["id"] for s in steps], "plan": plan})
    db.add(run)
    _feed(db, run, f"{run.title}: started", plan["summary"])
    await db.commit()
    first = {"run_id": str(run.id), "template": planner.PLANNED, "title": planned["title"],
             "product": workspace.name, "folder": folder, "workspace_id": str(workspace.id),
             "user_id": str(user_id), "tasks": {}, "results": {}, "stopped": None}
    await _advance(db, run, start=first, saver_factory=saver_factory, ports=ports)
    return run


async def tick(db: AsyncSession, *, saver_factory: Optional[Callable] = None,
               ports: Optional[engine.Ports] = None) -> Dict[str, int]:
    """Move on every run whose mission has finished or whose gate Richard decided, when its workspace is free."""
    from app.core.runtime import lifecycle
    from app.models import WorkflowRun
    from app.models.task import Task

    moved = waiting = 0
    runs = (await db.execute(select(WorkflowRun).where(WorkflowRun.status.in_(OPEN)))).scalars().all()
    for run in runs:
        resume = (run.steps or {}).get("pending_resume")
        if resume is None and run.status == "waiting_mission" and run.waiting_task_id:
            task = (await db.execute(select(Task).where(Task.id == run.waiting_task_id))).scalar_one_or_none()
            status = lifecycle.normalise(task.status) if task is not None else lifecycle.FAILED
            if status not in lifecycle.TERMINAL:
                waiting += 1
                continue
            card = (task.result or {}).get("card") if task is not None and isinstance(task.result, dict) else None
            resume = {"status": status, "headline": (card or {}).get("headline")}
        if resume is None:
            continue
        if await _busy(db, run.workspace_id, except_task=run.waiting_task_id) is not None:
            waiting += 1
            continue
        try:
            moved += int(await _advance(db, run, resume=resume, saver_factory=saver_factory, ports=ports))
        except Exception as exc:  # noqa: BLE001 - one run's failure never stops the others
            logger.exception(f"workflow {run.id} could not move on: {exc}")
            await db.rollback()
    return {"moved": moved, "waiting": waiting, "open": len(runs)}


async def gate_decided(db: AsyncSession, gate: Any, *, approved: bool, note: Optional[str] = None,
                       saver_factory: Optional[Callable] = None, ports: Optional[engine.Ports] = None) -> Optional[Any]:
    """Richard approved or rejected a workflow gate: keep the decision on its run and move the run on now if its
    workspace is free (otherwise the next tick does)."""
    from app.models import WorkflowRun

    run_id = (gate.meta_data or {}).get("workflow_run_id")
    if not run_id:
        return None
    run = (await db.execute(select(WorkflowRun).where(WorkflowRun.id == UUID(str(run_id))))).scalar_one_or_none()
    if run is None or run.status != "waiting_approval":
        return run
    run.steps = {**(run.steps or {}), "pending_resume": {"approved": approved, "note": note}}
    run.status = "running"
    await db.commit()
    await tick(db, saver_factory=saver_factory, ports=ports)
    return run


async def cancel(db: AsyncSession, run: Any, *, actor: str) -> Any:
    """Stop a workflow: no further step starts. A mission it started is left to finish or be cancelled on its own
    page; an open gate is cancelled."""
    from app.core.runtime import lifecycle
    from app.models.task import Task

    if run.status not in OPEN:
        return run
    if run.status == "waiting_approval" and run.waiting_task_id:
        gate = (await db.execute(select(Task).where(Task.id == run.waiting_task_id))).scalar_one_or_none()
        if gate is not None and lifecycle.normalise(gate.status) == lifecycle.BLOCKED:
            lifecycle.transition(gate, lifecycle.CANCELLED, actor=actor, reason="workflow cancelled")
    run.status, run.finished_at, run.stopped_reason = "cancelled", _now(), f"Cancelled by {actor}."
    _feed(db, run, f"{run.title}: cancelled", "No further step will start.", severity="warning")
    await db.commit()
    return run


def describe(run: Any) -> Dict[str, Any]:
    """A run for the dashboard and the voice: where it is and how each step went."""
    info = _info(run)
    results = (run.steps or {}).get("results") or {}
    tasks = (run.steps or {}).get("tasks") or {}
    return {
        "id": str(run.id), "title": run.title, "template": run.template, "product": run.product,
        "status": run.status, "current_step": run.current_step, "stopped_reason": run.stopped_reason,
        "waiting_task_id": str(run.waiting_task_id) if run.waiting_task_id else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "steps": [{"id": s["id"], "title": s["title"], "gate": bool(s.get("gate")),
                   "specialist": s.get("specialist"), "task_id": tasks.get(s["id"]),
                   "status": (results.get(s["id"]) or {}).get("status")
                   or ("in progress" if s["id"] == run.current_step else "not started"),
                   "headline": (results.get(s["id"]) or {}).get("headline")} for s in info["steps"]],
    }


def catalogue() -> List[Dict[str, Any]]:
    """The workflows Richard can start, with their councils and steps."""
    from app.core.command.mission_org import SPECIALISTS

    return [{"id": name, "title": t["title"], "summary": t["summary"].replace("{product}", "the product"),
             "council": [SPECIALISTS[c]["title"] for c in t["council"]],
             "steps": [{"id": s["id"], "title": s["title"], "gate": bool(s.get("gate")),
                        "specialist": SPECIALISTS[s["specialist"]]["title"] if s.get("specialist") else "You"}
                       for s in t["steps"]]} for name, t in templates.TEMPLATES.items()]
