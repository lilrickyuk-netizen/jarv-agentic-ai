"""Live voice conversation, and missions surviving a failed log write on their own session.

Real: the database (PostgreSQL in the test run), the audit logger, the tool-run
logger, the mission status change, the authenticated live-conversation API and
its tools (status, missions under the approval gate, cancel, workspaces).
Outgoing OpenAI requests go to an httpx MockTransport (the 12e-4c fixture);
no provider is called.
"""
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, inspect, select

from app.core.audit import AuditLogger
from app.core.auth import get_current_user_id
from app.core.config import settings
from app.core.runtime import lifecycle
from app.core.tools.run_logging import write_tool_run
from app.core.voice import engine, live
from app.main import app
from app.models.agent import Agent
from app.models.operations import AuditLog
from app.models.task import Task
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e4c_voice import _seed, voice  # noqa: F401 - voice is a fixture


def _run(coro):
    return asyncio.run(coro)


# What a mission reads and writes after its agents run; none of it may be expired by a log write.
_MISSION_FIELDS = {"title", "status", "meta_data", "workspace_id", "result", "error_message"}


def _intact(task) -> bool:
    return not (_MISSION_FIELDS & set(inspect(task).expired_attributes))


async def _mission(db, owner, ws_id) -> Task:
    task = Task(workspace_id=ws_id, title="Add a sub function", description="Add a sub function",
                task_type="command", status=lifecycle.RUNNING, priority=5, meta_data={"channel": "typed"})
    db.add(task)
    await db.commit()
    return task


# ----- a mission's own session survives a failed log write -----------------------------------

def test_an_unregistered_agent_is_audited_on_the_mission_session_without_breaking_it():
    """The orchestrator runs in memory (no agents-table row); auditing it on the mission's session
    used to break the foreign key, roll the session back and crash the mission at its status change."""
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            task = await _mission(db, owner, ws_id)
            task.meta_data = {**task.meta_data, "step": "planned"}  # unsaved work on the same session
            instance = uuid4()
            entry = await AuditLogger.log_agent_complete(
                session=db, agent_name="orchestrator", result="success", execution_time=1.0,
                tokens_used={"total": 10}, cost_estimate=0.0, user_id=owner, workspace_id=ws_id,
                agent_id=instance, task_id=task.id)
            loaded = _intact(task)
            lifecycle.transition(task, lifecycle.COMPLETED, reason="done", actor="orchestrator")
            await db.commit()
            stored = (await db.execute(select(Task).where(Task.id == task.id))).scalar_one()
            return entry, instance, loaded, stored

    entry, instance, loaded, stored = _run(run())
    assert entry.agent_id is None and entry.meta_data["agent_instance_id"] == str(instance)
    assert loaded
    assert stored.status == lifecycle.COMPLETED and stored.meta_data["step"] == "planned"


def test_a_failed_audit_write_undoes_only_itself():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            task = await _mission(db, owner, ws_id)
            runner = uuid4()
            db.add(Agent(id=runner, name="coding_agent runtime", agent_type="coding_agent", workspace_id=ws_id,
                         is_active=True, config={}, allowed_tools=[], blocked_tools=[]))
            await db.commit()
            title = task.title
            def refuse(mapper, connection, target):
                raise RuntimeError("audit row refused by the database")

            # The database refuses the entry itself (as it refused the orchestrator's foreign key).
            event.listen(AuditLog, "before_insert", refuse)
            try:
                with pytest.raises(RuntimeError, match="refused by the database"):
                    await AuditLogger.log_agent_execution(session=db, agent_name="coding_agent", action="step",
                                                          result="success", user_id=owner, workspace_id=ws_id,
                                                          task_id=task.id)
            finally:
                event.remove(AuditLog, "before_insert", refuse)
            loaded = _intact(task) and task.title == title
            tool_logged = await write_tool_run(
                db, tool_name="read_file", tool_group="file", description="Read a file",
                input_schema_json={}, output_schema_json={}, minimum_authority_level=1,
                requires_approval=False, status="completed", success=True, input_data={"path": "a.py"},
                output_data={"ok": True}, error_message=None, started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc), authority_level_used=1, agent_id=runner)
            still_loaded = _intact(task)
            lifecycle.transition(task, lifecycle.COMPLETED, reason="done", actor="orchestrator")
            await db.commit()
            return loaded, title, tool_logged, still_loaded, task.status

    loaded, title, tool_logged, still_loaded, status = _run(run())
    assert loaded and title == "Add a sub function"
    assert tool_logged is True and still_loaded
    assert status == lifecycle.COMPLETED


