"""
JAI's natural voice service: Chatterbox Turbo. POST /speak {"text", "voice"} returns the sentence as raw 16-bit mono
PCM at 24 kHz. A voice is a reference clip in /srv/voices/<name>.wav (over five seconds), prepared once and kept;
without one, Chatterbox's own built-in voice speaks. One sentence is spoken at a time on the GPU (a lock keeps
conversations from competing for it). Health reports the device and the voices.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("jai.chatterbox")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

VOICES = Path(os.environ.get("VOICES_DIR", "/srv/voices"))
SAMPLE_RATE = 24000
_state: Dict[str, object] = {}
_lock = threading.Lock()


def model():
    """Chatterbox Turbo on the GPU when there is one; Chatterbox Nano (built for processors) otherwise."""
    if "model" not in _state:
        import torch
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        if torch.cuda.is_available():
            _state["model"], _state["device"] = ChatterboxTurboTTS.from_pretrained(device="cuda"), "gpu"
        else:
            _state["model"], _state["device"] = ChatterboxTurboTTS.from_pretrained(device="cpu", nano=True), "cpu"
        _state["builtin"] = _state["model"].conds
        _state["voices"] = {}
    return _state["model"]


def _use_voice(name: Optional[str]) -> str:
    """Point the model at a voice (prepared once from its clip and kept); the built-in voice if there is none."""
    tts = model()
    prepared: Dict[str, object] = _state["voices"]  # type: ignore[assignment]
    clip = VOICES / f"{re.sub(r'[^a-z0-9_-]', '', (name or '').lower())}.wav" if name else None
    if clip is not None and clip.exists():
        if name not in prepared:
            tts.prepare_conditionals(str(clip))
            prepared[name] = tts.conds
        tts.conds = prepared[name]
        return name
    tts.conds = _state["builtin"]
    return "built-in"


def speak(text: str, voice: Optional[str]) -> bytes:
    with _lock:
        used = _use_voice(voice)
        started = time.monotonic()
        wav = model().generate(text)
        samples = wav.squeeze(0).numpy() if hasattr(wav, "numpy") else np.asarray(wav).squeeze()
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        logger.info(f"timing chatterbox {len(text)} characters in {time.monotonic() - started:.2f}s "
                    f"({len(samples) / SAMPLE_RATE:.1f}s of speech, voice {used})")
        return pcm


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: Optional[str] = Field(None, max_length=60)


app = FastAPI(title="JAI natural voice", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def _load():
    try:
        await asyncio.to_thread(speak, "Ready.", os.environ.get("DEFAULT_VOICE", "george"))
        logger.info(f"Chatterbox is loaded on the {_state.get('device')}")
    except Exception:  # noqa: BLE001 - the first request loads it instead
        logger.exception("Chatterbox could not be loaded at start")


@app.get("/health")
async def health():
    voices = sorted(p.stem for p in VOICES.glob("*.wav")) if VOICES.exists() else []
    return {"status": "ok" if "model" in _state else "loading", "device": _state.get("device"),
            "voices": voices, "sample_rate": SAMPLE_RATE}


@app.post("/speak")
async def speak_route(request: SpeakRequest):
    try:
        pcm = await asyncio.to_thread(speak, request.text.strip(), request.voice)
    except Exception as exc:  # noqa: BLE001
        logger.exception("speech failed")
        raise HTTPException(status_code=500, detail=f"speech failed: {exc}"[:300])
    return Response(content=pcm, media_type="audio/L16", headers={"X-Sample-Rate": str(SAMPLE_RATE)})
