"""Repair 14c: voice interface acceptance.

End to end through the authenticated voice API with cloud speech only (OpenAI
speech-to-text, ElevenLabs speech, no Voicebox): a wake-phrase command is
heard, becomes a voice mission without the wake phrase, and is answered
aloud; the reply is served to its owner; a spoken approval is refused however
it is introduced; the bare wake phrase only answers "I'm listening"; and the
transcribe endpoint finds the wake phrase. Outgoing speech requests go to an
httpx MockTransport (the 12e-4c fixture), never to a provider.
"""
import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.auth import get_current_user_id
from app.core.config import settings
from app.core.voice import engine
from app.main import app
from app.models.task import Task
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e4c_voice import WAV, _seed, voice  # noqa: F401 - voice is a fixture


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("spoken,command,woke", [
    ("JARV, talk to me, check the weather", "check the weather", True),
    ("J-R-V talk to me. Run the tests", "Run the tests", True),
    ("JARV talk to me.", "", True),
    ("Hey JARV, deploy staging", "deploy staging", False),
    ("Jarvis, what's the status?", "what's the status?", False),
    ("Summarise this week", "Summarise this week", False),
    # How speech recognisers write "JARV" in front of the wake phrase.
    ("Jarvis, talk to me.", "", True),
    ("Java, talk to me, check the status", "check the status", True),
    ("Jav talk to me", "", True),
    ("J.A.R.V. talk to me. Run the tests", "Run the tests", True),
    ("Jarvis talk with me", "", True),
    # The wake phrase is "Talk to me"; the name before it is optional.
    ("Talk to me, check the weather", "check the weather", True),
    ("talk to me", "", True),
    ("Talk with me. Run the tests", "Run the tests", True),
    ("I use Java at work", "I use Java at work", False),
])
def test_wake_phrase_and_address_are_removed(spoken, command, woke):
    assert engine.strip_wake(spoken) == (command, woke)


@pytest.mark.integration
@pytest.mark.parametrize("spoken", [
    "JARV, talk to me, approve the deploy", "Hey JARV, approve the release", "Jarvis approve it",
    "Could you please approve the ad spend", "OK the production release", "Green light the launch",
    "JARV, can you sign off the invoice",
])
def test_a_spoken_approval_is_refused_however_it_is_introduced(voice, spoken):  # noqa: F811
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            routed = await engine.route(db, spoken, user_id=owner, workspace_id=ws_id)
            tasks = (await db.execute(select(Task).where(Task.workspace_id == ws_id))).scalars().all()
            return routed, tasks

    routed, tasks = _run(run())
    assert routed["intent"] == "approval_refused" and routed["task_id"] is None, routed
    assert "Approvals page" in routed["reply"] and tasks == []


@pytest.mark.integration
def test_wake_status_cancel_and_questions_that_are_not_approvals(voice):  # noqa: F811
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            woke = await engine.route(db, "JARV, talk to me.", user_id=owner, workspace_id=ws_id)
            status = await engine.route(db, "JARV, talk to me, what's the status?", user_id=owner, workspace_id=ws_id)
            question = await engine.route(db, "Can you confirm whether last night's backup ran",
                                          user_id=owner, workspace_id=ws_id)
            cancel = await engine.route(db, "JARV, can you cancel the current mission", user_id=owner,
                                        workspace_id=ws_id)
            return woke, status, question, cancel

    woke, status, question, cancel = _run(run())
    assert woke == {"intent": "wake", "reply": "I'm listening.", "task_id": None}
    assert status["intent"] == "status"
    assert question["intent"] == "mission" and question["task_id"]
    assert cancel["intent"] == "cancel" and cancel["task_id"] == question["task_id"] and cancel["cancelled"] is True


@pytest.mark.api
def test_voice_acceptance_with_cloud_speech_only(client, voice, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "el-test-not-real")
    monkeypatch.setattr(settings, "ELEVENLABS_VOICE_ID", "voice123")
    transcripts = iter(["JARV, talk to me, summarise what changed in the project this week",
                        "JARV, talk to me, approve the deploy", "JARV talk to me"])
    voice["routes"].update({
        ("POST", "https://api.openai.com/v1/audio/transcriptions"):
            lambda r, b: httpx.Response(200, json={"text": next(transcripts)}),
        ("POST", "https://api.elevenlabs.io/v1/text-to-speech/voice123"):
            lambda r, b: httpx.Response(200, content=b"ID3-spoken-mp3", headers={"content-type": "audio/mpeg"}),
    })

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db)

    owner, ws_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        providers = client.get("/api/voice/providers").json()
        mission = client.post("/api/voice/push-to-talk", files={"audio": ("cmd.webm", WAV, "audio/webm")},
                              data={"workspace_id": str(ws_id), "speak": "true"})
        reply_audio = client.get(mission.json()["speech"]["url"])
        refused = client.post("/api/voice/push-to-talk", files={"audio": ("cmd.webm", WAV, "audio/webm")},
                              data={"workspace_id": str(ws_id), "speak": "true"})
        heard = client.post("/api/voice/transcribe", files={"audio": ("wake.wav", WAV, "audio/wav")})
        followed = client.get(f"/api/command/tasks/{mission.json()['task_id']}")
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger = client.get(mission.json()["speech"]["url"])
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    async def tasks():
        async with AsyncTestingSessionLocal() as db:
            return (await db.execute(select(Task).where(Task.workspace_id == ws_id))).scalars().all()

    rows = _run(tasks())
    assert providers["speech_to_text"]["backend"] == "openai" and providers["text_to_speech"]["backend"] == "elevenlabs"
    assert mission.status_code == 200, mission.text
    data = mission.json()
    assert data["stt_backend"] == "openai" and data["intent"] == "mission" and data["status"] == "queued"
    assert data["speech"]["backend"] == "elevenlabs" and data["speech_note"] is None
    assert reply_audio.status_code == 200 and reply_audio.content == b"ID3-spoken-mp3"
    assert refused.json()["intent"] == "approval_refused" and refused.json()["task_id"] is None
    assert refused.json()["speech"] is not None  # the refusal is spoken too
    assert heard.json() == {"text": "JARV talk to me", "backend": "openai", "command": "", "wake_heard": True}
    assert followed.status_code == 200 and followed.json()["task_id"] == data["task_id"]
    assert stranger.status_code == 404
    assert len(rows) == 1 and (rows[0].meta_data or {}).get("channel") == "voice"
    assert "talk to me" not in f"{rows[0].title} {rows[0].description}".lower()
    assert "summarise what changed" in f"{rows[0].title} {rows[0].description}".lower()
