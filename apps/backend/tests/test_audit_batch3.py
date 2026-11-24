"""
Audit batch 3 (24 November): one engine for non-development work. A Claude Agent SDK session inside the sandbox
(services/openhands/app/claude_run.py, tested there against the real Claude Code engine) for every non-development
package; OpenHands for software builds. Here: the engine each package gets, what the sandbox is sent, and JAI's
gateway streaming Anthropic's answers to it with a token of that run only, held to that run's own allowance.

Real: the gateway, Redis (the test double), the sandbox specialist's request, the skills table. Anthropic and the
sandbox are httpx MockTransports: no model is called and nothing is spent.
"""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.core import gateway, spend
from app.core.command import sandbox_engine
from app.core.command.mission_org import Package
from app.core.config import settings

SONNET = "claude-sonnet-5-5"


def _team(*packages):
    return SimpleNamespace(packages=list(packages), runtime=SimpleNamespace(task_id=None, workspace_id=None,
                                                                            user_id=None, authority_level=3),
                           workspace_root="/test_workspaces/x", lead_agent_id=None,
                           _brief=lambda p, m: "YOUR FINAL MESSAGE (call finish with it): the report")


def _video():
    return Package("P1", "The openmontage skill, end to end", "creation", "g", [], [], [], "")


def _carousel():
    return Package("P1", "The carousel skill, end to end", "creation", "g", [], [], [], "")


def _builder(acting_as=None):
    return Package("B1", "Build", "builder", "g", [], [], [], "", acting_as=acting_as)


# ----- which engine ---------------------------------------------------------------------------------------------

def test_software_stays_on_openhands_and_the_rest_moves_to_the_claude_engine():
    verifier = Package("VER", "Check", "verifier", "g", [], [], [], "")
    build = _builder()
    assert sandbox_engine.engine_for(build, _team(build, verifier), "Build MYCO Phase 3", SONNET) == "openhands"
    assert sandbox_engine.engine_for(verifier, _team(build, verifier), "Build MYCO Phase 3", SONNET) == "openhands"
    sales = _builder(acting_as="sales")
    assert sandbox_engine.engine_for(sales, _team(sales, verifier), "Build the investors database", SONNET) == "claude"
    assert sandbox_engine.engine_for(verifier, _team(sales, verifier), "Build the investors database",
                                     SONNET) == "claude"  # a check follows the work it checks
    carousel = _carousel()
    assert sandbox_engine.engine_for(carousel, _team(carousel), "Make a carousel", SONNET) == "claude"


def test_videos_run_on_the_claude_sdk_and_a_brief_can_choose_openhands():
    """Richard, 24 November 02:39: "videos should be changing that was the whole point"."""
    video = _video()
    team = _team(video)
    assert settings.SANDBOX_VIDEO_ENGINE == "claude"
    assert sandbox_engine.engine_for(video, team, "Use OpenMontage to make a reel", SONNET) == "claude"
    assert sandbox_engine.engine_for(video, team, "Use OpenMontage to make a reel on OpenHands",
                                     SONNET) == "openhands"
    assert sandbox_engine.engine_for(_carousel(), _team(_carousel()), "Make a carousel on OpenHands",
                                     SONNET) == "openhands"


def test_a_package_on_an_openai_model_stays_on_openhands():
    carousel = _carousel()
    assert sandbox_engine.engine_for(carousel, _team(carousel), "Make a carousel", "gpt-6-sol") == "openhands"


