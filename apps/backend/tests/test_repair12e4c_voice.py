"""Repair 12e-4c: voice tools.

Real: the tools through the registry, audio decoding and resampling for the
wake spotter, stored replies with owner checks, and spoken commands routed into
real Command Center missions under the approval gate. Replaced at the boundary
only: the speech services' HTTP endpoints (httpx.MockTransport playing
Voicebox, OpenAI and ElevenLabs) and, for the wake test, the sherpa-onnx
spotter itself (its model is a 3 MB download installed by an admin).
"""
import asyncio
import base64
import io
import json
import shutil
import struct
import wave
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.auth import get_current_user_id
from app.core.config import settings
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import create_tool, get_registry
from app.core.voice import engine, wake_service
from app.main import app
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.voice import VOICE_TOOLS
from tests.conftest import AsyncTestingSessionLocal

SANDBOX = Path("/tmp/jarv_sandbox")
WAV = b"RIFF0000WAVEfmt fake-recording"


def _run(coro):
    return asyncio.run(coro)


async def _call(name, data, ctx, level=AuthorityLevel.LEVEL_5_NETWORK_ACCESS):
    return await create_tool(name, ToolConfig(authority_level=level)).execute(data, ctx)


async def _seed(db, host=None):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="MYCO", slug=f"myco-{ws_id.hex[:8]}", description="",
                     workspace_type="project", authority_level=5, is_active=True,
                     config={"root_path": host} if host else {}))
    await db.commit()
    return user_id, ws_id


