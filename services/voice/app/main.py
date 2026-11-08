"""
JAI's voice service: one WebSocket per conversation at /ws?token=<Richard's access token>. The token is checked by
JAI's backend (the brief is refused without a valid one) and every tool runs there as him, so this service holds
no authority of its own. Audio in is 16 kHz mono PCM16, audio out 24 kHz mono PCM16; text messages are JSON.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI, WebSocket
from pipecat.frames.frames import LLMRunFrame
from pipecat.workers.runner import WorkerRunner

from app import pipeline
from app.backend import Backend, openai_key

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("jai.voice")

ALLOWED_ORIGINS = {o.strip() for o in os.environ.get("PIPECAT_ALLOWED_ORIGINS", "").split(",") if o.strip()}

app = FastAPI(title="JAI voice", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def _load_the_voice():
    """Load JAI's voice once when the service starts, not in the first conversation."""
    import asyncio

    try:
        device = await asyncio.to_thread(pipeline.warm_up)
        logger.info(f"JAI's voice is loaded and runs on the {device}")
    except Exception:  # noqa: BLE001 - the first conversation loads it instead
        logger.exception("JAI's voice could not be loaded at start")


@app.get("/health")
async def health():
    key = bool(openai_key())
    return {"status": "ok" if key else "degraded", "engine": "pipecat", "openai_key": key,
            "voice_device": pipeline.kokoro_device(),
            "setup": None if key else "Set OPENAI_API_KEY in apps/backend/.env (the voice service reads it from there)."}


def origin_allowed(origin: str | None) -> bool:
    return not ALLOWED_ORIGINS or (origin or "") in ALLOWED_ORIGINS


@app.websocket("/ws")
async def conversation(websocket: WebSocket):
    if not origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=4403, reason="This page may not talk to JAI's voice")
        return
    token = websocket.query_params.get("token") or ""
    await websocket.accept()
    if not token:
        await websocket.send_json({"type": "stop", "reason": "Sign in to talk to JAI."})
        await websocket.close(code=4401)
        return
    api_key = openai_key()
    if not api_key:
        await websocket.send_json({"type": "stop", "reason": "JAI's voice needs OPENAI_API_KEY in apps/backend/.env."})
        await websocket.close(code=4503)
        return
    backend = Backend(token)
    try:
        brief = await backend.brief()
        if brief.get("error"):
            await websocket.send_json({"type": "stop", "reason": brief["error"]})
            await websocket.close(code=4403)
            return
        backend.use_session(brief.pop("session_token", None))
        transport, worker, _context = pipeline.build(websocket, backend, brief, api_key)

        @transport.event_handler("on_client_connected")
        async def _greet(_transport, _client):
            # JAI opens the conversation itself, from the situation in its instructions (no canned greeting).
            await worker.queue_frames([LLMRunFrame()])

        @transport.event_handler("on_client_disconnected")
        async def _gone(_transport, _client):
            await worker.cancel()

        await websocket.send_json({"type": "ready", "engine": "pipecat", "model": brief.get("model")})
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        await runner.run()
    except Exception as exc:  # noqa: BLE001 - the browser is told, and falls back to the other voice
        logger.exception("voice conversation failed")
        try:
            await websocket.send_json({"type": "stop", "reason": f"JAI's voice stopped: {exc}"[:300]})
        except Exception:  # noqa: BLE001
            pass
    finally:
        await backend.close()
