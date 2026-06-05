"""
Behaviour tests for Orchestrator delegation (Repair 1).

These prove the Orchestrator actually delegates planned work to real
registered specialist agents through the AgentRunner -> registry ->
agent.execute() path, and reports HONEST counts derived from real
execution outcomes (not the old fabricated "planned / 0 / []").

The only thing mocked is the LLM/provider layer (so planning is
deterministic). The delegation logic, registry, runner, and specialist
execution are all real and unmocked.
"""
import asyncio
from uuid import uuid4

import pytest

from app.agents.orchestrator import OrchestratorAgent
from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.registry import get_registry


def _make_orchestrator() -> OrchestratorAgent:
    config = AgentConfig(
        agent_id=uuid4(),
        workspace_id=uuid4(),
        authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION,
    )
    return OrchestratorAgent(config)


@pytest.mark.agent
@pytest.mark.integration
def test_orchestrator_delegates_to_real_registered_agents(monkeypatch):
    """
    A mission enters the orchestrator, a plan is produced, and the planned
    tasks are delegated to REAL registered agents through the runner/registry
    path. agents_used and completed_tasks come from real execution; the status
    is never the old 'planned' sentinel.
    """
    # Mock ONLY the provider layer: make LLM planning unavailable so the
    # orchestrator falls back to its deterministic built-in plan (research + qa).
    def _no_router():
        raise RuntimeError("provider disabled for deterministic test")

    monkeypatch.setattr("app.agents.orchestrator.get_router", _no_router)

    orch = _make_orchestrator()
    ctx = AgentContext(workspace_id=orch.config.workspace_id)

    result = asyncio.run(
        orch.execute(
            {"mission": "Analyze the authentication module and report findings"},
            ctx,
        )
    )
    data = result.result_data

    # Status must be a real outcome, NOT the removed 'planned' sentinel.
    assert data["mission_status"] in {"completed", "partial", "failed"}
    assert data["mission_status"] != "planned"

    # The deterministic fallback plan delegates to real registry agents.
    assert data["total_tasks"] == 2
    assert data["agents_used"], "no agents were actually invoked"
    assert set(data["agents_used"]) == {"research", "qa"}

    # Every agent reported as used must be a real IMPLEMENTED registry agent,
    # proving delegation went through the registry (not a hardcoded list).
    registry = get_registry()
    for name in data["agents_used"]:
        assert registry.is_implemented(name), f"{name} is not an implemented registry agent"

    # Counts are derived from real execution.
    assert data["completed_tasks"] == 2
    assert data["failed_tasks"] == 0
    assert data["completed_tasks"] + data["failed_tasks"] <= data["total_tasks"]

    # Both stub specialists succeed -> mission completed honestly.
    assert data["mission_status"] == "completed"

    # Per-task results prove each agent actually executed (real output text).
    statuses = {tr["task_id"]: tr["status"] for tr in data["task_results"]}
    assert statuses, "no per-task delegation results recorded"
    assert all(s == "completed" for s in statuses.values())
    assert all((tr["output_preview"] or "") for tr in data["task_results"]), \
        "delegated agents produced no output (they did not really execute)"

    # The orchestrator's own run succeeded because real work completed.
    assert result.success is True


@pytest.mark.agent
@pytest.mark.integration
def test_orchestrator_defers_approval_tasks(monkeypatch):
    """
    When the mission carries constraints, the fallback plan flags the
    verification task as requires_approval. The orchestrator must DEFER it
    (not auto-execute it) and report requires_human_input, with status
    'partial' rather than 'completed'.
    """
    def _no_router():
        raise RuntimeError("provider disabled for deterministic test")

    monkeypatch.setattr("app.agents.orchestrator.get_router", _no_router)

    orch = _make_orchestrator()
    ctx = AgentContext(workspace_id=orch.config.workspace_id)

    result = asyncio.run(
        orch.execute(
            {
                "mission": "Refactor billing and prepare release",
                "constraints": ["do not touch production data"],
            },
            ctx,
        )
    )
    data = result.result_data

    # One task delegated (research), one deferred for approval (qa verify).
    assert data["requires_human_input"] is True
    deferred = [tr for tr in data["task_results"] if tr["status"] == "deferred_approval"]
    assert deferred, "approval-gated task was not deferred"
    # Not everything executed, so it cannot be 'completed'.
    assert data["mission_status"] == "partial"
    assert "research" in data["agents_used"]


@pytest.mark.agent
@pytest.mark.unit
def test_derive_mission_status_is_honest():
    """
    Pure-logic proof that the orchestrator never claims 'completed' when all
    delegated work failed, and reports 'partial'/'failed' correctly.
    """
    orch = _make_orchestrator()

    # All delegated work failed -> failed (never 'completed').
    assert orch._derive_mission_status(
        {"attempted": 3, "completed": 0, "deferred": 0}
    ) == "failed"

    # All delegated work succeeded, nothing deferred -> completed.
    assert orch._derive_mission_status(
        {"attempted": 2, "completed": 2, "deferred": 0}
    ) == "completed"

    # Mixed success -> partial.
    assert orch._derive_mission_status(
        {"attempted": 3, "completed": 1, "deferred": 0}
    ) == "partial"

    # Nothing executed (all deferred/skipped) -> partial, not completed.
    assert orch._derive_mission_status(
        {"attempted": 0, "completed": 0, "deferred": 2}
    ) == "partial"

    # Everything that ran succeeded but approvals remain -> partial.
    assert orch._derive_mission_status(
        {"attempted": 2, "completed": 2, "deferred": 1}
    ) == "partial"
