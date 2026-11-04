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

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndFrame,
    ErrorFrame,
    LLMContextFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMRunFrame,
    LLMTextFrame,
    MetricsFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, STTUsageMetricsData, TTFBMetricsData, TTSUsageMetricsData
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService, OpenAIResponsesReasoningConfig
from pipecat.services.openai.stt import OpenAIRealtimeSTTService
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.utils.text.base_text_filter import BaseTextFilter
from pipecat.utils.text.markdown_text_filter import MarkdownTextFilter

import os

from app.backend import Backend
from app.serializer import IN_RATE, OUT_RATE, JaiFrameSerializer

# Tools that start, resume or stop work: only ever on Richard's own request, never after an activity update.
ACTING_TOOLS = frozenset({"start_mission", "resume_mission", "cancel_mission"})
REFUSED_AFTER_UPDATE = ("Richard has not asked for this. An activity update is reported to him, never acted on: tell "
                        "him what it says and wait for him to ask.")

# Where each reply's time goes, in the voice service's log ("timing ..." lines): how long each service took to
# start answering, each tool call, and from Richard's last word being heard to JAI's first words.
timing = logging.getLogger("jai.voice.timing")
logger = logging.getLogger("jai.voice")

ACTION_LABELS = {"start_mission": "Started a mission", "resume_mission": "Carried on with a mission",
                 "cancel_mission": "Cancelled a mission", "ask_jarv": "Asked JAI", "show_on_screen": "Put it on screen",
                 "list_workspaces": "Listed workspaces", "research_web": "Looked it up on the web", "make_image": "Made an image", "list_workspace_files": "Looked in a workspace",
                 "read_workspace_file": "Read a file", "trace_artifact": "Traced it"}


def message(payload: Dict[str, Any]) -> OutputTransportMessageUrgentFrame:
    return OutputTransportMessageUrgentFrame(message=payload)