# ----- live conversation ------------------------------------------------------------------------

@pytest.mark.api
def test_live_conversation_needs_the_openai_key_and_never_hands_it_to_the_browser(client, voice, monkeypatch):  # noqa: F811
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db)

    owner, _ws = _run(seed())
    anonymous = client.post("/api/voice/live/session")
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        unset = client.post("/api/voice/live/session")
        providers_unset = client.get("/api/voice/providers").json()["live"]
        monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-real")
        voice["routes"][("POST", live.REALTIME_SECRETS)] = lambda r, b: httpx.Response(
            200, json={"value": "ek_test_ephemeral", "expires_at": 1893456000, "session": {"type": "realtime"}})
        started = client.post("/api/voice/live/session")
        providers_set = client.get("/api/voice/providers").json()["live"]
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert anonymous.status_code == 401
    assert unset.status_code == 503 and "OPENAI_API_KEY" in unset.json()["detail"]
    assert providers_unset["ready"] is False and providers_set["ready"] is True
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["client_secret"] == "ek_test_ephemeral" and "sk-test" not in started.text
    request, raw = voice["requests"][-1]
    sent = json.loads(raw)
    assert request.headers["authorization"] == "Bearer sk-test-not-real"
    assert request.headers["openai-safety-identifier"] != str(owner)
    session = sent["session"]
    assert session["type"] == "realtime" and session["model"] == settings.OPENAI_REALTIME_MODEL
    assert {t["name"] for t in session["tools"]} == {"get_status", "start_mission", "get_mission",
                                                     "cancel_mission", "list_workspaces", "list_workspace_files",
                                                     "read_workspace_file"}
    assert "Never tell him you cannot access his files" in session["instructions"]
    assert "MYCO" in session["instructions"] and "Approvals page" in session["instructions"]
    assert session["audio"]["output"]["voice"] == settings.OPENAI_REALTIME_VOICE

    async def audit():
        async with AsyncTestingSessionLocal() as db:
            return (await db.execute(select(AuditLog).where(AuditLog.action == live.SESSION_ACTION,
                                                            AuditLog.user_id == owner))).scalars().all()

    assert len(_run(audit())) == 1


@pytest.mark.api
@pytest.mark.integration
def test_live_conversation_tools_act_as_the_operator_under_the_approval_gate(client, voice):  # noqa: F811
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            stranger, _other = await _seed(db)
            return owner, ws_id, stranger

    owner, ws_id, stranger_id = _run(seed())

    def call(name, **arguments):
        return client.post("/api/voice/live/tool", json={"name": name, "arguments": arguments})

    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        spaces = call("list_workspaces").json()
        mission = call("start_mission", instruction="Summarise what changed in MYCO this week", workspace="myco").json()
        detail = call("get_mission", task_id=mission["task_id"]).json()
        refused = call("start_mission", instruction="Approve the production release").json()
        status = call("get_status").json()
        cancelled = call("cancel_mission", workspace="MYCO").json()
        unknown_space = call("get_status", workspace="Pardosa").json()
        unknown_tool = call("send_email", to="x@y.z")
        app.dependency_overrides[get_current_user_id] = lambda: str(stranger_id)
        stranger = call("get_mission", task_id=mission["task_id"]).json()
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert spaces == {"workspaces": ["MYCO"]}
    assert mission["intent"] == "mission" and mission["task_id"]
    assert detail["task_id"] == mission["task_id"] and detail["title"]
    assert refused["intent"] == "approval_refused" and refused["task_id"] is None
    assert status["intent"] == "status"
    assert cancelled["intent"] == "cancel" and cancelled["task_id"] == mission["task_id"]
    assert "No workspace called Pardosa" in unknown_space["error"]
    assert unknown_tool.status_code == 404
    assert stranger == {"error": "No mission found."}

    async def records():
        async with AsyncTestingSessionLocal() as db:
            tools = (await db.execute(select(AuditLog).where(AuditLog.action == live.TOOL_ACTION,
                                                             AuditLog.user_id == owner))).scalars().all()
            tasks = (await db.execute(select(Task).where(Task.workspace_id == ws_id))).scalars().all()
            return tools, tasks

    tools, tasks = _run(records())
    assert len(tools) == 7  # every tool call the operator made is audited
    assert len(tasks) == 1 and (tasks[0].meta_data or {}).get("channel") == "voice"


