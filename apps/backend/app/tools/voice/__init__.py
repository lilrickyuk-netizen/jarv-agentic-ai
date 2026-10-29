"""
JARV Backend - Voice tools (Repair 12e-4c)

transcribe_voice, speak_response, listen_push_to_talk, wake_word_detect and
route_voice_command on the voice engine (app.core.voice.engine). Audio comes
in as base64 or as a file inside the workspace folder; spoken replies are
stored for the workspace owner and served at /api/voice/audio/{id}. Spoken
commands become Command Center missions under the same approval gate, and
approvals are never taken by voice.
"""
from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.voice import engine
from app.tools._scoped import ScopedTool


class _VoiceTool(ScopedTool):
    _category = "voice"
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS


class _Audio(BaseModel):
    audio_base64: Optional[str] = Field(None, description="The recording, base64-encoded")
    file: Optional[str] = Field(None, description="Or a recording inside the workspace folder (relative path)")
    filename: Optional[str] = Field(None, description="Name with extension when sending base64, e.g. command.webm")
    language: str = Field("en", description="Spoken language, e.g. en or en-GB")


async def _audio(db, context, data) -> tuple[bytes, str]:
    if bool(data.get("audio_base64")) == bool(data.get("file")):
        raise ValueError("Give the recording as audio_base64 or as a workspace file (one of them)")
    if data.get("audio_base64"):
        raw = data["audio_base64"].split(",", 1)[-1] if data["audio_base64"].startswith("data:") else data["audio_base64"]
        if len(raw) > engine.max_audio_bytes() * 4 // 3 + 8:
            raise ValueError("The audio is too large")
        try:
            audio = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("audio_base64 is not valid base64") from None
        return audio, data.get("filename") or "speech.wav"
    from app.core.workspaces import fs_inspector
    from app.models.workspace import Workspace

    ws = (await db.execute(select(Workspace).where(Workspace.id == context.workspace_id))).scalar_one()
    host = (ws.config or {}).get("root_path")
    root = fs_inspector.host_to_container(host) if host else None
    if root is None or not root.is_dir():
        raise ValueError("This workspace has no folder")
    root = root.resolve()
    target = (root / data["file"]).resolve()
    if root != target and root not in target.parents:
        raise PermissionError("The recording must be inside the workspace folder")
    if fs_inspector._is_banned(str(target)) or not target.is_file():
        raise LookupError(f"No recording at {data['file']}")
    if target.stat().st_size > engine.max_audio_bytes():
        raise ValueError("The audio is too large")
    return target.read_bytes(), target.name


async def _unavailable(call):
    try:
        return await call
    except engine.VoiceUnavailable as exc:
        raise RuntimeError(str(exc)) from None


class TranscribeVoiceTool(_VoiceTool):
    _name = "transcribe_voice"
    _description = "Transcribe a voice recording to text (Voicebox locally, or OpenAI transcription)."
    _input = _Audio

    async def act(self, db, context, owner, data):
        audio, name = await _audio(db, context, data)
        result = await _unavailable(engine.transcribe(audio, filename=name, language=data["language"]))
        return result, f"Heard: {result['text'][:200]}"


class _Speak(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    language: str = "en"
    voice: Optional[str] = Field(None, description="Backend voice id; defaults to JARV's configured voice")


class SpeakResponseTool(_VoiceTool):
    _name = "speak_response"
    _description = "Turn a reply into speech in JARV's voice; returns the audio link for the owner."
    _input = _Speak

    async def act(self, db, context, owner, data):
        result = await _unavailable(engine.speak(data["text"], owner=owner, language=data["language"],
                                                 voice=data.get("voice")))
        return result, f"Spoken reply ready ({result['backend']}, {result['bytes']} bytes): {result['url']}"


class _Command(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000, description="What was said")


class RouteVoiceCommandTool(_VoiceTool):
    _name = "route_voice_command"
    _description = ("Act on a spoken command: status questions are answered from the mission records, 'cancel the "
                    "last mission' cancels it, anything else becomes a Command Center mission under the approval "
                    "gate. Approvals are never taken by voice.")
    _input = _Command
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def act(self, db, context, owner, data):
        result = await engine.route(db, data["text"], user_id=owner, workspace_id=context.workspace_id)
        return result, result["reply"]


class _PushToTalk(_Audio):
    speak: bool = Field(True, description="Also speak the reply")


class ListenPushToTalkTool(_VoiceTool):
    _name = "listen_push_to_talk"
    _description = ("Push-to-talk: transcribe the recording, act on it as a voice command, and speak the reply "
                    "(the reply text is always returned, with or without a speech backend).")
    _input = _PushToTalk

    async def act(self, db, context, owner, data):
        audio, name = await _audio(db, context, data)
        heard = await _unavailable(engine.transcribe(audio, filename=name, language=data["language"]))
        routed = await engine.route(db, heard["text"], user_id=owner, workspace_id=context.workspace_id)
        spoken, note = None, None
        if data["speak"]:
            try:
                spoken = await engine.speak(routed["reply"], owner=owner, language=data["language"])
            except engine.VoiceUnavailable as exc:
                note = f"Reply not spoken: {exc}"
            except RuntimeError as exc:
                note = f"Reply not spoken: {exc}"
        return {"heard": heard["text"], "stt_backend": heard["backend"], **routed, "speech": spoken,
                "speech_note": note}, f"Heard \"{heard['text'][:120]}\": {routed['reply']}"


class _Wake(BaseModel):
    audio_base64: Optional[str] = None
    file: Optional[str] = None
    filename: Optional[str] = None
    sample_format: str = Field("wav", description="wav (PCM, any rate, mono or stereo) or f32le (raw float32, 16 kHz)")


class WakeWordDetectTool(_VoiceTool):
    _name = "wake_word_detect"
    _description = "Check a recording for the wake phrase \"JARV, talk to me.\" with the local keyword spotter."
    _input = _Wake
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        if data["sample_format"] not in ("wav", "f32le"):
            raise ValueError("sample_format is wav or f32le")
        audio, _name = await _audio(db, context, {**data, "language": "en"})
        result = await _unavailable(engine.detect_wake(audio, sample_format=data["sample_format"]))
        text = (f"Wake phrase heard at {result['at_seconds']}s" if result["detected"]
                else f"No wake phrase in {result['seconds_scanned']}s of audio")
        return result, text


VOICE_TOOLS = [TranscribeVoiceTool, SpeakResponseTool, ListenPushToTalkTool, WakeWordDetectTool,
               RouteVoiceCommandTool]
