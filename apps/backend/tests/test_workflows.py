"""
Workflows and councils on LangGraph (Richard, 10 November: "you stop writing briefs"). Real: LangGraph's graph,
interrupts and checkpointers (in memory, and Postgres for surviving a restart), JAI's database rows, the Approvals API
deciding a gate, and the one-minute tick. Stood in: starting a mission (a task row stands for it; no mission runs and
no provider credit is spent).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.core.auth import get_current_user_id
from app.core.command import work_type
from app.core.workflows import engine, service, templates
from app.main import app
from app.models import LiveOperationsFeedItem, WorkflowRun
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal

FOLDER = "C:\\Users\\lilri\\Projects\\PLEXECUTE_IMAGES"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def stand_ins(monkeypatch):
    """LangGraph in memory, gates opened on the test database, and missions stood in by task rows."""
    saver = InMemorySaver()

    @asynccontextmanager
    async def memory():
        yield saver

    started = []

    async def start_mission(state, step):
        async with AsyncTestingSessionLocal() as db:
            task = Task(id=uuid4(), workspace_id=UUID(state["workspace_id"]), title=step["title"],
                        description=step["brief"], task_type="command", status="running", priority=5,
                        meta_data={"workflow_run_id": state["run_id"], "workflow_step": step["id"]})
            db.add(task)
            await db.commit()
            started.append((step["id"], step["brief"]))
            return str(task.id)

    monkeypatch.setattr(engine, "postgres_saver", memory)
    monkeypatch.setattr(service, "_session_factory", lambda: AsyncTestingSessionLocal)
    monkeypatch.setattr(service, "PORTS", engine.Ports(start_mission=start_mission, open_gate=service.open_gate))
    yield started


async def _seed():
    async with AsyncTestingSessionLocal() as db:
        user_id, ws_id = uuid4(), uuid4()
        db.add(User(id=user_id, username=f"w{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                    password_hash="x", is_active=True, is_admin=False))
        db.add(Workspace(id=ws_id, owner_id=user_id, name="Plexecute", slug=f"plexecute-{ws_id.hex[:8]}",
                         description="", workspace_type="project", authority_level=5, is_active=True,
                         config={"root_path": FOLDER}))
        await db.commit()
        return user_id, ws_id


async def _start(user_id, ws_id, template="investor_outreach"):
    async with AsyncTestingSessionLocal() as db:
        workspace = (await db.execute(select(Workspace).where(Workspace.id == ws_id))).scalar_one()
        run = await service.start(db, user_id=user_id, workspace=workspace, template=template)
        return run.id


async def _get_run(run_id):
    async with AsyncTestingSessionLocal() as db:
        return (await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalar_one()


async def _finish(task_id, status, headline=None):
    async with AsyncTestingSessionLocal() as db:
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        task.status = status
        task.result = {"card": {"headline": headline}} if headline else {}
        await db.commit()


async def _tick():
    async with AsyncTestingSessionLocal() as db:
        return await service.tick(db)


def test_every_step_names_its_council_member_and_starts_fresh_work():
    for name, info in templates.TEMPLATES.items():
        for step in templates.steps(name, product="Plexecute", folder=FOLDER):
            if step.get("gate"):
                assert "Plexecute" in step["ask"] and "stays with you" in step["ask"]
                continue
            route = work_type.specialist_for(step["brief"])
            assert route["specialist"] == step["specialist"] and route["source"] == "workflow"
            assert FOLDER in step["brief"] and step["brief"].endswith(templates.NEW)
            assert not __import__("re").search(r"\b(carry on|continue|resume|pick up|left off|finish)\b",
                                               step["brief"], __import__("re").I), step["id"]
    assert templates.template_named("run investor outreach for Plexecute") == "investor_outreach"
    assert templates.template_named("grow the waiting list for Plexecute") == "waitlist_growth"
    assert templates.slug("my app") == "My-App"


def test_investor_outreach_runs_mission_by_mission_and_waits_for_richard_at_the_gate(client, stand_ins):
    user_id, ws_id = _run(_seed())
    run_id = _run(_start(user_id, ws_id))
    run = _run(_get_run(run_id))
    assert run.status == "waiting_mission" and run.current_step == "prospects" and run.product == "Plexecute"
    assert [s for s, _ in stand_ins] == ["prospects"] and stand_ins[0][1].startswith("Specialist: sales. In C:")
    assert "outreach/Plexecute-Prospects.xlsx" in stand_ins[0][1]

    assert _run(_tick())["waiting"] == 1  # the mission is still working: nothing moves
    _run(_finish(run.waiting_task_id, "completed", "38 investors found"))
    _run(_tick())
    run = _run(_get_run(run_id))
    assert run.current_step == "introductions" and [s for s, _ in stand_ins] == ["prospects", "introductions"]
    assert run.steps["results"]["prospects"]["headline"] == "38 investors found"

    _run(_finish(run.waiting_task_id, "partial"))  # done with gaps: the workflow goes on
    _run(_tick())
    run = _run(_get_run(run_id))
    assert run.status == "waiting_approval" and run.current_step == "review"
    gate_id = run.waiting_task_id

    async def gate():
        async with AsyncTestingSessionLocal() as db:
            return (await db.execute(select(Task).where(Task.id == gate_id))).scalar_one()
    blocked = _run(gate())
    assert blocked.status == "blocked" and blocked.task_type == service.GATE_TASK_TYPE
    assert blocked.meta_data["boundary_type"] == "workflow_gate" and "sending stays with you" in blocked.description

    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    listed = client.get("/api/approvals/command-blocks").json()
    assert any(item["task_id"] == str(gate_id) and item["boundary_type"] == "workflow_gate" for item in listed)
    approved = client.post(f"/api/approvals/command-blocks/{gate_id}/approve", json={"note": "sent the six"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "completed"
    run = _run(_get_run(run_id))
    assert run.status == "waiting_mission" and run.current_step == "follow_ups"
    assert stand_ins[-1][1].startswith("Specialist: content.")
    assert run.steps["results"]["review"] == {"status": "approved", "note": "sent the six"}

    _run(_finish(run.waiting_task_id, "completed"))
    _run(_tick())
    run = _run(_get_run(run_id))
    assert run.status == "completed" and run.finished_at is not None and run.waiting_task_id is None
    described = service.describe(run)
    assert [s["status"] for s in described["steps"]] == ["completed", "partial", "approved", "completed"]

    async def feed():
        async with AsyncTestingSessionLocal() as db:
            return (await db.execute(select(LiveOperationsFeedItem.title).where(
                LiveOperationsFeedItem.workspace_id == ws_id, LiveOperationsFeedItem.item_type == "workflow")
            )).scalars().all()
    titles = _run(feed())
    assert "Investor outreach for Plexecute: started" in titles and "Investor outreach for Plexecute: done" in titles
    assert "Investor outreach for Plexecute: waiting for you" in titles
    app.dependency_overrides.pop(get_current_user_id, None)


def test_a_failed_mission_or_a_rejected_gate_stops_the_workflow(client, stand_ins):
    user_id, ws_id = _run(_seed())
    run_id = _run(_start(user_id, ws_id, "waitlist_growth"))
    _run(_finish(_run(_get_run(run_id)).waiting_task_id, "failed"))
    _run(_tick())
    run = _run(_get_run(run_id))
    assert run.status == "stopped" and "Find the audiences" in run.stopped_reason and len(stand_ins) == 1

    user_id, ws_id = _run(_seed())
    run_id = _run(_start(user_id, ws_id, "waitlist_growth"))
    for _ in range(2):
        _run(_finish(_run(_get_run(run_id)).waiting_task_id, "completed"))
        _run(_tick())
    gate_id = _run(_get_run(run_id)).waiting_task_id
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    rejected = client.post(f"/api/approvals/command-blocks/{gate_id}/reject", json={})
    assert rejected.status_code == 200 and rejected.json()["status"] == "cancelled"
    run = _run(_get_run(run_id))
    assert run.status == "stopped" and "Richard stopped the workflow" in run.stopped_reason
    app.dependency_overrides.pop(get_current_user_id, None)


def test_a_step_never_starts_while_another_mission_works_in_the_folder(stand_ins):
    user_id, ws_id = _run(_seed())
    run_id = _run(_start(user_id, ws_id))
    _run(_finish(_run(_get_run(run_id)).waiting_task_id, "completed"))

    async def other():
        async with AsyncTestingSessionLocal() as db:
            task = Task(id=uuid4(), workspace_id=ws_id, title="Richard's own mission", description="d",
                        task_type="command", status="running", priority=5)
            db.add(task)
            await db.commit()
            return task.id
    busy = _run(other())
    assert _run(_tick())["moved"] == 0 and len(stand_ins) == 1
    _run(_finish(busy, "completed"))
    _run(_tick())
    assert len(stand_ins) == 2 and _run(_get_run(run_id)).current_step == "introductions"


def test_one_workflow_per_workspace_and_a_folder_is_needed(client, stand_ins):
    user_id, ws_id = _run(_seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    catalogue = client.get("/api/workflows").json()
    assert {w["id"] for w in catalogue} == {"investor_outreach", "waitlist_growth"}
    outreach = next(w for w in catalogue if w["id"] == "investor_outreach")
    assert outreach["council"] == ["Sales Lead", "Content Lead"] and outreach["steps"][2]["specialist"] == "You"
    started = client.post("/api/workflows/start", json={"template": "investor_outreach", "workspace_id": str(ws_id)})
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "waiting_mission"
    again = client.post("/api/workflows/start", json={"template": "waitlist_growth", "workspace_id": str(ws_id)})
    assert again.status_code == 409 and "already running" in again.json()["detail"]
    runs = client.get("/api/workflows/runs").json()
    assert runs[0]["title"] == "Investor outreach for Plexecute" and runs[0]["steps"][0]["status"] == "in progress"
    cancelled = client.post(f"/api/workflows/runs/{runs[0]['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    unknown = client.post("/api/workflows/start", json={"template": "world_domination", "workspace_id": str(ws_id)})
    assert unknown.status_code == 409 and "Investor outreach" in unknown.json()["detail"]
    app.dependency_overrides.pop(get_current_user_id, None)

    async def without_folder():
        async with AsyncTestingSessionLocal() as db:
            workspace = Workspace(id=uuid4(), owner_id=user_id, name="Bare", slug=f"bare-{uuid4().hex[:8]}",
                                  description="", workspace_type="project", authority_level=5, is_active=True,
                                  config={})
            db.add(workspace)
            await db.commit()
            try:
                await service.start(db, user_id=user_id, workspace=workspace, template="investor_outreach")
            except service.WorkflowError as exc:
                return str(exc)
    assert "has no folder" in _run(without_folder())


def test_a_workflow_survives_a_restart_in_postgres(monkeypatch):
    """LangGraph's Postgres checkpointer on JAI's database: the pause is still there in a new connection."""
    from app.core.config import settings

    if "postgresql" not in str(settings.DATABASE_URL):
        pytest.skip("needs JAI's Postgres database")
    monkeypatch.undo()  # the real checkpointer, not the in-memory one
    starts = []

    async def start_mission(state, step):
        starts.append(step["id"])
        return str(uuid4())

    async def open_gate(state, step):
        return str(uuid4())

    ports = engine.Ports(start_mission=start_mission, open_gate=open_gate)
    steps = templates.steps("investor_outreach", product="Plexecute", folder=FOLDER)
    run_id = str(uuid4())
    first = {"run_id": run_id, "template": "investor_outreach", "product": "Plexecute", "folder": FOLDER,
             "workspace_id": str(uuid4()), "user_id": str(uuid4()), "tasks": {}, "results": {}, "stopped": None}

    async def before_restart():
        async with engine.postgres_saver() as saver:
            return await engine.advance(steps, ports, saver, run_id, start=first)

    async def after_restart():
        async with engine.postgres_saver() as saver:
            return await engine.advance(steps, ports, saver, run_id, resume={"status": "completed"})

    paused = _run(before_restart())
    assert paused["paused"]["kind"] == "mission" and paused["paused"]["step"] == "prospects"
    resumed = _run(after_restart())
    assert resumed["paused"]["step"] == "introductions" and starts == ["prospects", "introductions"]
    assert resumed["state"]["results"]["prospects"]["status"] == "completed"
