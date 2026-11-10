"""
A specialist's mission is done by that specialist's own agent, the way the role works (Richard, 10 November: "why
would a marketing agent start a mission like a software engineer? It makes no sense"). Real: the routing, the role's
toolbox on a real workspace folder with the permission gate, the spreadsheet tool writing a real .xlsx, the model
choice, the spending allowance and the waiting-list workflow's briefs. No model is called and no provider credit is
spent.
"""
from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.agents.workspace_ops import xlsx_bytes
from app.core.command import role_mission
from app.core.command.mission_org import MissionTeam
from app.core.config import settings
from app.core.councils import templates
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e3a_workspace_tools import _seed, project  # noqa: F401


def _run(coro):
    return asyncio.run(coro)


def _team():
    team = MissionTeam.__new__(MissionTeam)
    team.route = {}
    return team


@pytest.mark.parametrize("brief, role", [
    ("Find free places to market Plexecute", "marketing"),
    ("Find investors for Plexecute", "sales"),
    ("Write a competitor analysis of habit and wellbeing apps", "research"),
    ("Write the business plan for MYCO", "business"),
    ("Add sub(a, b) to the project and document it.", None),            # software: the builder
    ("Build the landing page for Plexecute", None),
    ("Make the Plexecute launch video with your BRAG Slim skill.", None),  # a named skill: the builder runs it
    ("Find free places to market Plexecute, in parallel.", None),        # asked to split: the team
])
def test_the_work_goes_to_the_roles_own_agent_and_software_to_the_builder(brief, role):
    assert _run(_team()._role(brief)) == role


def test_role_agents_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "ROLE_AGENTS_ENABLED", False)
    assert _run(_team()._role("Find free places to market Plexecute")) is None


def test_each_role_has_its_trades_tools_and_nothing_that_acts_for_richard():
    marketing = role_mission.role_tools("marketing")
    assert {"web_search", "fetch_url", "write_spreadsheet", "read_document", "recall_richard",
            "consult_specialist_knowledge", "generate_image", "social_draft"} <= set(marketing)
    sales = role_mission.role_tools("sales")
    assert {"discover_prospect_companies", "find_decision_makers", "verify_prospect_email",
            "draft_outreach_sequence"} <= set(sales)
    assert "create_partner_shortlist" in role_mission.role_tools("partnerships")
    for role in ("marketing", "sales", "partnerships", "research", "customer_support", "content", "legal"):
        tools = set(role_mission.role_tools(role))
        assert not tools & {"run_command", "run_build", "run_tests", "install_package", "git_push_with_boundary",
                            "delete_file_with_boundary"}, role
        assert not any("send" in t or "publish" in t for t in tools), role
    assert "generate_image" not in role_mission.role_tools("research")


def test_luna_does_the_work_and_sonnet_takes_over_a_stuck_round(monkeypatch):
    from app.core.providers import router

    no_credit = set()

    async def has_no_credit(provider):
        return provider in no_credit

    monkeypatch.setattr(router, "has_no_credit", has_no_credit)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "ck-test", raising=False)
    assert _run(role_mission.role_model()) == "gpt-6-luna"
    assert _run(role_mission.role_model(stuck=True)) == "claude-sonnet-5-5"
    no_credit.add("openai")
    assert _run(role_mission.role_model()) == "claude-sonnet-5-5"
    no_credit.clear()
    no_credit.add("claude")
    assert _run(role_mission.role_model(stuck=True)) == "gpt-6-luna"


def test_the_agent_speaks_as_its_role_not_as_a_software_engineer():
    runner = role_mission.RoleExecutor(SimpleNamespace(), "gpt-6-luna", "C:\\Users\\lilri\\Projects\\PLEXECUTE",
                                       role="marketing")
    prompt = runner._system_prompt(True)
    assert prompt.startswith("You are JAI's Marketing") and "not a software engineer" in prompt
    assert "write_spreadsheet" in prompt and "round-up" in prompt and "do not stop early" in prompt
    assert "Contact, send, post, publish and spend nothing" in prompt
    assert "autonomous software engineer" not in prompt


def test_a_role_mission_stops_at_its_own_allowance(monkeypatch):
    monkeypatch.setattr(settings, "ROLE_MISSION_MAX_COST_USD", 2.5)
    runner = role_mission.RoleExecutor(SimpleNamespace(), "gpt-6-luna", None, role="sales")
    runner._spent_before = 1.0
    runner.usage.cost_usd = 1.0
    assert _run(runner._over_allowance()) is None and runner.capped is False
    runner.usage.cost_usd = 1.6
    stop = _run(runner._over_allowance())
    assert runner.capped is True and "$2.60 of $2.50" in stop and "saved in the folder" in stop


def test_the_spreadsheet_is_a_real_workbook():
    data = xlsx_bytes([{"name": "Creators", "rows": [["Name", "Followers"], ["Ali & Co <x>", 12000]]},
                       {"name": "Read: me?", "rows": [["Note"], ["ok"]]}])
    archive = zipfile.ZipFile(io.BytesIO(data))
    workbook = archive.read("xl/workbook.xml").decode()
    assert 'name="Creators"' in workbook and 'name="Read  me"' in workbook
    sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert "Ali &amp; Co &lt;x&gt;" in sheet and "<v>12000</v>" in sheet and 's="1"' in sheet


@pytest.mark.integration
def test_the_role_agent_works_in_the_products_folder_with_its_own_tools(project):  # noqa: F811
    from app.core.command.tool_runtime import ToolRuntime

    host, root = project

    async def go():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, host)
            runtime = ToolRuntime(db, ws_id, None, operator="agent:marketing", authority_level=3, user_id=user_id)
            runner = role_mission.RoleExecutor(runtime, "gpt-6-luna", host, role="marketing")
            tools = {t["name"] for t in await runner._prepare_tools()}
            written = await runner.toolbox.call("write_spreadsheet", {
                "path": "growth/free-places.xlsx",
                "sheets": [{"name": "Creators", "rows": [["Name", "Contact"], ["A creator", "hello@example.com"]]}]})
            outside = await runner.toolbox.call("write_spreadsheet", {
                "path": "../escape.xlsx", "sheets": [{"name": "x", "rows": [["a"]]}]})
            shell = await runner.toolbox.call("run_command", {"command": "ls"})
            return tools, written, outside, shell

    tools, written, outside, shell = _run(go())
    assert {"web_search", "write_spreadsheet", "read_document", "finish"} <= tools
    assert "run_command" not in tools and "install_package" not in tools
    assert written["success"] and written["rows_per_sheet"] == {"Creators": 1}
    saved = Path(root) / "growth" / "free-places.xlsx"
    assert saved.exists() and "A creator" in zipfile.ZipFile(saved).read("xl/worksheets/sheet1.xml").decode()
    assert outside["success"] is False and not (Path(root).parent / "escape.xlsx").exists()
    assert shell["success"] is False  # not one of a marketer's tools


def test_the_waiting_list_workflow_follows_richards_rules():
    steps = {s["id"]: s for s in templates.steps("waitlist_growth", product="Plexecute", folder="C:\\P")}
    growth, pitches = steps["growth_list"]["brief"], steps["pitches"]["brief"]
    assert "podcast" not in growth.lower() and "Nothing paid" in growth and "fitness" not in growth
    assert "free guest articles" in growth and "partner businesses" in growth
    assert "sponsorship" not in pitches and "podcast" not in pitches.lower()
    assert "signed by Richard by name" in pitches and "Claim no customers" in pitches