class HeardRelay(FrameProcessor):
    """What Richard said, to the dashboard and to the conversation history (after speech-to-text). Once he
    speaks, what he asks for next is his own request again."""

    def __init__(self, backend: Backend, state: Optional[Dict[str, Any]] = None, on_heard=None, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
        self._state = state if state is not None else {}
        self._on_heard = on_heard

    async def _heard(self, frame: Frame) -> None:
        if isinstance(frame, TranscriptionFrame) and (frame.text or "").strip():
            self._state["update_only"] = False
            self._state["heard_at"] = time.monotonic()
            if self._on_heard is not None:
                self._on_heard(frame.text.strip())  # JAI starts looking while it decides he has finished
            await self.push_frame(message({"type": "you", "text": frame.text.strip()}))
            await self._backend.turn("you", frame.text.strip())

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self._heard(frame)
        await self.push_frame(frame, direction)


STATE_MARK = "[JAI's live state, not from Richard]"


class BrainContext(FrameProcessor):
    """Makes the voice JAI's brain: before every reply, JAI's live state as it bears on what Richard just said
    (missions and their progress, the mission he means with its whole report, approvals, memory, knowledge,
    spend, the date) goes into the conversation just before his words, replacing the previous one, so the model
    always answers from the truth of now. If the backend is slow the last state is used."""

    def __init__(self, backend: Backend, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
        self._last: Optional[str] = None
        self._early: Optional[tuple] = None  # (what he said, the lookup already started for it)

    def prefetch(self, said: str) -> None:
        """Start fetching JAI's live state for what Richard has just said, as soon as it is transcribed: the turn
        detector is still deciding whether he has finished, so the wait overlaps it."""
        try:
            self._early = (said, asyncio.get_running_loop().create_task(self._backend.context(said)))
        except RuntimeError:  # no running loop (tests calling directly)
            self._early = None

    async def _state_for(self, said: str) -> Dict[str, Any]:
        early, self._early = self._early, None
        if early is not None:
            text, task = early
            if text and (text in said or said in text):
                try:
                    return await task
                except Exception:  # noqa: BLE001 - fall back to asking now
                    pass
            else:
                task.cancel()
        return await self._backend.context(said)

    @staticmethod
    def _is_state(message: Any) -> bool:
        return isinstance(message, dict) and message.get("role") == "user" and \
            str(message.get("content", "")).startswith(STATE_MARK)

    @staticmethod
    def _said_last(messages: List[Any]) -> str:
        # The context also holds provider-specific entries (reasoning and tool items from OpenAI's Responses API),
        # which are not plain messages: only plain ones are read.
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            if message.get("role") == "user" and STATE_MARK not in str(message.get("content")):
                content = message.get("content")
                if isinstance(content, list):
                    return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
                return str(content or "")
        return ""

    async def refresh(self, context: LLMContext, fetch: bool = True) -> None:
        messages = [m for m in context.get_messages() if not self._is_state(m)]
        if fetch:
            started = time.monotonic()
            found = await self._state_for(self._said_last(messages))
            if found.get("state"):
                self._last = str(found["state"])
            timing.info(f"timing brain-context {time.monotonic() - started:.2f}s")
        if self._last:
            last_user = max((i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "user"),
                            default=len(messages))
            messages.insert(last_user, {"role": "user", "content": f"{STATE_MARK}\n{self._last}"})
        context.set_messages(messages)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self.refresh_safely(frame.context, fetch=not getattr(frame, "speculation", False))
        await self.push_frame(frame, direction)

    async def refresh_safely(self, context: LLMContext, fetch: bool = True) -> bool:
        """refresh(), but a failure never stops the reply: JAI answers without the new state and it is logged."""
        try:
            await self.refresh(context, fetch=fetch)
            return True
        except Exception:  # noqa: BLE001 - the live state must never stop JAI from answering
            logger.exception("JAI's live state could not be added to this reply; answering without it")
            return False


class SaidRelay(FrameProcessor):
    """What JAI said, once each reply is complete, to the dashboard and the history (after the model)."""

    def __init__(self, backend: Backend, state: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(**kwargs)
        self._backend = backend
        self._state = state if state is not None else {}
        self._parts: List[str] = []

    async def _said(self, frame: Frame) -> None:
        if isinstance(frame, LLMTextFrame):
            heard = self._state.pop("heard_at", None)
            if heard is not None and not self._parts:
                timing.info(f"timing heard-to-first-words {time.monotonic() - heard:.2f}s")
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
                if isinstance(data, TTFBMetricsData):
                    if data.value:
                        timing.info(f"timing {data.processor} first-response {float(data.value):.2f}s")
                    continue
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
            started = time.monotonic()
            if worker_ref.get("update_only") and _name in ACTING_TOOLS:
                result: Dict[str, Any] = {"error": REFUSED_AFTER_UPDATE}
            else:
                result = await backend.tool(_name, dict(params.arguments or {}))
            timing.info(f"timing tool {_name} {time.monotonic() - started:.2f}s")
            worker = worker_ref.get("worker")
            if worker is not None:
                # The dashboard follows a mission JAI starts or carries on, and tells JAI how it ended.
                refused = result.get("error") == REFUSED_AFTER_UPDATE
                frames: List[Frame] = [message({"type": "action", "name": _name,
                                                "label": ("Did not act: you had not asked" if refused
                                                          else ACTION_LABELS.get(_name, _name)),
                                                "error": None if refused else result.get("error"), "task_id": result.get("task_id"),
                                                "intent": result.get("intent"), "resumed": result.get("resumed")})]
                if result.get("card"):  # show_on_screen, research_web: what JAI puts on his screen
                    frames.append(message({"type": "card", "card": result["card"]}))
                await worker.queue_frames(frames)
            await params.result_callback(result)

        schemas.append(FunctionSchema(name=name, description=tool.get("description") or name,
                                      properties=parameters.get("properties") or {},
                                      required=list(parameters.get("required") or []), handler=handler))
    return schemas


class SpokenText(BaseTextFilter):
    """What the voice says, as a person would say it: JAI is "Jay" (one word, never spelled out), links and file
    paths are not read out character by character. The screen still shows the text as written."""

    _NAME = re.compile(r"(?<![A-Za-z0-9_])JAI(?![A-Za-z0-9_])")
    _URL = re.compile(r"https?://\S+")

    async def update_settings(self, settings):
        return None

    async def filter(self, text: str) -> str:
        return self._URL.sub("the link on your screen", self._NAME.sub("Jay", text))

    async def handle_interruption(self):
        return None

    async def reset_interruption(self):
        return None


def spoken_filters():
    return [MarkdownTextFilter(), SpokenText()]


KOKORO_MODEL = os.environ.get("KOKORO_MODEL", "/srv/voice/models/kokoro-v1.0.onnx")
KOKORO_VOICES = os.environ.get("KOKORO_VOICES", "/srv/voice/models/voices-v1.0.bin")

# JAI's voice model, loaded once for the whole service (it is 325 MB: loading it for each conversation cost about
# ten seconds before the first word) and shared by every conversation, on the graphics card when there is one.
_kokoro: Dict[str, Any] = {}


def kokoro_engine():
    """The shared Kokoro voice: on the NVIDIA GPU (CUDA) when Docker gives this container one and VOICE_GPU is not
    off, otherwise on the processor."""
    if "engine" not in _kokoro:
        import onnxruntime as ort
        from kokoro_onnx import Kokoro

        if hasattr(ort, "preload_dlls"):
            try:
                ort.preload_dlls()  # the CUDA and cuDNN libraries installed with onnxruntime-gpu
            except Exception:  # noqa: BLE001 - without them the voice runs on the processor
                pass
        session = None
        if os.environ.get("VOICE_GPU", "auto").lower() != "off" and "CUDAExecutionProvider" in ort.get_available_providers():
            try:  # the graphics card, if Docker gave this container one and its driver supports this CUDA
                session = ort.InferenceSession(KOKORO_MODEL, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
            except Exception:  # noqa: BLE001 - no usable GPU here: the processor
                session = None
        if session is None:
            session = ort.InferenceSession(KOKORO_MODEL, providers=["CPUExecutionProvider"])
        _kokoro["engine"] = Kokoro.from_session(session, KOKORO_VOICES)
        _kokoro["device"] = "gpu" if session.get_providers()[0] == "CUDAExecutionProvider" else "cpu"
    return _kokoro["engine"]


def kokoro_device() -> Optional[str]:
    return _kokoro.get("device")


def warm_up(voice: str = "bm_george") -> str:
    """Load the voice and speak one short sentence silently, so the first real reply starts at once."""
    kokoro_engine().create("Ready.", voice=voice, lang="en-gb")
    return kokoro_device() or "cpu"


def _shared_kokoro(*_args, **_kwargs):
    return kokoro_engine()


# Pipecat's Kokoro service builds its own Kokoro for every conversation; it is given the shared one instead.
import pipecat.services.kokoro.tts as _kokoro_tts  # noqa: E402

_kokoro_tts.Kokoro = _shared_kokoro


CHATTERBOX_URL = os.environ.get("CHATTERBOX_URL", "").rstrip("/")
CHATTERBOX_RATE = 24000


FIRST_PHRASE_WORDS = 9     # the first thing JAI says is short, so it starts speaking at once
PHRASE_WORDS = 18          # later phrases are about a breath long


def phrases(text: str) -> List[str]:
    """A sentence as phrases to speak one after another: split at commas, semicolons, colons and dashes (never
    inside a number such as 1,500), the first phrase short, later ones about a breath long, none under three words."""
    text = " ".join((text or "").split())
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[,;:])\s+(?=\D)|(?<=\s)(?=[\u2013\u2014-]\s)", text) if p.strip()]
    out: List[str] = []
    current = ""
    for part in parts:
        target = FIRST_PHRASE_WORDS if not out else PHRASE_WORDS
        if not current or len(current.split()) + len(part.split()) <= target:
            current = f"{current} {part}".strip()
        else:
            out.append(current)
            current = part
    if current:
        out.append(current)
    cut: List[str] = []
    for phrase in out:  # a long stretch with no punctuation is cut at a word, about a breath in
        words = phrase.split()
        while len(words) > (FIRST_PHRASE_WORDS if not cut else PHRASE_WORDS) + 6:
            size = FIRST_PHRASE_WORDS if not cut else PHRASE_WORDS
            cut.append(" ".join(words[:size]))
            words = words[size:]
        if words:
            cut.append(" ".join(words))
    final: List[str] = []
    for phrase in cut:  # a scrap of one or two words joins the phrase before it
        if final and len(phrase.split()) < 3:
            final[-1] = f"{final[-1]} {phrase}"
        else:
            final.append(phrase)
    return final


class ChatterboxTTSService(TTSService):
    """JAI's natural voice: each sentence spoken by the Chatterbox service (Chatterbox Turbo on the GPU) in the
    named reference voice, returned as 24 kHz 16-bit PCM and streamed into the conversation."""

    Settings = TTSSettings

    def __init__(self, *, base_url: str, voice: str, client=None, **kwargs):
        settings = TTSSettings(model="chatterbox-turbo", voice=voice, language=None)
        super().__init__(push_start_frame=True, push_stop_frames=True, settings=settings, **kwargs)
        import httpx

        self._url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=3.0))

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str):
        # Chatterbox makes a whole piece before any of it can play, and a long sentence takes seconds on a laptop
        # GPU. So a sentence is spoken in phrases: the first one short, so Richard hears JAI at once, and each next
        # phrase is made while the one before it plays, so there are no gaps.
        try:
            await self.start_tts_usage_metrics(text)
            for piece in phrases(text):
                started = time.monotonic()
                response = await self._client.post(f"{self._url}/speak",
                                                   json={"text": piece, "voice": self._settings.voice})
                if response.status_code != 200:
                    yield ErrorFrame(error=f"JAI's natural voice answered {response.status_code}: {response.text[:200]}")
                    return
                timing.info(f"timing chatterbox-phrase {len(piece)} characters {time.monotonic() - started:.2f}s")

                async def pcm(audio=response.content):
                    for start in range(0, len(audio), 9600):  # 0.2 s pieces
                        yield audio[start:start + 9600]

                async for frame in self._stream_audio_frames_from_iterator(pcm(), in_sample_rate=CHATTERBOX_RATE,
                                                                           context_id=context_id):
                    await self.stop_ttfb_metrics()
                    yield frame
        except Exception as exc:  # noqa: BLE001
            yield ErrorFrame(error=f"JAI's natural voice failed: {exc}")
        finally:
            await self.stop_ttfb_metrics()


