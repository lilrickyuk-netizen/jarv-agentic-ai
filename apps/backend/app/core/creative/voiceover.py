"""
JAI Backend - Voiceovers (Wave 4c)

Narration in JAI's natural voice: Chatterbox Turbo (open source, MIT) on Richard's GPU, in the voice of a reference
clip (George, British, made with Kokoro, Apache-2.0). Text is spoken a sentence at a time and joined with short
pauses into one 24 kHz WAV. Free: it runs on his own card.
"""
from __future__ import annotations

import io
import re
import wave
from typing import Optional

import httpx

RATE = 24000
PAUSE_SECONDS = 0.28


class VoiceoverUnavailable(RuntimeError):
    """JAI's natural voice is not running or could not speak this."""


def chatterbox_url() -> str:
    from app.core.config import settings

    return str(getattr(settings, "CHATTERBOX_URL", "") or "").rstrip("/")


def sentences(text: str):
    """Sentences of at most about 300 characters (Chatterbox speaks one at a time)."""
    parts = re.split(r"(?<=[.!?])\s+", " ".join((text or "").split()))
    for part in parts:
        while len(part) > 300:
            comma = part.rfind(",", 0, 300)
            cut = comma + 1 if comma > 80 else 300  # after a comma when there is one, otherwise at 300
            yield part[:cut].strip()
            part = part[cut:].strip()
        if part:
            yield part


def to_wav(pcm: bytes, rate: int = RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(pcm)
    return buffer.getvalue()


async def speak(text: str, voice: Optional[str] = None, client: Optional[httpx.AsyncClient] = None) -> dict:
    """The whole text in JAI's voice: WAV bytes and their length in seconds."""
    from app.core.config import settings

    base = chatterbox_url()
    if not base:
        raise VoiceoverUnavailable("JAI's natural voice (Chatterbox) is turned off on this computer.")
    lines = list(sentences(text))
    if not lines:
        raise VoiceoverUnavailable("There is nothing to say.")
    voice = voice or settings.VOICE_PIPELINE_CHATTERBOX_VOICE
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))
    pause = b"\x00\x00" * int(RATE * PAUSE_SECONDS)
    pcm = bytearray()
    try:
        for line in lines:
            try:
                spoken = await client.post(f"{base}/speak", json={"text": line, "voice": voice})
            except httpx.HTTPError as exc:
                raise VoiceoverUnavailable(f"JAI's natural voice could not be reached ({type(exc).__name__}).") from exc
            if spoken.status_code != 200:
                raise VoiceoverUnavailable(f"JAI's natural voice answered {spoken.status_code}: {spoken.text[:200]}")
            pcm.extend(spoken.content)
            pcm.extend(pause)
    finally:
        if own:
            await client.aclose()
    return {"wav": to_wav(bytes(pcm)), "seconds": round(len(pcm) / 2 / RATE, 1), "sentences": len(lines),
            "voice": voice}
