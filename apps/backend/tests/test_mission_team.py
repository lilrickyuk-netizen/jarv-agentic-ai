"""
Missions are run by a team: the Orchestrator plans work packages, the Swarm Manager spawns one specialist sub-agent
per package (recorded on the Swarm page with its parent agent, dissolved when its package ends), specialists work in
parallel writing only inside the paths they own, and an integration lead builds and tests the whole before the
independent Verifier accepts it. A step that hangs is stopped by a watchdog, and a command that would never end on
its own (a dev server, a watcher) is not run. Real: the toolbox, runtime and database records on a sandbox workspace,
with a scripted model (no provider is called).
"""
import asyncio
import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.command import agent_executor, mission_org
from app.core.command.mission_org import MissionTeam, Package, next_wave, parse_plan
from app.core.command.tool_runtime import _stop_group, never_ends
from app.core.config import settings
from app.core.providers import CompletionResponse
from tests.conftest import _SQLITE, AsyncTestingSessionLocal

# The team's specialists each write through their own database session at the same time; SQLite has one writer.
needs_postgres = pytest.mark.skipif(_SQLITE, reason="parallel specialists need PostgreSQL's concurrent writers")


def _calls(*pairs):
    return [{"id": f"c{i}-{time.monotonic_ns()}", "type": "function",
             "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(pairs)]


TWO_PACKAGES = {"approach": "Code and its documentation side by side.", "packages": [
    {"id": "P1", "title": "sub()", "specialist": "coding_agent", "goal": "Add sub(a, b) in src/sub.py",
     "owns": ["src/"], "requirements": ["R1"], "done_when": "python3 -m py_compile src/sub.py passes"},
    {"id": "P2", "title": "Usage notes", "specialist": "documentation", "goal": "Explain sub in docs/usage.md",
     "owns": ["docs/"], "requirements": ["R2"], "done_when": "docs/usage.md explains sub"},
]}


class TeamRouter:
    """The scripted model: the requirements, the plan, each specialist's turns (told apart by its work package),
    the integration lead's turns and the Verifier's verdict. Specialists' calls overlap when they run in parallel."""

    def __init__(self, plan, turns):
        self.plan, self.turns = plan, {k: list(v) for k, v in turns.items()}
        self.offered, self.briefs = {}, {}
        self.live = self.most = 0

    async def complete(self, request):
        system = request.system or ""
        first = request.messages[0].content if request.messages else ""
        first = first if isinstance(first, str) else json.dumps(first)
        if system.startswith("You are JAI's requirements analyst"):
            calls = [("record_requirements", {"requirements": [
                {"text": "src/sub.py defines sub(a, b)", "source": "mission"},
                {"text": "docs/usage.md explains sub", "source": "mission"}]})]
        elif system.startswith("You are JAI's Orchestrator"):
            calls = [("plan_work", self.plan)]
        elif system.startswith("You are JAI's Verifier Agent"):
            calls = [("verdict", {"verified": True, "unmet": [], "checks": [
                {"requirement": "R1 src/sub.py defines sub(a, b)", "met": True, "evidence": "read src/sub.py"},
                {"requirement": "R2 docs/usage.md explains sub", "met": True, "evidence": "read docs/usage.md"}]})]
        elif system.startswith("You are JAI, an autonomous"):
            who = next((p for p in ("P1", "P2") if f"YOUR WORK PACKAGE {p}:" in first), "lead")
            self.offered.setdefault(who, sorted(t["name"] for t in request.tools or []))
            self.briefs.setdefault(who, first)
            self.live += 1
            self.most = max(self.most, self.live)
            await asyncio.sleep(0.2)
            self.live -= 1
            queue = self.turns.get(who) or []
            calls = queue.pop(0) if queue else [("finish", {"summary": f"{who} done.", "success": True})]
        else:
            calls = []  # the report writer: the rules write the report from the evidence
        return CompletionResponse(id="r", model="test", content="", usage={"total_tokens": 5},
                                  tool_calls=_calls(*calls))


def _team(monkeypatch, router):
    monkeypatch.setattr(settings, "MISSION_TEAM_ENABLED", True)
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)
    monkeypatch.setattr(mission_org, "get_router", lambda: router)


@pytest.mark.integration
@needs_postgres
def test_a_mission_is_run_by_a_team_of_specialists_in_parallel(monkeypatch):
    from sqlalchemy import select

    from app.models.swarm import SubAgent, SubAgentLog, SwarmRun
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    router = TeamRouter(TWO_PACKAGES, {
        "P1": [[("write_file", {"path": "src/sub.py", "content": "def sub(a, b):\n    return a - b\n"})],
               [("write_file", {"path": "docs/notes.md", "content": "not mine"})],
               [("requirement_status", {"id": "R1", "status": "done", "evidence": "wrote src/sub.py"})],
               [("finish", {"summary": "sub() is in src/sub.py.", "success": True})]],
        "P2": [[("write_file", {"path": "docs/usage.md", "content": "# sub\n\nsub(a, b) returns a - b.\n"})],
               [("requirement_status", {"id": "R2", "status": "done", "evidence": "wrote docs/usage.md"})],
               [("finish", {"summary": "docs/usage.md explains sub.", "success": True})]],
        "lead": [[("run_command", {"command": "python3 -m py_compile src/sub.py"})],
                 [("finish", {"summary": "Built and checked the whole.", "success": True})]],
    })
    _team(monkeypatch, router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            team = MissionTeam(rt, "test-model", host, session_factory=AsyncTestingSessionLocal)
            result = await team.run("Add sub(a, b) to the project and document it.", max_continuations=1)
            await session.commit()
        async with AsyncTestingSessionLocal() as db:
            swarm = (await db.execute(select(SwarmRun).where(SwarmRun.workspace_id == rt.workspace_id))).scalar_one()
            children = (await db.execute(select(SubAgent).where(SubAgent.swarm_run_id == swarm.id)
                                         .order_by(SubAgent.subagent_name))).scalars().all()
            logs = (await db.execute(select(SubAgentLog).where(
                SubAgentLog.subagent_id.in_([c.id for c in children])))).scalars().all()
        return rt, result, swarm, children, logs

    try:
        rt, result, swarm, children, logs = asyncio.run(run())
        assert (folder / "src" / "sub.py").read_text().startswith("def sub")
        assert (folder / "docs" / "usage.md").exists()
        assert not (folder / "docs" / "notes.md").exists()  # outside the coding agent's package
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    assert result["success"] is True and result["verification"]["verified"] is True
    assert [p["status"] for p in result["team"]["packages"]] == ["finished", "finished"]
    assert result["answer"].startswith("**The team** (2 specialists")
    assert router.most == 2  # the two specialists worked at the same time
    assert "Senior Software Engineer" in router.briefs["P1"] and "Technical Writer" in router.briefs["P2"]
    for who in ("P1", "P2"):  # deleting and pushing stay with the lead
        assert "write_file" in router.offered[who]
        assert "git_push_with_boundary" not in router.offered[who]
        assert "delete_file_with_boundary" not in router.offered[who]
    assert "git_push_with_boundary" in router.offered["lead"]
    assert "YOUR ROLE NOW: you are the integration lead" in router.briefs["lead"]
    assert {r["id"]: r["status"] for r in result["requirements"]} == {"R1": "done", "R2": "done"}
    by_agent = {c.get("agent") for c in rt.calls}
    assert {"coding_agent", "documentation"} <= by_agent

    assert swarm.swarm_type == "mission_team" and swarm.status == "completed" and swarm.success is True
    assert [c.subagent_type for c in children] == ["coding_agent", "documentation"]
    for child in children:
        assert child.status == "dissolved" and child.success is True
        assert child.meta_data["parent_agent_id"] == str(swarm.parent_agent_id)
        assert child.meta_data["authority_ceiling"] == rt.authority_level
    assert logs and all(log.context["parent_agent_id"] == str(swarm.parent_agent_id) for log in logs)
    refused = [log for log in logs if log.log_level == "warning" and "docs/notes.md" in log.log_message]
    assert refused and "outside your work package" in refused[0].log_message


@pytest.mark.integration
def test_one_small_change_is_done_by_one_agent(monkeypatch):
    from sqlalchemy import select

    from app.models.swarm import SwarmRun
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    one = {"approach": "One edit.", "packages": [TWO_PACKAGES["packages"][0]]}
    router = TeamRouter(one, {"lead": [
        [("write_file", {"path": "src/sub.py", "content": "def sub(a, b):\n    return a - b\n"})],
        [("finish", {"summary": "Done.", "success": True})]]})
    _team(monkeypatch, router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            result = await MissionTeam(rt, "test-model", host, session_factory=AsyncTestingSessionLocal).run(
                "Add sub(a, b).", max_continuations=0)
        async with AsyncTestingSessionLocal() as db:
            swarms = (await db.execute(select(SwarmRun).where(SwarmRun.workspace_id == rt.workspace_id))).all()
        return result, swarms

    try:
        result, swarms = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert result["success"] is True and "team" not in result and swarms == []
    assert set(router.offered) == {"lead"}


def test_the_plan_is_cleaned_and_runs_in_dependency_waves():
    plan = parse_plan({"approach": "x", "packages": [
        {"id": "P1", "title": "API", "specialist": "coding_agent", "goal": "g", "owns": ["apps/api/", "../up"],
         "requirements": ["R1", "R2"], "done_when": "pytest"},
        {"id": "P1", "title": "Web", "specialist": "wizard", "goal": "g", "owns": ["./apps/web"],
         "depends_on": ["P1", "P9"], "requirements": ["R2", "R3"], "done_when": ""},
        {"id": "P3", "title": "Docs", "specialist": "documentation", "goal": "d", "owns": ["docs/"]},
        {"title": "", "goal": ""}]}, ["R1", "R2", "R3", "R4"], 10)
    ids = [(p.id, p.specialist, p.owns, p.depends_on, p.requirements) for p in plan["packages"]]
    assert ids == [("P1", "coding_agent", ["apps/api/"], [], ["R1", "R2"]),
                   ("P2", "coding_agent", ["apps/web"], ["P1"], ["R3"]),
                   ("P3", "documentation", ["docs/"], [], [])]
    assert plan["unassigned"] == ["R4"]

    def pkg(pid, owns, deps=()):
        return Package(pid, pid, "coding_agent", "g", list(owns), list(deps), [], "")

    api, tests, docs = pkg("A", ["apps/api/"]), pkg("B", ["apps/api/tests/"]), pkg("C", ["docs/"])
    anywhere, web = pkg("D", []), pkg("E", ["web/"], ["A"])
    assert [p.id for p in next_wave([api, tests, docs, anywhere, web], {}, 4)] == ["A", "C"]
    assert [p.id for p in next_wave([tests, anywhere, web], {"A": api, "C": docs}, 4)] == ["B", "E"]
    assert [p.id for p in next_wave([anywhere], {}, 4)] == ["D"]  # a package that may write anywhere runs alone
    assert [p.id for p in next_wave([api, docs], {}, 1)] == ["A"]


@pytest.mark.parametrize("command, endless", [
    ("npm run dev", True), ("pnpm dev", True), ("npx -y next dev", True), ("vite", True), ("vitest", True),
    ("uvicorn app.main:app", True), ("docker compose up", True), ("jest --watch", True), ("tsc -w", True),
    ("python3 -m http.server", True), ("php artisan serve", True), ("yarn start", True),
    ("npm test", False), ("npm run build", False), ("vitest run", False), ("vite build", False),
    ("docker compose up -d", False), ("pytest", False), ("tsc --noEmit", False), ("php artisan migrate", False),
    ("pnpm install", False),
])
def test_commands_that_never_end_are_not_run(command, endless):
    reason = never_ends(command.split())
    assert bool(reason) is endless
    if endless:
        assert "Run the check once instead" in reason


def test_a_stopped_command_takes_everything_it_started_with_it():
    async def run():
        proc = await asyncio.create_subprocess_exec("sh", "-c", "sleep 30 & sleep 30", start_new_session=True,
                                                    stdout=asyncio.subprocess.DEVNULL)
        await asyncio.sleep(0.2)
        _stop_group(proc)
        await proc.wait()
        await asyncio.sleep(0.2)
        return proc.pid

    pgid = asyncio.run(run())
    alive = []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(fields[2]) == pgid and fields[0] != "Z":  # a killed orphan may linger as a zombie, never running
            alive.append(stat.parent.name)
    assert alive == []


def test_a_hung_tool_is_stopped_and_the_agent_told(monkeypatch):
    monkeypatch.setattr(agent_executor, "TOOL_STEP_SECONDS", 1)
    executor = object.__new__(agent_executor.AgentExecutor)
    executor.runtime = SimpleNamespace(task_id=None)

    async def hangs(name, args):
        await asyncio.sleep(10)

    executor._dispatch = hangs
    out = asyncio.run(executor._tool_step("run_tests", {}))
    assert out["success"] is False and out["timed_out"] is True and "run_tests did not return" in out["error"]


@pytest.mark.integration
def test_a_model_that_stops_answering_ends_the_round_not_the_mission(monkeypatch):
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    class Silent:
        async def complete(self, request):
            if (request.system or "").startswith("You are JAI's requirements analyst"):
                return CompletionResponse(id="r", model="test", content="", usage={}, tool_calls=[])
            await asyncio.sleep(30)

    monkeypatch.setattr(agent_executor, "MODEL_STEP_SECONDS", 1)
    monkeypatch.setattr(agent_executor, "get_router", lambda: Silent())
    host, folder = _mission_folder()

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            return await agent_executor.AgentExecutor(rt, "test-model", host).run("Tidy src/app.py.",
                                                                                   max_continuations=0)

    try:
        started = time.monotonic()
        result = asyncio.run(run())
        took = time.monotonic() - started
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert took < 20
    assert result["needs_continuation"] is True and result["finished"] is False
    assert "did not answer" in result["answer"] and result["iterations"] == 0
