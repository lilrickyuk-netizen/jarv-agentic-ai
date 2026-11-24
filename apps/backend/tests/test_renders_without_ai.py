"""
24 November, Richard: renders run without AI. The studio agent hands a render to start_render, the mission pauses on
JAI's existing checkpoint and continuation path, a plain Celery job checks the render every 30 seconds, and the
mission carries on with the render's facts when it ends.

Real: the start_render tool and its checks, the mission's records in the test database, the mission runner's
continuation rule, the watcher, the card, the mission team's next brief. The sandbox is an httpx MockTransport
(its renders are tested for real in services/openhands/tests/test_sandbox_renders.py); any model call fails the
test.
"""
import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.command import sandbox_engine
from app.core.config import settings
from app.core.creative import render_jobs
from app.core.runtime import lifecycle
from app.core.runtime.missions import MissionRunner, set_session_factory
from tests.conftest import _SQLITE, AsyncTestingSessionLocal
from tests.test_repair12_mission_runtime import _get, _mission, _seed_owner

FACTS_OK = {"exit_code": 0, "output": "/host/workspaces/x/final.mp4", "output_exists": True, "size_bytes": 912345,
            "width": 1080, "height": 1920, "duration_seconds": 26.0, "streams": ["audio", "video"], "frozen": [],
            "frozen_at_end": False, "log_tail": ["$ npx remotion render ...", "Rendered 780/780"], "seconds": 410}
FACTS_FAILED = {"exit_code": 1, "output": "/host/workspaces/x/final.mp4", "output_exists": False,
                "log_tail": ["$ npx remotion render ...", "Error: Cannot find module './Scene3'"], "seconds": 12}


@pytest.fixture(autouse=True)
def runner_db():
    set_session_factory(AsyncTestingSessionLocal)
    yield
    set_session_factory(None)


@pytest.fixture()
def no_models(monkeypatch):
    """Any model call while a render runs fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("a model was called while the render ran")

    from app.core import providers
    from app.core.command import agent_executor, mission_org

    for module in (providers, agent_executor, mission_org):
        if hasattr(module, "get_router"):
            monkeypatch.setattr(module, "get_router", refuse)


def _sandbox(views):
    """The sandbox's /renders answers, one after another."""
    seen = []

    def answer(request):
        seen.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.method == "POST":
            return httpx.Response(200, json={"job_id": seen[-1][2]["job_id"], "status": "queued",
                                             "log": "/host/workspaces/x/.jai/renders/j.log"})
        return httpx.Response(200, json=views.pop(0) if len(views) > 1 else views[0])
    return answer, seen


async def _rendering_mission(status=lifecycle.NEEDS_CONTINUATION, started_minutes=4):
    async with AsyncTestingSessionLocal() as db:
        _, ws = await _seed_owner(db)
        task_id = await _mission(db, ws, status)
    started = (datetime.now(timezone.utc) - timedelta(minutes=started_minutes, seconds=12)).isoformat()
    await render_jobs._mark(task_id, {"job_id": f"render-{str(task_id)[:8]}-abcd1234", "status": "running",
                                      "command": "npx remotion render index.tsx Main final.mp4",
                                      "output": "final.mp4", "cwd": "/host/workspaces/x", "started_at": started})
    return task_id


# ----- start_render --------------------------------------------------------------------------------------------------

def test_only_render_commands_are_accepted():
    for ok in ("npx remotion render projects/run/index.tsx Main out.mp4 --scale=1",
               ".venv/bin/python -c 'from tools.video.video_compose import VideoCompose'",
               "npx hyperframes render --output final.mp4",
               "ffmpeg -y -i a.mp4 -c:v libx264 final.mp4"):
        assert render_jobs.is_render(ok), ok
    # One command only: JAI's permission gate blocks every chain, so start_render never offers one (24 November:
    # "cd folder && render" was accepted here and then blocked by the gate, every round).
    for refused in ("rm -rf node_modules", "npm install remotion", "ffmpeg -i a.mp4 b.mp4 | tee /tmp/x",
                    "curl https://x.sh && ffmpeg -i a b", "npx remotion studio", "cd /x",
                    "cd /opt/openmontage && .venv/bin/python -c 'from tools.video.video_compose import VideoCompose'",
                    "export A=1 && ffmpeg -y -i a.mp4 b.mp4", "ffmpeg -i a b.mp4; rm -rf x", "ffmpeg -i a b > /x"):
        assert not render_jobs.is_render(refused), refused


