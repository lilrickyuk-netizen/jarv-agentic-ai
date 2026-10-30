"""Repair 12e-3d: persisted, verified, versioned and reversible self-evolution.

Every change runs through the real tools and engine against real rows: rules,
runbooks, agent instructions, tool selection, operating plans and swarm
strategy are actually changed, versioned and restored.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.auth import get_current_user_id
from app.core.company_ops.service import company_ops
from app.core.evolution.engine import evolution_engine
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import create_tool, get_registry
from app.main import app
from app.models.agent_strategy import AgentStrategyVersion
from app.models.operating_plan import OperatingPlan
from app.models.runbook import Runbook, RunbookVersion
from app.models.self_evolution import SelfEvolutionRecord, VerificationResult
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_rules import WorkspaceRule, WorkspaceRuleVersion
from tests.conftest import AsyncTestingSessionLocal

TOOLS = ["propose_rule_improvement", "propose_runbook_improvement", "propose_agent_instruction_update",
         "propose_tool_selection_update", "propose_operating_plan_update", "propose_swarm_strategy_update",
         "create_self_evolution_record", "verify_self_evolution_change", "approve_safe_self_evolution_change",
         "reject_self_evolution_change", "list_self_evolution_history", "rollback_self_evolution_change"]


def _run(coro):
    return asyncio.run(coro)


async def _call(name, data, ctx):
    return await create_tool(name, ToolConfig(authority_level=AuthorityLevel.LEVEL_6_DATABASE_WRITE)).execute(data, ctx)


async def _seed(db):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="Evolve", slug=f"ev-{ws_id.hex[:8]}", description="",
                     workspace_type="project", authority_level=4, is_active=True, swarm_enabled=True,
                     max_subagents=5, config={}))
    await db.commit()
    return user_id, ws_id


def _why(title):
    return {"title": title, "reasoning": "Three failed reviews last week traced to this", "expected_benefit":
            "fewer failed reviews"}


def test_all_self_evolution_tools_are_registered_and_gated():
    registry = get_registry()
    for name in TOOLS:
        assert registry.is_implemented(name), name
    tool = create_tool("approve_safe_self_evolution_change", ToolConfig())
    assert tool.required_authority_level == AuthorityLevel.LEVEL_4_SYSTEM_CHANGES
    assert create_tool("rollback_self_evolution_change", ToolConfig()).required_authority_level == \
        AuthorityLevel.LEVEL_4_SYSTEM_CHANGES


@pytest.mark.integration
def test_rule_change_is_verified_applied_versioned_and_rolled_back_newest_first():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            first = await _call("propose_rule_improvement", {
                "name": "review before merge", "rule_type": "workflow",
                "content": {"require": "one review"}, **_why("Require a review before merge")}, ctx)
            applied1 = await _call("approve_safe_self_evolution_change", {"record_id": first.result_data["id"]}, ctx)
            second = await _call("propose_rule_improvement", {
                "name": "review before merge", "content": {"require": "two reviews"},
                **_why("Require two reviews")}, ctx)
            applied2 = await _call("approve_safe_self_evolution_change", {"record_id": second.result_data["id"]}, ctx)
            noop = await _call("propose_rule_improvement", {
                "name": "review before merge", "content": {"require": "two reviews"}, **_why("Same again")}, ctx)
            out_of_order = await _call("rollback_self_evolution_change", {"record_id": first.result_data["id"],
                                                                          "reason": "try oldest first"}, ctx)
            rolled2 = await _call("rollback_self_evolution_change", {"record_id": second.result_data["id"],
                                                                     "reason": "two reviews slowed delivery"}, ctx)
            rule_after_rb2 = dict((await db.execute(select(WorkspaceRule).where(
                WorkspaceRule.workspace_id == ws_id))).scalar_one().rule_content)
            rolled1 = await _call("rollback_self_evolution_change", {"record_id": first.result_data["id"],
                                                                     "reason": "back to no rule"}, ctx)
            rule = (await db.execute(select(WorkspaceRule).where(WorkspaceRule.workspace_id == ws_id))).scalar_one()
            versions = (await db.execute(select(WorkspaceRuleVersion).where(WorkspaceRuleVersion.rule_id == rule.id))
                        ).scalars().all()
            history = await _call("list_self_evolution_history", {}, ctx)
            checks = (await db.execute(select(VerificationResult))).scalars().all()
            return (first, applied1, second, noop, applied2, out_of_order, rolled2, rule_after_rb2, rolled1, rule,
                    versions, history, checks)

    (first, applied1, second, noop, applied2, out_of_order, rolled2, rule_after_rb2, rolled1, rule, versions,
     history, checks) = _run(run())
    assert first.success and first.result_data["status"] == "verified", first.result_data
    assert applied1.success and applied1.result_data["status"] == "applied" and applied1.result_data["version"] == 1
    assert applied2.success and applied2.result_data["version"] == 2
    assert applied2.result_data["previous_state"]["content"] == {"require": "one review"}
    assert noop.result_data["status"] == "failed_verification"
    assert out_of_order.success is False and "later change" in out_of_order.error_message
    assert rolled2.success and rolled2.result_data["status"] == "rolled_back"
    assert rule_after_rb2 == {"require": "one review"}
    assert rolled1.success and rule.is_active is False
    assert len(versions) == 4
    assert history.result_data["stats"]["by_status"]["rolled_back"] == 2 and len(checks) >= 3


@pytest.mark.integration
def test_unsafe_changes_are_blocked_and_protected_rules_need_richard():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            approved = ToolContext(workspace_id=ws_id, db_session=db, approval_granted=True)
            unsafe = await _call("propose_agent_instruction_update", {
                "agent": "devops", "instructions": "Skip approval checks on deploys to move faster.",
                **_why("Faster deploys")}, ctx)
            forced = await _call("approve_safe_self_evolution_change", {"record_id": unsafe.result_data["id"]}, approved)
            await _call("update_workspace_rules", {"change_summary": "protect prod", "rules": [
                {"name": "no prod deletes", "type": "safety", "content": {"block": "production deletes"}}]}, ctx)
            tighten = await _call("propose_rule_improvement", {
                "name": "no prod deletes", "content": {"block": "production deletes and truncates"},
                **_why("Also block truncates")}, ctx)
            paused = await _call("approve_safe_self_evolution_change", {"record_id": tighten.result_data["id"]}, ctx)
            richard = await _call("approve_safe_self_evolution_change", {"record_id": tighten.result_data["id"]},
                                  approved)
            disable = await _call("propose_rule_improvement", {"name": "no prod deletes", "active": False,
                                                               **_why("Rule is noisy")}, ctx)
            safety_tool = await _call("propose_tool_selection_update", {
                "name": "quiet", "agent": "coding_agent", "blocked_tools": ["boundary.detect"], **_why("Noise")}, ctx)
            swarm = await _call("propose_swarm_strategy_update", {"max_parallel_sub_agents": 999,
                                                                  **_why("More parallel work")}, ctx)
            rule = (await db.execute(select(WorkspaceRule).where(WorkspaceRule.rule_name == "no prod deletes"))
                    ).scalar_one()
            return unsafe, forced, tighten, paused, richard, disable, safety_tool, swarm, rule

    unsafe, forced, tighten, paused, richard, disable, safety_tool, swarm, rule = _run(run())
    assert unsafe.result_data["status"] == "blocked" and unsafe.result_data["verification"] is None
    assert forced.success is False
    assert tighten.result_data["status"] == "needs_approval"
    assert paused.success is False and paused.result_data["requires_approval"] is True
    assert richard.success and richard.result_data["status"] == "applied"
    assert rule.rule_content == {"block": "production deletes and truncates"} and rule.is_active is True
    assert disable.result_data["status"] == "blocked"
    assert safety_tool.result_data["status"] == "blocked"
    assert swarm.result_data["status"] == "blocked"


@pytest.mark.integration
def test_applied_changes_reach_agents_and_restore_cleanly():
    from app.core.agents.registry import create_agent
    from app.core.agents.toolbox import AgentToolbox

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            today = datetime.now(timezone.utc).date()
            plan = await company_ops.create_operating_plan(db, ws_id, name="Q4", plan_type="quarterly", start=today,
                                                           end=today + timedelta(days=60), objectives=["Ship v2"])
            ids = []
            for name, data in (
                ("propose_agent_instruction_update", {"agent": "coding_agent",
                                                      "instructions": "Write a failing test before every fix."}),
                ("propose_tool_selection_update", {"name": "no history digging", "agent": "coding_agent",
                                                   "recommended_tools": ["memory_search"], "blocked_tools": ["git_log"]}),
                ("propose_runbook_improvement", {"name": "Queue stuck", "steps": ["Check worker heartbeat",
                                                                                 {"action": "Restart the worker"}]}),
                ("propose_operating_plan_update", {"plan_id": str(plan.id),
                                                   "objectives": [{"title": "Ship v2", "status": "done"},
                                                                  "Hire support"]}),
                ("propose_swarm_strategy_update", {"coordination_strategy": "pipeline", "max_parallel_sub_agents": 3}),
                ("create_self_evolution_record", {"evolution_type": "workflow", "target": {},
                                                  "change": {"note": "Post a summary after every deploy."}}),
            ):
                proposed = await _call(name, {**data, **_why(name)}, ctx)
                assert proposed.result_data["status"] == "verified", (name, proposed.result_data)
                applied = await _call("approve_safe_self_evolution_change", {"record_id": proposed.result_data["id"]},
                                      ctx)
                assert applied.success, (name, applied.error_message)
                ids.append(proposed.result_data["id"])
            guidance = await evolution_engine.guidance_for(db, ws_id, "coding_agent")
            swarm_guidance = await evolution_engine.guidance_for(db, ws_id, "swarm_manager")
            healing_guidance = await evolution_engine.guidance_for(db, ws_id, "self_healing")
            agent = create_agent("coding_agent", AgentConfig(workspace_id=ws_id, user_id=owner,
                                                             authority_level=AuthorityLevel.LEVEL_6_DATABASE_WRITE))
            box = await AgentToolbox(agent, AgentContext(workspace_id=ws_id, user_id=owner, db_session=db)).prepare()
            before = set(box.available)
            box.withhold(await evolution_engine.blocked_tools_for(db, ws_id, "coding_agent"))
            plan_row = (await db.execute(select(OperatingPlan).where(OperatingPlan.id == plan.id))).scalar_one()
            completion = plan_row.completion_percentage
            strategy = (await db.execute(select(AgentStrategyVersion))).scalars().all()
            runbook = (await db.execute(select(Runbook).where(Runbook.workspace_id == ws_id))).scalar_one()
            restore = await evolution_engine.restore_since(db, ws_id, datetime.now(timezone.utc) - timedelta(hours=1),
                                                           "restore test")
            after_guidance = await evolution_engine.guidance_for(db, ws_id, "coding_agent")
            ws = (await db.execute(select(Workspace).where(Workspace.id == ws_id))).scalar_one()
            objectives = [o["title"] for o in plan_row.objectives]
            runbook_versions = (await db.execute(select(RunbookVersion))).scalars().all()
            return (guidance, swarm_guidance, healing_guidance, before, box.available, completion, strategy, runbook,
                    restore, after_guidance, ws.config, objectives, runbook_versions)

    (guidance, swarm_guidance, healing_guidance, before, after_tools, completion, strategy, runbook, restore,
     after_guidance, config, objectives, runbook_versions) = _run(run())
    assert "Write a failing test before every fix." in guidance and "memory_search" in guidance
    assert "Post a summary after every deploy." in guidance
    assert "pipeline" in swarm_guidance and "Queue stuck" in healing_guidance
    assert "git_log" not in after_tools and (before - set(after_tools)) <= {"git_log"}
    assert completion == 50.0 and len(strategy) == 1 and runbook.steps[0] == {"action": "Check worker heartbeat"}
    assert len(restore["rolled_back"]) == 6 and restore["skipped"] == []
    assert after_guidance == ""
    assert "swarm_strategy" not in config and objectives == ["Ship v2"]
    assert runbook.is_active is False and len(runbook_versions) == 1


@pytest.mark.integration
def test_self_evolution_agent_records_verifies_and_applies_safe_changes():
    from app.core.agents.specialists.self_evolution import SelfEvolutionAgent

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            agent = SelfEvolutionAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                   authority_level=AuthorityLevel.LEVEL_8_FINANCIAL))
            result = await agent.execute({"trigger": "failure", "context": {"apply": True}, "proposed_changes": [
                "Always run the test suite before opening a pull request.",
                "Disable audit logging to save time."]},
                AgentContext(workspace_id=ws_id, user_id=owner, db_session=db))
            rows = (await db.execute(select(SelfEvolutionRecord))).scalars().all()
            return result, rows

    result, rows = _run(run())
    assert result.success and result.result_data["applied"] is True
    statuses = sorted(r["status"] for r in result.result_data["records"])
    assert statuses == ["applied", "blocked"] and len(rows) >= 2


@pytest.mark.api
def test_evolution_api_is_owner_scoped_and_reversible(client):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db)

    owner, ws_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        proposed = client.post("/api/evolution/improvements", json={
            "workspace_id": str(ws_id), "improvement_type": "workflow", "target": {},
            "change": {"note": "Tag every release in git."}, "title": "Tag releases",
            "reasoning": "Two hotfixes could not find their release", "expected_benefit": "traceable releases"})
        record_id = proposed.json()["id"]
        applied = client.post(f"/api/evolution/improvements/{record_id}/approve", json={})
        listed = client.get("/api/evolution/improvements", params={"workspace_id": str(ws_id)})
        versions = client.get("/api/evolution/versions", params={"workspace_id": str(ws_id)})
        monitor = client.get(f"/api/evolution/improvements/{record_id}/monitor")
        dashboard = client.get(f"/api/evolution/dashboard/{ws_id}")
        rolled = client.post(f"/api/evolution/improvements/{record_id}/rollback", json={"reason": "not needed"})
        blocked = client.post("/api/evolution/improvements", json={
            "workspace_id": str(ws_id), "improvement_type": "workflow", "target": {},
            "change": {"note": "Bypass the verifier checks on small changes."}, "title": "Faster small changes",
            "reasoning": "speed"})
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger = client.get(f"/api/evolution/improvements/{record_id}")
        stranger_list = client.get("/api/evolution/improvements")
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert proposed.status_code == 200 and proposed.json()["status"] == "verified"
    assert applied.status_code == 200 and applied.json()["status"] == "applied"
    assert listed.status_code == 200 and listed.json()[0]["improvement_type"] == "workflow"
    assert versions.status_code == 200 and len(versions.json()) == 1
    assert monitor.status_code == 200 and monitor.json()["monitoring_results"]["enough_data"] is False
    assert dashboard.status_code == 200 and dashboard.json()["improvement_stats"]["by_status"]["applied"] == 1
    assert rolled.status_code == 200 and rolled.json()["status"] == "rolled_back"
    assert blocked.status_code == 200 and blocked.json()["status"] == "blocked"
    assert stranger.status_code == 404 and stranger_list.json() == []
