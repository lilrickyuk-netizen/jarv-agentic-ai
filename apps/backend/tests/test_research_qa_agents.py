"""
Behaviour tests for Repair 2: real Research Agent and QA Agent.

These prove the two agents no longer fabricate output:
- Research: honest limitations when no provider/external search; uses the real
  provider boundary's output when a provider is present; structured output
  grounded in the real query; invokable via the registry/runner path.
- QA: no fake coverage; runs real py_compile checks; honestly blocks shell
  commands it cannot run; invokable via the registry/runner path.

Plus an integration test proving the repaired orchestrator delegates to both
agents and gets back non-fabricated structured outputs.

Only the provider boundary is mocked. The orchestrator, registry, runner, and
the agents' own logic are NOT mocked.
"""
import asyncio
import json
from uuid import uuid4

import pytest

import app.core.providers as providers_mod
from app.agents.orchestrator import OrchestratorAgent
from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.registry import get_registry
from app.core.agents.runner import AgentRunner
from app.core.agents.specialists.research import ResearchAgent
from app.core.agents.specialists.qa import QAAgent


def _cfg(level=AuthorityLevel.LEVEL_9_SWARM_CREATION) -> AgentConfig:
    return AgentConfig(agent_id=uuid4(), workspace_id=uuid4(), authority_level=level)


# ---------- Research Agent ----------------------------------------------------

@pytest.mark.agent
@pytest.mark.unit
def test_research_no_provider_returns_honest_limitations(monkeypatch):
    """No provider configured -> local-only analysis with honest limitations,
    no fabricated sources/confidence."""
    monkeypatch.setattr(ResearchAgent, "_provider_configured", staticmethod(lambda: False))

    agent = ResearchAgent(_cfg())
    ctx = AgentContext(workspace_id=agent.config.workspace_id)
    result = asyncio.run(agent.execute({"query": "best practices for async retries"}, ctx))
    data = result.result_data

    assert result.success is True
    assert data["external_search_used"] is False
    assert data["provider_used"] is None
    # The old fabricated schema/values must be gone.
    assert "confidence" not in data
    blob = json.dumps(data)
    assert "Source 1" not in blob and "Source 2" not in blob
    assert "0.85" not in blob
    # Honest limitations actually present.
    assert any("no llm provider" in l.lower() or "no external web" in l.lower()
               for l in data["limitations"])
    # Output is grounded in the real query.
    assert "async retries" in json.dumps(data["findings"]).lower()


@pytest.mark.agent
@pytest.mark.unit
def test_research_uses_real_provider_output(monkeypatch):
    """When a provider is present, findings come from the provider boundary's
    real response, not from hardcoded templates."""

    class _Resp:
        content = json.dumps({
            "findings": [{"point": "Use jitter", "detail": "Add randomized backoff"}],
            "recommendations": ["Cap max retries"],
            "related_topics": ["exponential backoff"],
        })
        provider = "claude"
        model = "claude-test"
        usage = {"input_tokens": 11, "output_tokens": 22}

    class _Router:
        async def complete(self, req):
            return _Resp()

    monkeypatch.setattr(ResearchAgent, "_provider_configured", staticmethod(lambda: True))
    monkeypatch.setattr(providers_mod, "get_router", lambda: _Router())

    agent = ResearchAgent(_cfg())
    ctx = AgentContext(workspace_id=agent.config.workspace_id)
    result = asyncio.run(agent.execute({"query": "retry strategy"}, ctx))
    data = result.result_data

    assert result.success is True
    assert data["provider_used"] == "claude:claude-test"
    assert any(f.get("point") == "Use jitter" for f in data["findings"])
    assert "Cap max retries" in data["recommendations"]
    assert any("model:claude:claude-test" == s for s in data["sources_consulted"])
    # external search still honestly false (no real search tool exists).
    assert data["external_search_used"] is False


@pytest.mark.agent
@pytest.mark.integration
def test_research_invokable_via_runner(monkeypatch):
    """Research runs through the real registry/runner path and returns honest,
    non-fabricated output."""
    monkeypatch.setattr(ResearchAgent, "_provider_configured", staticmethod(lambda: False))

    runner = AgentRunner()
    out = asyncio.run(runner.run_agent("research", "investigate caching options", uuid4()))

    assert out["success"] is True
    assert out["output_text"]
    assert "0.85" not in out["output_text"]
    assert "external_search=False" in out["output_text"]


# ---------- QA Agent ----------------------------------------------------------