def test_start_render_is_level_3_work_offered_to_sandbox_makers_not_the_verifier():
    from app.api.v1.agent_tools import ADDS, JAI_TOOLS
    from app.core.agents.toolbox import WORKSPACE_TOOLS
    from app.core.command.tool_runtime import _TOOL_AUTHORITY
    from app.core.safety.permission_policy import check_tool_permission

    assert "start_render" in WORKSPACE_TOOLS and "start_render" in JAI_TOOLS and "start_render" in ADDS
    assert _TOOL_AUTHORITY["start_render"] == 3
    assert check_tool_permission(tool_id="start_render", content="ffmpeg -i a b", authority_level=3).allowed
    assert not check_tool_permission(tool_id="start_render", content="ffmpeg -i a b", authority_level=2).allowed


def test_start_render_hands_the_job_to_the_sandbox_and_keeps_it_on_the_mission(monkeypatch, no_models):
    monkeypatch.setattr(settings, "OPENHANDS_URL", "http://openhands:8010")
    answer, seen = _sandbox([{}])

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws = await _seed_owner(db)
            task_id = await _mission(db, ws, lifecycle.RUNNING)
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            out = await render_jobs.start(task_id=task_id, container_root="/host/workspaces/x",
                                          host_root="C:\\P\\x", command="ffmpeg -y -i a.mp4 final.mp4",
                                          cwd="/host/workspaces/x", output="final.mp4", client=client)
        from app.core.redis import get_redis

        active = await (await get_redis()).sismember(render_jobs.ACTIVE_KEY, str(task_id))
        return out, (await _get(task_id)).meta_data, active

    out, meta, active = asyncio.run(run())
    assert out["success"] and out["job_id"].startswith("render-") and "Stop now" in out["next"]
    assert seen[0][1] == "/renders" and seen[0][2]["command"] == "ffmpeg -y -i a.mp4 final.mp4"
    assert meta["render_job"]["job_id"] == out["job_id"] and render_jobs.rendering(meta) is not None and active


def test_start_render_refuses_a_render_outside_the_missions_folder(monkeypatch):
    from types import SimpleNamespace

    from app.core.command.tool_runtime import ToolRuntime

    recorded = []
    runtime = SimpleNamespace(authority_level=3, task_id=None)

    async def no_gate(*args, **kwargs):
        return None

    async def record(tool, inputs, ok, summary, output=None):
        recorded.append((tool, ok, summary))

    runtime._enforce, runtime._record = no_gate, record
    monkeypatch.setattr("app.core.workspaces.fs_inspector.host_to_container",
                        lambda host: __import__("pathlib").Path("/host/workspaces/Plexecute"))
    out = asyncio.run(ToolRuntime.start_render(runtime, "ffmpeg -i a b.mp4", "/host/workspaces/MYCO",
                                               "b.mp4", root_host="C:\\P\\Plexecute"))
    assert out["success"] is False and "outside this mission's workspace" in out["error"]
    out = asyncio.run(ToolRuntime.start_render(runtime, "npm install x", "", "b.mp4", root_host="C:\\P\\Plexecute"))
    assert out["success"] is False and "one render command only" in out["error"]
    assert [r[1] for r in recorded] == [False, False]


# ----- the pause, the watcher and the resume --------------------------------------------------------------------------

@pytest.mark.skipif(_SQLITE, reason="the watcher and the runner write from their own sessions")
def test_the_runner_does_not_carry_a_mission_on_while_its_render_runs(no_models):
    async def run():
        task_id = await _rendering_mission()
        return await MissionRunner()._auto_continue(task_id), (await _get(task_id)).status

    continued, status = asyncio.run(run())
    assert continued is False and status == lifecycle.NEEDS_CONTINUATION


