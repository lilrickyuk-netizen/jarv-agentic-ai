"""
JARV Backend - Voice Command API (Repair 12e-4c)

Authenticated voice endpoints on the voice engine:
- POST /api/voice/push-to-talk: recording in; transcript, the action taken
  (status answer, cancellation, or a Command Center mission under the approval
  gate) and the spoken reply out.
- POST /api/voice/transcribe: speech to text only, with the wake phrase found.
- POST /api/voice/command/text: the same for a typed command.
- POST /api/voice/speak: speech for a reply; GET /api/voice/audio/{id} serves
  it to its owner.
- POST /api/voice/wake/detect: the wake phrase in a recorded clip.
- POST /api/voice/status/speak: a short spoken status phrase.
- GET /api/voice/providers and /api/voice/health: which backends are ready
  and what to set for the others.
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId, get_current_user_id
from app.core.database import get_db
from app.core.voice import SpokenStatusReplies, StatusType, engine
from app.models.workspace import Workspace

router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(get_current_user_id)])


class VoiceCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=2000)
    workspace_id: Optional[UUID] = None
    language: str = "en"
    speak: bool = True


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    language: str = "en"
    voice: Optional[str] = None


class VoiceStatusRequest(BaseModel):
    status_type: str
    details: Optional[str] = None


async def _scope(db: AsyncSession, user_id: str, workspace_id: Optional[UUID]) -> Optional[UUID]:
    if workspace_id is None:
        return None
    found = (await db.execute(select(Workspace.id).where(Workspace.id == workspace_id,
                                                         Workspace.owner_id == UUID(str(user_id))))).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return found


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, engine.VoiceUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


async def _reply(db: AsyncSession, user_id: str, text: str, workspace_id: Optional[UUID], language: str,
                 speak: bool) -> Dict[str, Any]:
    try:
        routed = await engine.route(db, text, user_id=UUID(str(user_id)), workspace_id=workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    speech, note = None, None
    if speak:
        try:
            speech = await engine.speak(routed["reply"], owner=UUID(str(user_id)), language=language)
        except (engine.VoiceUnavailable, RuntimeError, ValueError) as exc:
            note = f"Reply not spoken: {exc}"
    return {**routed, "speech": speech, "speech_note": note}


@router.post("/push-to-talk")
async def push_to_talk(user_id: CurrentUserId, audio: UploadFile = File(...), language: str = Form("en"),
                       workspace_id: Optional[UUID] = Form(None), speak: bool = Form(True),
                       db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    scope = await _scope(db, user_id, workspace_id)
    data = await audio.read(engine.max_audio_bytes() + 1)
    try:
        heard = await engine.transcribe(data, filename=audio.filename or "speech.wav", language=language,
                                        content_type=audio.content_type)
    except (engine.VoiceUnavailable, RuntimeError, ValueError) as exc:
        raise _http(exc)
    return {"heard": heard["text"], "stt_backend": heard["backend"],
            **await _reply(db, user_id, heard["text"], scope, language, speak)}


@router.post("/transcribe")
async def transcribe(user_id: CurrentUserId, audio: UploadFile = File(...),
                     language: str = Form("en")) -> Dict[str, Any]:
    """Speech to text only (the dashboard's local wake-phrase check); nothing is acted on or stored."""
    data = await audio.read(engine.max_audio_bytes() + 1)
    try:
        heard = await engine.transcribe(data, filename=audio.filename or "speech.wav", language=language,
                                        content_type=audio.content_type)
    except (engine.VoiceUnavailable, RuntimeError, ValueError) as exc:
        raise _http(exc)
    return {"text": heard["text"], "backend": heard["backend"],
            "command": engine.strip_wake(heard["text"])[0], "wake_heard": engine.strip_wake(heard["text"])[1]}


@router.post("/command/text")
async def text_command(request: VoiceCommandRequest, user_id: CurrentUserId,
                       db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    scope = await _scope(db, user_id, request.workspace_id)
    return {"heard": request.command, **await _reply(db, user_id, request.command, scope, request.language,
                                                      request.speak)}


@router.post("/speak")
async def speak(request: SpeakRequest, user_id: CurrentUserId) -> Dict[str, Any]:
    try:
        return await engine.speak(request.text, owner=UUID(str(user_id)), language=request.language,
                                  voice=request.voice)
    except (engine.VoiceUnavailable, RuntimeError, ValueError) as exc:
        raise _http(exc)


@router.get("/audio/{audio_id}")
async def audio(audio_id: str, user_id: CurrentUserId):
    try:
        path, media = engine.audio_file(audio_id, UUID(str(user_id)))
    except LookupError:
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(path, media_type=media, headers={"Cache-Control": "no-store"})


@router.post("/wake/detect")
async def wake_detect(user_id: CurrentUserId, audio: UploadFile = File(...),
                      sample_format: str = Form("wav")) -> Dict[str, Any]:
    if sample_format not in ("wav", "f32le"):
        raise HTTPException(status_code=400, detail="sample_format is wav or f32le")
    data = await audio.read(engine.max_audio_bytes() + 1)
    if len(data) > engine.max_audio_bytes():
        raise HTTPException(status_code=413, detail="The audio is too large")
    try:
        return await engine.detect_wake(data, sample_format=sample_format)
    except (engine.VoiceUnavailable, RuntimeError, ValueError) as exc:
        raise _http(exc)


@router.post("/status/speak")
async def speak_status(request: VoiceStatusRequest) -> Dict[str, Any]:
    try:
        status_type = StatusType(request.status_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status type: {request.status_type}. "
                                                    f"Valid types: {[s.value for s in StatusType]}")
    text = SpokenStatusReplies(language="en-US").get_status_reply(status_type=status_type, details=request.details)
    return {"status_text": text, "status_type": request.status_type}


@router.get("/providers")
async def providers() -> Dict[str, Any]:
    return {**engine.status(),
            "options": {"speech_to_text": ["voicebox (self-hosted, VOICEBOX_BASE_URL)", "openai (OPENAI_API_KEY)"],
                        "text_to_speech": ["voicebox (self-hosted, JARV voice profile)",
                                           "elevenlabs (ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID)",
                                           "openai (OPENAI_API_KEY)"]}}


@router.get("/health")
async def voice_health() -> Dict[str, Any]:
    state = engine.status()
    ready = {name: part["ready"] for name, part in state.items()}
    return {"status": "operational" if ready["speech_to_text"] and ready["text_to_speech"] else "degraded",
            "components": ready, "setup": [part["setup"] for part in state.values() if part.get("setup")]}
