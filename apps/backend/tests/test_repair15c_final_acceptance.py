"""Repair 15c: final acceptance. Richard gives JARV a mission and JARV carries it through.

Through the authenticated API, as Richard uses it: a multi-agent mission is
submitted in the Command Center; the orchestrator plans it and delegates each
step to its registered specialist; the coding agent edits the workspace's code
and the verifier compiles it, both through their own authority-checked, logged
toolboxes on the real filesystem; the production go-live step reaches a hard
boundary and only that step pauses (boundary report, checkpoint, pending
approval) while the safe steps complete; every handoff is a child task, an
operations-feed entry and a delegation memory; Richard approves and JARV
resumes from the checkpoint and finishes the step; another operator sees none
of it.

Only the model is scripted (no provider credit is spent): the plan and each
agent's tool calls. The API, command service, orchestrator, runner, agents,
toolboxes, tools, permission policy, filesystem, command execution, boundary
workflow, approvals, resume and database are all real.
"""
import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AgentBase
from app.core.auth import get_current_user_id
from app.core.config import settings
from app.core.knowledge.catalog import specialist_knowledge
from app.core.knowledge.service import knowledge_service
from app.core.runtime.missions import set_session_factory
from app.main import app
from app.models.boundary import BoundaryReport
from app.models.company_operations import LiveOperationsFeedItem
from app.models.memory import Memory
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal

SANDBOX = Path("/tmp/jarv_sandbox")
MISSION = ("Delegate a multi-agent mission on MYCO: the coding agent adds a sub(a, b) function to src/app.py, "
           "the verifier confirms it compiles, then the production go-live.")
PLAN = {"tasks": [
    {"task_id": 1, "description": "Add a sub(a, b) function to src/app.py", "assigned_agent": "coding_agent",
     "dependencies": []},
    {"task_id": 2, "description": "Verify src/app.py compiles", "assigned_agent": "verifier", "dependencies": [1]},
    {"task_id": 3, "description": "Production go-live of the new version", "assigned_agent": "devops",
     "dependencies": [2], "requires_approval": True},
]}
NEW_CODE = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"


def _run(coro):
    return asyncio.run(coro)


class MissionRouter:
    """The model, scripted: the orchestrator's plan and each agent's tool calls."""

    def __init__(self):
        self.scripts = {
            "coding agent": [
                {"tools": [("read_file", {"path": "src/app.py"})]},
                {"tools": [("write_file", {"path": "src/app.py", "content": NEW_CODE})]},
                {"tools": [("finish", {"summary": "Added sub(a, b) to src/app.py.", "success": True,
                                       "outputs": ["src/app.py"]})]},
            ],
            "verifier": [
                {"tools": [("run_command", {"command": "python3 -m py_compile src/app.py"})]},
                {"tools": [("finish", {"summary": "src/app.py compiles; sub(a, b) is present.", "success": True})]},
            ],
            "devops": [
                {"tools": [("finish", {"summary": "Go-live checklist completed for the approved release.",
                                       "success": True})]},
            ],
        }
        self.agents_called = []

    def get_provider_info(self):
        return {"test": {"configured": True}}

    async def complete(self, request):
        system = request.system or ""
        if request.tools:
            agent = next((k for k in self.scripts if f"JARV's {k} agent" in system), None)
            self.agents_called.append(agent)
            queue = self.scripts.get(agent) or []
            turn = queue.pop(0) if queue else {"tools": [("finish", {"summary": "Nothing more to do.",
                                                                     "success": True})]}
            calls = [{"id": f"call-{agent}-{len(queue)}-{i}", "function": {"name": n, "arguments": json.dumps(a)}}
                     for i, (n, a) in enumerate(turn["tools"])]
            return SimpleNamespace(content="", tool_calls=calls, usage={"total_tokens": 20}, provider="test",
                                   model="test")
        prompt = " ".join(getattr(m, "content", "") or "" for m in request.messages)
        content = json.dumps(PLAN) if '"tasks"' in prompt else "Mission report: steps ran as recorded."
        return SimpleNamespace(content=content, tool_calls=[], usage={"total_tokens": 20}, provider="test",
                               model="test")


@pytest.fixture
def project():
    name = f"r15c-{uuid4().hex[:8]}"
    root = SANDBOX / name
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    yield f"/test_workspaces/{name}", root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def mission_runtime(monkeypatch):
    router = MissionRouter()
    for target in ("app.core.providers.get_router", "app.agents.orchestrator.get_router",
                   "app.core.command.service.get_router"):
        monkeypatch.setattr(target, lambda: router)
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "test-key-not-real")
    # Agents use their toolboxes whenever a mission gives them a session and a workspace, as in production.
    monkeypatch.setattr(AgentBase, "tools_enabled",
                        lambda self, ctx: ctx.db_session is not None and ctx.workspace_id is not None)
    monkeypatch.setenv("MISSION_EXECUTION_MODE", "sync")
    set_session_factory(AsyncTestingSessionLocal)
    yield router
    set_session_factory(None)


