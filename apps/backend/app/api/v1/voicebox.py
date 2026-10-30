"""Authenticated adapter for the local Voicebox HTTP API."""

import asyncio
import json
import hashlib
import secrets
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.core.auth import CurrentAdminUserId, CurrentUserId
from app.core.config import settings
from app.core.redis import get_redis
from app.core.voice import wake_service

router = APIRouter(prefix="/voicebox", tags=["voicebox"])
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm", ".opus"}
PROFILE_KEY = "voice:jarv-profile-id"
PROFILE_LOCK_KEY = "voice:jarv-profile-provision-lock"


class SpeechRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    language: str = Field(default="en", min_length=2, max_length=12)


def _voicebox_url(path: str = "") -> str:
    base_url = (settings.VOICEBOX_BASE_URL or "").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="Voicebox is not configured")
    return f"{base_url}/{path.lstrip('/')}" if path else base_url


def _http_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.VOICEBOX_CONNECT_TIMEOUT_SECONDS,
        read=settings.VOICEBOX_READ_TIMEOUT_SECONDS,
        write=settings.VOICEBOX_READ_TIMEOUT_SECONDS,
        pool=settings.VOICEBOX_CONNECT_TIMEOUT_SECONDS,
    )


def _upstream_error(response: httpx.Response) -> HTTPException:
    message = "Voicebox request failed"
    try:
        body = response.json()
        message = body.get("detail") or body.get("error") or message
    except (ValueError, AttributeError):
        pass
    return HTTPException(status_code=502, detail=str(message)[:500])


