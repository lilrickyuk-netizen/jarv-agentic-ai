"""
JAI's voice pipeline (Pipecat 1.12): Richard's speech -> OpenAI streaming speech-to-text -> JAI's model (OpenAI
Responses over a WebSocket) with JAI's tools ->
JAI's voice -> his speakers. The voice is Kokoro (open source, run on this computer, free) speaking British
English with a British voice; OpenAI text-to-speech is the alternative. Silero voice-activity detection hears him start (so he can talk over JAI)
and Pipecat's Smart Turn v3 model decides when he has actually finished, from how he sounds, not a fixed silence. JAI's model speaks for JAI's whole system: for anything about JAI's work it calls the
backend's tools (ask_jarv, show_on_screen, start_mission and the rest) as him, exactly as before.

Alongside the audio it sends the dashboard what was said (both sides, also kept as conversation history), the
cards JAI puts on screen and the actions it takes; and it reports every model, speech-to-text and text-to-speech
use to JAI's daily spend, ending the conversation if today's limit is reached.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMRunFrame,
    LLMTextFrame,
    MetricsFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, STTUsageMetricsData, TTSUsageMetricsData
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.services.openai.stt import OpenAIRealtimeSTTService
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

import os

from app.backend import Backend
from app.serializer import IN_RATE, OUT_RATE, JaiFrameSerializer

# Tools that start, resume or stop work: only ever on Richard's own request, never after an activity update.
ACTING_TOOLS = frozenset({"start_mission", "resume_mission", "cancel_mission"})
REFUSED_AFTER_UPDATE = ("Richard has not asked for this. An activity update is reported to him, never acted on: tell "
                        "him what it says and wait for him to ask.")

ACTION_LABELS = {"start_mission": "Started a mission", "resume_mission": "Carried on with a mission",
                 "cancel_mission": "Cancelled a mission", "ask_jarv": "Asked JAI", "show_on_screen": "Put it on screen",
                 "list_workspaces": "Listed workspaces", "research_web": "Looked it up on the web", "list_workspace_files": "Looked in a workspace",
                 "read_workspace_file": "Read a file", "trace_artifact": "Traced it"}


def message(payload: Dict[str, Any]) -> OutputTransportMessageUrgentFrame:
    return OutputTransportMessageUrgentFrame(message=payload)


class HeardRelay(FrameProcessor):
    """What Richard said, to the dashboard and to the conversation history (after speech-to-text). Once he
    speaks, what he asks for next is his own request again."""

    def __init__(self, backend: Backend, state: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
        self._state = state if state is not None else {}

    async def _heard(self, frame: Frame) -> None:
        if isinstance(frame, TranscriptionFrame) and (frame.text or "").strip():
            self._state["update_only"] = False
            await self.push_frame(message({"type": "you", "text": frame.text.strip()}))
            await self._backend.turn("you", frame.text.strip())

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self._heard(frame)
        await self.push_frame(frame, direction)


class SaidRelay(FrameProcessor):
    """What JAI said, once each reply is complete, to the dashboard and the history (after the model)."""

    def __init__(self, backend: Backend, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
        self._parts: List[str] = []

    async def _said(self, frame: Frame) -> None:
        if isinstance(frame, LLMTextFrame):
            self._parts.append(frame.text or "")
        elif isinstance(frame, LLMFullResponseEndFrame):
            text, self._parts = "".join(self._parts).strip(), []
            if text:
                await self.push_frame(message({"type": "jai", "text": text}))
                await self._backend.turn("jarv", text)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        # Interrupted replies still end with LLMFullResponseEndFrame, so what JAI got out is what is kept.
        await self._said(frame)
        await self.push_frame(frame, direction)


class SpendMeter(FrameProcessor):
    """Every model, speech-to-text and text-to-speech use, reported to JAI's daily spend; at the daily limit the
    conversation ends with the reason. A voice run on this computer (Kokoro) costs nothing and is not reported."""

    def __init__(self, backend: Backend, local_voice: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
        self._local_voice = local_voice
        self._stopped = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self._report(frame)
        await self.push_frame(frame, direction)

    async def _report(self, frame: Frame) -> None:
        if isinstance(frame, MetricsFrame):
            for data in frame.data:
                result: Optional[Dict[str, Any]] = None
                if isinstance(data, LLMUsageMetricsData):
                    usage = data.value
                    result = await self._backend.spend(
                        "llm", model=data.model, prompt_tokens=usage.prompt_tokens,
                        completion_tokens=usage.completion_tokens,
                        cached_tokens=usage.cache_read_input_tokens or 0)
                elif isinstance(data, TTSUsageMetricsData) and not self._local_voice:
                    result = await self._backend.spend("tts", model=data.model, characters=int(data.value))
                elif isinstance(data, STTUsageMetricsData):
                    result = await self._backend.spend("stt", model=data.model, seconds=float(data.value.audio_seconds))
                if result and result.get("stop") and not self._stopped:
                    self._stopped = True
                    await self.push_frame(message({"type": "stop", "reason": result.get("reason")}))
                    await self.push_frame(EndFrame())


def function_schemas(tools: List[Dict[str, Any]], backend: Backend, worker_ref: Dict[str, Any]) -> List[FunctionSchema]:
    """JAI's voice tools (as the backend describes them) as Pipecat functions that run on the backend as Richard."""
    schemas = []
    for tool in tools:
        name = tool["name"]
        parameters = tool.get("parameters") or {}

        async def handler(params: FunctionCallParams, _name: str = name):
            if worker_ref.get("update_only") and _name in ACTING_TOOLS:
                result: Dict[str, Any] = {"error": REFUSED_AFTER_UPDATE}
            else:
                result = await backend.tool(_name, dict(params.arguments or {}))
            worker = worker_ref.get("worker")
            if worker is not None:
                # The dashboard follows a mission JAI starts or carries on, and tells JAI how it ended.
                frames: List[Frame] = [message({"type": "action", "name": _name,
                                                "label": ACTION_LABELS.get(_name, _name),
                                                "error": result.get("error"), "task_id": result.get("task_id"),
                                                "intent": result.get("intent"), "resumed": result.get("resumed")})]
                if result.get("card"):  # show_on_screen, research_web: what JAI puts on his screen
                    frames.append(message({"type": "card", "card": result["card"]}))
                await worker.queue_frames(frames)
            await params.result_callback(result)

        schemas.append(FunctionSchema(name=name, description=tool.get("description") or name,
                                      properties=parameters.get("properties") or {},
                                      required=list(parameters.get("required") or []), handler=handler))
    return schemas