@pytest.mark.integration
@pytest.mark.api
def test_richard_gives_a_mission_and_jarv_carries_it_through(client, project, mission_runtime):
    root_host, root = project

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = uuid4(), uuid4()
            db.add(User(id=owner, username=f"richard{owner.hex[:6]}", email=f"richard{owner.hex[:6]}@t.io",
                        password_hash="x", is_active=True, is_admin=True))
            db.add(Workspace(id=ws_id, owner_id=owner, name="MYCO", slug=f"myco-{ws_id.hex[:8]}",
                             description="Booking platform", workspace_type="software", authority_level=7,
                             is_active=True, config={"root_path": root_host}))
            await knowledge_service.ingest(db, specialist_knowledge())
            await db.commit()
            return owner, ws_id

    owner, ws_id = _run(seed())
    anonymous = client.post("/api/command/execute", json={"command": MISSION, "workspace_id": str(ws_id)})
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        submitted = client.post("/api/command/execute", json={"command": MISSION, "workspace_id": str(ws_id)})
        mission = submitted.json()
        detail = client.get(f"/api/command/tasks/{mission['task_id']}").json()
        pending = client.get("/api/richard/pending").json()
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger = client.get(f"/api/command/tasks/{mission['task_id']}")
        stranger_pending = client.get("/api/richard/pending").json()
        app.dependency_overrides[get_current_user_id] = lambda: str(owner)
        code_after_mission = (root / "src" / "app.py").read_text()
        agents_before_approval = list(mission_runtime.agents_called)

        async def boundary():
            async with AsyncTestingSessionLocal() as db:
                return (await db.execute(select(BoundaryReport).where(BoundaryReport.workspace_id == ws_id))
                        ).scalars().all()

        reports = _run(boundary())
        decided = client.post(f"/api/richard/reports/{reports[0].id}/decision",
                              json={"approve": True, "reason": "Go live", "authority_granted": 8,
                                    "expiry_seconds": 3600}) if reports else None
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    async def records():
        async with AsyncTestingSessionLocal() as db:
            children = (await db.execute(select(Task).where(Task.workspace_id == ws_id,
                                                            Task.task_type == "subtask"))).scalars().all()
            feed = (await db.execute(select(LiveOperationsFeedItem).where(
                LiveOperationsFeedItem.workspace_id == ws_id))).scalars().all()
            memories = (await db.execute(select(Memory).where(Memory.workspace_id == ws_id,
                                                              Memory.memory_type == "delegation"))).scalars().all()
            return children, feed, memories

    children, feed, memories = _run(records())
    by_agent = {(c.context or {}).get("agent"): c for c in children}

    # The mission ran under the operator's own sign-in only.
    assert anonymous.status_code == 401
    assert submitted.status_code == 200, submitted.text

    # The orchestrator planned and delegated to the registered specialists, each through its own tools.
    assert mission["status"] == "waiting_on_approval", mission
    assert agents_before_approval[:3] == ["coding agent", "coding agent", "coding agent"]
    assert "verifier" in agents_before_approval and "devops" not in agents_before_approval
    assert code_after_mission == NEW_CODE  # the coding agent really changed the workspace
    assert by_agent["coding_agent"].status == "completed" and by_agent["verifier"].status == "completed"
    assert "compiles" in (by_agent["verifier"].result or {}).get("output", "")

    # Only the hard-boundary step paused; it was recorded for Richard with a checkpoint.
    assert by_agent["devops"].status == "waiting_on_approval"
    assert len(reports) == 1 and reports[0].workspace_id == ws_id
    assert any(p.get("boundary_report_id") == str(reports[0].id) for p in pending)
    assert stranger.status_code == 404 and stranger_pending == []

    # Every handoff is visible: child tasks, operations feed and delegation memory.
    assert sum(1 for f in feed if f.item_type == "delegation") == 3
    assert len(memories) == 3
    assert detail["status"] == "waiting_on_approval" and detail["events"]

    # Richard clears the gate; JARV resumes from the checkpoint and finishes the paused step.
    assert decided is not None and decided.status_code == 200, decided.text if decided else "no report"
    auto = decided.json()["auto_resume"]
    assert auto["dispatched"] is True and auto["result"]["resumed"] is True, auto
    assert "devops" in mission_runtime.agents_called
