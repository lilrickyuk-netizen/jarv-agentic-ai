"""Repair 12 tests for inherited swarm authority and workspace scope."""
import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.swarm.manager import SwarmManager, SwarmRunCreate
from app.core.knowledge.catalog import specialist_knowledge
from app.core.knowledge.service import knowledge_service
from app.models.agent import Agent
from app.models.operations import AuditLog
from app.models.swarm import SubAgent, SubAgentLog, SubAgentTask, SwarmRun
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal


async def _seed_lead(session, *, authority=4, tools=None):
    user_id, workspace_id, agent_id = uuid4(), uuid4(), uuid4()
    session.add(User(
        id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
        password_hash="test", is_active=True, is_admin=False,
    ))
    session.add(Workspace(
        id=workspace_id, name="Swarm test", slug=f"swarm-{workspace_id.hex[:8]}",
        description="", owner_id=user_id, is_active=True,
        workspace_type="test", authority_level=authority, swarm_enabled=True,
    ))
    session.add(Agent(
        id=agent_id, name="Lead", agent_type="research", workspace_id=workspace_id,
        is_active=True, authority_level=authority, allowed_tools=tools or ["file_read"],
        blocked_tools=[], config={}, model_provider="test", model_name="test-model",
    ))
    await session.commit()
    await knowledge_service.ingest(session, specialist_knowledge())
    await session.commit()
    return user_id, workspace_id, agent_id


async def _create_run(manager, session, user_id, workspace_id, agent_id):
    return await manager.create_swarm_run(
        SwarmRunCreate(
            workspace_id=workspace_id,
            lead_agent_id=agent_id,
            lead_agent_name="Lead",
            swarm_purpose="bounded research",
            max_sub_agents=2,
        ),
        db=session,
        authenticated_user_id=user_id,
    )


@pytest.mark.integration
def test_swarm_run_is_persisted_and_owner_scoped():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            owner_id, workspace_id, lead_id = await _seed_lead(session)
            swarm_id = await _create_run(
                SwarmManager(), session, owner_id, workspace_id, lead_id)
            row = (await session.execute(
                select(SwarmRun).where(SwarmRun.id == swarm_id)
            )).scalar_one()
            return row

    row = asyncio.run(run())
    assert row.parent_agent_id is not None
    assert row.workspace_id is not None
    assert row.status == "initializing"


@pytest.mark.integration
def test_swarm_owner_cannot_be_substituted():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            owner_id, workspace_id, lead_id = await _seed_lead(session)
            other_id = uuid4()
            session.add(User(
                id=other_id, username=f"u{other_id.hex[:8]}", email=f"{other_id.hex[:8]}@t.io",
                password_hash="test", is_active=True, is_admin=False,
            ))
            await session.commit()
            with pytest.raises(PermissionError, match="own"):
                await _create_run(SwarmManager(), session, other_id, workspace_id, lead_id)

    asyncio.run(run())


@pytest.mark.integration
def test_child_authority_and_tools_cannot_exceed_lead():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            owner_id, workspace_id, lead_id = await _seed_lead(
                session, authority=4, tools=["file_read"])
            manager = SwarmManager()
            swarm_id = await _create_run(manager, session, owner_id, workspace_id, lead_id)

            with pytest.raises(PermissionError, match="authority"):
                await manager.spawn_sub_agent(
                    swarm_id, "documentation", "inspect project", 5, ["file_read"],
                    db=session, authenticated_user_id=owner_id,
                )

            with pytest.raises(PermissionError, match="tools"):
                await manager.spawn_sub_agent(
                    swarm_id, "documentation", "inspect project", 4, ["shell_exec"],
                    db=session, authenticated_user_id=owner_id,
                )

            child_id = await manager.spawn_sub_agent(
                swarm_id, "documentation", "inspect project", 3, ["file_read"],
                db=session, authenticated_user_id=owner_id,
            )
            child = (await session.execute(
                select(SubAgent).where(SubAgent.id == child_id)
            )).scalar_one()
            return child, swarm_id

    child, swarm_id = asyncio.run(run())
    assert child.swarm_run_id == swarm_id
    assert child.meta_data["authority_level"] == 3
    assert child.meta_data["allowed_tools"] == ["file_read"]
    assert child.meta_data["workspace_scope"] == "parent_swarm"


