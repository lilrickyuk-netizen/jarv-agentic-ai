"""
JAI's model tiers (Richard's choice): hard thinking on Claude Opus 5.5, moving to GPT-6 Sol when Anthropic has no
credit; light work on GPT-6 Luna. Real: the router's tiers, failover and resting, the metered router's light roles,
the gateway's Anthropic side and the sandbox's choice of model. Providers and Anthropic are in-process doubles, so
no provider is called.
"""
import asyncio
import json

import httpx
import pytest

from app.core import gateway, spend
from app.core.command import sandbox_engine
from app.core.command.metrics import MeteredRouter, Usage
from app.core.config import settings
from app.core.providers.base import CompletionRequest, InvalidRequestError, Message
from app.core.providers.router import has_no_credit, mark_no_credit, tiered
from tests.test_repair12e_provider_failover import FakeProvider, _ask, _router


async def _forget_no_credit():
    from app.core.redis import get_redis

    await (await get_redis()).delete("provider:claude:no_credit")


@pytest.fixture(autouse=True)
def _no_credit_mark_cleared():
    asyncio.run(_forget_no_credit())
    yield
    asyncio.run(_forget_no_credit())


@pytest.fixture
def tiers(monkeypatch):
    monkeypatch.setattr(settings, "MODEL_TIERS_ENABLED", True)
    monkeypatch.setattr(settings, "DEFAULT_MODEL", "claude-opus-5-5")
    monkeypatch.setattr(settings, "LIGHT_MODEL", "gpt-6-luna")
    monkeypatch.setattr(settings, "OPENAI_REASONING_MODEL", "gpt-6-sol")


def test_hard_work_stays_on_opus_and_light_work_goes_to_luna(tiers):
    assert tiered("claude-opus-5-5") == "claude-opus-5-5"
    assert tiered("gpt-6-sol") == "gpt-6-sol"
    for light in ("claude-sonnet-4-6", "claude-haiku-4-5", "gpt-6-luna"):
        assert tiered(light) == "gpt-6-luna"


def test_opus_without_credit_moves_to_sol_and_tells_the_rest_of_jai(tiers, monkeypatch):
    claude = FakeProvider("claude", InvalidRequestError(
        "Invalid request to Claude API: Your credit balance is too low to access the Anthropic API.",
        provider="claude", status_code=400))
    openai = FakeProvider("openai")
    router = _router(monkeypatch, claude=claude, openai=openai)
    first = _ask(router, "claude-opus-5-5")
    second = _ask(router, "claude-opus-5-5")
    assert first.content == second.content == "openai answered"
    assert claude.calls == ["claude-opus-5-5"] and openai.calls == ["gpt-6-sol", "gpt-6-sol"]
    assert asyncio.run(has_no_credit("claude")) is True


def test_light_work_never_spends_opus(tiers, monkeypatch):
    claude, openai = FakeProvider("claude"), FakeProvider("openai")
    router = _router(monkeypatch, claude=claude, openai=openai)
    _ask(router, "claude-sonnet-4-6")
    assert openai.calls == ["gpt-6-luna"] and claude.calls == []

    async def report():
        metered = MeteredRouter(router, Usage(), "mission").as_role("report")
        return await metered.complete(CompletionRequest(model="claude-opus-5-5",
                                                        messages=[Message(role="user", content="write it up")]))

    asyncio.run(report())
    assert openai.calls[-1] == "gpt-6-luna"  # the mission's report is written on Luna


def test_opus_and_sol_are_priced(tiers):
    assert spend.text_cost("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 0}) == pytest.approx(4.0)
    assert spend.text_cost("claude-opus-5-5", {"input_tokens": 0, "output_tokens": 1_000_000}) == pytest.approx(20.0)
    assert spend.text_cost("gpt-6-sol", {"prompt_tokens": 1_000_000, "completion_tokens": 0}) == pytest.approx(2.0)


def test_the_gateway_passes_anthropic_on_within_the_limit_and_shares_a_credit_failure(monkeypatch, client):
    monkeypatch.setattr(settings, "JAI_GATEWAY_TOKEN", "gateway-token-0123456789")
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "anthropic-key-for-tests")
    monkeypatch.setattr(settings, "GATEWAY_MODELS", "claude-opus-5-5,gpt-6-sol")
    assert client.post("/api/gateway/anthropic/v1/messages", json={}).status_code == 401
    seen = []

    def anthropic(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers["x-api-key"], json.loads(request.content)["model"]))
        if seen[-1][1] == "claude-opus-5-5" and len(seen) > 1:
            return httpx.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "Your credit balance is too low to access the API."}})
        return httpx.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                                         "content": [{"type": "text", "text": "done"}],
                                         "usage": {"input_tokens": 1000, "output_tokens": 100}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(anthropic)) as c:
            ok = await gateway.forward_anthropic({"model": "claude-opus-5-5", "max_tokens": 10, "messages": []},
                                                 client=c)
            broke = await gateway.forward_anthropic({"model": "claude-opus-5-5", "max_tokens": 10, "messages": []},
                                                    client=c)
            with pytest.raises(gateway.GatewayRefused):
                await gateway.forward_anthropic({"model": "claude-haiku-4-5", "messages": []}, client=c)
            return ok, broke, await has_no_credit("claude")

    ok, broke, flagged = asyncio.run(run())
    assert ok[0] == 200 and broke[0] == 400 and flagged is True
    assert seen[0] == ("anthropic-key-for-tests", "claude-opus-5-5")  # the real key never leaves the backend


def test_the_sandbox_thinks_with_opus_and_with_sol_once_anthropic_is_out_of_credit(monkeypatch):
    from types import SimpleNamespace

    from app.core.command.mission_org import Package

    team = SimpleNamespace(runtime=SimpleNamespace(task_id=None), workspace_root="/test_workspaces/x",
                           _brief=lambda p, m: "brief")
    specialist = sandbox_engine.SandboxSpecialist(team, Package("P1", "t", "coding_agent", "g", [], [], [], ""),
                                                  "m", None)
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", None)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    assert asyncio.run(specialist.model()) == "gpt-6-sol"
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "anthropic-key-for-tests")
    # A hands-on writer works with Sonnet 5.5; since 10 November so do the builder and the check, and Opus takes
    # over a writer that stopped short (lead=True) or a round that completed nothing.
    assert asyncio.run(specialist.model()) == "claude-sonnet-5-5"
    assert asyncio.run(specialist.model(lead=True)) == "claude-opus-5-5"
    asyncio.run(mark_no_credit("claude"))
    assert asyncio.run(specialist.model()) == "gpt-6-sol"
    assert sandbox_engine._no_credit({"success": False, "error": "BadRequestError: Your credit balance is too low"})
    assert not sandbox_engine._no_credit({"success": False, "error": "tests failed"})
