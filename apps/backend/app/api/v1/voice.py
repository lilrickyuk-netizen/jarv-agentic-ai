"""
JAI Backend - Voice Command API (Repair 12e-4c)

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
- POST /api/voice/live/session: a short-lived OpenAI Realtime client secret for a
  live spoken conversation with JAI (the API key never reaches the browser).
- POST /api/voice/live/tool: one action JAI takes during that conversation
  (status, mission start, mission state, cancel, workspaces), run as the operator.
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
from app.core.voice import SpokenStatusReplies, StatusType, engine, live
from app.models.workspace import Workspace

router = APIRouter(prefix="/voice", tags=["voice"], dependencies=[Depends(get_current_user_id)])
# Images JAI made, by their short-lived links: an <img> on Richard's screen cannot send his sign-in.
image_router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=2000)
    workspace_id: Optional[UUID] = None
    language: str = "en"
    speak: bool = True


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    language: str = "en"
    voice: Optional[str] = None


class LiveToolRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    arguments: Dict[str, Any] = Field(default_factory=dict)


class LiveTurnRequest(BaseModel):
    who: str = Field(..., pattern="^(you|jarv)$")
    text: str = Field(..., min_length=1, max_length=4000)


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
            "live": {"ready": live.available(), "backend": "openai realtime" if live.available() else None,
                     "setup": live.setup_hint()},
            "options": {"speech_to_text": ["voicebox (self-hosted, VOICEBOX_BASE_URL)", "openai (OPENAI_API_KEY)"],
                        "text_to_speech": ["voicebox (self-hosted, JAI voice profile)",
                                           "elevenlabs (ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID)",
                                           "openai (OPENAI_API_KEY)"]}}


@router.get("/health")
async def voice_health() -> Dict[str, Any]:
    state = engine.status()
    ready = {name: part["ready"] for name, part in state.items()}
    return {"status": "operational" if ready["speech_to_text"] and ready["text_to_speech"] else "degraded",
            "components": ready, "setup": [part["setup"] for part in state.values() if part.get("setup")]}


@router.post("/live/session")
async def live_session(user_id: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        return await live.create_session(db, UUID(str(user_id)))
    except live.LiveUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


class LiveUsageRequest(BaseModel):
    usage: Dict[str, Any] = Field(default_factory=dict)


@router.post("/live/usage")
async def live_usage(request: LiveUsageRequest, user_id: CurrentUserId) -> Dict[str, Any]:
    """The usage of one live voice reply: added to today's AI spend; says whether the conversation must stop."""
    return await live.record_usage(request.usage)


class PipelineSpendRequest(BaseModel):
    kind: str
    model: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    characters: int = 0
    seconds: float = 0


@router.get("/live/engine")
async def live_engine(user_id: CurrentUserId) -> Dict[str, Any]:
    """Which voice Talk with JAI uses (the Pipecat service first, the Realtime voice as its fallback)."""
    return live.engine_choice()


@router.get("/live/brief")
async def live_brief(user_id: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """JAI's instructions, tools, model and voice for one Pipecat conversation (asked by the voice service as
    the signed-in operator)."""
    try:
        return await live.pipeline_brief(db, UUID(str(user_id)))
    except live.LiveUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class LiveContextRequest(BaseModel):
    text: str = Field("", max_length=4000)


@router.post("/live/context")
async def live_context(request: LiveContextRequest, user_id: CurrentUserId,
                       db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """JAI's live state as it bears on what Richard just said, for the brain voice's next reply."""
    return await live.live_context(db, UUID(str(user_id)), request.text)


@router.post("/live/spend")
async def live_spend(request: PipelineSpendRequest, user_id: CurrentUserId) -> Dict[str, Any]:
    """One model, speech-to-text or text-to-speech use by the Pipecat voice: added to today's AI spend; says
    whether the conversation must stop."""
    try:
        return await live.record_pipeline_usage(request.kind, request.model_dump(exclude={"kind"}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@image_router.get("/image/{token}")
async def voice_image(token: str):
    """An image JAI made, by the short-lived link it put on Richard's screen (no sign-in: an image tag cannot send
    one; the random token is the permission, and only files inside the workspaces are served)."""
    from fastapi.responses import FileResponse

    path = await live.image_for(token)
    if path is None:
        raise HTTPException(status_code=404, detail="That image link has expired.")
    return FileResponse(path, media_type=live.media_type(path), headers={"Cache-Control": "private, max-age=3600"})


@router.get("/spend/today")
async def spend_today(user_id: CurrentUserId) -> Dict[str, Any]:
    """Today's AI spend (text models and the live voice), the daily limit and what is left."""
    from app.core import spend

    return await spend.today()


@router.post("/live/turn")
async def live_turn(request: LiveTurnRequest, user_id: CurrentUserId) -> Dict[str, Any]:
    """Keep one spoken turn so the next conversation carries on from this one."""
    return await live.remember_turn(UUID(str(user_id)), request.who, request.text)


@router.get("/live/history")
async def live_history(user_id: CurrentUserId) -> Dict[str, Any]:
    """The recent spoken conversation (oldest first), so the panel shows it after a reload or a page change."""
    return {"turns": await live.recent_turns(UUID(str(user_id)), 12)}


@router.post("/live/tool")
async def live_tool(request: LiveToolRequest, user_id: CurrentUserId,
                    db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        return await live.run_tool(db, UUID(str(user_id)), request.name, request.arguments)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
