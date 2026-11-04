"""
Wave 2b: Talk with JAI on Pipecat. The voice service (services/voice) asks JAI's backend, as the signed-in
operator, for the conversation's brief (instructions with the current picture, the voice tools, the model and
voice), runs every tool here as him, and reports each model, speech-to-text and text-to-speech use to today's
AI spend; at the daily limit the brief is refused and the conversation ends. The OpenAI key never leaves the
backend's own settings through these endpoints. Real: the database, the audit log, the spend meter (test Redis).
"""
import asyncio

import pytest
from sqlalchemy import select

from app.core import spend
from app.core.auth import get_current_user_id
from app.core.config import settings
from app.core.voice import live
from app.main import app
from app.models.operations import AuditLog
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e4c_voice import _seed, voice  # noqa: F401 - voice is a fixture


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _a_fresh_day():
    async def clear():
        await (await spend._redis()).delete(spend.key())

    _run(clear())
    yield


@pytest.fixture
def operator():
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db)

    owner, _ws = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    yield owner
    app.dependency_overrides.pop(get_current_user_id, None)


def test_the_pipecat_voice_uses_each_kind_of_use_at_its_price():
    assert spend.pipeline_cost("tts", {"characters": 1_000_000}) == pytest.approx(15.0)
    assert spend.pipeline_cost("stt", {"seconds": 60}) == pytest.approx(0.006)
    luna = spend.pipeline_cost("llm", {"model": "gpt-6-luna", "prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert luna == pytest.approx(0.10)
    assert spend.pipeline_cost("llm", {"model": "unlisted", "prompt_tokens": 1_000_000}) == pytest.approx(luna)


def test_the_brief_carries_jais_instructions_tools_and_voice_but_never_the_key(client, voice, operator, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    unset = client.get("/api/voice/live/brief")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-real")
    brief = client.get("/api/voice/live/brief")
    engine_choice = client.get("/api/voice/live/engine").json()

    assert unset.status_code == 503 and "OPENAI_API_KEY" in unset.json()["detail"]
    assert brief.status_code == 200, brief.text
    body = brief.json()
    assert "sk-test" not in brief.text
    assert body["engine"] == "pipecat" and body["model"] == settings.VOICE_PIPELINE_MODEL
    # The natural voice (Chatterbox, George's British voice) by default, with Kokoro's British voice as its
    # fallback; Kokoro or OpenAI's voice when chosen.
    assert body["tts_engine"] == "chatterbox" and body["tts_voice"] == settings.VOICE_PIPELINE_CHATTERBOX_VOICE
    assert body["fallback_voice"].startswith(("bm_", "bf_"))
    monkeypatch.setattr(settings, "VOICE_PIPELINE_TTS", "kokoro")
    assert client.get("/api/voice/live/brief").json()["tts_voice"] == settings.VOICE_PIPELINE_KOKORO_VOICE
    monkeypatch.setattr(settings, "VOICE_PIPELINE_TTS", "openai")
    openai_voice = client.get("/api/voice/live/brief").json()
    assert openai_voice["tts_engine"] == "openai" and openai_voice["tts_voice"] == settings.VOICE_PIPELINE_TTS_VOICE
    assert "British" in openai_voice["tts_instructions"]
    # The voice is JAI's brain: JAI's tools, and no ask_jarv (it is given JAI's live state every turn instead).
    assert {t["name"] for t in body["tools"]} == {"start_mission", "resume_mission", "cancel_mission",
                                                  "list_workspaces", "list_workspace_files", "read_workspace_file",
                                                  "trace_artifact", "show_on_screen", "research_web",
                                                  "make_image"}
    assert "You are JAI's own mind" in body["instructions"] and "never markdown" in body["instructions"]
    assert "call ask_jarv" not in body["instructions"] and "Never answer about the outside world" in body["instructions"]
    assert body["reasoning"] == "low" and body["stt_model"] == "gpt-transcribe" and "Plexecute" in body["stt_prompt"]
    assert "Approvals page" in body["instructions"]
    assert engine_choice["engine"] == "pipecat" and engine_choice["url"].startswith("ws")
    assert engine_choice["fallback"] == "realtime"

    async def audit():
        async with AsyncTestingSessionLocal() as db:
            return (await db.execute(select(AuditLog).where(AuditLog.action == live.SESSION_ACTION,
                                                            AuditLog.user_id == operator))).scalars().all()

    assert [(a.meta_data or {}).get("engine") for a in _run(audit())] == ["pipecat", "pipecat", "pipecat"]


def test_the_brief_needs_a_signed_in_operator(client):
    assert client.get("/api/voice/live/brief").status_code == 401
    assert client.post("/api/voice/live/spend", json={"kind": "tts", "characters": 10}).status_code == 401


def test_voice_use_is_counted_and_the_limit_ends_and_refuses_the_conversation(client, voice, operator, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(settings, "DAILY_SPEND_LIMIT_USD", 0.02)
    first = client.post("/api/voice/live/spend", json={"kind": "tts", "characters": 1000}).json()   # $0.015
    second = client.post("/api/voice/live/spend", json={"kind": "stt", "seconds": 60}).json()        # $0.006
    wrong = client.post("/api/voice/live/spend", json={"kind": "music"})
    refused = client.get("/api/voice/live/brief")

    assert first["stop"] is False and first["cost_usd"] == pytest.approx(0.015)
    assert second["stop"] is True and "spending limit is reached" in second["reason"]
    assert second["today"]["voice_usd"] == pytest.approx(0.021)
    assert wrong.status_code == 400
    assert refused.status_code == 503 and "live conversation cannot start" in refused.json()["detail"]


def test_the_realtime_voice_can_be_chosen_instead(client, operator, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_ENGINE", "realtime")
    assert client.get("/api/voice/live/engine").json()["engine"] == "realtime"


def test_every_reply_of_the_brain_voice_gets_jais_live_state(client, voice, operator, monkeypatch):  # noqa: F811
    from app.core.runtime import lifecycle
    from app.models.task import Task
    from app.models.workspace import Workspace

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            ws = (await db.execute(select(Workspace).where(Workspace.owner_id == operator))).scalars().first()
            db.add(Task(workspace_id=ws.id, title="Plexecute marketing plan", description="plan", task_type="command",
                        status=lifecycle.COMPLETED, priority=5,
                        result={"response": "The plan: positioning, audience, channels. " * 200}))
            await db.commit()

    _run(seed())
    state = client.post("/api/voice/live/context", json={"text": "Read out the last mission's report"})
    assert state.status_code == 200
    import json
    facts = json.loads(state.json()["state"])
    assert facts["mission_asked_about"]["title"] == "Plexecute marketing plan"
    assert len(facts["mission_asked_about"]["result"]) > 5000            # the whole report, not its first lines
    assert "now" in facts and "working_now" in facts and "recent_conversation" not in facts