KOKORO_MODEL = os.environ.get("KOKORO_MODEL", "/srv/voice/models/kokoro-v1.0.onnx")
KOKORO_VOICES = os.environ.get("KOKORO_VOICES", "/srv/voice/models/voices-v1.0.bin")


def speech(brief: Dict[str, Any], api_key: str):
    """JAI's voice for this conversation, and whether it runs on this computer (free): Kokoro speaking British
    English (the model and voices are in the image), or OpenAI text-to-speech."""
    if (brief.get("tts_engine") or "kokoro") == "kokoro":
        return KokoroTTSService(model_path=KOKORO_MODEL, voices_path=KOKORO_VOICES, settings=KokoroTTSService.Settings(
            voice=brief.get("tts_voice") or "bm_george", language=Language.EN_GB,
            speed=float(brief.get("tts_speed") or 1.0))), True
    return OpenAITTSService(api_key=api_key, settings=OpenAITTSService.Settings(
        model=brief.get("tts_model") or "gpt-4o-mini-tts", voice=brief.get("tts_voice") or "fable",
        instructions=brief.get("tts_instructions") or "Speak in a British accent.")), False


def build(websocket, backend: Backend, brief: Dict[str, Any], api_key: str):
    """The transport, the pipeline and its worker for one conversation."""
    # One conversation's shared state: the worker (for the tools' screen messages) and whether the last thing
    # JAI heard was an activity update rather than Richard.
    worker_ref: Dict[str, Any] = {"update_only": False}
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False,
                                      audio_in_sample_rate=IN_RATE, audio_out_sample_rate=OUT_RATE,
                                      serializer=JaiFrameSerializer(worker_ref)))
    stt = OpenAIRealtimeSTTService(api_key=api_key)
    # The Responses API over a WebSocket: Pipecat's recommended service for conversation (lowest latency, only the
    # new part of the context sent each turn, nothing stored on OpenAI's side). Reasoning stays off for speed; the
    # thinking happens in ask_jarv, JAI's brain on the backend.
    llm = OpenAIResponsesLLMService(api_key=api_key, settings=OpenAIResponsesLLMService.Settings(
        model=brief.get("model") or "gpt-6-luna", system_instruction=brief.get("instructions") or ""))
    tts, local_voice = speech(brief, api_key)
    context = LLMContext(tools=function_schemas(brief.get("tools") or [], backend, worker_ref))
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))
    pipeline = Pipeline([transport.input(), stt, HeardRelay(backend, worker_ref), user_aggregator, llm, SaidRelay(backend), tts,
                         SpendMeter(backend, local_voice), transport.output(), assistant_aggregator])
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True))
    worker_ref["worker"] = worker
    return transport, worker, context
