"""
Upgrade 7: Fish Audio as a selectable British voice. Real: the voice choice, the brief the Pipecat voice gets (never
the key), and the Fish request JAI sends, answered by an httpx MockTransport, so no credit is spent.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from app.core.config import settings
from app.core.voice import engine, live


def test_the_conversation_speaks_with_fish_only_when_it_has_a_key(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_PIPELINE_TTS", "fish")
    monkeypatch.setattr(settings, "FISH_API_KEY", None)
    assert live.pipeline_voice() == ("kokoro", settings.VOICE_PIPELINE_KOKORO_VOICE)
    monkeypatch.setattr(settings, "FISH_API_KEY", "fish-test-key")
    assert live.pipeline_voice() == ("fish", "612b878b113047d9a770c069c8b4fdfe")
    monkeypatch.setattr(settings, "VOICE_PIPELINE_TTS", "chatterbox")
    assert live.pipeline_voice()[0] == "chatterbox"  # the previous voice stays the default


def test_spoken_replies_can_use_fish_and_fall_back_when_it_is_not_set(monkeypatch):
    monkeypatch.setattr(settings, "VOICEBOX_BASE_URL", None)
    monkeypatch.setattr(settings, "TTS_PROVIDER", "fish")
    monkeypatch.setattr(settings, "FISH_API_KEY", None)
    assert engine.tts_backend() is None and "FISH_API_KEY" in engine._tts_missing()
    monkeypatch.setattr(settings, "FISH_API_KEY", "fish-test-key")
    assert engine.tts_backend() == "fish"
    monkeypatch.setattr(settings, "TTS_PROVIDER", "auto")
    monkeypatch.setattr(settings, "FISH_API_KEY", None)
    assert engine.tts_backend() in (None, "elevenlabs", "openai")


def test_the_fish_request_carries_the_voice_and_model_and_the_key_stays_on_the_backend(monkeypatch):
    monkeypatch.setattr(settings, "FISH_API_KEY", "fish-test-key")
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ID3fake-mp3")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
            return await engine.fish_speech(client, "Good morning, boss.")

    audio, fmt = asyncio.run(run())
    body = json.loads(seen[0].content)
    assert (audio, fmt) == (b"ID3fake-mp3", "mp3")
    assert str(seen[0].url) == "https://api.fish.audio/v1/tts"
    assert seen[0].headers["authorization"] == "Bearer fish-test-key" and seen[0].headers["model"] == "s2.1-pro"
    assert body["reference_id"] == "612b878b113047d9a770c069c8b4fdfe" and body["text"] == "Good morning, boss."
