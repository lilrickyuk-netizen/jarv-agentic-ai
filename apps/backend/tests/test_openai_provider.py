import pytest

from app.api.command import command_info
from app.core.command.service import _provider_name_for_model
from app.core.config import settings
from app.core.providers.base import CompletionRequest, Message
from app.core.providers.openai import OpenAIProvider


def test_gpt_6_luna_is_registered_with_standard_pricing():
    assert OpenAIProvider.MODELS["gpt-6-luna"] == {
        "input_cost": 0.10,
        "output_cost": 0.50,
        "context_window": 1_050_000,
    }


@pytest.mark.asyncio
async def test_gpt_6_luna_request_is_bounded_and_uses_standard_tier():
    provider = OpenAIProvider(api_key="unit-test-key")
    try:
        request = CompletionRequest(
            model="gpt-6-luna",
            messages=[Message(role="user", content="Check service health.")],
            max_tokens=48,
        )

        payload = provider._convert_request(request)

        assert provider.validate_model("gpt-6-luna")
        assert payload["model"] == "gpt-6-luna"
        assert payload["max_completion_tokens"] == 48
        assert payload["reasoning_effort"] == "low"
        assert payload["service_tier"] == "default"
        assert "max_tokens" not in payload
        assert "temperature" not in payload
        assert "frequency_penalty" not in payload
        assert "presence_penalty" not in payload
    finally:
        await provider.client.aclose()


def test_command_provider_name_uses_model_family():
    assert _provider_name_for_model("gpt-6-luna") == "openai"
    assert _provider_name_for_model("claude-sonnet-4-6") == "claude"


@pytest.mark.asyncio
async def test_command_info_reports_configured_model(monkeypatch):
    monkeypatch.setattr(settings, "DEFAULT_MODEL", "gpt-6-luna")

    assert await command_info() == {"provider": "openai", "model": "gpt-6-luna"}


def _assert_valid_openai_chat(payload):
    """The request shape OpenAI's chat completions API accepts for tool use."""
    import re

    for tool in payload.get("tools", []):
        assert tool["type"] == "function" and "parameters" in tool["function"]
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tool["function"]["name"]), tool["function"]["name"]
    pending = set()
    for message in payload["messages"]:
        assert message["role"] in ("system", "user", "assistant", "tool")
        if message["role"] == "assistant":
            pending = {c["id"] for c in message.get("tool_calls", [])}
            for call in message.get("tool_calls", []):
                assert call["type"] == "function" and isinstance(call["function"]["arguments"], str)
        elif message["role"] == "tool":
            assert message["tool_call_id"] in pending and isinstance(message["content"], str)
        else:
            assert isinstance(message["content"], str)


@pytest.mark.asyncio
async def test_agent_tool_turns_are_sent_in_openai_shape():
    """Agents define tools and record turns in the Anthropic shape. OpenAI rejected the raw tools with
    "Missing required parameter: 'tools[0].type'", which failed every agent mission on OpenAI."""
    import json

    import httpx

    from app.core.agents.tool_loop import FINISH_TOOL

    tools = [{"name": "read_file", "description": "Read a file.",
              "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
             FINISH_TOOL]
    messages = [
        Message(role="user", content="TASK:\nRead the MYCO design and write a build plan."),
        Message(role="assistant", content=[
            {"type": "text", "text": "Reading the design first."},
            {"type": "tool_use", "id": "call_1", "name": "read_file", "input": {"path": "docs/spec.md"}}]),
        Message(role="user", content=[
            {"type": "tool_result", "tool_use_id": "call_1", "content": {"success": True, "content": "# MYCO V3"}}]),
    ]
    sent = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "model": "gpt-6-luna", "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                                                  "total_tokens": 15},
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_2", "type": "function",
                    "function": {"name": "finish", "arguments": json.dumps({"summary": "Plan written.",
                                                                            "success": True})}}]}}]})

    provider = OpenAIProvider(api_key="unit-test-key")
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url=provider.API_BASE, transport=httpx.MockTransport(answer))
    try:
        response = await provider.complete(CompletionRequest(
            model="gpt-6-luna", messages=messages, system="You are JARV's coding agent.", tools=tools,
            max_tokens=256, temperature=0.0))
    finally:
        await provider.client.aclose()

    payload = sent[0]
    _assert_valid_openai_chat(payload)
    assert payload["reasoning_effort"] == "none"  # gpt-6-luna refuses function tools with reasoning on
    assert [t["function"]["name"] for t in payload["tools"]] == ["read_file", "finish"]
    assert payload["tools"][0]["function"]["parameters"]["required"] == ["path"]
    assistant = payload["messages"][2]
    assert assistant["content"] == "Reading the design first."
    assert assistant["tool_calls"][0]["function"] == {"name": "read_file", "arguments": '{"path": "docs/spec.md"}'}
    assert payload["messages"][3] == {"role": "tool", "tool_call_id": "call_1",
                                      "content": '{"success": true, "content": "# MYCO V3"}'}
    assert response.tool_calls[0]["function"]["name"] == "finish"


