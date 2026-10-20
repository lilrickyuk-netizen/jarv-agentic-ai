"""Authoritative JARV 31-agent roster regression tests."""

from app.core.agents.registry import get_registry


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
