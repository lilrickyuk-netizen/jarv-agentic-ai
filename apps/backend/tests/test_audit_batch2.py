"""
Audit batch 2 (24 November): learning on every mission. The debrief business missions already had (command/debrief)
now runs after every builder and skill mission too (videos, content made with commands, software builds), and every
content piece checks and adds to its product's used-facts list.

Real: the test database, the mission team, the learning service and its safety guard, the content rules and the
Plexecute playbook. Stood in: the sandbox's answers and the debrief's model reply (tests never spend credit).
"""
import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.command import debrief, sandbox_engine
from app.core.config import settings
from app.core.knowledge import content_rules
from app.models.self_evolution import ExperienceRecord
from tests.conftest import _SQLITE, AsyncTestingSessionLocal

VIDEO = "Use OpenMontage to make 1 short vertical video for Plexecute about keeping a streak going."
FRAME = "/tmp/check-frame-0001.png"


# ----- the used-facts list ------------------------------------------------------------------------------------------

def test_the_playbook_records_the_fact_richard_said_never_to_use_again():
    facts = content_rules.used_facts(None, "A Plexecute reel")
    assert any("Sheeran" in line and "53%" in line for line in facts)
    assert content_rules.used_facts(None, "A reel for another product") == []


def test_every_content_mission_is_told_what_is_used_and_to_add_what_it_uses(tmp_path):
    (tmp_path / ".jai").mkdir()
    (tmp_path / content_rules.USED_FACTS).write_text(
        "# Used facts\n- 66 days to form a habit (Lally 2009, UCL; reel-07.mp4; 2026-11-20)\n", encoding="utf-8")
    rule = content_rules.used_facts_rule(tmp_path, "A Plexecute carousel about habits")
    assert "66 days to form a habit" in rule and "Sheeran" in rule
    assert "use none of them again" in rule and content_rules.USED_FACTS in rule
    assert "never changing or deleting a line" in rule
    fresh = content_rules.used_facts_rule(tmp_path / "nowhere", "A reel for another product")
    assert "None is recorded yet" in fresh and "creating the file" in fresh


def test_the_independent_check_holds_a_piece_to_the_used_facts_list():
    check = content_rules.content_check("A Plexecute reel")
    assert content_rules.USED_FACTS in check and "already on the used-facts list" in check


def test_the_studio_the_content_skills_and_the_content_specialists_all_get_the_list():
    from app.core.command.mission_org import MissionTeam

    team = MissionTeam.__new__(MissionTeam)
    team.workspace_root = None
    for studio in (True, False):
        assert "USED FACTS" in team._content_rules("A Plexecute reel", studio=studio)
    source = Path(__file__).resolve().parents[1] / "app" / "core" / "command" / "mission_org.py"
    text = source.read_text()
    assert "if role in CONTENT_SPECIALISTS:" in text and '"CONTENT RULES:" + self._content_rules(mission)' in text


# ----- the debrief on builder and skill missions -------------------------------------------------------------------

async def _workspace(session, host):
    from app.models.user import User
    from app.models.workspace import Workspace

    uid, wid = uuid4(), uuid4()
    session.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io", password_hash="$2b$12$x",
                     is_active=True, is_admin=False))
    session.add(Workspace(id=wid, name="Plexecute", slug=f"plexecute-{wid.hex[:8]}", description="d", owner_id=uid,
                          is_active=True, workspace_type="content", authority_level=4, config={"root_path": host}))
    await session.commit()
    return uid, wid


async def _mission(session, uid, wid):
    from app.core.command.tool_runtime import ToolRuntime
    from app.models.task import Task

    task = Task(id=uuid4(), title="Video", description=VIDEO, workspace_id=wid, status="running", priority=5,
                task_type="command")
    session.add(task)
    await session.commit()
    return ToolRuntime(session, wid, task.id, operator=str(uid), authority_level=4, user_id=uid)


