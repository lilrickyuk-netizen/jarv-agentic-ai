"""
Repair 5 behaviour tests: the formerly-fabricated specialist agents now return
honest real/limited output (no fabricated metrics, no simulated execution).

Coverage:
- Every repaired agent can be created via the registry and invoked via the real
  agent execution path (create_agent -> agent.execute, the same path AgentRunner
  uses) and through AgentRunner.run_agent itself.
- With NO provider configured, agents return honest structured output / honest
  limitations (no fabrication) and success=True.
- Local-analysis agents (security, coding_agent, workspace_manager) produce
  output DERIVED FROM REAL INPUT (real secret scan, real py_compile, real dir
  scan).
- Model-backed agents use the real provider boundary: a mocked router response
  flows through to the draft; provider/registry/runner are NOT mocked.
- rollback returns an honest BLOCKED result (no fake "rollback complete").
- Source guard: no fabricated tokens remain in the live agent files.

Only the provider boundary (settings keys / providers.get_router) is mocked.
"""
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

import app.core.config as app_config
import app.core.providers as providers_mod
from app.core.agents.registry import get_registry, create_agent
from app.core.agents.runner import AgentRunner, _auto_input
from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.specialists._helpers import FORBIDDEN_FAKE_TOKENS

# The 26 agents repaired in Repair 5 (excludes already-real research, qa,
# customer_support, swarm_manager, and the Repair-1 orchestrator).
REPAIRED_AGENTS = [
    "coding_agent", "debugging_agent", "verifier", "security", "analytics",
    "monitoring", "infrastructure", "memory", "workspace_manager", "devops",
    "marketing", "growth", "business", "finance", "sales",
    "content", "community", "onboarding", "partnerships", "legal", "creation",
    "company_operator", "self_evolution", "self_healing", "rollback", "documentation",
]

# Tokens that must never appear in repaired agent output.
_FAKE_TOKENS = list(FORBIDDEN_FAKE_TOKENS) + ["88.5", "0.85", "0.92"]

_PROVIDER_KEYS = ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")


def _cfg() -> AgentConfig:
    return AgentConfig(
        agent_id=uuid4(), workspace_id=uuid4(),
        authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION,
    )


def _disable_provider(monkeypatch):
    """Make provider_configured() return False (honest no-provider path)."""
    for attr in _PROVIDER_KEYS:
        monkeypatch.setattr(app_config.settings, attr, None, raising=False)


def _enable_provider(monkeypatch):
    monkeypatch.setattr(app_config.settings, "CLAUDE_API_KEY", "test-key", raising=False)


def _assert_no_fakes(payload: str):
    for tok in _FAKE_TOKENS:
        assert tok not in payload, f"fabricated token {tok!r} found in agent output"


async def _exec(name: str, input_data: dict, ctx: AgentContext):
    agent = create_agent(name, _cfg())
    assert agent is not None, f"{name} could not be created via registry"
    return await agent.execute(input_data, ctx)


# --- every repaired agent: created via registry + real execution, honest, no fakes

@pytest.mark.agent
@pytest.mark.integration
@pytest.mark.parametrize("name", REPAIRED_AGENTS)
def test_repaired_agent_runs_honestly_without_provider(name, monkeypatch):
    _disable_provider(monkeypatch)
    registry = get_registry()
    assert registry.is_implemented(name)

    agent = create_agent(name, _cfg())
    assert agent is not None
    task = "prepare the launch and assess the auth module"
    input_data = _auto_input(agent.input_schema, task)
    ctx = AgentContext(workspace_id=agent.config.workspace_id)

    result = asyncio.run(agent.execute(input_data, ctx))

    # Honest success (truthful assessment/draft/limitation) and real output text.
    assert result.success is True, f"{name} did not return a truthful success result"
    assert (result.output_text or "").strip(), f"{name} produced no output_text"
    _assert_no_fakes(json.dumps(result.result_data) + (result.output_text or ""))


# --- runner path (the real AgentRunner) for representative local-analysis agents

@pytest.mark.agent
@pytest.mark.integration
@pytest.mark.parametrize("name", ["security", "verifier", "monitoring"])
def test_repaired_agent_invokable_via_runner(name, monkeypatch):
    _disable_provider(monkeypatch)
    out = asyncio.run(AgentRunner().run_agent(name, "assess the module", uuid4()))
    assert out["success"] is True
    assert out["output_text"]
    _assert_no_fakes(out["output_text"] + json.dumps(out.get("result_data", {})))


# --- local analysis derived from REAL input: security secret scan

@pytest.mark.agent
@pytest.mark.integration
def test_security_real_secret_scan(tmp_path, monkeypatch):
    _disable_provider(monkeypatch)
    secret_file = tmp_path / "leak.py"
    secret_file.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')  # matches AKIA[16]
    clean_file = tmp_path / "clean.py"
    clean_file.write_text("def add(a, b):\n    return a + b\n")

    ctx = AgentContext(workspace_id=uuid4())
    res_secret = asyncio.run(_exec(
        "security",
        {"scan_type": "code", "targets": [str(secret_file)], "severity_threshold": "low"},
        ctx,
    ))
    res_clean = asyncio.run(_exec(
        "security",
        {"scan_type": "code", "targets": [str(clean_file)], "severity_threshold": "low"},
        ctx,
    ))

    blob_secret = json.dumps(res_secret.result_data)
    # Real finding on the leaked key; clean file yields none. Counts are real.
    assert res_secret.result_data.get("vulnerabilities_found", 0) >= 1
    assert "secret" in blob_secret or "aws" in blob_secret.lower()
    assert res_clean.result_data.get("vulnerabilities_found", 0) == 0
    _assert_no_fakes(blob_secret)


