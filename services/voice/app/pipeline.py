"""
JAI's voice pipeline (Pipecat 1.12): Richard's speech -> OpenAI streaming speech-to-text -> JAI's model (OpenAI
Responses over a WebSocket) with JAI's tools ->
OpenAI text-to-speech -> his speakers. Silero voice-activity detection hears him start (so he can talk over JAI)
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
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from app.backend import Backend
from app.serializer import IN_RATE, OUT_RATE, JaiFrameSerializer

# Tools that start, resume or stop work: only ever on Richard's own request, never after an activity update.
ACTING_TOOLS = frozenset({"start_mission", "resume_mission", "cancel_mission"})
REFUSED_AFTER_UPDATE = ("Richard has not asked for this. An activity update is reported to him, never acted on: tell "
                        "him what it says and wait for him to ask.")

ACTION_LABELS = {"start_mission": "Started a mission", "resume_mission": "Carried on with a mission",
                 "cancel_mission": "Cancelled a mission", "ask_jarv": "Asked JAI", "show_on_screen": "Put it on screen",
                 "list_workspaces": "Listed workspaces", "list_workspace_files": "Looked in a workspace",
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
    conversation ends with the reason."""

    def __init__(self, backend: Backend, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
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
                elif isinstance(data, TTSUsageMetricsData):
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
                if _name == "show_on_screen" and result.get("card"):
                    frames.append(message({"type": "card", "card": result["card"]}))
                await worker.queue_frames(frames)
            await params.result_callback(result)

        schemas.append(FunctionSchema(name=name, description=tool.get("description") or name,
                                      properties=parameters.get("properties") or {},
                                      required=list(parameters.get("required") or []), handler=handler))
    return schemas


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
    tts = OpenAITTSService(api_key=api_key, settings=OpenAITTSService.Settings(
        model=brief.get("tts_model") or "gpt-4o-mini-tts", voice=brief.get("tts_voice") or "ballad",
        instructions=brief.get("tts_instructions") or "Speak with a calm, clear British accent at a natural pace."))
    context = LLMContext(tools=function_schemas(brief.get("tools") or [], backend, worker_ref))
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))
    pipeline = Pipeline([transport.input(), stt, HeardRelay(backend, worker_ref), user_aggregator, llm, SaidRelay(backend), tts,
                         SpendMeter(backend), transport.output(), assistant_aggregator])
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True))
    worker_ref["worker"] = worker
    return transport, worker, context
