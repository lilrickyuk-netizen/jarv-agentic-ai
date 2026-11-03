"""
JAI said no mission was running while the MYCO acceptance mission was between two rounds (status
needs_continuation): its voice counted only running, queued and recovering. Every way JAI answers "what's going
on" now counts a mission as in progress for as long as it is being worked on, and each conversation opens with
what is running and an instruction to check before answering.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.runtime import lifecycle
from app.core.voice import engine, live
from app.models.task import Task
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e4c_voice import _seed


async def _with(status: str, **result):
    from app.models.company_operations import LiveOperationsFeedItem

    async with AsyncTestingSessionLocal() as db:
        owner, ws_id = await _seed(db)
        now = datetime.now(timezone.utc)
        # Distinct start times: rows added in one transaction would otherwise share it, and "the latest
        # mission" would be a tie.
        db.add(Task(created_at=now - timedelta(hours=2), id=uuid4(), workspace_id=ws_id, title="Earlier mission", task_type="command",
                    status="completed", priority=5, meta_data={}, result={"response": "All done earlier."}))
        task = Task(id=uuid4(), workspace_id=ws_id, title="Bring MYCO Phase 0 into conformance",
                    task_type="command", status=status, priority=5, meta_data={}, created_at=now,
                    result={"response": "Round 1 stopped at its step limit.", **result})
        db.add(task)
        await db.flush()
        db.add(LiveOperationsFeedItem(id=uuid4(), workspace_id=ws_id, item_type="tool", severity="info",
                                      title="Tool: run_command", message="pnpm install --frozen-lockfile",
                                      related_task_id=task.id, requires_action=False, created_at=now,
                                      updated_at=now))
        await db.commit()
        mission = await live.run_tool(db, owner, "get_mission", {})
        status = await live.run_tool(db, owner, "get_status", {})
        recent = await live._recent_missions(db, owner)
        opening = await live.situation_block(db, owner)
        return mission, status, recent, opening


@pytest.mark.parametrize("status", [lifecycle.NEEDS_CONTINUATION, lifecycle.RUNNING, lifecycle.PENDING,
                                    lifecycle.QUEUED, "in_progress"])
def test_a_mission_being_worked_on_is_reported_as_in_progress(status):
    mission, reply, recent, opening = asyncio.run(_with(status, continuation_count=2))
    assert mission["in_progress"] is True and mission["title"].startswith("Bring MYCO")
    assert "result" not in mission  # the last round's report is not the result
    assert any("pnpm install" in line for line in mission["latest_activity"])
    assert reply["in_flight"] >= 1 and reply["running"] == ["Bring MYCO Phase 0 into conformance"]
    assert "Bring MYCO Phase 0" in reply["reply"] and "nothing is running" not in reply["reply"]
    current = next(m for m in recent if m["title"].startswith("Bring MYCO"))
    assert current["in_progress"] is True and "last_report" not in current
    assert "Missions in progress:" in opening and "Bring MYCO Phase 0" in opening and "pnpm install" in opening


def test_between_rounds_is_said_plainly():
    mission, _, recent, opening = asyncio.run(_with(lifecycle.NEEDS_CONTINUATION, continuation_count=2))
    assert mission["rounds_done"] == 2 and "next is queued" in mission["note"]
    assert next(m for m in recent if m.get("in_progress"))["between_rounds"] is True
    assert "between rounds, next round queued" in opening


def test_a_finished_mission_is_not_in_progress():
    mission, reply, _, opening = asyncio.run(_with(lifecycle.COMPLETED))
    assert "in_progress" not in mission and mission["result"].startswith("Round 1")
    assert "nothing is running" in reply["reply"]
    assert "No mission is in progress." in opening


def test_jai_checks_before_saying_what_is_running():
    text = live.instructions([])
    assert "before you say whether anything is running" in text and "never answer it from memory" in text
    assert engine.strip_wake("Jay, talk to me")[1] is True


# ----- a mission's live progress: where it is, step by step -----------------------------------------------------

CALLS = [
    {"tool": "read_file", "inputs": {"path": "MYCO_V3_SPEC.md"}, "success": True, "summary": "read 9000 bytes"},
    {"tool": "write_file", "inputs": {"path": ".python-version"}, "success": True, "summary": "wrote 7 bytes"},
    {"tool": "run_command", "inputs": {"command": "pnpm install --frozen-lockfile"}, "success": False,
     "summary": "exit=1: lockfile out of date", "output": {"exit_code": 1}},
    {"tool": "edit_file", "inputs": {"path": "package.json"}, "success": True, "summary": "edited"},
    {"tool": "write_file", "inputs": {"path": ".python-version"}, "success": True, "summary": "wrote 7 bytes"},
]
REQS = [{"id": "R1", "text": "Python pinned to 3.14.7", "status": "done", "evidence": ".python-version"},
        {"id": "R2", "text": "pnpm install passes with the locked versions", "status": "open", "evidence": ""},
        {"id": "R3", "text": "README claims match the files", "status": "open", "evidence": ""}]


def test_progress_says_exactly_where_a_mission_is():
    from app.core.command.progress import snapshot

    p = snapshot(CALLS, REQS, round_no=3, step=17, step_budget=40, phase="working",
                 usage={"calls": 17, "input": 1000, "cached": 9000, "output": 400, "cost_usd": 0.0123})
    assert (p["phase"], p["round"], p["step"]) == ("working", 3, 17)
    assert p["files_changed"] == [".python-version", "package.json"] and p["files_changed_count"] == 2
    assert p["commands_run"] == 1 and p["commands_failed"] == 1
    assert p["recent_failures"][0] == {"tool": "run_command", "target": "pnpm install --frozen-lockfile",
                                       "why": "exit=1: lockfile out of date"}
    assert p["requirements"]["by_status"] == {"done": 1, "open": 2}
    assert p["doing_now"]["target"] == ".python-version" and p["tokens"]["cost_usd"] == 0.0123


def test_progress_names_files_as_the_workspace_sees_them():
    from app.core.command.progress import snapshot

    calls = [{"tool": "write_file", "inputs": {"path": "C:\\Users\\lilri\\MYCO\\apps\\web\\package.json"},
              "success": True, "summary": "wrote"},
             {"tool": "write_file", "inputs": {"path": "/test_workspaces/myco/./.python-version"}, "success": True,
              "summary": "wrote"}]
    first = snapshot(calls[:1], [], round_no=1, step=1, step_budget=8, phase="working", root="C:\\Users\\lilri\\MYCO")
    second = snapshot(calls[1:], [], round_no=1, step=1, step_budget=8, phase="working", root="/test_workspaces/myco")
    assert first["files_changed"] == ["apps/web/package.json"] and second["files_changed"] == [".python-version"]


def test_a_running_mission_keeps_its_progress_after_every_step(monkeypatch):
    import shutil

    from app.core.command import agent_executor, progress
    from app.core.command.agent_executor import AgentExecutor
    from tests.test_upgrade3_artifact_graph import _Router
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    monkeypatch.setattr(agent_executor, "get_router", lambda: _Router())
    seen = []
    real_save = progress.save

    async def save(task_id, data):
        seen.append(data)
        return await real_save(task_id, data)

    monkeypatch.setattr(progress, "save", save)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            await AgentExecutor(rt, "test-model", host).run("Add sub(a, b) to src/app.py.", max_continuations=0)
            return await progress.load(rt.task_id)

    try:
        stored = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    working = [p for p in seen if p["phase"] == "working"]
    assert len(working) >= 4 and [p["step"] for p in working] == sorted(p["step"] for p in working)
    after_write = next(p for p in working if p["files_changed"])
    assert after_write["files_changed"] == ["src/app.py"] and after_write["requirements"]["total"] == 2
    assert any(p["requirements"]["by_status"].get("done") for p in working)  # requirement_status was recorded
    assert "independent check" in [p["phase"] for p in seen]
    assert stored == seen[-1]  # what the voice reads is the latest step


def test_the_voice_reports_from_the_mission_progress():
    from app.core.command import progress

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            task = Task(id=uuid4(), workspace_id=ws_id, title="Bring MYCO Phase 0 into conformance",
                        task_type="command", status=lifecycle.RUNNING, priority=5, meta_data={}, result={})
            db.add(task)
            await db.commit()
            await progress.save(task.id, progress.snapshot(CALLS, REQS, round_no=3, step=17, step_budget=40,
                                                           phase="working"))
            return (await live.run_tool(db, owner, "get_mission", {}), await live._recent_missions(db, owner),
                    await live.situation_block(db, owner))

    mission, recent, opening = asyncio.run(run())
    assert mission["progress"]["round"] == 3 and mission["progress"]["recent_failures"][0]["target"].startswith("pnpm")
    assert "requirements done and open" in mission["note"]
    brief = recent[0]["progress"]
    assert brief["requirements_done"] == 1 and brief["requirements_total"] == 3 and brief["commands_failed"] == 1
    assert brief["open"] == ["R2 pnpm install passes with the locked versions", "R3 README claims match the files"]
    assert "round 3 step 17, 1 of 3 requirements done, 2 files changed, 1 commands failed" in opening


def test_jai_reports_specifics_and_never_resumes_a_running_mission():
    text = live.instructions([])
    assert "keeping pace" in text and "Never use filler" in text  # named as forbidden filler
    assert "never call resume_mission for it" in text
    resume = next(t for t in live.TOOLS if t["name"] == "resume_mission")
    assert "Never for a mission in progress" in resume["description"]


# ----- the Tasks page counts a running mission as in progress ------------------------------------------------------

@pytest.mark.api
@pytest.mark.integration
@pytest.mark.parametrize("status", [lifecycle.RUNNING, lifecycle.NEEDS_CONTINUATION, lifecycle.QUEUED, "in_progress"])
def test_the_tasks_page_counts_a_running_mission_as_in_progress(client, signed_in, db_session, test_workspace,
                                                                 status):
    db_session.add(Task(id=uuid4(), workspace_id=test_workspace.id, title="MYCO conformance",
                        task_type="command", status=status, priority=5, meta_data={}, result={}))
    db_session.add(Task(id=uuid4(), workspace_id=test_workspace.id, title="Old", task_type="command",
                        status="completed", priority=5, meta_data={}, result={}))
    db_session.commit()
    stats = client.get("/api/tasks/stats").json()
    assert stats["in_progress_tasks"] == 1 and stats["completed_tasks"] == 1, stats
    listed = client.get("/api/tasks/list?task_status=in_progress").json()
    assert [t["title"] for t in listed] == ["MYCO conformance"]
