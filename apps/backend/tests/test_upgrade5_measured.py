"""
Upgrade 5: measured routing and proactive context. Every model call a mission makes is counted (uncached, cached,
cache-write, output and reasoning tokens, cost from the price table) and stored with the mission; every call shares
the mission's prompt-cache key and the opening of successive steps is byte-identical; before the first step the
mission is given its stack, commands and recent failures.
"""
from __future__ import annotations

import asyncio
import json
import shutil

import pytest

from app.core.command.metrics import Usage, merge
from tests.conftest import AsyncTestingSessionLocal


def test_usage_counts_both_providers_and_prices_the_model():
    usage = Usage()
    # OpenAI Responses: the input count includes cached reads and cache writes.
    usage.add({"prompt_tokens": 10_000, "completion_tokens": 1_000, "cached_tokens": 8_000,
               "cache_write_tokens": 1_000, "reasoning_tokens": 600, "total_tokens": 11_000}, "gpt-6-luna", "mission")
    usage.add({"prompt_tokens": 2_000, "completion_tokens": 500, "total_tokens": 2_500}, "gpt-6-luna", "verifier")
    summary = usage.summary()
    assert summary["input"] == 1_000 + 2_000 and summary["cached"] == 8_000 and summary["cache_write"] == 1_000
    assert summary["output"] == 1_500 and summary["reasoning"] == 600 and summary["calls"] == 2
    # 3,000 x 0.10 + 1,500 x 0.50 + 8,000 x 0.01 + 1,000 x 0.125, per million
    assert summary["cost_usd"] == round((3_000 * 0.10 + 1_500 * 0.50 + 8_000 * 0.01 + 1_000 * 0.125) / 1e6, 4)
    assert summary["cache_hit_rate"] == round(8_000 / 12_000, 3)
    assert summary["by_role"]["verifier"]["calls"] == 1
    claude = Usage()
    claude.add({"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 50}, "claude-sonnet-4-6", "mission")
    assert claude.summary()["cached"] == 900 and claude.summary()["cost_usd"] is None  # no price recorded


def test_figures_add_up_across_rounds():
    first = {"usage": {"calls": 3, "input": 100, "cached": 50, "cache_write": 0, "output": 10, "reasoning": 5,
                       "cost_usd": 0.001}, "steps": 8, "steps_to_first_edit": 3}
    second = {"usage": {"calls": 2, "input": 40, "cached": 60, "cache_write": 10, "output": 4, "reasoning": 1,
                        "cost_usd": 0.0005}, "steps": 5, "steps_to_first_edit": None}
    total = merge(first, second)
    assert total["usage"]["calls"] == 5 and total["usage"]["cached"] == 110 and total["steps"] == 13
    assert total["usage"]["cost_usd"] == 0.0015 and total["steps_to_first_edit"] == 3
    assert total["rounds_measured"] == 2


def test_the_mission_cache_key_goes_to_the_responses_api():
    from app.core.providers.base import CompletionRequest, Message
    from app.core.providers.openai import OpenAIProvider

    provider = object.__new__(OpenAIProvider)
    tools = [{"name": "read_file", "description": "d", "input_schema": {"type": "object"}}]
    body = provider._responses_request(CompletionRequest(model="gpt-6-luna", messages=[Message(role="user", content="x")],
                                                         tools=tools, prompt_cache_key="jarv-mission-123"))
    assert body["prompt_cache_key"] == "jarv-mission-123" and "prompt_cache_options" not in body
    reply = provider._convert_responses_response({"id": "r", "model": "gpt-6-luna", "output": [], "usage": {
        "input_tokens": 1000, "output_tokens": 10, "total_tokens": 1010,
        "input_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 50}}}, "gpt-6-luna")
    assert reply.usage["cached_tokens"] == 900 and reply.usage["cache_write_tokens"] == 50


class _Router:
    def __init__(self):
        self.mission_requests = []
        self.turns = [[("write_file", {"path": "src/sub.py", "content": "def sub(a, b):\n    return a - b\n"})],
                      [("finish", {"summary": "Added.", "success": True})]]

    async def complete(self, request):
        from app.core.providers import CompletionResponse

        system = request.system or ""
        usage = {"prompt_tokens": 1000, "completion_tokens": 50, "cached_tokens": 800, "total_tokens": 1050}
        if system.startswith("You are JARV's Verifier Agent"):
            calls = [("verdict", {"verified": True, "unmet": [], "checks": [
                {"requirement": "sub", "met": True, "evidence": "read src/sub.py"}]})]
        elif system.startswith("You are JARV's"):
            calls = []
        else:
            # A snapshot at call time: the conversation list grows after each step.
            self.mission_requests.append((request.prompt_cache_key, request.system, json.dumps(request.tools),
                                          json.dumps(request.messages[0].content, default=str)))
            calls = self.turns.pop(0) if self.turns else [("finish", {"summary": "x", "success": True})]
        return CompletionResponse(id="r", model="gpt-6-luna", content="", usage=usage, tool_calls=[
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(calls)])


@pytest.mark.integration
def test_a_mission_is_measured_cached_and_starts_with_its_context(monkeypatch):
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    (folder / "package.json").write_text(json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}))
    router = _Router()
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            result = await AgentExecutor(rt, "gpt-6-luna", host).run("Add sub(a, b) in src/sub.py.",
                                                                     max_continuations=0)
            return result, rt.task_id

    try:
        result, task_id = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    metrics = result["metrics"]
    assert metrics["usage"]["calls"] >= 3 and metrics["usage"]["cached"] >= 2400
    assert metrics["usage"]["cost_usd"] is not None and metrics["usage"]["by_role"]["verifier"]["calls"] == 1
    assert metrics["steps_to_first_edit"] == 1
    first, second = router.mission_requests[0], router.mission_requests[1]
    assert first[0] == second[0] == f"jarv-mission-{task_id}"
    # The cached opening (instructions, tools, the mission's first message) is byte-identical on every step.
    assert first[1:] == second[1:]
    opening = json.loads(first[3])
    assert "STARTING CONTEXT" in opening and "detect_stack" in opening and "detect_commands" in opening