@pytest.mark.agent
@pytest.mark.unit
def test_qa_real_compile_pass_and_fail(tmp_path):
    """QA runs a REAL py_compile check: a valid file passes, a broken file
    fails with a real error. No fabricated coverage or test counts."""
    good = tmp_path / "good_mod.py"
    good.write_text("def add(a, b):\n    return a + b\n")
    bad = tmp_path / "bad_mod.py"
    bad.write_text("def broken(:\n    return\n")  # syntax error

    agent = QAAgent(_cfg(AuthorityLevel.LEVEL_3_CODE_EXECUTION))
    ctx = AgentContext(workspace_id=agent.config.workspace_id)
    result = asyncio.run(agent.execute(
        {"test_type": "compile", "target_files": [str(good), str(bad)]}, ctx
    ))
    data = result.result_data

    assert result.success is True  # produced a real assessment
    assert "coverage_percentage" not in data
    assert data["files_checked"] == 2
    assert data["files_passed"] == 1
    assert data["files_failed"] == 1
    assert any(f["file"] == str(bad) for f in data["failures"])
    assert any("py_compile" in c for c in data["commands_attempted"])
    # No fabricated metric anywhere.
    assert "88.5" not in json.dumps(data)


@pytest.mark.agent
@pytest.mark.unit
def test_qa_blocks_shell_command_honestly(tmp_path):
    """A requested shell/test command is NOT executed; it is reported as
    blocked / needs-approval truthfully."""
    agent = QAAgent(_cfg(AuthorityLevel.LEVEL_3_CODE_EXECUTION))
    ctx = AgentContext(workspace_id=agent.config.workspace_id)
    result = asyncio.run(agent.execute(
        {"test_type": "unit", "target_files": [], "test_command": "pytest -q"}, ctx
    ))
    data = result.result_data

    assert "pytest -q" in data["commands_blocked"]
    assert data["files_checked"] == 0  # nothing was actually executed as a test
    assert any("approval" in l.lower() or "not available" in l.lower()
               for l in data["limitations"])
    assert "coverage_percentage" not in data


@pytest.mark.agent
@pytest.mark.unit
def test_qa_no_targets_is_honest():
    """No targets and no command -> honest 'nothing executed', no fake counts."""
    agent = QAAgent(_cfg(AuthorityLevel.LEVEL_3_CODE_EXECUTION))
    ctx = AgentContext(workspace_id=agent.config.workspace_id)
    result = asyncio.run(agent.execute({"test_type": "unit", "target_files": []}, ctx))
    data = result.result_data

    assert result.success is True
    assert data["files_checked"] == 0
    assert data["files_passed"] == 0
    assert data["files_failed"] == 0
    assert data["recommended_next_action"]
    assert any("no target" in l.lower() for l in data["limitations"])


@pytest.mark.agent
@pytest.mark.integration
def test_qa_invokable_via_runner():
    """QA runs through the real registry/runner path and returns honest output
    with no fabricated coverage."""
    runner = AgentRunner()
    out = asyncio.run(runner.run_agent("qa", "validate the module", uuid4()))

    assert out["success"] is True  # assessment agent
    assert out["output_text"]
    assert "88.5" not in out["output_text"]
    assert "checked=" in out["output_text"]


# ---------- Orchestrator integration -----------------------------------------

@pytest.mark.agent
@pytest.mark.integration
def test_orchestrator_delegates_to_real_research_and_qa(monkeypatch):
    """The repaired orchestrator delegates to the repaired Research and QA
    agents through the real path and gets non-fabricated structured outputs."""
    # Force deterministic fallback plan (research + qa) by disabling the
    # orchestrator's planning provider; disable research provider for no network.
    monkeypatch.setattr("app.agents.orchestrator.get_router",
                        lambda: (_ for _ in ()).throw(RuntimeError("no provider")))
    monkeypatch.setattr(ResearchAgent, "_provider_configured", staticmethod(lambda: False))

    orch = OrchestratorAgent(_cfg())
    ctx = AgentContext(workspace_id=orch.config.workspace_id)
    result = asyncio.run(orch.execute({"mission": "Assess the auth module"}, ctx))
    data = result.result_data

    assert data["mission_status"] == "completed"
    assert set(data["agents_used"]) == {"research", "qa"}
    registry = get_registry()
    for name in data["agents_used"]:
        assert registry.is_implemented(name)

    previews = " ".join((tr.get("output_preview") or "") for tr in data["task_results"])
    # Real, non-fabricated signatures present; old fakes absent.
    assert "external_search=False" in previews
    assert "checked=" in previews
    assert "0.85" not in previews
    assert "88.5" not in previews
