"""
JAI takes any mission (Richard, 10 November: "get JAI working with all of its skills, knowledge and agents doing any
mission it's given"): every business agent has its own work routed to it, and a mission that needs several agents
is split by the Orchestrator and run step by step on the workflow engine, each step by its own agent. Real: the
routing, the planner's rules, the workflow service and LangGraph (in memory), the test database. Stood in: the
Orchestrator's model (no test spends provider credit) and the missions the steps start (task rows).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.command import role_mission, work_type
from app.core.command.service import CommandService
from app.core.councils import planner, service
from app.models import WorkflowRun
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal
from tests.test_workflows import FOLDER, _finish, _get_run, _run, _seed, _tick, stand_ins  # noqa: F401

LAUNCH = "Launch Plexecute: research the competitors, write the launch plan, then write the launch posts"
PLAN = {"split": True, "title": "Plexecute launch", "steps": [
    {"agent": "research", "title": "Research the competitors",
     "brief": "Write research/competitors.md comparing the main habit and planning apps."},
    {"agent": "marketing", "title": "Write the launch plan",
     "brief": "Finish growth/launch-plan.md from the competitor research."},
    {"gate": True, "title": "Richard reads the plan", "ask": "Read growth/launch-plan.md."},
    {"agent": "content", "title": "Write the launch posts",
     "brief": "Write growth/launch-posts.md: two weeks of posts from the plan."},
    {"gate": True, "title": "A gate with nothing after it", "ask": "Nothing follows."}]}


class Orchestrator:
    """Stands in for the Orchestrator's model."""

    def __init__(self, answer):
        self.answer, self.asked = answer, []

    async def complete(self, request):
        self.asked.append(request)
        return SimpleNamespace(content=json.dumps(self.answer), usage={}, tool_calls=[])


@pytest.mark.parametrize("brief, agent", [
    ("Write the onboarding emails for Plexecute", "onboarding"),
    ("Write community guidelines for the Plexecute Discord", "community"),
    ("Do a funnel analysis of the Plexecute waiting list", "analytics"),
    ("Design a referral programme for Plexecute", "growth"),
    ("Find free places to market Plexecute", "marketing"),          # unchanged
    ("Find 30 UK creators and communities for Plexecute", "marketing"),
])
def test_every_business_agent_gets_its_own_work(brief, agent):
    assert work_type.specialist_for(brief)["specialist"] == agent
    assert agent in work_type.DESCRIBED and role_mission.role_tools(agent)


def test_software_named_in_an_onboarding_brief_stays_with_the_builder():
    assert work_type.specialist_for("Build the onboarding screen for the app") is None


def test_only_a_short_request_for_several_kinds_of_work_is_put_to_the_orchestrator():
    assert planner.may_need_several(LAUNCH)
    assert planner.may_need_several("Build the website for Plexecute and write the launch plan for it")
    assert not planner.may_need_several("Find free places to market Plexecute")             # one kind of work
    assert not planner.may_need_several("Specialist: marketing. " + LAUNCH)                  # a workflow's own step
    assert not planner.may_need_several("Carry on with the competitor research and the launch plan")
    assert not planner.may_need_several("In C:\\P, revise growth/pitches.xlsx in place. 1) Remove the podcast "
                                        "rows. 2) Offer a guest article. 3) Keep the investor line.")
    assert not planner.may_need_several(LAUNCH + " " + "Detail. " * 120)                     # a detailed brief


def test_the_plan_is_checked_before_it_runs():
    plan = planner._clean(PLAN)
    assert plan["title"] == "Plexecute launch"
    assert [s.get("specialist", "gate") for s in plan["steps"]] == ["research", "marketing", "gate", "content"]
    assert "Finish" not in plan["steps"][1]["brief"] and "work on" in plan["steps"][1]["brief"].lower()
    assert planner._clean({"split": False}) is None
    assert planner._clean({"split": True, "steps": [{"agent": "nobody", "title": "x", "brief": "y"}]}) is None
    one_agent = {"split": True, "steps": [{"agent": "sales", "title": "a", "brief": "b"},
                                          {"agent": "sales", "title": "c", "brief": "d"}]}
    assert planner._clean(one_agent) is None  # two steps for one agent is one agent's job


def test_the_orchestrator_is_asked_once_and_never_without_a_model():
    model = Orchestrator(PLAN)
    plan = _run(planner.plan(model, "m", LAUNCH))
    assert plan and len(model.asked) == 1 and "research (" in model.asked[0].system
    assert _run(planner.plan(None, "m", LAUNCH)) is None
    assert _run(planner.plan(Orchestrator({"split": False}), "m", LAUNCH)) is None


def test_each_step_names_its_agent_and_is_new_work():
    steps = planner.fill(planner._clean(PLAN), product="Plexecute", folder=FOLDER)
    assert [s["id"] for s in steps] == ["s1", "s2", "s3", "s4"]
    assert steps[0]["brief"].startswith(f"Specialist: research. In {FOLDER}, for Plexecute:")
    assert steps[0]["brief"].endswith("This is new work with its own checklist.")
    assert work_type.specialist_for(steps[1]["brief"])["specialist"] == "marketing"
    assert steps[2]["gate"] and "Approve to let the plan go on" in steps[2]["ask"]