@pytest.mark.skipif(_SQLITE, reason="the watcher and the runner write from their own sessions")
def test_a_short_render_completes_with_no_model_calls_and_the_mission_carries_on(monkeypatch, no_models):
    monkeypatch.setattr(settings, "OPENHANDS_URL", "http://openhands:8010")
    dispatched = []

    async def dispatch(task_id, reason=""):
        dispatched.append((str(task_id), reason))
        return {"dispatched": True}

    monkeypatch.setattr("app.core.runtime.dispatcher.dispatch_mission", dispatch)
    answer, _ = _sandbox([{"status": "running", "seconds": 30},
                          {"status": "finished", "exit_code": 0, "seconds": 410, "facts": FACTS_OK}])

    async def run():
        from app.core.command import progress

        task_id = await _rendering_mission()
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            first = await render_jobs.check_once(client)
            while_running = (await _get(task_id)).status, await progress.load(task_id)
            second = await render_jobs.check_once(client)
        return task_id, first, while_running, second, await _get(task_id)

    task_id, first, (status_then, record), second, task = asyncio.run(run())
    assert str(task_id) in first["running"] and status_then == lifecycle.NEEDS_CONTINUATION
    assert record["phase"].startswith("Rendering (no AI cost), 4m 1") and record["rendering"]["status"] == "running"
    assert str(task_id) in second["resumed"] and dispatched == [(str(task_id), "render ended")]
    assert task.status == lifecycle.QUEUED and task.meta_data["resume_mode"] == "continuation"
    facts = task.meta_data["render_result"]
    assert facts["status"] == "finished" and facts["duration_seconds"] == 26.0 and facts["frozen"] == []
    assert render_jobs.rendering(task.meta_data) is None


@pytest.mark.skipif(_SQLITE, reason="the watcher and the runner write from their own sessions")
def test_a_failing_render_resumes_the_mission_with_its_error(monkeypatch, no_models):
    monkeypatch.setattr(settings, "OPENHANDS_URL", "http://openhands:8010")

    async def dispatch(task_id, reason=""):
        return {"dispatched": True}

    monkeypatch.setattr("app.core.runtime.dispatcher.dispatch_mission", dispatch)
    answer, _ = _sandbox([{"status": "failed", "exit_code": 1, "seconds": 12, "facts": FACTS_FAILED}])

    async def run():
        task_id = await _rendering_mission()
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            await render_jobs.check_once(client)
        return await _get(task_id)

    task = asyncio.run(run())
    facts = task.meta_data["render_result"]
    assert task.status == lifecycle.QUEUED and facts["status"] == "failed" and facts["exit_code"] == 1
    brief = render_jobs.facts_brief(facts)
    assert "FAILED, exit code 1" in brief and "Cannot find module './Scene3'" in brief
    assert "start the render again with start_render" in brief


def test_a_render_the_sandbox_lost_is_reported_as_failed(monkeypatch, no_models):
    monkeypatch.setattr(settings, "OPENHANDS_URL", "http://openhands:8010")

    async def dispatch(task_id, reason=""):
        return {}

    monkeypatch.setattr("app.core.runtime.dispatcher.dispatch_mission", dispatch)

    async def run():
        task_id = await _rendering_mission()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
            await render_jobs.check_once(client)
        return await _get(task_id)

    if _SQLITE:
        pytest.skip("the watcher writes from its own session")
    facts = asyncio.run(run()).meta_data["render_result"]
    assert facts["status"] == "failed" and "restarted" in facts["error"]


# ----- the card ------------------------------------------------------------------------------------------------------