# --- local analysis derived from REAL input: coding_agent compiles real files

@pytest.mark.agent
@pytest.mark.integration
def test_coding_agent_real_compile(tmp_path, monkeypatch):
    _disable_provider(monkeypatch)
    good = tmp_path / "good.py"
    good.write_text("def f(x):\n    return x * 2\n")
    bad = tmp_path / "bad.py"
    bad.write_text("def f(:\n    return\n")  # syntax error

    ctx = AgentContext(workspace_id=uuid4())
    res = asyncio.run(_exec(
        "coding_agent",
        {"task": "static check", "language": "python", "files": [str(good), str(bad)],
         "requirements": "", "context": {}},
        ctx,
    ))
    blob = json.dumps(res.result_data)
    # At least one real compile pass and one real compile failure are reflected.
    assert res.success is True
    assert ("bad.py" in blob) or (res.result_data.get("compile_failed") or 0) >= 1 \
        or "fail" in blob.lower()
    # And it must NOT claim it wrote/modified files.
    assert res.result_data.get("files_modified", []) in ([], None)
    _assert_no_fakes(blob)


# --- local analysis derived from REAL input: workspace_manager scans a real dir

@pytest.mark.agent
@pytest.mark.integration
def test_workspace_manager_real_scan(tmp_path, monkeypatch):
    _disable_provider(monkeypatch)
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname='x'\n")
    (tmp_path / "main.py").write_text("print('hi')\n")

    ctx = AgentContext(workspace_id=uuid4(), metadata={"workspace_path": str(tmp_path)})
    res = asyncio.run(_exec(
        "workspace_manager",
        {"operation": "configure", "workspace_name": "x", "config": {}},
        ctx,
    ))
    blob = json.dumps(res.result_data)
    assert res.success is True
    # Real detection of the stack marker that actually exists in the temp dir.
    assert "pyproject.toml" in blob
    _assert_no_fakes(blob)


# --- model-backed agent uses the REAL provider boundary (mocked router only)

@pytest.mark.agent
@pytest.mark.integration
def test_marketing_uses_real_provider_output(monkeypatch):
    _enable_provider(monkeypatch)

    sentinel = "DRAFT_CAMPAIGN_SENTINEL_42"

    class _Resp:
        content = sentinel
        provider = "claude"
        model = "claude-test"
        usage = {"input_tokens": 5, "output_tokens": 7}

    class _Router:
        async def complete(self, req):
            return _Resp()

    monkeypatch.setattr(providers_mod, "get_router", lambda: _Router())

    ctx = AgentContext(workspace_id=uuid4())
    res = asyncio.run(_exec(
        "marketing",
        {"campaign_type": "social", "target_audience": "devs",
         "message": "launch", "channels": ["twitter"]},
        ctx,
    ))
    blob = json.dumps(res.result_data)
    assert res.success is True
    # The mocked provider's real text flows into the draft.
    assert sentinel in blob
    # And no external action is claimed.
    assert res.result_data.get("external_action_taken", False) is False
    _assert_no_fakes(blob + (res.output_text or ""))


# --- model-backed agent: honest limitation when no provider

@pytest.mark.agent
@pytest.mark.integration
def test_marketing_honest_limitation_without_provider(monkeypatch):
    _disable_provider(monkeypatch)
    ctx = AgentContext(workspace_id=uuid4())
    res = asyncio.run(_exec(
        "marketing",
        {"campaign_type": "social", "target_audience": "devs",
         "message": "launch", "channels": ["twitter"]},
        ctx,
    ))
    assert res.success is True
    limblob = json.dumps(res.result_data).lower()
    assert "limitation" in limblob or "no llm provider" in limblob or "provider" in limblob
    # No fabricated reach/posts.
    _assert_no_fakes(json.dumps(res.result_data))
    assert "estimated_reach" not in res.result_data


# --- blocked agent: rollback honestly refuses (no fake success)

@pytest.mark.agent
@pytest.mark.integration
def test_rollback_is_honestly_blocked(monkeypatch):
    _disable_provider(monkeypatch)
    ctx = AgentContext(workspace_id=uuid4())
    res = asyncio.run(_exec(
        "rollback",
        {"deployment_id": "dep-1", "reason": "bad release", "target_version": "previous"},
        ctx,
    ))
    blob = json.dumps(res.result_data)
    # Honest: blocked, did not perform a rollback, no fake "completed" claim.
    assert res.result_data.get("blocked") is True
    assert res.result_data.get("rollback_performed", False) is False
    assert res.result_data.get("rollback_completed", False) in (False, None)
    _assert_no_fakes(blob)


# --- source guard: no fabricated tokens remain in the live agent files

@pytest.mark.agent
@pytest.mark.unit
def test_no_fabrication_tokens_in_live_agent_sources():
    specialists_dir = Path(__file__).resolve().parents[1] / "app" / "core" / "agents" / "specialists"
    # Exclude the helper (which defines the token list) and non-registered
    # generator/verifier scaffolding scripts.
    excluded = {"_helpers.py", "enhance_agents.py", "generate_agents.py",
                "verify_agents.py", "__init__.py"}
    bad = []
    for path in specialists_dir.glob("*.py"):
        if path.name in excluded:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for tok in ("Simulate test execution", "Simulate research", "Simulate security scan",
                    "Simulate deployment", "Simulate health checks", " * 5000", " * 50.0",
                    "= 88.5", ": 88.5", "mem_123", "Finding about"):
            if tok in text:
                bad.append(f"{path.name}: {tok!r}")
    assert not bad, f"fabrication tokens still present: {bad}"