def test_a_split_mission_runs_agent_by_agent_and_waits_for_richard(stand_ins):  # noqa: F811
    user_id, ws_id = _run(_seed())

    async def start():
        async with AsyncTestingSessionLocal() as db:
            workspace = (await db.execute(select(Workspace).where(Workspace.id == ws_id))).scalar_one()
            run = await service.start_planned(db, user_id=user_id, workspace=workspace,
                                              planned=planner._clean(PLAN))
            return run.id

    run_id = _run(start())
    run = _run(_get_run(run_id))
    assert run.template == planner.PLANNED and run.title == "Plexecute launch for Plexecute"
    assert run.status == "waiting_mission" and run.current_step == "s1"
    assert stand_ins[0][1].startswith("Specialist: research.")
    _run(_finish(run.waiting_task_id, "completed", "Six competitors compared"))
    _run(_tick())
    run = _run(_get_run(run_id))
    assert run.current_step == "s2" and stand_ins[-1][1].startswith("Specialist: marketing.")
    _run(_finish(run.waiting_task_id, "partial"))
    _run(_tick())
    run = _run(_get_run(run_id))
    assert run.status == "waiting_approval" and run.current_step == "s3"

    async def decide():
        async with AsyncTestingSessionLocal() as db:
            from app.models.task import Task

            gate = (await db.execute(select(Task).where(Task.id == run.waiting_task_id))).scalar_one()
            assert gate.title == "Plexecute launch for Plexecute: Richard reads the plan"
            await service.gate_decided(db, gate, approved=True, note="read it")

    _run(decide())
    run = _run(_get_run(run_id))
    assert run.status == "waiting_mission" and run.current_step == "s4"
    _run(_finish(run.waiting_task_id, "completed"))
    _run(_tick())
    run = _run(_get_run(run_id))
    assert run.status == "completed"
    described = service.describe(run)
    assert [s["status"] for s in described["steps"]] == ["completed", "partial", "approved", "completed"]
    assert [s["specialist"] for s in described["steps"]] == ["research", "marketing", None, "content"]


def test_the_mission_handler_splits_only_when_the_orchestrator_says_so(monkeypatch, stand_ins):  # noqa: F811
    user_id, ws_id = _run(_seed())
    answers = [planner._clean(PLAN)]

    async def planned(router, model, brief):
        return answers.pop(0) if answers else None

    async def model(self):
        return "m"

    monkeypatch.setattr(planner, "plan", planned)
    monkeypatch.setattr(CommandService, "_orchestrator_model", model)

    async def go(brief):
        async with AsyncTestingSessionLocal() as db:
            runtime = SimpleNamespace(workspace_id=ws_id, task_id=None)
            return await CommandService()._orchestrate(db, runtime, brief)

    assert _run(go("Find free places to market Plexecute")) is None  # one agent's job: the Orchestrator is not asked
    assert len(answers) == 1
    answer, steps, agents, extra = _run(go(LAUNCH))
    assert "the Orchestrator has split it: Plexecute launch for Plexecute" in answer
    assert "JAI's Research Analyst" in answer and "you, on the Approvals page" in answer
    assert extra["orchestrated"] is True and len(steps) == 4 and "orchestrator" in agents

    async def runs():
        async with AsyncTestingSessionLocal() as db:
            return (await db.execute(select(WorkflowRun).where(WorkflowRun.workspace_id == ws_id))).scalars().all()

    assert len(_run(runs())) == 1
    # A workflow is already open in the workspace: the next such mission runs as one mission.
    answers.append(planner._clean(PLAN))
    assert _run(go(LAUNCH)) is None


def test_the_one_builder_starts_with_its_playbooks_knowledge_and_richards_rules(tmp_path, monkeypatch):
    from app.core.command import expertise, sandbox_engine
    from app.core.command.mission_org import Package
    from app.core.config import settings
    from app.core.knowledge import skill_packs

    entry = next(e for e in skill_packs.SKILLS if e["skill"] == "test-driven-development" and e["sandbox"])
    folder = tmp_path / entry["pack"] / skill_packs.skill_path(entry)
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text('---\nname: test-driven-development\ndescription: "Use when implementing any '
                                     'feature or bugfix, before writing implementation code"\n---\n# TDD\n\nWrite '
                                     "the failing test first, watch it fail, then make it pass.\n", encoding="utf-8")
    monkeypatch.setattr(settings, "SKILL_PACKS_DIR", str(tmp_path))
    job = _run(expertise.job_for(None, "m", "With test driven development, fix the failing unit tests and add a test for sub()",
                                 "builder", set_out=False))
    assert "test-driven-development" in job.skills and job.text == ""  # the brief is not rewritten for software
    job.rules = ["Plexecute has not launched: never claim customers."]
    team = SimpleNamespace(runtime=SimpleNamespace(task_id=None), workspace_root="/test_workspaces/x",
                           _brief=lambda p, m: "brief", job=job)
    builder = Package("B1", "t", "builder", "g", [], [], [], "")
    brief = sandbox_engine.SandboxSpecialist(team, builder, "m", None)._brief([])
    assert "=== test-driven-development ===" in brief and "Write the failing test first" in brief
    checker = Package("VER", "t", "verifier", "g", [], [], [], "")
    assert "=== test-driven-development ===" not in sandbox_engine.SandboxSpecialist(team, checker, "m", None)._brief([])
    assert "never claim customers" in job.brief_for_team()