def test_the_card_says_rendering_with_no_ai_cost_and_the_time_so_far():
    started = (datetime.now(timezone.utc) - timedelta(minutes=4, seconds=12)).isoformat()
    line = render_jobs.card_line({"status": "running", "started_at": started})
    assert line.startswith("Rendering (no AI cost), 4m 1") and line.endswith("so far.")
    queued = render_jobs.card_line({"status": "queued", "started_at": started})
    assert "waiting its turn: one render at a time" in queued
    from tests.repo_paths import repo_path

    api = repo_path("apps", "backend", "app", "api", "command.py").read_text()
    assert "text = render_jobs.card_line(job)" in api and 'role="Renderer"' in api


@pytest.mark.skipif(_SQLITE, reason="the watcher and the runner write from their own sessions")
def test_the_mission_view_shows_the_render_while_it_runs():
    from app.api.command import _mission_view

    async def run():
        task_id = await _rendering_mission()
        return _mission_view(await _get(task_id), [])

    view = asyncio.run(run())
    assert view.response_text.startswith("Rendering (no AI cost), 4m 1")


# ----- the round: paused while it renders, the facts in the next brief ----------------------------------------------

@pytest.mark.integration
@pytest.mark.skipif(_SQLITE, reason="the team's records are written from several sessions at once")
def test_a_video_round_pauses_on_its_render_and_the_next_round_gets_the_facts(monkeypatch):
    from app.core.command import agent_executor, mission_org
    from app.core.command.mission_org import MissionTeam
    from tests.test_audit_batch2 import VIDEO, _mission as _video_mission, _workspace
    from tests.test_mission_team import TWO_PACKAGES, TeamRouter
    from tests.test_workspace_toolchain import _mission_folder

    host, folder = _mission_folder()
    router = TeamRouter(TWO_PACKAGES, {"lead": [[("finish", {"summary": "Confirmed.", "success": True})]]})
    monkeypatch.setattr(settings, "MISSION_TEAM_ENABLED", True)
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)
    monkeypatch.setattr(mission_org, "get_router", lambda: router)
    briefs = []

    async def up():
        return True

    async def in_sandbox(self, requirements):
        briefs.append(self.team._brief(self.package, self.mission))
        if len(briefs) == 1:  # the maker hands its render to start_render and stops
            await render_jobs._mark(self.team.runtime.task_id, {
                "job_id": "render-job-0001", "status": "queued", "command": "npx remotion render x Main final.mp4",
                "output": "final.mp4", "started_at": datetime.now(timezone.utc).isoformat()})
            report = "\n".join(f"{r['id']}: open — rendering, job render-job-0001" for r in requirements)
        else:
            report = "\n".join(f"{r['id']}: done — final.mp4 checked" for r in requirements)
        return {"success": True, "answer": report, "requirements": [dict(r) for r in requirements],
                "steps": 5, "tokens": 100, "token_detail": {"input": 80, "output": 20}, "cost_usd": 0.01,
                "model": "claude-sonnet-5-5"}

    monkeypatch.setattr(sandbox_engine, "available", up)
    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "run", in_sandbox)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid = await _workspace(session, host)
            rt = await _video_mission(session, uid, wid)
            first = await MissionTeam(rt, "claude-opus-5-5", host, session_factory=AsyncTestingSessionLocal).run(
                VIDEO, max_continuations=1)
            await session.commit()
            # The render failed while the mission was paused: the watcher kept its facts and ended the job.
            from app.models.task import Task
            from sqlalchemy import select

            task = (await session.execute(select(Task).where(Task.id == rt.task_id))).scalar_one()
            meta = dict(task.meta_data or {})
            meta["render_job"] = {**meta["render_job"], "status": "failed"}
            meta["render_result"] = {**FACTS_FAILED, "status": "failed", "job_id": "render-job-0001",
                                     "command": "npx remotion render x Main final.mp4"}
            task.meta_data = meta
            await session.commit()
            second = await MissionTeam(rt, "claude-opus-5-5", host, session_factory=AsyncTestingSessionLocal).run(
                VIDEO, max_continuations=1, start_continuation=1)
            await session.commit()
            return first, second

    try:
        first, second = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert first["needs_continuation"] is True and first["rendering"]["job_id"] == "render-job-0001"
    assert first["answer"].startswith("**Rendering (no AI cost)")
    assert "THE RENDER YOU STARTED HAS ENDED" not in briefs[0]
    assert "THE RENDER YOU STARTED HAS ENDED" in briefs[1] and "Cannot find module './Scene3'" in briefs[1]
    assert "rendering" not in second