def _validated_generation_id(generation_id: str) -> str:
    try:
        return str(UUID(generation_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid generation id") from exc


@router.get("/status")
async def configured_voicebox_status(
    _operator: CurrentUserId,
    redis: Redis = Depends(get_redis),
):
    if not settings.VOICEBOX_BASE_URL:
        return {
            "configured": False,
            "connected": False,
            "profile_configured": False,
            "wake_word": wake_service.WAKE_PHRASE_DISPLAY,
        }
    profile_id = settings.VOICEBOX_PROFILE_ID or await redis.get(PROFILE_KEY)
    try:
        async with httpx.AsyncClient(timeout=_http_timeout()) as client:
            response = await client.get(_voicebox_url("health"))
        response.raise_for_status()
        return {
            "configured": True,
            "connected": True,
            "profile_configured": bool(profile_id),
            "voicebox": response.json(),
            "wake_word": wake_service.WAKE_PHRASE_DISPLAY,
        }
    except httpx.HTTPStatusError as exc:
        return {
            "configured": True,
            "connected": False,
            "profile_configured": bool(profile_id),
            "error": f"Voicebox health check failed ({exc.response.status_code})",
            "wake_word": wake_service.WAKE_PHRASE_DISPLAY,
        }
    except httpx.HTTPError as exc:
        return {
            "configured": True,
            "connected": False,
            "profile_configured": bool(profile_id),
            "error": "Voicebox is unreachable",
            "wake_word": wake_service.WAKE_PHRASE_DISPLAY,
        }


@router.post("/profile/provision")
async def provision_jarv_voice_profile(
    _operator: CurrentAdminUserId,
    redis: Redis = Depends(get_redis),
):
    if not settings.VOICEBOX_BASE_URL:
        raise HTTPException(status_code=503, detail="Voicebox is not configured")
    profile_id = settings.VOICEBOX_PROFILE_ID or await redis.get(PROFILE_KEY)
    lock_token = secrets.token_urlsafe(18)
    acquired = await redis.set(PROFILE_LOCK_KEY, lock_token, ex=60, nx=True)
    if not acquired:
        raise HTTPException(status_code=409, detail="Voice profile provisioning is already in progress")
    try:
        profile_id = settings.VOICEBOX_PROFILE_ID or await redis.get(PROFILE_KEY)
        profile = {
            "name": "JARV",
            "description": "JARV's conversational British male voice.",
            "language": "en",
            "voice_type": "preset",
            "preset_engine": "kokoro",
            "preset_voice_id": "bm_george",
            "default_engine": "kokoro",
            "personality": None,
        }
        async with httpx.AsyncClient(timeout=_http_timeout()) as client:
            if not profile_id:
                listed = await client.get(_voicebox_url("profiles"))
                listed.raise_for_status()
                profiles = listed.json()
                if isinstance(profiles, list):
                    existing = next((item for item in profiles if item.get("name") == "JARV"), None)
                    if existing and isinstance(existing.get("id"), str):
                        profile_id = existing["id"]
            if profile_id:
                response = await client.put(_voicebox_url(f"profiles/{profile_id}"), json=profile)
            else:
                response = await client.post(_voicebox_url("profiles"), json=profile)
            response.raise_for_status()
            configured = response.json()
        profile_id = configured.get("id") or profile_id
        if not isinstance(profile_id, str) or not profile_id:
            raise HTTPException(status_code=502, detail="Voicebox did not return a profile id")
        await redis.set(PROFILE_KEY, profile_id)
        return {"configured": True, "profile_id": profile_id, "voice": "Kokoro British male preset (George)"}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise _upstream_error(exc.response) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Voicebox profile creation is unavailable") from exc
    finally:
        if await redis.get(PROFILE_LOCK_KEY) == lock_token:
            await redis.delete(PROFILE_LOCK_KEY)


@router.post("/transcribe")
async def transcribe_audio(
    _operator: CurrentUserId,
    file: UploadFile = File(...),
    language: str = Form(default="en"),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix and suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported audio format")
    audio = await file.read(settings.VOICEBOX_MAX_AUDIO_BYTES + 1)
    if not audio:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    if len(audio) > settings.VOICEBOX_MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio file exceeds the configured size limit")
    try:
        async with httpx.AsyncClient(timeout=_http_timeout()) as client:
            response = await client.post(
                _voicebox_url("transcribe"),
                data={"language": language},
                files={"file": (file.filename or "speech.wav", audio, file.content_type or "audio/wav")},
            )
        response.raise_for_status()
        payload = response.json()
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=502, detail="Voicebox returned an empty transcript")
        return {"text": text.strip(), "duration": payload.get("duration")}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise _upstream_error(exc.response) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Voicebox transcription is unavailable") from exc


@router.post("/speak")
async def generate_speech(
    request: SpeechRequest,
    _operator: CurrentUserId,
    redis: Redis = Depends(get_redis),
):
    profile_id = settings.VOICEBOX_PROFILE_ID or await redis.get(PROFILE_KEY)
    if not profile_id:
        raise HTTPException(status_code=503, detail="Provision a Voicebox speech profile before enabling spoken responses")
    try:
        async with httpx.AsyncClient(timeout=_http_timeout()) as client:
            response = await client.post(
                _voicebox_url("generate"),
                json={"profile_id": profile_id, "text": request.text, "language": request.language},
            )
        response.raise_for_status()
        generation = response.json()
        generation_id = generation.get("id")
        if not isinstance(generation_id, str) or not generation_id:
            raise HTTPException(status_code=502, detail="Voicebox did not return a speech generation id")
        return {"id": generation_id, "status": generation.get("status", "generating")}
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise _upstream_error(exc.response) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Voicebox speech generation is unavailable") from exc


@router.get("/generate/{generation_id}/status")
async def generation_status(generation_id: str, _operator: CurrentUserId):
    generation_id = _validated_generation_id(generation_id)

    async def events() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=_http_timeout()) as client:
                async with client.stream("GET", _voicebox_url(f"generate/{generation_id}/status")) as response:
                    if response.is_error:
                        body = await response.aread()
                        try:
                            detail = json.loads(body).get("detail", "Voicebox status request failed")
                        except (ValueError, AttributeError):
                            detail = "Voicebox status request failed"
                        yield f"event: error\ndata: {json.dumps({'detail': str(detail)[:300]})}\n\n".encode()
                        return
                    async for line in response.aiter_lines():
                        yield f"{line}\n".encode()
        except httpx.HTTPError:
            yield b'event: error\ndata: {"detail":"Voicebox status stream disconnected"}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/generate/{generation_id}/cancel")
async def cancel_generation(generation_id: str, _operator: CurrentUserId):
    generation_id = _validated_generation_id(generation_id)
    try:
        async with httpx.AsyncClient(timeout=_http_timeout()) as client:
            response = await client.post(_voicebox_url(f"generate/{generation_id}/cancel"))
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise _upstream_error(exc.response) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Voicebox cancellation is unavailable") from exc


@router.get("/audio/{generation_id}")
async def generated_audio(generation_id: str, _operator: CurrentUserId):
    generation_id = _validated_generation_id(generation_id)
    try:
        async with httpx.AsyncClient(timeout=_http_timeout()) as client:
            response = await client.get(_voicebox_url(f"audio/{generation_id}"))
        response.raise_for_status()
        return Response(
            content=response.content,
            media_type=response.headers.get("content-type", "audio/wav"),
            headers={"Cache-Control": "no-store"},
        )
    except httpx.HTTPStatusError as exc:
        raise _upstream_error(exc.response) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Voicebox audio is unavailable") from exc


@router.get("/wake/status")
async def wake_status(_operator: CurrentUserId):
    return wake_service.install_status()


@router.post("/wake/model/install")
async def install_wake_model(_operator: CurrentAdminUserId):
    return await wake_service.install_model()


@router.post("/wake/ticket")
async def create_wake_ticket(
    request: Request,
    _operator: CurrentUserId,
    redis: Redis = Depends(get_redis),
):
    if not wake_service.model_is_ready():
        raise HTTPException(status_code=503, detail="Install the local wake-word model before enabling hands-free mode")
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(status_code=403, detail="A browser origin is required for hands-free mode")
    ticket = secrets.token_urlsafe(32)
    ticket_key = f"voice:wake-ticket:{hashlib.sha256(ticket.encode()).hexdigest()}"
    stored = await redis.set(ticket_key, json.dumps({"origin": origin}), ex=30, nx=True)
    if not stored:
        raise HTTPException(status_code=503, detail="Could not create a wake session")
    return {"ticket": ticket, "expires_in": 30, "phrase": wake_service.WAKE_PHRASE_DISPLAY}


@router.websocket("/wake")
async def wake_stream(websocket: WebSocket, redis: Redis = Depends(get_redis)):
    offered_protocols = [value.strip() for value in websocket.headers.get("sec-websocket-protocol", "").split(",")]
    ticket = next((value.removeprefix("ticket.") for value in offered_protocols if value.startswith("ticket.")), None)
    if not ticket or len(ticket) > 100:
        await websocket.close(code=4401, reason="Wake session ticket required")
        return

    ticket_key = f"voice:wake-ticket:{hashlib.sha256(ticket.encode()).hexdigest()}"
    stored = await redis.getdel(ticket_key)
    if not stored:
        await websocket.close(code=4401, reason="Wake session ticket expired")
        return
    try:
        ticket_data = json.loads(stored)
    except (TypeError, ValueError):
        await websocket.close(code=4401, reason="Invalid wake session ticket")
        return
    if websocket.headers.get("origin") != ticket_data.get("origin"):
        await websocket.close(code=4403, reason="Wake session origin mismatch")
        return
    if not wake_service.model_is_ready():
        await websocket.close(code=1013, reason="Wake-word model is not installed")
        return

    await websocket.accept(subprotocol="jarv-wake")
    stream = None
    try:
        stream = await asyncio.to_thread(wake_service.create_stream)
        await websocket.send_json({"type": "ready", "sample_rate": 16000, "phrase": wake_service.WAKE_PHRASE_DISPLAY})
        while True:
            frame = await websocket.receive_bytes()
            keyword = await asyncio.to_thread(wake_service.process_audio_frame, stream, frame)
            if keyword:
                await websocket.send_json({"type": "wake", "keyword": keyword})
    except WebSocketDisconnect:
        pass
    except ValueError as exc:
        await websocket.close(code=1003, reason=str(exc)[:120])
    finally:
        if stream is not None:
            await asyncio.to_thread(wake_service.free_stream, stream)
            stream = None
