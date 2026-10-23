"""Authoritative JARV 31-agent roster regression tests."""

from app.core.agents.registry import get_registry
from app.core.agents.runner import AgentRunner
from app.core.config import settings
from app.core.knowledge.catalog import specialist_knowledge
from app.core.knowledge.service import knowledge_service
from tests.conftest import AsyncTestingSessionLocal
from uuid import uuid4
import asyncio
import pytest


EXPECTED_CORE_AGENTS = {
    "orchestrator",
    "swarm_manager",
}

EXPECTED_SPECIALIST_AGENTS = {
    "coding_agent",
    "debugging_agent",
    "verifier",
    "qa",
    "devops",
    "infrastructure",
    "monitoring",
    "self_healing",
    "rollback",
    "security",
    "company_operator",
    "workspace_manager",
    "business",
    "finance",
    "documentation",
    "research",
    "memory",
    "self_evolution",
    "marketing",
    "growth",
    "customer_support",
    "sales",
    "onboarding",
    "community",
    "partnerships",
    "content",
    "creation",
    "legal",
    "analytics",
}

EXPECTED_AGENTS = EXPECTED_CORE_AGENTS | EXPECTED_SPECIALIST_AGENTS


def test_authoritative_roster_contains_exactly_31_agents():
    registry = get_registry()

    assert len(EXPECTED_CORE_AGENTS) == 2
    assert len(EXPECTED_SPECIALIST_AGENTS) == 29
    assert len(EXPECTED_AGENTS) == 31
    assert set(registry.REQUIRED_AGENTS) == EXPECTED_AGENTS


def test_all_31_design_agents_are_registered_and_implemented():
    registry = get_registry()

    failures = []

    for agent_name in sorted(EXPECTED_AGENTS):
        if not registry.is_registered(agent_name):
            failures.append(f"{agent_name}: not registered")
            continue

        if not registry.is_implemented(agent_name):
            failures.append(f"{agent_name}: not implemented")

    assert failures == []


def test_example_agent_is_not_part_of_design_roster():
    registry = get_registry()

    assert "example" not in registry.REQUIRED_AGENTS
    assert "example_agent" not in registry.REQUIRED_AGENTS


def test_swarm_manager_agent_executes_through_runner(test_user, test_workspace):
    async def run():
        async with AsyncTestingSessionLocal() as session:
            await knowledge_service.ingest(session, specialist_knowledge())
            await session.commit()
            return await AgentRunner().run_agent(
                "swarm_manager", "report actual swarm limits", test_workspace.id,
                user_id=test_user.id, db=session,
            )

    result = asyncio.run(run())

    assert result["success"] is True
    assert result["agent"] == "swarm_manager"
    assert result["output_text"]
    assert "limits" in result["result_data"]

@pytest.mark.agent
@pytest.mark.integration
@pytest.mark.parametrize("agent_name", sorted(EXPECTED_AGENTS))
def test_all_31_agents_execute_through_runner_without_external_credentials(
    agent_name, monkeypatch, test_user, test_workspace,
):
    for key in ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(settings, key, None, raising=False)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            await knowledge_service.ingest(session, specialist_knowledge())
            await session.commit()
            return await AgentRunner().run_agent(
                agent_name,
                "Inspect a sample project and provide a truthful role-specific assessment",
                test_workspace.id,
                user_id=test_user.id,
                db=session,
            )

    result = asyncio.run(run())

    assert result["agent"] == agent_name
    assert result["success"] is True, result.get("error")
    assert result["output_text"].strip()
    assert result["result_data"]
    assert result["specialist_knowledge"]