def test_speech_service_failures_are_reported_not_crashed(voice, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "VOICEBOX_BASE_URL", "http://voicebox.test")
    monkeypatch.setattr(settings, "VOICEBOX_STT_MODEL", "small")
    wav = b"RIFF" + b"\x00" * 64

    def unreachable(request, body):
        raise httpx.ConnectError("connection refused", request=request)

    voice["routes"][("POST", "http://voicebox.test/transcribe")] = unreachable
    with pytest.raises(RuntimeError, match="Voicebox could not be reached"):
        _run(engine.transcribe(wav, filename="a.wav"))
    voice["routes"][("POST", "http://voicebox.test/transcribe")] = lambda r, b: httpx.Response(
        202, json={"detail": {"message": "downloading", "downloading": True}})
    with pytest.raises(RuntimeError, match="downloading the Whisper small model"):
        _run(engine.transcribe(wav, filename="a.wav"))
    voice["routes"][("POST", "http://voicebox.test/transcribe")] = lambda r, b: httpx.Response(200, json={"text": "Talk to me."})
    heard = _run(engine.transcribe(wav, filename="a.wav"))
    _request, body = voice["requests"][-1]
    assert heard["text"] == "Talk to me." and b'name="model"\r\n\r\nsmall' in body


# ----- worker: consecutive missions share one event loop -----------------------------------------

def test_consecutive_worker_tasks_reuse_clients_bound_to_the_first_loop():
    """A client created during one task (a database pool, Redis, a provider's HTTP client) is bound to
    that task's event loop. With asyncio.run per task the second task found it closed: "Event loop is
    closed". The worker's run_async keeps one loop per process."""
    from app.workers.tasks import run_async

    cached = {}

    async def task():
        loop = asyncio.get_running_loop()
        if "client" not in cached:
            cached["client"] = asyncio.Queue()  # bound to the loop it is first used on
            cached["loop"] = loop
        await cached["client"].put("job")
        return await cached["client"].get(), loop is cached["loop"]

    assert run_async(task()) == ("job", True)
    assert run_async(task()) == ("job", True)
    assert not cached["loop"].is_closed()


@pytest.mark.api
def test_live_conversation_reads_the_workspace_folder_and_stays_inside_it(client, voice):  # noqa: F811
    """JARV told Richard it could not access his files; it can look in each workspace's own folder."""
    import shutil
    from pathlib import Path

    name = f"live-{uuid4().hex[:8]}"
    root = Path("/tmp/jarv_sandbox") / name
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "MYCO-V3-spec.md").write_text("# MYCO V3\nAutonomous software engineering platform.\n")

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            owner, _ws = await _seed(db, host=f"/test_workspaces/{name}")
            bare, _other = await _seed(db)
            return owner, bare

    owner, bare = _run(seed())

    def call(name_, **arguments):
        return client.post("/api/voice/live/tool", json={"name": name_, "arguments": arguments}).json()

    try:
        app.dependency_overrides[get_current_user_id] = lambda: str(owner)
        top = call("list_workspace_files", workspace="MYCO")
        docs = call("list_workspace_files", workspace="MYCO", path="docs")
        spec = call("read_workspace_file", workspace="MYCO", path="docs/MYCO-V3-spec.md")
        escape = call("read_workspace_file", workspace="MYCO", path="../../etc/passwd")
        missing = call("read_workspace_file", workspace="MYCO", path="docs/nothing.md")
        app.dependency_overrides[get_current_user_id] = lambda: str(bare)
        no_folder = call("list_workspace_files", workspace="MYCO")
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
        shutil.rmtree(root, ignore_errors=True)

    assert top["entries"] == [{"name": "docs", "folder": True}]
    assert docs["entries"] == [{"name": "MYCO-V3-spec.md", "folder": False}]
    assert spec["content"].startswith("# MYCO V3") and spec["truncated"] is False
    assert escape == {"error": "That path is outside the workspace."}
    assert "error" in missing
    assert no_folder == {"error": "MYCO has no folder registered."}