def test_settings_put_work_back_on_openhands(monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_NON_DEV_ENGINE", "openhands")
    carousel = _carousel()
    assert sandbox_engine.engine_for(carousel, _team(carousel), "Make a carousel", SONNET) == "openhands"


# ----- what the sandbox is sent ---------------------------------------------------------------------------------

def test_a_claude_run_gets_its_own_token_the_backends_limits_and_its_token_dies_with_the_run(monkeypatch):
    carousel = _carousel()
    team = _team(carousel)
    sent, seen_token = [], {}

    async def no_register(self, root):
        return None

    async def follow(self, client, root):
        seen_token["live"] = await gateway.run_of_token(sent[0]["model_token"])
        return {"status": "finished", "final_message": "R1: done — carousel.png", "steps": 3,
                "tokens": {"input": 10, "output": 5}, "cost_usd": 0.02}

    def sandbox(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"run_id": sent[-1]["run_id"], "status": "starting"})

    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "_register", no_register)
    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "_follow", follow)
    monkeypatch.setattr(settings, "OPENHANDS_URL", "http://openhands:8010")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(sandbox)) as client:
            specialist = sandbox_engine.SandboxSpecialist(team, carousel, "Make a carousel", None, client=client)
            out = await specialist._attempt([{"id": "R1", "text": "a carousel"}], "/host/workspaces/x", SONNET)
            return out, await gateway.run_of_token(sent[0]["model_token"])

    out, after = asyncio.run(run())
    body = sent[0]
    assert body["engine"] == "claude" and out["engine"] == "claude" and out["success"] is True
    assert body["model_token"].startswith("jai-run-") and body["model_token"] != settings.JAI_GATEWAY_TOKEN
    assert body["api_timeout_ms"] == settings.SANDBOX_CLAUDE_API_TIMEOUT_MS
    assert body["max_retries"] == settings.SANDBOX_CLAUDE_MAX_RETRIES
    assert "YOUR FINAL MESSAGE (your last reply, when the work is done)" in body["brief"]
    # Every skill JAI has is offered; the specialist's own trade is described in full.
    from app.core.knowledge.skill_packs import all_skills, sandbox_skills

    assert body["skills"] == (all_skills(plugins_apart=bool(body["plugins"])) or sandbox_skills("creation"))
    assert body["mission_id"] and body["ecc_learning"] is settings.ECC_LEARNING_ENABLED
    assert body["skills_in_full"] == [p.rsplit("/", 1)[-1] for p in sandbox_skills("creation")]
    assert seen_token["live"]["run"] == body["run_id"]
    assert seen_token["live"]["max_cost_usd"] == pytest.approx(body["max_cost_usd"])
    assert after is None  # revoked when the run ended


def test_an_openhands_run_is_sent_no_run_token(monkeypatch):
    build = _builder()
    sent = []

    async def no_register(self, root):
        return None

    async def follow(self, client, root):
        return {"status": "finished", "final_message": "R1: done — x", "steps": 1, "tokens": {}, "cost_usd": 0}

    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "_register", no_register)
    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "_follow", follow)
    monkeypatch.setattr(settings, "OPENHANDS_URL", "http://openhands:8010")

    def sandbox(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"run_id": sent[-1]["run_id"], "status": "starting"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(sandbox)) as client:
            await sandbox_engine.SandboxSpecialist(_team(build), build, "Build it", None, client=client)._attempt(
                [], "/host/workspaces/x", SONNET)

    asyncio.run(run())
    assert sent[0]["engine"] == "openhands" and "model_token" not in sent[0]
    assert "call finish with it" in sent[0]["brief"]


# ----- the gateway streams to a Claude session, with its run's token, within its run's allowance ------------------

def _sse(*events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


STREAM = _sse({"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant",
                                                     "model": SONNET, "content": [],
                                                     "usage": {"input_tokens": 1000, "output_tokens": 1,
                                                               "cache_read_input_tokens": 2000}}},
              {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
              {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "done"}},
              {"type": "content_block_stop", "index": 0},
              {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 300}},
              {"type": "message_stop"})


def test_the_streams_usage_is_read_from_its_own_events():
    usage = gateway.stream_usage(STREAM.decode(), {})
    assert usage["input_tokens"] == 1000 and usage["cache_read_input_tokens"] == 2000
    assert usage["output_tokens"] == 300


