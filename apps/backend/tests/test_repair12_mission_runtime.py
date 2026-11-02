"""Repair 12a: mission runtime, recovery, and automatic resume.

Covers the enforced mission lifecycle, submit-then-dispatch, single-owner
claims, heartbeat-based recovery of missions whose worker died, honest closure
of legacy abandoned missions, repeated-loss failure, cancellation that a
finishing worker cannot overwrite, automatic continuation, the authenticated
command API (owner-scoped status, history, cancel, retry), approval that
re-queues and resumes the mission, and Richard decisions that resume the
paused mission without a second call.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.auth import get_current_user_id
from app.core.command import CommandService
from app.core.runtime import lifecycle
from app.core.runtime.missions import MissionRunner, cancel_mission, set_session_factory
from app.main import app
from app.models.company_operations import LiveOperationsFeedItem
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal


@pytest.fixture(autouse=True)
def runtime_on_test_db():
    set_session_factory(AsyncTestingSessionLocal)
    yield
    set_session_factory(None)


def _run(coro):
    return asyncio.run(coro)


async def _seed_owner(db):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="R12", slug=f"r12-{ws_id.hex[:8]}",
                     description="", workspace_type="test", authority_level=5, is_active=True))
    await db.commit()
    return user_id, ws_id


async def _mission(db, ws_id, status, **fields):
    task = Task(id=uuid4(), workspace_id=ws_id, title="m", description=fields.pop("description", "m"),
                task_type="command", status=status, priority=5, meta_data={"operator": "op"},
                created_at=datetime.now(timezone.utc), updated_at=fields.pop("updated_at", datetime.now(timezone.utc)),
                **fields)
    db.add(task)
    await db.commit()
    return task.id


async def _get(task_id):
    async with AsyncTestingSessionLocal() as db:
        return (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()


# ----- lifecycle --------------------------------------------------------------

def test_lifecycle_allows_only_defined_transitions_and_records_history():
    task = Task(id=uuid4(), workspace_id=uuid4(), title="t", task_type="command",
                status="pending", priority=5, meta_data={})
    lifecycle.transition(task, lifecycle.QUEUED, reason="accepted", actor="tester")
    lifecycle.transition(task, lifecycle.RUNNING, actor="worker")
    with pytest.raises(lifecycle.IllegalTransition):
        lifecycle.transition(task, lifecycle.PENDING)
    lifecycle.transition(task, lifecycle.COMPLETED)
    with pytest.raises(lifecycle.IllegalTransition):
        lifecycle.transition(task, lifecycle.QUEUED)
    history = task.meta_data["status_history"]
    assert [h["to"] for h in history] == ["queued", "running", "completed"]
    assert history[0]["actor"] == "tester" and history[0]["reason"] == "accepted"
    assert task.completed_at is not None
    assert lifecycle.normalise("approved") == lifecycle.BLOCKED


# ----- submit / claim / run ---------------------------------------------------------

@pytest.mark.integration
def test_submit_queues_safe_commands_and_blocks_approval_commands():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed_owner(db)
            service = CommandService()
            safe = await service.submit("Remember that the weekly review is on Thursday", db,
                                        workspace_id=ws_id, operator=str(user_id))
            risky = await service.submit("Delete the old customer records", db,
                                         workspace_id=ws_id, operator=str(user_id))
            stranger = str(uuid4())
            with pytest.raises(ValueError):
                await service.submit("Remember x", db, workspace_id=ws_id, operator=stranger)
            return safe, risky

    safe, risky = _run(run())
    assert safe.status == "queued" and risky.status == "blocked" and risky.requires_approval
    queued = _run(_get(UUID(safe.task_id)))
    assert [h["to"] for h in queued.meta_data["status_history"]] == ["queued"]


@pytest.mark.integration
def test_only_one_worker_can_claim_a_mission():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_id = await _seed_owner(db)
            task_id = await _mission(db, ws_id, "queued")
        async with AsyncTestingSessionLocal() as a, AsyncTestingSessionLocal() as b:
            first = await MissionRunner(worker_id="worker-a").claim(a, task_id)
            second = await MissionRunner(worker_id="worker-b").claim(b, task_id)
        return task_id, first, second

    task_id, first, second = _run(run())
    assert first is not None and second is None
    claimed = _run(_get(task_id))
    assert claimed.status == "running" and claimed.lease_owner == "worker-a"
    assert claimed.heartbeat_at is not None
    assert claimed.meta_data["status_history"][-1]["actor"] == "worker-a"


@pytest.mark.integration
def test_runner_executes_mission_end_to_end_and_releases_lease():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed_owner(db)
            submitted = await CommandService().submit(
                "Remember that the weekly review is on Thursday", db,
                workspace_id=ws_id, operator=str(user_id))
        outcome = await MissionRunner(worker_id="worker-a").run(submitted.task_id)
        return submitted, outcome

    submitted, outcome = _run(run())
    assert outcome["claimed"] is True
    task = _run(_get(UUID(submitted.task_id)))
    assert task.status == "completed", task.error_message
    assert task.lease_owner is None
    assert "weekly review" in task.result["response"]
    assert [h["to"] for h in task.meta_data["status_history"]] == ["queued", "running", "completed"]


# ----- recovery -------------------------------------------------------------------

@pytest.mark.integration
def test_recovery_requeues_missions_whose_worker_stopped_heartbeating(monkeypatch):
    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")
    old = datetime.now(timezone.utc) - timedelta(minutes=10)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_id = await _seed_owner(db)
            lost = await _mission(db, ws_id, "running", heartbeat_at=old, lease_owner="dead-worker",
                                  started_at=old, updated_at=old)
            fresh = await _mission(db, ws_id, "running", heartbeat_at=datetime.now(timezone.utc),
                                   lease_owner="live-worker")
            looping = await _mission(db, ws_id, "running", heartbeat_at=old, lease_owner="dead-worker",
                                     retry_count=2, updated_at=old)
            legacy = await _mission(db, ws_id, "running", updated_at=old - timedelta(hours=2))
        summary = await MissionRunner().recover_stale()
        return summary, lost, fresh, looping, legacy

    summary, lost, fresh, looping, legacy = _run(run())
    assert str(lost) in summary["recovered"]
    recovered = _run(_get(lost))
    assert recovered.status == "queued" and recovered.retry_count == 1 and recovered.lease_owner is None
    assert [h["to"] for h in recovered.meta_data["status_history"]][-2:] == ["recovering", "queued"]
    assert _run(_get(fresh)).status == "running"
    assert str(looping) in summary["failed"] and _run(_get(looping)).status == "failed"
    assert str(legacy) in summary["abandoned"] and _run(_get(legacy)).status == "failed"


@pytest.mark.integration
def test_recovered_mission_runs_again_in_sync_mode(monkeypatch):
    monkeypatch.setenv("MISSION_EXECUTION_MODE", "sync")
    old = datetime.now(timezone.utc) - timedelta(minutes=10)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed_owner(db)
            task_id = await _mission(
                db, ws_id, "running", heartbeat_at=old, lease_owner="dead-worker", updated_at=old,
                description="Remember that invoices go out on the first working day")
            task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
            task.meta_data = {"operator": str(user_id)}
            await db.commit()
        await MissionRunner().recover_stale()
        return task_id

    task = _run(_get(_run(run())))
    assert task.status == "completed", task.error_message
    assert task.retry_count == 1
    assert "first working day" in task.result["response"]


# ----- cancellation and continuation --------------------------------------------------

@pytest.mark.integration
def test_cancelled_mission_cannot_be_claimed_or_overwritten():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_id = await _seed_owner(db)
            queued = await _mission(db, ws_id, "queued")
            task = (await db.execute(select(Task).where(Task.id == queued))).scalar_one()
            assert await cancel_mission(db, task, actor="op") is True
            await db.commit()
            claim = await MissionRunner().claim(db, queued)

            running = await _mission(db, ws_id, "running")
            runner_view = (await db.execute(select(Task).where(Task.id == running))).scalar_one()
        async with AsyncTestingSessionLocal() as other:
            t = (await other.execute(select(Task).where(Task.id == running))).scalar_one()
            await cancel_mission(other, t, actor="op")
            await other.commit()
        async with AsyncTestingSessionLocal() as db:
            runner_view = (await db.execute(select(Task).where(Task.id == running))).scalar_one()
            final = await CommandService()._finish(db, runner_view, "completed", None)
            await db.commit()
        return claim, final, running

    claim, final, running = _run(run())
    assert claim is None
    assert final == "cancelled" and _run(_get(running)).status == "cancelled"


@pytest.mark.integration
def test_step_limited_mission_is_continued_automatically(monkeypatch):
    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_id = await _seed_owner(db)
            # continuation_count also counts the pauses inside each run (13 after one long round);
            # only the runner's own re-queues (auto_rounds) are capped.
            under = await _mission(db, ws_id, "needs_continuation",
                                   result={"continuation_count": 13, "auto_rounds": 1})
            capped = await _mission(db, ws_id, "needs_continuation", result={"auto_rounds": 6})
        runner = MissionRunner()
        return under, capped, await runner._auto_continue(under), await runner._auto_continue(capped)

    under, capped, continued, held = _run(run())
    assert continued is True and held is False
    resumed = _run(_get(under))
    assert resumed.status == "queued" and resumed.meta_data["resume_mode"] == "continuation"
    assert _run(_get(capped)).status == "needs_continuation"
    assert resumed.result["auto_rounds"] == 2


@pytest.mark.integration
def test_resuming_a_paused_mission_queues_it_on_the_worker(client, test_user, test_workspace, monkeypatch):
    """Resume used to run the next round inside the web request. It now queues the same mission on the worker,
    with a fresh allowance of automatic rounds, so leaving the dashboard cannot stop it."""
    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return (await _mission(db, test_workspace.id, "needs_continuation",
                                   result={"continuation_count": 13, "auto_rounds": 6, "mission": "Phase 0"}),
                    await _mission(db, test_workspace.id, "completed"))

    paused, done = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)
    resumed = client.post(f"/api/tasks/{paused}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "queued" and resumed.json()["resumed"] is True
    row = _run(_get(paused))
    assert row.status == "queued" and row.meta_data["resume_mode"] == "continuation"
    assert row.result["auto_rounds"] == 0 and row.result["continuation_count"] == 13
    assert client.post(f"/api/tasks/{done}/resume").status_code == 400


@pytest.mark.integration
def test_voice_carries_on_with_the_paused_mission_instead_of_starting_a_new_one(test_user, test_workspace,
                                                                              monkeypatch):
    """Asked by voice to resume the mission, JARV started a new mission that had none of the old one's
    progress. resume_mission queues the paused mission itself."""
    from app.core.voice.live import run_tool

    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            paused = await _mission(db, test_workspace.id, "needs_continuation",
                                    result={"mission": "Phase 0", "workspace_path": "/test_workspaces/myco"})
            before = (await db.execute(select(Task.id))).scalars().all()
            output = await run_tool(db, test_user.id, "resume_mission", {})
            after = (await db.execute(select(Task.id))).scalars().all()
            nothing = await run_tool(db, test_user.id, "resume_mission", {})
            return paused, output, len(before), len(after), nothing

    paused, output, before, after, nothing = _run(run())
    assert output["resumed"] is True and output["task_id"] == str(paused)
    assert after == before  # no new mission
    assert _run(_get(paused)).status == "queued"
    assert "no paused mission" in nothing["error"]


# ----- command API ------------------------------------------------------------------

@pytest.mark.integration
def test_command_api_runs_mission_and_scopes_status_history_and_controls(
    client, db_session, test_user, test_workspace, monkeypatch,
):
    monkeypatch.setenv("MISSION_EXECUTION_MODE", "sync")
    assert client.post("/api/command/execute", json={"command": "hi"}).status_code == 401

    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)
    done = client.post("/api/command/execute", json={
        "command": "Remember that support hours are 9 to 5", "workspace_id": str(test_workspace.id)})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "completed" and body["finished"] is True
    status = client.get(f"/api/command/tasks/{body['task_id']}").json()
    assert status["status"] == "completed" and status["events"]
    assert [h["to"] for h in status["status_history"]] == ["queued", "running", "completed"]
    assert client.get("/api/command/history").json()[0]["task_id"] == body["task_id"]

    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")
    queued = client.post("/api/command/execute", json={
        "command": "Remember that the office is closed on Monday", "workspace_id": str(test_workspace.id)}).json()
    assert queued["status"] == "queued" and queued["finished"] is False
    cancelled = client.post(f"/api/command/tasks/{queued['task_id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert client.post(f"/api/command/tasks/{queued['task_id']}/cancel").status_code == 409

    stranger = User(id=uuid4(), username="stranger", email="s@t.io", password_hash="x",
                    is_active=True, is_admin=False)
    db_session.add(stranger)
    db_session.commit()
    app.dependency_overrides[get_current_user_id] = lambda: str(stranger.id)
    assert client.get(f"/api/command/tasks/{body['task_id']}").status_code == 404
    assert client.get("/api/command/history").json() == []
    assert client.post("/api/command/execute", json={
        "command": "Remember y", "workspace_id": str(test_workspace.id)}).status_code == 400


@pytest.mark.integration
def test_approving_a_blocked_command_requeues_and_runs_it(
    client, db_session, test_user, test_workspace, monkeypatch,
):
    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")
    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)
    blocked = client.post("/api/command/execute", json={
        "command": "Delete the stale preview environment", "workspace_id": str(test_workspace.id)}).json()
    assert blocked["status"] == "blocked"
    listed = client.get("/api/approvals/command-blocks").json()
    assert [item["task_id"] for item in listed] == [blocked["task_id"]]

    stranger = User(id=uuid4(), username="other", email="o@t.io", password_hash="x",
                    is_active=True, is_admin=False)
    db_session.add(stranger)
    db_session.commit()
    app.dependency_overrides[get_current_user_id] = lambda: str(stranger.id)
    assert client.post(f"/api/approvals/command-blocks/{blocked['task_id']}/approve").status_code == 404
    assert client.get("/api/approvals/command-blocks").json() == []

    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)
    approved = client.post(f"/api/approvals/command-blocks/{blocked['task_id']}/approve",
                           json={"note": "go ahead"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "queued"
    task = _run(_get(UUID(blocked["task_id"])))
    assert task.meta_data["approval_grant"]["single_mission"] is True
    assert [h["to"] for h in task.meta_data["status_history"]] == ["blocked", "queued"]
    feed = _run(_feed_titles(task.id))
    assert "Approval granted" in feed


async def _feed_titles(task_id):
    async with AsyncTestingSessionLocal() as db:
        return [row.title for row in (await db.execute(
            select(LiveOperationsFeedItem).where(LiveOperationsFeedItem.related_task_id == task_id)
        )).scalars().all()]


@pytest.mark.integration
def test_richard_approval_resumes_the_paused_mission_automatically(client, monkeypatch):
    """Approving through the decision endpoint resumes the mission in the same
    call (sync mode), with no separate resume request."""
    from app.models.boundary import ResumeAction
    from tests.test_repair9_relational_contract import _seed_boundary

    monkeypatch.setenv("MISSION_EXECUTION_MODE", "sync")

    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s)
            return str(uid), res

    owner, res = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: owner
    decided = client.post(f"/api/richard/reports/{res['boundary_report_id']}/decision",
                          json={"approve": True, "reason": "ok", "authority_granted": 8,
                                "expiry_seconds": 3600})
    assert decided.status_code == 200, decided.text
    auto = decided.json()["auto_resume"]
    assert auto["dispatched"] is True and auto["result"]["resumed"] is True

    async def resumes():
        async with AsyncTestingSessionLocal() as s:
            return (await s.execute(select(ResumeAction))).scalars().all()
    assert len(_run(resumes())) == 1

    again = client.post(f"/api/richard/reports/{res['boundary_report_id']}/resume")
    assert again.status_code == 200 and again.json().get("idempotent") is True


@pytest.mark.integration
def test_missions_show_their_folder_and_can_be_closed_and_archived(client, test_user, test_workspace, monkeypatch):
    """A stray partial mission could not be closed or hidden, and the dashboard could not tell missions apart.
    Every mission now shows its folder; a partial one can be closed; any mission that is not running can be
    archived (hidden from the list, never deleted) and brought back."""
    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            real = await _mission(db, test_workspace.id, "partial",
                                  result={"workspace_path": "C:\\\\Users\\\\lilri\\\\Projects\\\\MYCO", "response": "Phase 0"})
            stray = await _mission(db, test_workspace.id, "partial", result={"response": "no folder"})
            running = await _mission(db, test_workspace.id, "running")
            paused = await _mission(db, test_workspace.id, "needs_continuation", result={"workspace_path": "/w"})
            return real, stray, running, paused

    real, stray, running, paused = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(test_user.id)
    view = client.get(f"/api/command/tasks/{real}").json()
    assert view["folder"].endswith("MYCO") and view["resumable"] is True and view["archived"] is False
    history = {h["task_id"]: h for h in client.get("/api/command/history").json()}
    assert history[str(real)]["folder"].endswith("MYCO") and history[str(stray)]["folder"] is None

    closed = client.post(f"/api/command/tasks/{stray}/cancel")
    assert closed.status_code == 200 and closed.json()["status"] == "cancelled"
    archived = client.post(f"/api/command/tasks/{stray}/archive")
    assert archived.status_code == 200 and archived.json()["archived"] is True
    assert str(stray) not in {h["task_id"] for h in client.get("/api/command/history").json()}
    assert str(stray) in {h["task_id"] for h in client.get("/api/command/history?include_archived=true").json()}
    assert client.post(f"/api/command/tasks/{running}/archive").status_code == 409

    parked = client.post(f"/api/command/tasks/{paused}/archive").json()
    assert parked["archived"] is True and parked["status"] == "cancelled"  # never continued again
    assert client.post(f"/api/tasks/{paused}/resume").status_code == 400

    restored = client.post(f"/api/command/tasks/{stray}/unarchive").json()
    assert restored["archived"] is False


@pytest.mark.integration
def test_voice_resumes_and_reports_the_mission_that_has_a_folder(test_user, test_workspace, monkeypatch):
    """Voice resumed the newest paused mission, a stray one with no folder, again and again. It now resumes
    the mission that works in a folder, and get_mission reads the report that missions store."""
    from app.core.voice.live import run_tool

    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            real = await _mission(db, test_workspace.id, "partial",
                                  result={"workspace_path": "C:\\\\Users\\\\lilri\\\\Projects\\\\MYCO",
                                          "response": "Phase 0 committed as f0a60a1."})
            report = await run_tool(db, test_user.id, "get_mission", {"task_id": str(real)})
            await _mission(db, test_workspace.id, "partial", result={"response": "no folder"})  # newer stray
            resumed = await run_tool(db, test_user.id, "resume_mission", {})
            return real, report, resumed

    real, report, resumed = _run(run())
    assert report["result"] == "Phase 0 committed as f0a60a1." and report["folder"].endswith("MYCO")
    assert resumed["resumed"] is True and resumed["task_id"] == str(real)
