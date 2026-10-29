"""Repair 12e-3b: persisted swarm lifecycle, limits, costs, and the swarm tools.

Sub-agents run through the real AgentRunner (the documentation agent's
no-provider path), so every run, task, log and cost row here is real.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AgentContext, AuthorityLevel, AgentConfig
from app.core.auth import get_current_user_id
from app.core.knowledge.catalog import specialist_knowledge
from app.core.knowledge.service import knowledge_service
from app.core.swarm.limits import SwarmLimitManager
from app.core.swarm.manager import SwarmManager, SwarmRunCreate
from app.core.swarm.sub_agent import SubAgentManager, SubAgentTaskCreate
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import create_tool
from app.main import app
from app.models.agent import Agent
from app.models.swarm import SubAgent, SwarmCostRecord, SwarmRun
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal


def _run(coro):
    return asyncio.run(coro)


async def _seed(db, *, max_subagents=10):
    user_id, ws_id, lead_id = uuid4(), uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="Swarm", slug=f"sw-{ws_id.hex[:8]}", description="",
                     workspace_type="test", authority_level=5, is_active=True, swarm_enabled=True,
                     max_subagents=max_subagents))
    db.add(Agent(id=lead_id, name="Lead", agent_type="documentation", workspace_id=ws_id, is_active=True,
                 authority_level=4, allowed_tools=["file_read", "file_list", "memory_search"], blocked_tools=[],
                 config={}, model_provider="test", model_name="claude-sonnet-4-6"))
    await db.commit()
    await knowledge_service.ingest(db, specialist_knowledge())
    await db.commit()
    return user_id, ws_id, lead_id


async def _swarm(db, owner, ws_id, lead_id, max_sub_agents=3):
    return await SwarmManager().create_swarm_run(
        SwarmRunCreate(workspace_id=ws_id, lead_agent_id=lead_id, lead_agent_name="Lead",
                       swarm_purpose="document the modules", max_sub_agents=max_sub_agents),
        db=db, authenticated_user_id=owner)


async def _spawn(db, swarm_id, owner, task="Describe the project layout"):
    return await SwarmManager().spawn_sub_agent(swarm_id, "documentation", task, 2, ["file_read"], db=db,
                                                authenticated_user_id=owner)


@pytest.mark.integration
def test_swarm_lifecycle_is_persisted_end_to_end():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id, lead_id = await _seed(db)
            manager, subs = SwarmManager(), SubAgentManager()
            swarm_id = await _swarm(db, owner, ws_id, lead_id)
            first = await _spawn(db, swarm_id, owner)
            await manager.pause_swarm(db, swarm_id, owner)
            with pytest.raises(ValueError, match="paused"):
                await _spawn(db, swarm_id, owner)
            await manager.resume_swarm(db, swarm_id, owner)
            second = await _spawn(db, swarm_id, owner, "Describe the configuration")
            task_id = await subs.assign_task(db, SubAgentTaskCreate(
                sub_agent_id=first, task_title="Follow-up", task_description="List the entry points"), owner)
            status = await subs.get_status(db, first, owner)
            output = await subs.collect_output(db, first, owner)
            listed = await manager.list_swarms(db, owner, ws_id)
            stats = await manager.get_swarm_stats(db, ws_id)
            done = await manager.complete_swarm(db, swarm_id, owner)
            children = (await db.execute(select(SubAgent).where(SubAgent.swarm_run_id == swarm_id))).scalars().all()
            cost_rows = (await db.execute(select(SwarmCostRecord).where(
                SwarmCostRecord.swarm_run_id == swarm_id))).scalars().all()
            agents = (await db.execute(select(Agent).where(Agent.is_subagent.is_(True),
                                                           Agent.workspace_id == ws_id))).scalars().all()
            return task_id, status, output, listed, stats, done, children, cost_rows, agents, second

    task_id, status, output, listed, stats, done, children, cost_rows, agents, second = _run(run())
    assert status["assigned_tasks"] == 2 and status["completed_tasks"] == 2
    assert len(output["completed_tasks"]) == 2 and output["summary"]
    assert listed[0].status.value == "running" and listed[0].completed_sub_agents == 2
    assert stats["total_sub_agents_spawned"] == 2 and stats["succeeded_sub_agents"] == 2
    assert done.status == "completed" and done.success is True and done.completed_at is not None
    assert {c.status for c in children} == {"dissolved"} and all(c.success for c in children)
    assert len(cost_rows) == 1 and cost_rows[0].total_subagents == 2
    assert agents and not any(a.is_active for a in agents)


@pytest.mark.integration
def test_cancel_dissolves_and_owner_scope_holds():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id, lead_id = await _seed(db)
            stranger = uuid4()
            db.add(User(id=stranger, username=f"u{stranger.hex[:8]}", email=f"{stranger.hex[:8]}@t.io",
                        password_hash="x", is_active=True, is_admin=False))
            await db.commit()
            manager = SwarmManager()
            swarm_id = await _swarm(db, owner, ws_id, lead_id)
            await _spawn(db, swarm_id, owner)
            assert await manager.get_swarm_run(db, swarm_id, stranger) is None
            with pytest.raises(LookupError):
                await manager.pause_swarm(db, swarm_id, stranger)
            cancelled = await manager.cancel_swarm(db, swarm_id, owner, "objective changed")
            with pytest.raises(ValueError, match="already finished"):
                await manager.cancel_swarm(db, swarm_id, owner, "again")
            return cancelled

    cancelled = _run(run())
    assert cancelled.status == "cancelled" and cancelled.success is False


@pytest.mark.integration
def test_limits_are_enforced_from_policy_and_capped_at_global():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id, lead_id = await _seed(db)
            limits = SwarmLimitManager()
            policy = await limits.set_swarm_limit(db, ws_id, max_concurrent_swarms=1, max_sub_agents_per_swarm=999)
            await _swarm(db, owner, ws_id, lead_id, max_sub_agents=2)
            with pytest.raises(ValueError, match="already active"):
                await _swarm(db, owner, ws_id, lead_id, max_sub_agents=2)
            return policy, await limits.get_limit_stats(db, ws_id)

    policy, stats = _run(run())
    assert policy.max_concurrent_swarms == 1 and policy.max_subagents == 10  # capped at the global limit
    assert stats["current_usage"]["active_swarms"] == 1 and stats["remaining"]["swarms"] == 0


@pytest.mark.integration
def test_logs_attach_to_parent_task_and_stale_sub_agents_time_out():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id, lead_id = await _seed(db)
            swarm_id = await _swarm(db, owner, ws_id, lead_id)
            child_id = await _spawn(db, swarm_id, owner)
            parent = Task(id=uuid4(), workspace_id=ws_id, title="parent", description="parent", task_type="command",
                          status="running", priority=5, meta_data={})
            db.add(parent)
            stuck = SubAgent(swarm_run_id=swarm_id, subagent_name="qa", subagent_type="qa", role="scoped_subagent",
                             model_provider="test", model_name="test", status="working",
                             started_at=datetime.now(timezone.utc) - timedelta(hours=2),
                             meta_data={"timeout_seconds": 600})
            db.add(stuck)
            await db.flush()
            attached = await SubAgentManager().attach_logs_to_parent_task(db, child_id, owner, parent.id)
            timed_out = await SubAgentManager().time_out_stale(db)
            await db.commit()
            return attached, timed_out, parent.id, stuck.id

    attached, timed_out, parent_id, stuck_id = _run(run())
    assert attached["entries"] >= 1
    assert timed_out == [stuck_id]

    async def check():
        async with AsyncTestingSessionLocal() as db:
            parent = (await db.execute(select(Task).where(Task.id == parent_id))).scalar_one()
            stuck = (await db.execute(select(SubAgent).where(SubAgent.id == stuck_id))).scalar_one()
            return parent, stuck

    parent, stuck = _run(check())
    assert list(parent.context["subagent_logs"].values())[0]["entries"]
    assert stuck.status == "timed_out" and stuck.success is False


@pytest.mark.integration
def test_swarm_tools_spawn_under_a_named_lead_and_cancel_needs_approval():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id, _ = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            spawn = create_tool("spawn_sub_agent", ToolConfig(authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION))
            spawned = await spawn.execute({"agent_template": "documentation", "task": "Summarise the README",
                                           "lead_agent": "documentation"}, ctx)
            swarm_id = spawned.result_data["swarm_run_id"]
            cost = await create_tool("calculate_swarm_token_cost", ToolConfig()).execute({"swarm_run_id": swarm_id}, ctx)
            cancel = await create_tool("cancel_swarm_with_boundary", ToolConfig(
                authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION)).execute(
                {"swarm_run_id": swarm_id, "reason": "no longer needed"}, ctx)
            low = create_tool("spawn_sub_agent", ToolConfig(authority_level=AuthorityLevel.LEVEL_3_CODE_EXECUTION))
            refused = None
            try:
                await low.execute({"agent_template": "documentation", "task": "x" * 10}, ctx)
            except Exception as exc:  # noqa: BLE001
                refused = exc
            return spawned, cost, cancel, refused

    spawned, cost, cancel, refused = _run(run())
    assert spawned.success, spawned.error_message
    assert spawned.result_data["success"] is True and spawned.result_data["status"] == "completed"
    assert cost.success and "totals" in cost.result_data
    assert cancel.success is False and cancel.result_data["requires_approval"] is True
    assert refused is not None


@pytest.mark.integration
def test_swarm_manager_agent_runs_tasks_as_one_swarm():
    from app.core.agents.specialists.swarm_manager import SwarmManagerAgent

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id, _ = await _seed(db)
            agent = SwarmManagerAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                  authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION))
            result = await agent.execute({"objective": "document two areas", "lead_agent": "documentation",
                                          "tasks": [{"agent": "documentation", "task": "Describe the API layer"},
                                                    {"agent": "documentation", "task": "Describe the data model"}]},
                                         AgentContext(workspace_id=ws_id, user_id=owner, db_session=db))
            swarm = (await db.execute(select(SwarmRun).where(SwarmRun.workspace_id == ws_id))).scalar_one()
            return result, swarm

    result, swarm = _run(run())
    assert result.success, result.error_message
    assert len(result.result_data["sub_agents"]) == 2 and all(s["success"] for s in result.result_data["sub_agents"])
    assert swarm.status == "completed"


@pytest.mark.api
def test_swarm_api_lists_real_runs_for_the_owner_only(client):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id, lead_id = await _seed(db)
            swarm_id = await _swarm(db, owner, ws_id, lead_id)
            await db.commit()
            return owner, ws_id, swarm_id

    owner, ws_id, swarm_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    runs = client.get("/api/swarm/runs")
    stats = client.get(f"/api/swarm/runs/stats/{ws_id}")
    paused = client.post(f"/api/swarm/runs/{swarm_id}/pause")
    dashboard = client.get(f"/api/swarm/dashboard/{ws_id}")
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
    hidden = client.get("/api/swarm/runs")
    stranger = client.get(f"/api/swarm/runs/{swarm_id}")

    assert runs.status_code == 200 and [r["id"] for r in runs.json()] == [str(swarm_id)]
    assert stats.json()["total_swarms"] == 1
    assert paused.json()["status"] == "paused"
    assert dashboard.status_code == 200 and dashboard.json()["limits"]["current_usage"]["active_swarms"] == 1
    assert hidden.json() == [] and stranger.status_code == 404
