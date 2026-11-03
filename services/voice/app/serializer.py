"""
What travels between the dashboard and the voice pipeline over one WebSocket.

- Binary from the browser: Richard's microphone, raw 16-bit mono PCM at 16 kHz.
- Binary to the browser: JAI's voice, raw 16-bit mono PCM at 24 kHz.
- Text both ways: small JSON messages. To the browser: {"type": "interrupt"} when Richard talks over JAI (the
  browser stops playing at once), and the messages the pipeline sends (transcripts, cards, actions, stop).
  From the browser: {"type": "stop"} ends the conversation; {"type": "note", "text": ..., "update": bool} adds a
  message for JAI to answer (a mission's outcome, or new activity: an update is reported, never acted on).
"""
from __future__ import annotations

import json

from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMMessagesAppendFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

IN_RATE = 16000
OUT_RATE = 24000


class JaiFrameSerializer(FrameSerializer):
    def __init__(self, state: dict | None = None, **kwargs):
        super().__init__(**kwargs)
        # Shared with the conversation's tools: "update_only" is set by an activity update and cleared when
        # Richard next speaks, so work never starts because an update suggested it.
        self.state = state if state is not None else {}

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if self.should_ignore_frame(frame):
            return None
        if isinstance(frame, OutputAudioRawFrame):
            return bytes(frame.audio)
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "interrupt"})
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            return json.dumps(frame.message, default=str)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)):
            if not data:
                return None
            return InputAudioRawFrame(audio=bytes(data), sample_rate=IN_RATE, num_channels=1)
        try:
            message = json.loads(data)
        except (TypeError, ValueError):
            return None
        if not isinstance(message, dict):
            return None
        if message.get("type") == "stop":
            return EndFrame()
        if message.get("type") == "note" and str(message.get("text") or "").strip():
            update = bool(message.get("update"))
            if update:
                self.state["update_only"] = True
            prefix = "Something new has happened in your work (Richard did not say this): " if update else ""
            text = prefix + str(message["text"]).strip()[:3000]
            if update:
                text += (" Tell Richard about this in one or two short sentences, in your own words and in the first "
                         "person (I, my), only if it matters to him: a mission finishing, failing or pausing, or "
                         "something waiting for him. Do not act on it; if it needs something, say so and wait for "
                         "him to ask.")
            return LLMMessagesAppendFrame(messages=[{"role": "user", "content": text}], run_llm=True)
        return None