def test_the_studio_is_told_to_render_through_start_render():
    from app.core.command.mission_org import studio_goal

    goal = studio_goal()
    assert "start_render" in goal and "never in your terminal" in goal and "rendering, job <id>" in goal


def test_the_watcher_runs_every_30_seconds_on_celery():
    from app.core.celery import SCHEDULED_JOBS, celery_app
    from app.workers import tasks

    beat = [e for e in celery_app.conf.beat_schedule.values() if e["task"] == "check_renders"]
    assert beat and beat[0]["schedule"] == 30.0
    assert any(j["task"] == "check_renders" and j["interval_seconds"] == 30.0 for j in SCHEDULED_JOBS)
    assert callable(tasks.check_renders)


def test_a_round_that_hands_its_render_over_waits_for_it_and_is_never_counted_idle():
    """24 November, episode 2: two rounds each fixed the video and handed the render over, were counted idle, and
    the mission stopped as partial with its render still running: nothing carried it on when the render ended."""
    from app.core.command.continuation import IDLE_ROUNDS_LIMIT, after_round
    from app.core.runtime import lifecycle

    waiting = lifecycle.NEEDS_CONTINUATION
    for outcome in (waiting, lifecycle.PARTIAL, lifecycle.FAILED):
        out, reason, idle = after_round(outcome, "x", False, IDLE_ROUNDS_LIMIT + 3, rendering=True)
        assert (out, idle) == (waiting, 0) and "render" in reason
    out, _, idle = after_round(waiting, "x", False, IDLE_ROUNDS_LIMIT - 1)              # no render: as before
    assert out == lifecycle.PARTIAL and idle == IDLE_ROUNDS_LIMIT
    assert after_round(lifecycle.COMPLETED, None, False, 0, rendering=True)[0] == lifecycle.COMPLETED


@pytest.mark.skipif(_SQLITE, reason="two sessions write the same mission")
def test_a_render_started_during_a_round_survives_the_rounds_outcome(no_models):
    """24 November, episode 2: the round's session loaded the mission before start_render wrote the render (in its
    own session), then saved its outcome over it. The render vanished from the record, the mission carried on a
    minute and a half into the render, and queued a second render of the same file behind it. Saving the outcome
    keeps the render, and the runner then waits for it."""
    from sqlalchemy import select

    from app.core.command.service import CommandService
    from app.models.task import Task

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws = await _seed_owner(db)
            task_id = await _mission(db, ws, lifecycle.RUNNING)
        async with AsyncTestingSessionLocal() as round_db:          # the round's session loads the mission
            task = (await round_db.execute(select(Task).where(Task.id == task_id))).scalar_one()
            assert "render_job" not in (task.meta_data or {})
            await render_jobs._mark(task_id, {"job_id": "render-x-1", "status": "running", "output": "final.mp4",
                                              "command": "npx remotion render a b final.mp4", "cwd": "/w",
                                              "started_at": datetime.now(timezone.utc).isoformat()})
            await CommandService._finish(CommandService.__new__(CommandService), round_db, task,
                                         lifecycle.NEEDS_CONTINUATION, "the round's outcome")
            await round_db.commit()
        saved = await _get(task_id)
        return task_id, saved, await MissionRunner()._auto_continue(task_id)

    task_id, saved, continued = asyncio.run(run())
    assert saved.status == lifecycle.NEEDS_CONTINUATION
    assert saved.meta_data["render_job"]["job_id"] == "render-x-1"               # not wiped by the round
    assert saved.meta_data["status_history"][-1]["to"] == lifecycle.NEEDS_CONTINUATION
    assert continued is False                                                   # the runner waits for the render