@pytest.mark.integration
@pytest.mark.skipif(_SQLITE, reason="the team's records are written from several sessions at once")
def test_a_video_mission_is_debriefed_and_the_next_one_starts_with_its_lesson(monkeypatch):
    """The audit's test for batch 2, in code: the first video mission's mistake (check frames saved in /tmp, which
    the file viewer refused) becomes a lesson, and the second video mission's maker is briefed with it."""
    from app.core.command import agent_executor, mission_org
    from app.core.command.mission_org import MissionTeam
    from tests.test_mission_team import TWO_PACKAGES, TeamRouter
    from tests.test_workspace_toolchain import _mission_folder

    host, folder = _mission_folder()
    router = TeamRouter(TWO_PACKAGES, {"lead": [[("finish", {"summary": "Confirmed.", "success": True})]]})
    monkeypatch.setattr(settings, "MISSION_TEAM_ENABLED", True)
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)
    monkeypatch.setattr(mission_org, "get_router", lambda: router)
    briefs, asked = [], []

    async def up():
        return True

    async def in_sandbox(self, requirements):
        briefs.append((self.package.id, self.team._brief(self.package, self.mission)))
        if len(briefs) == 1:  # the first mission saved its check frame in /tmp and could not open it
            await self.team.adopt([{"tool": "read_file", "inputs": {"path": FRAME, "command": "view"},
                                    "success": False, "summary": f"Not done: {FRAME} is outside this mission's "
                                    "workspace", "agent": "creation", "package": "P1", "engine": "openhands"}])
        return {"success": True, "answer": "\n".join(f"{r['id']}: done — checked" for r in requirements),
                "requirements": [{**r, "status": "done", "evidence": "checked"} for r in requirements],
                "steps": 5, "tokens": 100, "token_detail": {"input": 80, "output": 20}, "cost_usd": 0.01,
                "model": "claude-sonnet-5-5"}

    async def stand_in(title, record, router=None):
        asked.append((title, record))
        if len(asked) > 1:
            return []
        return [{"situation": "Making a short video with OpenMontage in the sandbox",
                 "lesson": "Save check frames and stills in the mission folder's .jai/work/, where the file viewer "
                           "can open them, instead of /tmp.",
                 "kind": "avoid", "evidence": FRAME}]

    monkeypatch.setattr(sandbox_engine, "available", up)
    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "run", in_sandbox)
    monkeypatch.setattr(debrief, "_ask", stand_in)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid = await _workspace(session, host)
            outcomes = []
            for _ in range(2):
                rt = await _mission(session, uid, wid)
                outcomes.append(await MissionTeam(rt, "claude-opus-5-5", host,
                                                  session_factory=AsyncTestingSessionLocal).run(VIDEO,
                                                                                                max_continuations=1))
                await session.commit()
            rows = (await session.execute(select(ExperienceRecord).where(
                ExperienceRecord.workspace_id == wid, ExperienceRecord.experience_type == "debrief"))).scalars().all()
            return outcomes, rows

    try:
        outcomes, rows = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert [b[0] for b in briefs] == ["P1", "P1"]  # one maker per video mission (Richard judges videos)
    title, record = asked[0]
    assert title == "Product Designer" and FRAME in record and "WHAT FAILED" in record
    assert outcomes[0]["learning"] == {"recorded": 1, "in_use": 1, "rejected": 0}
    assert [r.agent_name for r in rows] == ["creation"]
    assert "WHAT YOU LEARNED ON EARLIER JOBS" not in briefs[0][1]  # nothing learned yet for the first one
    assert "WHAT YOU LEARNED ON EARLIER JOBS" in briefs[1][1] and "instead of /tmp" in briefs[1][1]
    assert outcomes[1]["learning"]["recorded"] == 0


@pytest.mark.integration
@pytest.mark.skipif(_SQLITE, reason="the team's records are written from several sessions at once")
def test_a_software_build_is_debriefed_as_the_lead_builder_and_its_verifier_gets_no_lessons(monkeypatch):
    from app.core.command import agent_executor, mission_org
    from app.core.command.mission_org import MissionTeam
    from tests.test_mission_team import TWO_PACKAGES, TeamRouter
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    router = TeamRouter(TWO_PACKAGES, {"lead": [[("finish", {"summary": "Confirmed.", "success": True})]]})
    monkeypatch.setattr(settings, "MISSION_TEAM_ENABLED", True)
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)
    monkeypatch.setattr(mission_org, "get_router", lambda: router)
    briefs, asked = {}, []

    async def up():
        return True

    async def in_sandbox(self, requirements):
        briefs[self.package.id] = self.team._brief(self.package, self.mission)
        return {"success": True, "answer": "\n".join(f"{r['id']}: done — checked" for r in requirements),
                "requirements": [{**r, "status": "done", "evidence": "checked"} for r in requirements],
                "steps": 5, "tokens": 100, "token_detail": {"input": 80, "output": 20}, "cost_usd": 0.01}

    async def stand_in(title, record, router=None):
        asked.append(title)
        return []

    async def known_lessons(db, workspace_id, role, mission):
        return ("WHAT YOU LEARNED ON EARLIER JOBS FOR THIS PRODUCT (...):\n- Run the type check before the tests.",
                ["k1"]) if role == "builder" else ("", [])

    monkeypatch.setattr(sandbox_engine, "available", up)
    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "run", in_sandbox)
    monkeypatch.setattr(debrief, "_ask", stand_in)
    monkeypatch.setattr(debrief, "lessons_for", known_lessons)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            result = await MissionTeam(rt, "claude-opus-5-5", host, session_factory=AsyncTestingSessionLocal).run(
                "Add sub(a, b) to the project and document it.", max_continuations=1)
            await session.commit()
            return result

    try:
        result = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    assert asked == ["Lead Builder"] and "learning" in result
    assert "Run the type check before the tests." in briefs["B1"]
    assert "Run the type check before the tests." not in briefs["VER"]
