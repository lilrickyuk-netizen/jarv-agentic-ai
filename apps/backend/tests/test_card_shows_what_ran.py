"""
25 November: Richard switched VIDEO_MODEL back to claude-sonnet-5-5, recreated the backend and worker, and the
mission cards still said "claude/claude-opus-5-5": the card fell back to the Orchestrator's model, recorded when the
mission was queued, and took package models from what JAI asked for. The card now names the model the engine's own
run reported (the Claude Agent SDK session's replies and model_usage, OpenHands' metrics), per role when the roles
differ, and nothing when no run has reported one. The sandbox is an httpx MockTransport: no model is called.
"""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.api.command import _mission_view
from app.core.command import sandbox_engine
from app.core.command.mission_org import SKILL_RUNS, Package
from app.core.command.service import worked_on
from app.core.config import settings

OPUS, SONNET = "claude-opus-5-5", "claude-sonnet-5-5"


class StudioSandbox:
    """The sandbox running a studio package on the Claude engine: it reports the model its session used."""

    def __init__(self, reported):
        self.reported, self.started, self.polls = reported, None, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/runs":
            self.started = json.loads(request.content)
            return httpx.Response(200, json={"run_id": self.started["run_id"], "status": "starting"})
        self.polls += 1
        if self.polls == 1:
            return httpx.Response(200, json={"status": "running", "steps": 2, "max_iterations": 200,
                                             "doing_now": "Planning the edit.", "actions": [],
                                             "models_used": {self.reported: {"replies": 2, "cost_usd": 0.0}}})
        return httpx.Response(200, json={
            "status": "finished", "steps": 9, "max_iterations": 200, "cost_usd": 0.31,
            "tokens": {"input": 9000, "output": 900, "cached": 0}, "final_message": "R1: done — rendered",
            "actions": [], "models_used": {self.reported: {"replies": 9, "cost_usd": 0.31}}})


def _studio_run(monkeypatch, reported):
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "anthropic-key-for-tests")
    monkeypatch.setattr(settings, "OPENHANDS_TOKEN", "sandbox-test-token")
    monkeypatch.setattr(settings, "OPENHANDS_URL", "http://openhands:8010")
    from tests.test_model_tiers import _forget_no_credit

    asyncio.run(_forget_no_credit())
    fake = StudioSandbox(reported)
    live = []

    async def adopt(calls):
        return None

    package = Package("P1", "The openmontage skill run", "creation", "Make the video.", [], [], ["R1"],
                      "the video is in the folder", **SKILL_RUNS["openmontage"])

    async def save_progress():
        live.append({"team": {"packages": [package.card()]}})

    team = SimpleNamespace(
        runtime=SimpleNamespace(task_id=uuid4(), workspace_id=uuid4(), user_id=None, authority_level=4),
        workspace_root="/test_workspaces/studio-card", lead_agent_id=None, adopt=adopt, save_progress=save_progress,
        packages=[package], _brief=lambda p, m: "YOUR WORK PACKAGE P1")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake), base_url="http://openhands:8010") as client:
            return await sandbox_engine.SandboxSpecialist(team, package, "Make the video.", None, client=client,
                                                          poll_seconds=0.01).run(
                [{"id": "R1", "text": "video", "source": "mission", "status": "open", "evidence": ""}])

    return fake, package, asyncio.run(run()), live


def _task(status, result=None):
    # The Orchestrator's model, recorded when the mission was queued: what the card used to fall back to.
    return SimpleNamespace(id=uuid4(), result=result, meta_data={"provider": "claude", "model": OPUS},
                           status=status, execution_duration_seconds=0, tokens_used=0, started_at=None,
                           error_message=None, description="Make the video.", title="t", context={},
                           workspace_id=uuid4(), created_at=None, updated_at=None, heartbeat_at=None, retry_count=0)


def test_a_studio_mission_with_video_model_sonnet_shows_sonnet_on_its_card(monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_MODEL", SONNET)
    monkeypatch.setattr(settings, "DEFAULT_MODEL", OPUS)  # the Orchestrator stays on Opus
    fake, package, result, live = _studio_run(monkeypatch, reported=SONNET)
    assert fake.started["model"] == SONNET  # VIDEO_MODEL is read as the run starts
    assert result["ran_on"] == SONNET and result["models_used"][SONNET]["cost_usd"] == 0.31

    # While it works: the running card names what the session said is answering, not the queued Opus.
    assert live and live[0]["team"]["packages"][0]["ran_on"] == SONNET
    running = _mission_view(_task("running"), [], live[-1])
    assert (running.provider, running.model) == ("claude", SONNET)

    # Once it has ended: the model its result recorded.
    package.ran_on, package.models_used = result["ran_on"], result["models_used"]
    did = worked_on({"team": {"packages": [package.card()]}})
    finished = _mission_view(_task("completed", {"provider": did["provider"], "model": did["model"],
                                                 "models_used": did["models"],
                                                 "models_by_role": did["by_role"]}), [])
    assert finished.model == SONNET and finished.provider == "claude" and finished.models_by_role == {}


def test_the_card_names_what_the_engine_reported_even_when_it_differs_from_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_MODEL", SONNET)
    _, _, result, _ = _studio_run(monkeypatch, reported=OPUS)
    assert result["ran_on"] == OPUS  # the session's own account, not VIDEO_MODEL


def test_a_running_mission_whose_engine_has_not_reported_shows_no_model():
    view = _mission_view(_task("running"), [], {"team": {"packages": [{"id": "P1", "ran_on": None}]}})
    assert view.provider is None and view.model is None


def test_roles_on_different_models_are_each_named():
    cards = [{"id": "P1", "role": "Product Designer", "ran_on": SONNET,
              "models_used": {SONNET: {"replies": 40, "cost_usd": 2.1}}},
             {"id": "VER", "role": "Verifier", "ran_on": "claude-haiku-5-5",
              "models_used": {"claude-haiku-5-5": {"replies": 5, "cost_usd": 0.05}}}]
    did = worked_on({"team": {"packages": cards}})
    assert did["model"] == SONNET and did["by_role"] == {"Product Designer": SONNET, "Verifier": "claude-haiku-5-5"}
    view = _mission_view(_task("completed", {"provider": did["provider"], "model": did["model"],
                                             "models_used": did["models"], "models_by_role": did["by_role"]}), [])
    assert view.models_by_role == {"Product Designer": SONNET, "Verifier": "claude-haiku-5-5"}


def test_the_claude_engine_books_the_models_its_session_reported():
    from app.core.command.claude_engine import ClaudeRoleExecutor

    engine = ClaudeRoleExecutor.__new__(ClaudeRoleExecutor)
    engine.engine_cost_usd, engine.tokens, engine.models_seen = 0.0, 0, {}
    engine.usage = SimpleNamespace(cost_usd=0.0, calls=0, by_role={}, totals={"input": 0, "cached": 0,
                                                                                "cache_write": 0, "output": 0})
    engine._book(SimpleNamespace(total_cost_usd=0.5, usage={}, num_turns=3,
                                 model_usage={SONNET: {"costUSD": 0.45}, "claude-haiku-5-5": {"costUSD": 0.05}}))
    assert sandbox_engine.main_model(engine.models_seen) == SONNET
