"""Hard gates for JARV's 31-agent tool and authority wiring."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.core.agents import runner as runner_module
from app.core.agents.base import AgentConfig, AuthorityLevel
from app.core.agents.registry import get_registry as get_agent_registry
from app.core.agents.runner import AgentRunner
from app.core.tools.registry import get_registry as get_tool_registry
from app.core.tools.base import ToolConfig
from app.core.knowledge.catalog import specialist_knowledge
from app.core.knowledge.service import knowledge_service
from tests.conftest import AsyncTestingSessionLocal


def test_every_declared_agent_tool_exists_and_is_implemented():
    agents = get_agent_registry()
    tools = get_tool_registry()

    failures = []

    for agent_name in agents.REQUIRED_AGENTS:
        agent = agents.get_metadata(agent_name)
        assert agent is not None

        for tool_name in agent.default_tools:
            tool = tools.get_metadata(tool_name)

            if tool is None:
                failures.append(f"{agent_name}: missing tool {tool_name}")
            elif not tool.is_implemented:
                failures.append(f"{agent_name}: placeholder tool {tool_name}")

    assert failures == []


def test_every_agent_has_enough_authority_for_its_declared_tools():
    agents = get_agent_registry()
    tools = get_tool_registry()

    failures = []

    for agent_name in agents.REQUIRED_AGENTS:
        agent = agents.get_metadata(agent_name)
        assert agent is not None

        for tool_name in agent.default_tools:
            tool = tools.get_metadata(tool_name)
            assert tool is not None

            if tool.required_authority_level > agent.required_authority_level:
                failures.append(
                    f"{agent_name} authority={agent.required_authority_level} "
                    f"cannot use {tool_name} authority={tool.required_authority_level}"
                )

    assert failures == []


def test_swarm_manager_gets_only_swarm_tools_and_no_wildcard_access():
    # Repair 12e-3b: the swarm manager works through the swarm tools only.
    agents = get_agent_registry()
    tools = get_tool_registry()
    meta = agents.get_metadata("swarm_manager")

    assert meta is not None and meta.default_tools
    assert {tools.get_metadata(name).category for name in meta.default_tools} == {"swarm"}

    agent = meta.agent_class(
        AgentConfig(
            authority_level=AuthorityLevel(meta.required_authority_level),
            allowed_tools=[],
        )
    )

    assert set(agent.get_allowed_tools()) == set(meta.default_tools)
    assert agent.can_use_tool("file_read") is False
    assert agent.can_use_tool("command_run") is False


def test_runner_uses_registered_agent_authority_not_level_9(
    monkeypatch, test_user, test_workspace,
):
    agents = get_agent_registry()
    meta = agents.get_metadata("documentation")

    assert meta is not None
    assert meta.required_authority_level == AuthorityLevel.LEVEL_2_FILE_OPERATIONS.value

    captured = {}

    class FakeAgent:
        @property
        def input_schema(self):
            raise AttributeError("no schema required for this test")

        async def execute(self, input_data, context):
            return SimpleNamespace(
                success=True,
                output_text="authority test complete",
                result_data={"ok": True},
                tokens_used={},
            )

    def fake_create_agent(agent_name, config):
        captured["agent_name"] = agent_name
        captured["config"] = config
        return FakeAgent()

    monkeypatch.setattr(runner_module, "create_agent", fake_create_agent)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            await knowledge_service.ingest(session, specialist_knowledge())
            await session.commit()
            return await AgentRunner().run_agent(
                "documentation", "test least privilege", test_workspace.id,
                user_id=test_user.id, db=session,
            )

    result = asyncio.run(run())

    assert result["success"] is True
    assert captured["agent_name"] == "documentation"

    config = captured["config"]

    assert config.authority_level == AuthorityLevel.LEVEL_2_FILE_OPERATIONS
    assert config.authority_level != AuthorityLevel.LEVEL_9_SWARM_CREATION
    assert config.allowed_tools == meta.default_tools

def test_every_required_tool_has_a_concrete_constructible_implementation():
    tools = get_tool_registry()
    config = ToolConfig(authority_level=AuthorityLevel.LEVEL_10_FULL_AUTONOMY)
    failures = []

    for tool_name in tools.REQUIRED_TOOLS:
        tool_class = tools.get(tool_name)
        if tool_class is None:
            failures.append(f"{tool_name}: no concrete class")
            continue
        try:
            tool = tools.create(tool_name, config)
        except Exception as exc:
            failures.append(f"{tool_name}: construction failed ({type(exc).__name__})")
            continue
        if tool is None or tool.name != tool_name or not callable(tool.execute):
            failures.append(f"{tool_name}: invalid executable instance")

    assert failures == []