@pytest.mark.integration
def test_swarm_mutations_require_authentication(client):
    create = client.post("/api/swarm/runs", json={
        "workspace_id": str(uuid4()),
        "lead_agent_id": str(uuid4()),
        "lead_agent_name": "lead",
        "swarm_purpose": "bounded task",
        "max_sub_agents": 1,
    })
    spawn = client.post(f"/api/swarm/runs/{uuid4()}/sub-agents", json={
        "agent_template": "research",
        "task_description": "inspect a bounded workspace",
        "authority_level": 1,
        "allowed_tools": ["file_read"],
    })

    assert create.status_code == 401
    assert spawn.status_code == 401


@pytest.mark.integration
def test_swarm_spawn_executes_child_and_persists_verified_outcome(monkeypatch):
    from app.core.agents.specialists.research import ResearchAgent

    monkeypatch.setattr(ResearchAgent, "_provider_configured", staticmethod(lambda: False))

    async def run():
        async with AsyncTestingSessionLocal() as session:
            owner_id, workspace_id, lead_id = await _seed_lead(
                session, authority=6,
                tools=["http_get", "http_post", "file_read", "memory_search"],
            )
            manager = SwarmManager()
            swarm_id = await _create_run(manager, session, owner_id, workspace_id, lead_id)
            child_id = await manager.spawn_sub_agent(
                swarm_id,
                "research",
                "Compare retry strategies and state provider limitations",
                5,
                ["file_read", "memory_search"],
                db=session,
                authenticated_user_id=owner_id,
            )
            child = (await session.execute(
                select(SubAgent).where(SubAgent.id == child_id)
            )).scalar_one()
            child_agent = (await session.execute(
                select(Agent).where(Agent.id == UUID(child.meta_data["agent_id"]))
            )).scalar_one()
            task = (await session.execute(
                select(Task).where(Task.id == UUID(child.meta_data["task_id"]))
            )).scalar_one()
            child_task = (await session.execute(
                select(SubAgentTask).where(SubAgentTask.subagent_id == child_id)
            )).scalar_one()
            logs = (await session.execute(
                select(SubAgentLog).where(SubAgentLog.subagent_id == child_id)
            )).scalars().all()
            swarm = (await session.execute(
                select(SwarmRun).where(SwarmRun.id == swarm_id)
            )).scalar_one()
            audits = (await session.execute(
                select(AuditLog).where(AuditLog.agent_id == child_agent.id)
            )).scalars().all()
            return child, child_agent, task, child_task, logs, swarm, audits

    child, child_agent, task, child_task, logs, swarm, audits = asyncio.run(run())
    assert child.status == "completed" and child.success is True
    assert child.result and child.result["output_text"]
    assert "external_search=False" in child.result["output_text"]
    assert task.status == "completed" and task.result["verified"] is True
    assert task.assigned_agent_id == child_agent.id
    assert child_task.status == "completed" and child_task.success is True
    assert logs and all(log.context["parent_agent_id"] for log in logs)
    assert child_agent.parent_agent_id is not None and child_agent.is_subagent is True
    assert child_agent.authority_level == 5
    assert child_agent.allowed_tools == ["file_read", "memory_search"]
    assert audits and all(
        row.meta_data["parent_agent_id"] == str(child_agent.parent_agent_id)
        for row in audits
    )
    assert swarm.actual_subagents == 1


@pytest.mark.integration
def test_swarm_child_failure_is_persisted_as_failure(monkeypatch):
    from app.core.agents.specialists.research import ResearchAgent

    async def fail_run(self, input_data, context):
        raise RuntimeError("research execution failed")

    monkeypatch.setattr(ResearchAgent, "run", fail_run)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            owner_id, workspace_id, lead_id = await _seed_lead(
                session, authority=6,
                tools=["http_get", "http_post", "file_read", "memory_search"],
            )
            manager = SwarmManager()
            swarm_id = await _create_run(manager, session, owner_id, workspace_id, lead_id)
            child_id = await manager.spawn_sub_agent(
                swarm_id,
                "research",
                "Assess a bounded research task",
                5,
                ["file_read", "memory_search"],
                db=session,
                authenticated_user_id=owner_id,
            )
            child = (await session.execute(
                select(SubAgent).where(SubAgent.id == child_id)
            )).scalar_one()
            task = (await session.execute(
                select(Task).where(Task.id == UUID(child.meta_data["task_id"]))
            )).scalar_one()
            child_task = (await session.execute(
                select(SubAgentTask).where(SubAgentTask.subagent_id == child_id)
            )).scalar_one()
            return child, task, child_task

    child, task, child_task = asyncio.run(run())
    assert child.status == "failed" and child.success is False
    assert child.result["error"]
    assert task.status == "failed" and task.result["verified"] is False
    assert child_task.status == "failed" and child_task.success is False