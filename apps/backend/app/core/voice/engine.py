"""
JARV Backend - Voice engine (Repair 12e-4c)

Speech in, speech out, the wake phrase, and voice commands, on real backends:

- Speech-to-text: the self-hosted Voicebox service (local, free) when
  VOICEBOX_BASE_URL is set, otherwise OpenAI transcription when OPENAI_API_KEY
  is set. STT_PROVIDER picks one explicitly (auto, voicebox, openai).
- Text-to-speech: Voicebox with the JARV voice profile, ElevenLabs
  (ELEVENLABS_API_KEY) or OpenAI speech. TTS_PROVIDER picks one (auto,
  voicebox, elevenlabs, openai). Audio is written to VOICE_AUDIO_DIR with its
  owner and served only to that owner.
- Wake phrase: the local sherpa-onnx keyword spotter ("JARV, talk to me.")
  run over a recorded clip; the live browser stream uses the same model.
- Commands: a spoken command becomes a mission through the Command Center
  pipeline, so the same deterministic safety gate applies; status questions
  are answered from the mission records; approvals are never given by voice,
  because anyone near a microphone can speak.

With no backend configured each step fails with the setting to add.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
import time
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

OPENAI_API = "https://api.openai.com/v1"
ELEVENLABS_API = "https://api.elevenlabs.io/v1"
PROFILE_KEY = "voice:jarv-profile-id"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac", ".webm", ".opus", ".mp4", ".mpeg", ".mpga"}
_CONTENT_TYPES = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "opus": "audio/ogg",
                  "flac": "audio/flac", "aac": "audio/aac"}


class VoiceUnavailable(RuntimeError):
    """No backend is configured for this step; the message names what to set."""


def http_client(**kwargs) -> httpx.AsyncClient:
    """Indirection for every outgoing voice request (tests replace the transport)."""
    return httpx.AsyncClient(**kwargs)


def _timeout() -> httpx.Timeout:
    read = float(getattr(settings, "VOICEBOX_READ_TIMEOUT_SECONDS", 180.0) or 180.0)
    return httpx.Timeout(connect=float(getattr(settings, "VOICEBOX_CONNECT_TIMEOUT_SECONDS", 3.0) or 3.0),
                         read=read, write=read, pool=10.0)


def max_audio_bytes() -> int:
    return int(getattr(settings, "VOICEBOX_MAX_AUDIO_BYTES", 25 * 1024 * 1024) or 25 * 1024 * 1024)


# ----- backend selection ------------------------------------------------------------------------

def _choice(name: str) -> str:
    value = str(getattr(settings, name, "") or "auto").strip().lower()
    return {"whisper": "openai", "openai_whisper": "openai", "": "auto"}.get(value, value)


def stt_backend() -> Optional[str]:
    voicebox, openai = bool(settings.VOICEBOX_BASE_URL), bool(settings.OPENAI_API_KEY)
    choice = _choice("STT_PROVIDER")
    if choice == "voicebox":
        return "voicebox" if voicebox else None
    if choice == "openai":
        return "openai" if openai else None
    return "voicebox" if voicebox else ("openai" if openai else None)


def tts_backend() -> Optional[str]:
    available = {"voicebox": bool(settings.VOICEBOX_BASE_URL),
                 "elevenlabs": bool(getattr(settings, "ELEVENLABS_API_KEY", None)),
                 "openai": bool(settings.OPENAI_API_KEY)}
    choice = _choice("TTS_PROVIDER")
    if choice in available:
        return choice if available[choice] else None
    return next((name for name in ("voicebox", "elevenlabs", "openai") if available[name]), None)


def _stt_missing() -> str:
    choice = _choice("STT_PROVIDER")
    if choice == "voicebox":
        return "Speech-to-text is set to Voicebox but VOICEBOX_BASE_URL is not set."
    if choice == "openai":
        return "Speech-to-text is set to OpenAI but OPENAI_API_KEY is not set."
    return ("No speech-to-text backend: set VOICEBOX_BASE_URL (the self-hosted Voicebox service) "
            "or OPENAI_API_KEY.")


def _tts_missing() -> str:
    choice = _choice("TTS_PROVIDER")
    named = {"voicebox": "VOICEBOX_BASE_URL", "elevenlabs": "ELEVENLABS_API_KEY", "openai": "OPENAI_API_KEY"}
    if choice in named:
        return f"Text-to-speech is set to {choice} but {named[choice]} is not set."
    return ("No text-to-speech backend: set VOICEBOX_BASE_URL (self-hosted), ELEVENLABS_API_KEY "
            "or OPENAI_API_KEY.")


def status() -> Dict[str, Any]:
    from app.core.voice import wake_service

    stt, tts = stt_backend(), tts_backend()
    wake = wake_service.model_is_ready()
    return {
        "speech_to_text": {"backend": stt, "ready": stt is not None, "setting": _choice("STT_PROVIDER"),
                           "setup": None if stt else _stt_missing()},
        "text_to_speech": {"backend": tts, "ready": tts is not None, "setting": _choice("TTS_PROVIDER"),
                           "setup": None if tts else _tts_missing()},
        "wake_word": {"ready": wake, "phrase": wake_service.WAKE_PHRASE_DISPLAY, "runtime": "local CPU",
                      "setup": None if wake else "An admin installs the local model: POST /api/voicebox/wake/model/install"},
        "commands": {"ready": True, "route": "Command Center missions with the approval gate"},
    }


# ----- speech to text ---------------------------------------------------------------------------

def check_audio(audio: bytes, filename: Optional[str]) -> None:
    if not audio:
        raise ValueError("The audio is empty")
    if len(audio) > max_audio_bytes():
        raise ValueError(f"The audio is larger than {max_audio_bytes()} bytes")
    suffix = Path(filename or "speech.wav").suffix.lower()
    if suffix and suffix not in AUDIO_EXTENSIONS:
        raise ValueError(f"'{suffix}' is not a supported audio format ({', '.join(sorted(AUDIO_EXTENSIONS))})")


def _error(response: httpx.Response, what: str) -> RuntimeError:
    detail = ""
    try:
        body = response.json()
        detail = body.get("detail") or body.get("error") or ""
        if isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail)[:200]
    except (ValueError, AttributeError):
        detail = response.text[:200]
    return RuntimeError(f"{what} failed ({response.status_code}){': ' + str(detail)[:300] if detail else ''}")


async def transcribe(audio: bytes, *, filename: str = "speech.wav", language: str = "en",
                     content_type: Optional[str] = None) -> Dict[str, Any]:
    check_audio(audio, filename)
    backend = stt_backend()
    if backend is None:
        raise VoiceUnavailable(_stt_missing())
    lang = (language or "en").split("-")[0].lower()
    mime = content_type or "audio/wav"
    started = time.monotonic()
    async with http_client(timeout=_timeout()) as client:
        if backend == "voicebox":
            response = await client.post(f"{settings.VOICEBOX_BASE_URL.rstrip('/')}/transcribe", data={"language": lang},
                                         files={"file": (filename, audio, mime)})
        else:
            response = await client.post(f"{OPENAI_API}/audio/transcriptions",
                                         headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                                         data={"model": getattr(settings, "OPENAI_STT_MODEL", "whisper-1"),
                                               "language": lang, "response_format": "json"},
                                         files={"file": (filename, audio, mime)})
    if response.status_code >= 400:
        raise _error(response, f"Transcription ({backend})")
    payload = response.json()
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("No speech was recognised in the audio")
    return {"text": text.strip(), "backend": backend, "language": lang, "duration": payload.get("duration"),
            "seconds": round(time.monotonic() - started, 3)}


# ----- text to speech ---------------------------------------------------------------------------

def audio_dir() -> Path:
    path = Path(getattr(settings, "VOICE_AUDIO_DIR", "/data/voice-audio")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prune(directory: Path) -> None:
    hours = float(getattr(settings, "VOICE_AUDIO_RETENTION_HOURS", 24) or 24)
    cutoff = time.time() - hours * 3600
    for path in directory.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


async def _voicebox_profile() -> Optional[str]:
    if settings.VOICEBOX_PROFILE_ID:
        return settings.VOICEBOX_PROFILE_ID
    try:
        from app.core.redis import get_redis

        redis = await get_redis()
        value = await asyncio.wait_for(redis.get(PROFILE_KEY), timeout=2)
        return value.decode() if isinstance(value, bytes) else value
    except Exception:  # noqa: BLE001 - no Redis means no stored profile
        return None


async def _voicebox_speech(client: httpx.AsyncClient, text: str, language: str) -> tuple[bytes, str]:
    profile = await _voicebox_profile()
    if not profile:
        raise VoiceUnavailable("Voicebox needs the JARV voice profile: an admin runs POST /api/voicebox/profile/provision "
                               "(or set VOICEBOX_PROFILE_ID).")
    base = settings.VOICEBOX_BASE_URL.rstrip("/")
    response = await client.post(f"{base}/generate", json={"profile_id": profile, "text": text, "language": language})
    if response.status_code >= 400:
        raise _error(response, "Speech generation (voicebox)")
    generation = response.json().get("id")
    if not isinstance(generation, str) or not generation:
        raise RuntimeError("Voicebox did not return a generation id")
    deadline = time.monotonic() + float(getattr(settings, "VOICEBOX_READ_TIMEOUT_SECONDS", 180.0) or 180.0)
    delay = 0.25
    while True:
        audio = await client.get(f"{base}/audio/{generation}")
        if audio.status_code == 200 and audio.content:
            kind = audio.headers.get("content-type", "audio/wav").split(";")[0]
            return audio.content, ("mp3" if "mpeg" in kind else kind.split("/")[-1] or "wav")
        if audio.status_code not in (202, 404, 409, 425):
            raise _error(audio, "Speech audio (voicebox)")
        if time.monotonic() > deadline:
            raise RuntimeError("Voicebox did not finish the speech in time")
        await asyncio.sleep(delay)
        delay = min(delay * 2, 2.0)


async def speak(text: str, *, owner: Optional[UUID] = None, language: str = "en",
                voice: Optional[str] = None) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing to say")
    if len(text) > 4000:
        raise ValueError("Speech is limited to 4000 characters per reply")
    backend = tts_backend()
    if backend is None:
        raise VoiceUnavailable(_tts_missing())
    lang = (language or "en").split("-")[0].lower()
    started = time.monotonic()
    async with http_client(timeout=_timeout()) as client:
        if backend == "voicebox":
            audio, fmt = await _voicebox_speech(client, text, lang)
        elif backend == "elevenlabs":
            voice_id = voice or getattr(settings, "ELEVENLABS_VOICE_ID", None)
            if not voice_id:
                raise VoiceUnavailable("ElevenLabs needs a voice: set ELEVENLABS_VOICE_ID")
            response = await client.post(f"{ELEVENLABS_API}/text-to-speech/{voice_id}",
                                         params={"output_format": "mp3_44100_128"},
                                         headers={"xi-api-key": settings.ELEVENLABS_API_KEY, "accept": "audio/mpeg"},
                                         json={"text": text, "model_id": getattr(settings, "ELEVENLABS_MODEL_ID",
                                                                                 "eleven_multilingual_v2")})
            if response.status_code >= 400:
                raise _error(response, "Speech generation (elevenlabs)")
            audio, fmt = response.content, "mp3"
        else:
            response = await client.post(f"{OPENAI_API}/audio/speech",
                                         headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                                         json={"model": getattr(settings, "OPENAI_TTS_MODEL", "tts-1"),
                                               "voice": voice or getattr(settings, "OPENAI_TTS_VOICE", "onyx"),
                                               "input": text, "response_format": "mp3"})
            if response.status_code >= 400:
                raise _error(response, "Speech generation (openai)")
            audio, fmt = response.content, "mp3"
    if not audio:
        raise RuntimeError(f"{backend} returned no audio")
    directory = audio_dir()
    _prune(directory)
    audio_id = uuid4().hex
    fmt = fmt if fmt in _CONTENT_TYPES else "wav"
    (directory / f"{audio_id}.{fmt}").write_bytes(audio)
    (directory / f"{audio_id}.json").write_text(json.dumps({
        "owner": str(owner) if owner else None, "format": fmt, "backend": backend, "chars": len(text),
        "created_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    return {"audio_id": audio_id, "url": f"/api/voice/audio/{audio_id}", "format": fmt, "bytes": len(audio),
            "backend": backend, "text": text, "seconds": round(time.monotonic() - started, 3)}


def audio_file(audio_id: str, owner: Optional[UUID]) -> tuple[Path, str]:
    """The stored speech for its owner (LookupError otherwise)."""
    if not re.fullmatch(r"[0-9a-f]{32}", audio_id or ""):
        raise LookupError("Audio not found")
    directory = audio_dir()
    meta_path = directory / f"{audio_id}.json"
    if not meta_path.is_file():
        raise LookupError("Audio not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("owner") and owner is not None and meta["owner"] != str(owner):
        raise LookupError("Audio not found")
    path = directory / f"{audio_id}.{meta.get('format', 'wav')}"
    if not path.is_file():
        raise LookupError("Audio not found")
    return path, _CONTENT_TYPES.get(meta.get("format"), "audio/wav")


# ----- wake phrase ------------------------------------------------------------------------------

def _samples(audio: bytes, sample_format: str):
    """16 kHz mono float32 samples from a WAV file or raw little-endian float32 at 16 kHz."""
    import numpy as np

    if sample_format == "f32le":
        if len(audio) % 4:
            raise ValueError("Raw float32 audio must be a whole number of 4-byte samples")
        samples = np.frombuffer(audio, dtype="<f4").astype("float32")
        rate = 16000
    else:
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
                frames = wav.readframes(wav.getnframes())
        except (wave.Error, EOFError) as exc:
            raise ValueError(f"Wake detection needs a PCM WAV clip (or raw f32le at 16 kHz): {exc}") from None
        if width == 2:
            data = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
        elif width == 4:
            data = np.frombuffer(frames, dtype="<i4").astype("float32") / 2147483648.0
        elif width == 1:
            data = (np.frombuffer(frames, dtype="u1").astype("float32") - 128.0) / 128.0
        else:
            raise ValueError(f"Unsupported WAV sample width: {width} bytes")
        if channels > 1:
            data = data[: len(data) - len(data) % channels].reshape(-1, channels).mean(axis=1)
        samples = data
    if rate != 16000 and len(samples):
        target = int(round(len(samples) * 16000 / rate))
        samples = np.interp(np.linspace(0, len(samples) - 1, target), np.arange(len(samples)), samples).astype("float32")
    if len(samples) > 16000 * 120:
        raise ValueError("Wake detection takes clips up to 2 minutes")
    if not np.isfinite(samples).all():
        raise ValueError("The audio contains invalid samples")
    return np.clip(samples, -1.0, 1.0).astype("<f4")


async def detect_wake(audio: bytes, *, sample_format: str = "wav") -> Dict[str, Any]:
    import numpy as np

    from app.core.voice import wake_service

    if not audio:
        raise ValueError("The audio is empty")
    if not wake_service.model_is_ready():
        raise VoiceUnavailable("The wake-word model is not installed: an admin runs POST /api/voicebox/wake/model/install")
    samples = _samples(audio, sample_format)
    samples = np.concatenate([samples, np.zeros(8000, dtype="<f4")])  # trailing silence flushes the decoder

    def scan() -> Dict[str, Any]:
        stream = wake_service.create_stream()
        try:
            chunk = 3200  # 0.2 s
            for start in range(0, len(samples), chunk):
                keyword = wake_service.process_audio_frame(stream, samples[start:start + chunk].tobytes())
                if keyword:
                    return {"detected": True, "keyword": keyword, "at_seconds": round(start / 16000, 2)}
            return {"detected": False, "keyword": None, "at_seconds": None}
        finally:
            wake_service.free_stream(stream)

    result = await asyncio.to_thread(scan)
    return {**result, "phrase": wake_service.WAKE_PHRASE_DISPLAY, "seconds_scanned": round((len(samples) - 8000) / 16000, 2)}


# ----- commands ---------------------------------------------------------------------------------

_APPROVE = re.compile(r"^\s*(please\s+)?(approve|authori[sz]e|grant|confirm|sign off|go ahead with|accept)\b", re.I)
_STATUS = re.compile(r"\b(status|what('?s| is) (going on|happening)|what are you (working on|doing)|"
                     r"any(thing)? (need|waiting)|update me|progress|how('?s| is) (it|everything) going)\b", re.I)
_CANCEL = re.compile(r"^\s*(please\s+)?(cancel|stop|abort)\s+(the\s+)?(last|current|latest)\s+(mission|task|job)\b",
                     re.I)


async def _owned_workspaces(db: AsyncSession, user_id: UUID):
    from app.models.workspace import Workspace

    return select(Workspace.id).where(Workspace.owner_id == user_id)


async def _status_reply(db: AsyncSession, user_id: UUID, workspace_id: Optional[UUID]) -> Dict[str, Any]:
    from app.core.runtime import lifecycle
    from app.models.company_operations import LiveOperationsFeedItem
    from app.models.task import Task

    scope = [workspace_id] if workspace_id else await _owned_workspaces(db, user_id)
    rows = (await db.execute(select(Task.status, func.count()).where(Task.workspace_id.in_(scope))
                             .group_by(Task.status))).all()
    counts = {lifecycle.normalise(s): int(n) for s, n in rows}
    in_flight = sum(n for s, n in counts.items() if s in lifecycle.IN_FLIGHT)
    waiting = counts.get(lifecycle.BLOCKED, 0) + counts.get(lifecycle.WAITING_ON_APPROVAL, 0)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    failed = (await db.execute(select(func.count()).select_from(Task).where(
        Task.workspace_id.in_(scope), Task.status == lifecycle.FAILED, Task.updated_at >= since))).scalar_one()
    latest = (await db.execute(select(LiveOperationsFeedItem).where(LiveOperationsFeedItem.workspace_id.in_(scope))
                               .order_by(LiveOperationsFeedItem.created_at.desc()).limit(1))).scalar_one_or_none()
    running = (await db.execute(select(Task.title).where(Task.workspace_id.in_(scope),
                                                         Task.status == lifecycle.RUNNING)
                                .order_by(Task.updated_at.desc()).limit(3))).scalars().all()
    parts = []
    if in_flight:
        parts.append(f"{in_flight} mission{'s' if in_flight != 1 else ''} in progress"
                     + (f", including {running[0][:80]}" if running else ""))
    else:
        parts.append("nothing is running right now")
    parts.append(f"{waiting} waiting for your approval" if waiting else "nothing needs your approval")
    if failed:
        parts.append(f"{failed} failed in the last day")
    reply = "Status: " + "; ".join(parts) + "."
    if latest is not None:
        reply += f" Latest: {latest.title}."
    return {"intent": "status", "reply": reply, "in_flight": in_flight, "awaiting_approval": int(waiting),
            "failed_24h": int(failed), "running": list(running)}


async def route(db: AsyncSession, text: str, *, user_id: UUID, workspace_id: Optional[UUID] = None) -> Dict[str, Any]:
    """Answer or act on a spoken command."""
    from app.core.command import CommandService
    from app.core.runtime import lifecycle
    from app.models.task import Task

    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        raise ValueError("The command is empty")
    if len(text) > 2000:
        raise ValueError("Spoken commands are limited to 2000 characters")
    if _APPROVE.search(text):
        return {"intent": "approval_refused", "reply": (
            "I can't take approvals by voice, because anyone near the microphone could give one. "
            "Approve it on the Approvals page and I'll carry on from where I paused."), "task_id": None}
    if _CANCEL.search(text):
        from app.core.runtime.missions import cancel_mission

        scope = [workspace_id] if workspace_id else await _owned_workspaces(db, user_id)
        task = (await db.execute(select(Task).where(Task.workspace_id.in_(scope),
                                                    Task.status.in_(list(lifecycle.IN_FLIGHT | {lifecycle.BLOCKED})))
                                 .order_by(Task.created_at.desc()).limit(1))).scalar_one_or_none()
        if task is None:
            return {"intent": "cancel", "reply": "There is no mission in progress to cancel.", "task_id": None}
        cancelled = await cancel_mission(db, task, actor=str(user_id), reason="Cancelled by voice command")
        await db.flush()
        title = (task.title or "the mission")[:80]
        return {"intent": "cancel", "task_id": str(task.id), "cancelled": cancelled,
                "reply": f"Cancelled: {title}." if cancelled else f"{title} has already finished."}
    if _STATUS.search(text) and len(text.split()) <= 14:
        return await _status_reply(db, user_id, workspace_id)
    service = CommandService()
    submitted = await service.submit(f"{text}", db, workspace_id=workspace_id, user_id=user_id, operator=str(user_id))
    task = (await db.execute(select(Task).where(Task.id == UUID(submitted.task_id)))).scalar_one()
    task.meta_data = {**(task.meta_data or {}), "channel": "voice"}
    await db.commit()
    dispatch = None
    if submitted.status == lifecycle.QUEUED:
        from app.core.runtime.dispatcher import dispatch_mission

        dispatch = (await dispatch_mission(submitted.task_id, reason="voice command")).get("mode")
        reply = "On it. I've started that as a mission and I'll report back when it's done."
    elif submitted.requires_approval:
        reply = (f"That needs your approval first: {submitted.approval_reason} "
                 "I've paused it; approve it on the Approvals page to continue.")
    else:
        reply = submitted.response_text
    return {"intent": "mission", "task_id": submitted.task_id, "status": submitted.status,
            "requires_approval": submitted.requires_approval, "dispatch_mode": dispatch, "reply": reply}