def test_a_stream_is_passed_on_whole_and_its_cost_recorded_for_today_and_for_the_run(monkeypatch):
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "anthropic-key-for-tests")
    recorded = []

    async def record(kind, amount):
        recorded.append((kind, amount))

    monkeypatch.setattr(spend, "record", record)
    seen = []

    def anthropic(request):
        seen.append((request.headers["x-api-key"], json.loads(request.content)["stream"]))
        return httpx.Response(200, content=STREAM, headers={"content-type": "text/event-stream"})

    async def run():
        token = await gateway.issue_run_token("run-a", 600, 1.0)
        live = await gateway.run_of_token(f"Bearer {token}")
        status, headers, chunks = await gateway.forward_anthropic_stream(
            {"model": SONNET, "max_tokens": 10, "stream": True, "messages": []}, run=live,
            client=httpx.AsyncClient(transport=httpx.MockTransport(anthropic)))
        body = b"".join([c async for c in chunks])
        return status, headers, body, await gateway.run_spent(live), token

    status, headers, body, run_spent, token = asyncio.run(run())
    assert status == 200 and headers["content-type"] == "text/event-stream" and body == STREAM
    assert seen == [("anthropic-key-for-tests", True)]  # the real key never leaves the backend
    expected = spend.text_cost(SONNET, {"input_tokens": 1000, "cache_read_input_tokens": 2000, "output_tokens": 300})
    assert recorded == [("text", pytest.approx(expected))] and run_spent == pytest.approx(expected)
    asyncio.run(gateway.revoke_run_token(token))


def test_a_run_token_is_refused_past_its_runs_allowance_and_after_the_run(monkeypatch):
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "anthropic-key-for-tests")

    async def run():
        token = await gateway.issue_run_token("run-b", 600, 0.05)
        live = await gateway.run_of_token(token)
        await gateway.add_run_spend(live, 0.05)
        with pytest.raises(gateway.GatewayRefused) as refused:
            await gateway.check_run(live)
        await gateway.revoke_run_token(token)
        return refused.value, await gateway.run_of_token(token), await gateway.run_of_token("jai-run-made-up")

    refused, after, made_up = asyncio.run(run())
    assert refused.status == 429 and "allowance" in refused.message
    assert after is None and made_up is None


def test_the_gateway_route_takes_a_run_token_and_streams(monkeypatch, client):
    monkeypatch.setattr(settings, "JAI_GATEWAY_TOKEN", "gateway-token-0123456789")
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "anthropic-key-for-tests")

    async def fake_stream(body, version=None, beta=None, caller="sandbox", client=None, run=None):
        async def chunks():
            yield STREAM
        fake_stream.run = run
        return 200, {"content-type": "text/event-stream"}, chunks()

    monkeypatch.setattr(gateway, "forward_anthropic_stream", fake_stream)
    token = asyncio.run(gateway.issue_run_token("run-c", 600, 1.0))
    body = {"model": SONNET, "max_tokens": 10, "stream": True, "messages": []}
    answer = client.post("/api/gateway/anthropic/v1/messages?beta=true", json=body,
                         headers={"Authorization": f"Bearer {token}"})
    assert answer.status_code == 200 and answer.content == STREAM and fake_stream.run["run"] == "run-c"
    asyncio.run(gateway.revoke_run_token(token))
    refused = client.post("/api/gateway/anthropic/v1/messages", json=body,
                          headers={"Authorization": f"Bearer {token}"})
    assert refused.status_code == 401
    assert client.post("/api/gateway/anthropic/v1/messages/count_tokens", json={"model": SONNET},
                       headers={"Authorization": "Bearer nope"}).status_code == 401


# ----- the skills table -------------------------------------------------------------------------------------------

def test_skills_that_need_services_jai_does_not_have_are_pointed_at_its_own_tools():
    from app.core.knowledge.skill_packs import SKILLS
    from tests.repo_paths import repo_path

    assert not any(e["skill"] == "lead-intelligence" for e in SKILLS)  # Apollo, Exa and X keys: removed
    for path in (repo_path("services", "openhands", "app", "server.py"),
                 repo_path("apps", "backend", "app", "core", "command", "claude_engine.py")):
        text = path.read_text()
        assert "Skills that name a service JAI does not have" in text and "never ask for a key" in text
        for service in ("Exa", "Ahrefs", "Apollo", "Browserbase", "ElevenLabs"):
            assert service in text