def chatterbox_ready(timeout: float = 1.5) -> bool:
    """Whether the natural voice is up and loaded (otherwise the conversation uses Kokoro)."""
    if not CHATTERBOX_URL:
        return False
    import httpx

    try:
        return httpx.get(f"{CHATTERBOX_URL}/health", timeout=timeout).json().get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def speech(brief: Dict[str, Any], api_key: str):
    """JAI's voice for this conversation, and whether it runs on this computer (free): Chatterbox (natural speech,
    on the GPU), Kokoro speaking British English (in the image; also the fallback when Chatterbox is not up), or
    OpenAI text-to-speech."""
    engine = brief.get("tts_engine") or "kokoro"
    if engine == "chatterbox" and chatterbox_ready():
        return ChatterboxTTSService(base_url=CHATTERBOX_URL, voice=brief.get("tts_voice") or "george",
                                    text_filters=spoken_filters()), True
    if engine == "chatterbox":
        brief = {**brief, "tts_voice": brief.get("fallback_voice") or "bm_george"}
        engine = "kokoro"
    if engine == "kokoro":
        return KokoroTTSService(model_path=KOKORO_MODEL, voices_path=KOKORO_VOICES, text_filters=spoken_filters(),
                                settings=KokoroTTSService.Settings(
            voice=brief.get("tts_voice") or "bm_george", language=Language.EN_GB,
            speed=float(brief.get("tts_speed") or 1.0))), True
    return OpenAITTSService(api_key=api_key, text_filters=spoken_filters(), settings=OpenAITTSService.Settings(
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
    # The most accurate transcription, told the names and words Richard uses, British English, a close microphone.
    stt = OpenAIRealtimeSTTService(api_key=api_key, settings=OpenAIRealtimeSTTService.Settings(
        model=brief.get("stt_model") or "gpt-transcribe", language=Language.EN,
        prompt=brief.get("stt_prompt") or None, noise_reduction="near_field"))
    # The Responses API over a WebSocket: Pipecat's recommended service for conversation (lowest latency, only the
    # new part of the context sent each turn, nothing stored on OpenAI's side). Reasoning stays off for speed; the
    # thinking happens in ask_jarv, JAI's brain on the backend.
    reasoning = brief.get("reasoning")
    llm = OpenAIResponsesLLMService(api_key=api_key, settings=OpenAIResponsesLLMService.Settings(
        model=brief.get("model") or "gpt-6-luna", system_instruction=brief.get("instructions") or "",
        **({"reasoning": OpenAIResponsesReasoningConfig(effort=reasoning)} if reasoning else {})))
    tts, local_voice = speech(brief, api_key)
    context = LLMContext(tools=function_schemas(brief.get("tools") or [], backend, worker_ref))
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))
    brain = BrainContext(backend)
    pipeline = Pipeline([transport.input(), stt, HeardRelay(backend, worker_ref, on_heard=brain.prefetch),
                         user_aggregator, brain, llm, SaidRelay(backend, worker_ref), tts,
                         SpendMeter(backend, local_voice), transport.output(), assistant_aggregator])
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True))
    worker_ref["worker"] = worker
    return transport, worker, context
