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


# How long a voiceover waits for the natural voice when it was switched back on after an image moments ago.
RESTART_WAIT_SECONDS = 120.0


async def _wait_if_starting(client: httpx.AsyncClient, base: str, wait_seconds: float = RESTART_WAIT_SECONDS) -> None:
    """The natural voice is switched off while an image is made and back on after (creative/images.py); a voiceover
    asked for in the moments after waits for it to finish loading instead of failing."""
    import asyncio
    import time

    from app.core.creative import images

    since = await images.voice_back_since()
    if since is None or time.time() - since > wait_seconds:
        return
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        try:
            answer = await client.get(f"{base}/health", timeout=5.0)
            if answer.status_code == 200 and answer.json().get("status") == "ok":  # "loading" while it loads
                return
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(3.0)


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
        await _wait_if_starting(client, base)
        for line in lines:
            try:
                spoken = await client.post(f"{base}/speak", json={"text": line, "voice": voice})
            except httpx.HTTPError as exc:
                raise VoiceoverUnavailable(f"JAI's natural voice could not be reached ({type(exc).__name__}). Switch it on in the Command Center (JAI's services panel).") from exc
            if spoken.status_code != 200:
                raise VoiceoverUnavailable(f"JAI's natural voice answered {spoken.status_code}: {spoken.text[:200]}")
            pcm.extend(spoken.content)
            pcm.extend(pause)
    finally:
        if own:
            await client.aclose()
    return {"wav": to_wav(bytes(pcm)), "seconds": round(len(pcm) / 2 / RATE, 1), "sentences": len(lines),
            "voice": voice}