@pytest.fixture
def voice(monkeypatch, tmp_path):
    """No backend configured, replies stored in a temporary folder, every request recorded."""
    for name, value in (("VOICEBOX_BASE_URL", None), ("VOICEBOX_PROFILE_ID", None), ("OPENAI_API_KEY", ""),
                        ("ELEVENLABS_API_KEY", None), ("ELEVENLABS_VOICE_ID", None), ("STT_PROVIDER", "auto"),
                        ("TTS_PROVIDER", "auto"), ("VOICE_AUDIO_DIR", str(tmp_path / "voice-audio"))):
        monkeypatch.setattr(settings, name, value)
    requests, routes = [], {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        requests.append((request, body))
        for (method, prefix), respond in routes.items():
            if request.method == method and str(request.url).startswith(prefix):
                return respond(request, body)
        return httpx.Response(404, json={"detail": "no route"})

    real = httpx.AsyncClient
    monkeypatch.setattr(engine, "http_client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return {"requests": requests, "routes": routes, "audio_dir": tmp_path / "voice-audio"}


def _voicebox(voice, monkeypatch, transcript="What's the status?"):
    monkeypatch.setattr(settings, "VOICEBOX_BASE_URL", "http://voicebox.test")
    monkeypatch.setattr(settings, "VOICEBOX_PROFILE_ID", "jarv-profile")
    polls = {"n": 0}

    def audio(request, body):
        polls["n"] += 1
        if polls["n"] == 1:
            return httpx.Response(404, json={"detail": "generating"})
        return httpx.Response(200, content=b"RIFF-spoken-reply", headers={"content-type": "audio/wav"})

    voice["routes"].update({
        ("POST", "http://voicebox.test/transcribe"): lambda r, b: httpx.Response(200, json={"text": transcript,
                                                                                           "duration": 1.4}),
        ("POST", "http://voicebox.test/generate"): lambda r, b: httpx.Response(200, json={"id": "gen-1",
                                                                                         "status": "generating"}),
        ("GET", "http://voicebox.test/audio/gen-1"): audio,
    })
    return polls


# ----- registry ---------------------------------------------------------------------------------

def test_voice_tools_registered_with_authority():
    registry = get_registry()
    names = [t._name for t in VOICE_TOOLS]
    assert names == ["transcribe_voice", "speak_response", "listen_push_to_talk", "wake_word_detect",
                     "route_voice_command"]
    for name in names:
        meta = registry.get_metadata(name)
        assert meta is not None and meta.is_implemented and meta.category == "voice", name
    assert registry.get_metadata("wake_word_detect").required_authority_level == 1
    assert registry.get_metadata("route_voice_command").required_authority_level == 2
    assert registry.get_metadata("transcribe_voice").required_authority_level == 5
    from app.core.agents.registry import get_registry as agents

    orchestrator = agents().get_metadata("orchestrator")
    assert {"transcribe_voice", "speak_response"} <= set(orchestrator.default_tools)


# ----- backends ---------------------------------------------------------------------------------

@pytest.mark.integration
def test_without_a_backend_each_step_names_the_setting(voice):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            heard = await _call("transcribe_voice", {"audio_base64": base64.b64encode(WAV).decode()}, ctx)
            said = await _call("speak_response", {"text": "Hello Richard"}, ctx)
            both = await _call("transcribe_voice", {"audio_base64": "AAAA", "file": "a.wav"}, ctx)
            garbage = await _call("transcribe_voice", {"audio_base64": "not base64!!"}, ctx)
            return heard, said, both, garbage

    heard, said, both, garbage = _run(run())
    assert heard.success is False and "VOICEBOX_BASE_URL" in heard.error_message
    assert "OPENAI_API_KEY" in heard.error_message
    assert said.success is False and "ELEVENLABS_API_KEY" in said.error_message
    assert both.success is False and "one of them" in both.error_message
    assert garbage.success is False and "base64" in garbage.error_message
    state = engine.status()
    assert state["speech_to_text"]["ready"] is False and state["text_to_speech"]["ready"] is False
    assert voice["requests"] == []


@pytest.mark.integration
def test_voicebox_transcribes_and_speaks_and_replies_belong_to_their_owner(voice, monkeypatch):
    polls = _voicebox(voice, monkeypatch, transcript="Check the deployment")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            heard = await _call("transcribe_voice", {"audio_base64": base64.b64encode(WAV).decode(),
                                                     "filename": "command.webm", "language": "en-GB"}, ctx)
            said = await _call("speak_response", {"text": "The deployment is healthy."}, ctx)
            bad_type = await _call("transcribe_voice", {"audio_base64": base64.b64encode(WAV).decode(),
                                                        "filename": "virus.exe"}, ctx)
            return owner, heard, said, bad_type

    owner, heard, said, bad_type = _run(run())
    assert heard.success, heard.error_message
    assert heard.result_data["text"] == "Check the deployment" and heard.result_data["backend"] == "voicebox"
    request, body = voice["requests"][0]
    assert request.url.path == "/transcribe" and b'name="language"' in body and b"\r\n\r\nen\r\n" in body
    assert b"fake-recording" in body
    assert said.success, said.error_message
    generate = json.loads(voice["requests"][1][1])
    assert generate == {"profile_id": "jarv-profile", "text": "The deployment is healthy.", "language": "en"}
    assert polls["n"] == 2  # waited for the generation to finish
    audio_id = said.result_data["audio_id"]
    assert said.result_data["url"] == f"/api/voice/audio/{audio_id}" and said.result_data["format"] == "wav"
    path, media = engine.audio_file(audio_id, owner)
    assert path.read_bytes() == b"RIFF-spoken-reply" and media == "audio/wav"
    with pytest.raises(LookupError):
        engine.audio_file(audio_id, uuid4())
    with pytest.raises(LookupError):
        engine.audio_file("../../etc/passwd", owner)
    assert bad_type.success is False and ".exe" in bad_type.error_message


@pytest.mark.integration
def test_openai_transcription_and_elevenlabs_speech(voice, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "el-test-not-real")
    monkeypatch.setattr(settings, "ELEVENLABS_VOICE_ID", "voice123")
    voice["routes"].update({
        ("POST", "https://api.openai.com/v1/audio/transcriptions"):
            lambda r, b: httpx.Response(200, json={"text": "  Show me revenue  "}),
        ("POST", "https://api.elevenlabs.io/v1/text-to-speech/voice123"):
            lambda r, b: httpx.Response(200, content=b"ID3-mp3-audio", headers={"content-type": "audio/mpeg"}),
    })

    async def run():
        heard = await engine.transcribe(WAV, filename="clip.wav", language="en-GB")
        said = await engine.speak("Revenue is up.", owner=uuid4())
        monkeypatch.setattr(settings, "TTS_PROVIDER", "openai")
        voice["routes"][("POST", "https://api.openai.com/v1/audio/speech")] = \
            lambda r, b: httpx.Response(401, json={"error": {"message": "Incorrect API key"}})
        try:
            await engine.speak("Revenue is up.")
        except RuntimeError as exc:
            failed = str(exc)
        return heard, said, failed

    heard, said, failed = _run(run())
    assert heard["text"] == "Show me revenue" and heard["backend"] == "openai"
    stt_request, stt_body = voice["requests"][0]
    assert stt_request.headers["authorization"] == "Bearer sk-test-not-real"
    assert b"whisper-1" in stt_body and b"\r\n\r\nen\r\n" in stt_body
    assert said["backend"] == "elevenlabs" and said["format"] == "mp3"
    tts_request, tts_body = voice["requests"][1]
    assert tts_request.headers["xi-api-key"] == "el-test-not-real"
    assert json.loads(tts_body)["text"] == "Revenue is up."
    assert "(401)" in failed and "Incorrect API key" in failed
    assert "sk-test-not-real" not in failed


# ----- commands ---------------------------------------------------------------------------------

@pytest.mark.integration
def test_spoken_commands_become_missions_under_the_approval_gate(voice):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            quiet = await _call("route_voice_command", {"text": "What's the status?"}, ctx)
            mission = await _call("route_voice_command",
                                  {"text": "Summarise what changed in the project this week"}, ctx)
            gated = await _call("route_voice_command", {"text": "Spend 200 pounds on Google ads"}, ctx)
            approve = await _call("route_voice_command", {"text": "Approve the ad spend"}, ctx)
            busy = await _call("route_voice_command", {"text": "status update please"}, ctx)
            cancel = await _call("route_voice_command", {"text": "Cancel the last mission"}, ctx)
            await db.commit()
            tasks = (await db.execute(select(Task).where(Task.workspace_id == ws_id)
                                      .order_by(Task.created_at))).scalars().all()
            return quiet, mission, gated, approve, busy, cancel, tasks

    quiet, mission, gated, approve, busy, cancel, tasks = _run(run())
    assert quiet.success and quiet.result_data["intent"] == "status"
    assert "nothing is running" in quiet.result_data["reply"] and "nothing needs your approval" in quiet.result_data["reply"]
    assert mission.success and mission.result_data["intent"] == "mission"
    assert mission.result_data["status"] == "queued" and mission.result_data["reply"].startswith("On it")
    assert gated.result_data["requires_approval"] is True and gated.result_data["status"] == "blocked"
    assert "spends money" in gated.result_data["reply"] and "Approvals page" in gated.result_data["reply"]
    assert approve.result_data["intent"] == "approval_refused" and approve.result_data["task_id"] is None
    assert busy.result_data["in_flight"] == 1 and busy.result_data["awaiting_approval"] == 1
    assert cancel.result_data["intent"] == "cancel" and cancel.result_data["cancelled"] is True
    assert cancel.result_data["task_id"] == gated.result_data["task_id"]  # the latest one
    assert len(tasks) == 2 and all((t.meta_data or {}).get("channel") == "voice" for t in tasks)
    assert [t.status for t in tasks] == ["queued", "cancelled"]


@pytest.mark.integration
def test_push_to_talk_hears_acts_and_answers(voice, monkeypatch):
    _voicebox(voice, monkeypatch, transcript="What's the status?")
    name = f"r12e4c-{uuid4().hex[:8]}"
    root = SANDBOX / name
    (root / "recordings").mkdir(parents=True)
    (root / "recordings" / "ask.wav").write_bytes(WAV)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db, f"/test_workspaces/{name}")
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            spoken = await _call("listen_push_to_talk", {"file": "recordings/ask.wav"}, ctx)
            silent = await _call("listen_push_to_talk", {"audio_base64": base64.b64encode(WAV).decode(),
                                                         "speak": False}, ctx)
            escape = await _call("listen_push_to_talk", {"file": "../../etc/passwd"}, ctx)
            missing = await _call("listen_push_to_talk", {"file": "recordings/none.wav"}, ctx)
            return spoken, silent, escape, missing

    try:
        spoken, silent, escape, missing = _run(run())
    finally:
        shutil.rmtree(root, ignore_errors=True)
    assert spoken.success, spoken.error_message
    assert spoken.result_data["heard"] == "What's the status?" and spoken.result_data["intent"] == "status"
    assert spoken.result_data["speech"]["backend"] == "voicebox" and spoken.result_data["speech_note"] is None
    assert silent.success and silent.result_data["speech"] is None
    assert escape.success is False and "inside the workspace" in escape.error_message
    assert missing.success is False and "No recording" in missing.error_message


# ----- wake phrase ------------------------------------------------------------------------------

def _wav(seconds=2.0, rate=8000, channels=2):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = int(seconds * rate)
        out.writeframes(b"".join(struct.pack("<" + "h" * channels, *([1000] * channels)) for _ in range(frames)))
    return buffer.getvalue()


@pytest.mark.integration
def test_wake_phrase_detection_decodes_resamples_and_scans(monkeypatch):
    frames, freed = [], []

    def process(stream, frame):
        frames.append(len(frame))
        return wake_service.WAKE_KEYWORD_ID if len(frames) == 6 else None

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            monkeypatch.setattr(wake_service, "model_is_ready", lambda: False)
            missing = await _call("wake_word_detect", {"audio_base64": base64.b64encode(_wav()).decode()}, ctx)
            monkeypatch.setattr(wake_service, "model_is_ready", lambda: True)
            monkeypatch.setattr(wake_service, "create_stream", lambda: "stream")
            monkeypatch.setattr(wake_service, "process_audio_frame", process)
            monkeypatch.setattr(wake_service, "free_stream", lambda stream: freed.append(stream))
            heard = await _call("wake_word_detect", {"audio_base64": base64.b64encode(_wav()).decode()}, ctx)
            frames.clear()
            raw = await _call("wake_word_detect", {"audio_base64": base64.b64encode(b"\x00" * 4 * 1600).decode(),
                                                   "sample_format": "f32le"}, ctx)
            not_wav = await _call("wake_word_detect", {"audio_base64": base64.b64encode(b"MP3 bytes").decode()}, ctx)
            return missing, heard, raw, not_wav

    missing, heard, raw, not_wav = _run(run())
    assert missing.success is False and "wake/model/install" in missing.error_message
    assert heard.success, heard.error_message
    assert heard.result_data["detected"] is True and heard.result_data["at_seconds"] == 1.0
    assert heard.result_data["seconds_scanned"] == 2.0  # 2 s at 8 kHz stereo, resampled to 16 kHz mono
    assert raw.success and raw.result_data["detected"] is False and raw.result_data["seconds_scanned"] == 0.1
    assert set(frames[:-1]) == {3200 * 4}  # 0.2 s float32 frames
    assert freed == ["stream", "stream"]
    assert not_wav.success is False and "WAV" in not_wav.error_message


# ----- API --------------------------------------------------------------------------------------

@pytest.mark.api
def test_voice_api_is_authenticated_and_owner_scoped(client, voice, monkeypatch):
    assert client.get("/api/voice/health").status_code == 401

    async def seed():
        async with AsyncTestingSessionLocal() as db:
            return await _seed(db)

    owner, ws_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        health = client.get("/api/voice/health")
        answered = client.post("/api/voice/command/text", json={"command": "What's the status?",
                                                               "workspace_id": str(ws_id)})
        _voicebox(voice, monkeypatch)
        spoken = client.post("/api/voice/speak", json={"text": "All systems healthy."})
        audio_id = spoken.json()["audio_id"]
        fetched = client.get(f"/api/voice/audio/{audio_id}")
        pushed = client.post("/api/voice/push-to-talk", files={"audio": ("ask.wav", WAV, "audio/wav")},
                             data={"workspace_id": str(ws_id), "speak": "false"})
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger_audio = client.get(f"/api/voice/audio/{audio_id}")
        stranger_ws = client.post("/api/voice/command/text", json={"command": "status", "workspace_id": str(ws_id)})
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert health.status_code == 200 and health.json()["status"] == "degraded" and health.json()["setup"]
    assert answered.status_code == 200 and answered.json()["intent"] == "status"
    assert answered.json()["speech"] is None and "Reply not spoken" in answered.json()["speech_note"]
    assert spoken.status_code == 200 and fetched.status_code == 200 and fetched.content == b"RIFF-spoken-reply"
    assert pushed.status_code == 200 and pushed.json()["heard"] == "What's the status?"
    assert stranger_audio.status_code == 404 and stranger_ws.status_code == 404