@pytest.mark.asyncio
async def test_tool_names_openai_would_reject_are_renamed_and_restored():
    """Registry tools such as boundary.detect have dots, which OpenAI's function names do not allow."""
    import json

    import httpx

    sent = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "chatcmpl-2", "model": "gpt-6-luna", "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                                                  "total_tokens": 2},
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_9", "type": "function",
                    "function": {"name": "boundary__detect", "arguments": "{}"}}]}}]})

    provider = OpenAIProvider(api_key="unit-test-key")
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url=provider.API_BASE, transport=httpx.MockTransport(answer))
    try:
        response = await provider.complete(CompletionRequest(
            model="gpt-6-luna", max_tokens=64,
            messages=[Message(role="user", content="Check this action."),
                      Message(role="assistant", content=[{"type": "tool_use", "id": "call_8",
                                                          "name": "boundary.detect", "input": {"action": "x"}}]),
                      Message(role="user", content=[{"type": "tool_result", "tool_use_id": "call_8",
                                                     "content": "no boundary"}])],
            tools=[{"name": "boundary.detect", "description": "Detect hard boundaries.",
                    "input_schema": {"type": "object", "properties": {"action": {"type": "string"}}}}]))
    finally:
        await provider.client.aclose()

    _assert_valid_openai_chat(sent[0])
    assert sent[0]["tools"][0]["function"]["name"] == "boundary__detect"
    assert sent[0]["messages"][1]["tool_calls"][0]["function"]["name"] == "boundary__detect"
    assert response.tool_calls[0]["function"]["name"] == "boundary.detect"


def test_every_registered_tool_is_a_valid_openai_function():
    """Whatever tools an agent is given, OpenAI accepts their definitions: valid names, and every
    array in a parameters schema states its items."""
    import re

    from app.core.providers.openai import _openai_tool
    from app.core.tools.base import ToolConfig
    from app.core.tools.registry import get_registry

    def arrays_have_items(node):
        if isinstance(node, dict):
            kinds = node.get("type") if isinstance(node.get("type"), list) else [node.get("type")]
            if "array" in kinds:
                assert "items" in node, node
            for value in node.values():
                arrays_have_items(value)
        elif isinstance(node, list):
            for value in node:
                arrays_have_items(value)

    registry = get_registry()
    checked = 0
    for meta in registry.list_all():
        name = meta.name
        if not meta.is_implemented:
            continue
        try:
            schema = meta.tool_class(ToolConfig()).input_schema.model_json_schema()
        except Exception:  # noqa: BLE001 - tools without a schema are never offered to agents
            continue
        tool = _openai_tool({"name": name, "description": meta.description or name, "input_schema": schema})
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tool["function"]["name"]), name
        arrays_have_items(tool["function"]["parameters"])
        checked += 1
    assert checked > 100


@pytest.mark.asyncio
async def test_the_same_agent_turns_work_on_claude():
    """Missions run on Claude or OpenAI (with failover between them): the same agent conversation is sent
    in Claude's shape, with names Claude accepts, and the reply comes back with JARV's own tool names."""
    import json
    import re

    import httpx

    from app.core.providers.claude import ClaudeProvider

    sent = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "stop_reason": "tool_use",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [{"type": "tool_use", "id": "toolu_2", "name": "boundary__detect", "input": {"action": "x"}}]})

    provider = ClaudeProvider(api_key="unit-test-key")
    await provider.client.aclose()
    provider.client = httpx.AsyncClient(base_url=provider.API_BASE, transport=httpx.MockTransport(answer))
    try:
        response = await provider.complete(CompletionRequest(
            model="claude-sonnet-4-6", max_tokens=64, system="You are JARV's coding agent.",
            messages=[Message(role="user", content="TASK:\nCheck the release."),
                      Message(role="assistant", content=[{"type": "tool_use", "id": "toolu_1",
                                                          "name": "boundary.detect", "input": {"action": "x"}}]),
                      Message(role="user", content=[{"type": "tool_result", "tool_use_id": "toolu_1",
                                                     "content": "no boundary"}])],
            tools=[{"name": "boundary.detect", "description": "Detect hard boundaries.",
                    "input_schema": {"type": "object", "properties": {"action": {"type": "string"}}}},
                   {"type": "function", "function": {"name": "read_file", "description": "Read a file.",
                                                     "parameters": {"type": "object", "properties": {}}}}]))
    finally:
        await provider.client.aclose()

    payload = sent[0]
    assert [t["name"] for t in payload["tools"]] == ["boundary__detect", "read_file"]
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", t["name"]) and "input_schema" in t for t in payload["tools"])
    assert payload["messages"][1]["content"][0]["name"] == "boundary__detect"
    assert payload["messages"][2]["content"][0]["type"] == "tool_result"
    assert response.tool_calls[0]["function"]["name"] == "boundary.detect"
