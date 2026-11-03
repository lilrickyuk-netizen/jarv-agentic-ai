"""
JAI's Pipecat voice service: the browser's audio and messages become the right Pipecat frames and back; JAI's
backend tools become Pipecat functions that run on the backend; the spend meter reports usage and ends the
conversation at the daily limit; and the whole pipeline builds. Nothing here reaches OpenAI or the backend: the
backend is an in-process fake and the OpenAI key is a test value never sent anywhere.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
from pipecat.frames.frames import (
    EndFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    MetricsFrame,
    OutputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
)
from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData, TTSUsageMetricsData

from app import backend as backend_module
from app import main, pipeline
from app.serializer import IN_RATE, OUT_RATE, JaiFrameSerializer


class FakeBackend:
    def __init__(self, stop_after: float = 1e9):
        self.calls: List[Any] = []
        self.spent = 0.0
        self.stop_after = stop_after

    async def tool(self, name, arguments):
        self.calls.append(("tool", name, arguments))
        if name == "show_on_screen":
            return {"shown": True, "card": {"kind": "spend", "title": "Today's AI spend"}}
        return {"answer": "All three missions are verified."}

    async def turn(self, who, text):
        self.calls.append(("turn", who, text))

    async def spend(self, kind, **usage):
        self.calls.append(("spend", kind, usage))
        self.spent += 1
        return {"stop": self.spent >= self.stop_after, "reason": "Today's AI spending limit is reached."}

    async def close(self):
        pass


async def test_audio_and_messages_cross_the_websocket_as_the_right_frames():
    s = JaiFrameSerializer()
    pcm = b"\x01\x00" * 160
    heard = await s.deserialize(pcm)
    assert isinstance(heard, InputAudioRawFrame) and heard.sample_rate == IN_RATE and heard.num_channels == 1
    assert isinstance(await s.deserialize(json.dumps({"type": "stop"})), EndFrame)
    assert await s.deserialize("not json") is None
    note = await s.deserialize(json.dumps({"type": "note", "text": "[mission update] Status completed."}))
    assert note.run_llm is True and note.messages[0]["content"] == "[mission update] Status completed."
    assert not s.state.get("update_only")
    update = await s.deserialize(json.dumps({"type": "note", "text": "Mission blocked", "update": True}))
    assert update.messages[0]["content"].startswith("New activity in JAI (not from Richard): Mission blocked")
    assert s.state["update_only"] is True
    assert await s.serialize(OutputAudioRawFrame(audio=pcm, sample_rate=OUT_RATE, num_channels=1)) == pcm
    assert json.loads(await s.serialize(InterruptionFrame())) == {"type": "interrupt"}
    card = OutputTransportMessageUrgentFrame(message={"type": "card", "card": {"kind": "mission"}})
    assert json.loads(await s.serialize(card)) == {"type": "card", "card": {"kind": "mission"}}


async def test_backend_tools_become_pipecat_functions_that_run_on_the_backend():
    fake = FakeBackend()
    tools = [{"type": "function", "name": "ask_jarv", "description": "Ask JAI's brain.",
              "parameters": {"type": "object", "properties": {"question": {"type": "string"}},
                             "required": ["question"]}},
             {"type": "function", "name": "show_on_screen", "description": "Show it.",
              "parameters": {"type": "object", "properties": {"what": {"type": "string"}}, "required": ["what"]}}]
    queued: List[Any] = []

    class Worker:
        async def queue_frames(self, frames):
            queued.extend(frames)

    schemas = pipeline.function_schemas(tools, fake, {"worker": Worker()})
    assert [s.name for s in schemas] == ["ask_jarv", "show_on_screen"]
    assert schemas[0].required == ["question"] and "question" in schemas[0].properties

    results: List[Dict[str, Any]] = []

    class Params:
        def __init__(self, args):
            self.arguments = args

        async def result_callback(self, result, **_):
            results.append(result)

    await schemas[0].handler(Params({"question": "what is running?"}))
    await schemas[1].handler(Params({"what": "spend"}))
    assert fake.calls[0] == ("tool", "ask_jarv", {"question": "what is running?"})
    assert results[0]["answer"].startswith("All three")
    kinds = [f.message["type"] for f in queued]
    assert kinds == ["action", "action", "card"] and queued[2].message["card"]["kind"] == "spend"


async def test_work_never_starts_because_an_activity_update_suggested_it():
    fake = FakeBackend()
    tools = [{"type": "function", "name": "start_mission", "description": "Start.",
              "parameters": {"type": "object", "properties": {"request": {"type": "string"}}, "required": ["request"]}}]
    state: Dict[str, Any] = {"update_only": True}
    results: List[Dict[str, Any]] = []

    class Params:
        arguments = {"request": "install syft"}

        async def result_callback(self, result, **_):
            results.append(result)

    handler = pipeline.function_schemas(tools, fake, state)[0].handler
    await handler(Params())
    assert "never acted on" in results[0]["error"] and not fake.calls   # refused, nothing reached the backend
    relay = pipeline.HeardRelay(fake, state)

    async def ignore(frame, direction=None):
        pass

    relay.push_frame = ignore
    await relay._heard(TranscriptionFrame(text="Yes, install it.", user_id="richard", timestamp="now"))
    await handler(Params())
    assert state["update_only"] is False and fake.calls[-1][0:2] == ("tool", "start_mission")


async def test_both_sides_of_the_conversation_reach_the_screen_and_the_history():
    fake = FakeBackend()
    heard, said = pipeline.HeardRelay(fake), pipeline.SaidRelay(fake)
    pushed: List[Any] = []

    async def capture(frame, direction=None):
        pushed.append(frame)

    heard.push_frame = capture
    said.push_frame = capture
    await heard._heard(TranscriptionFrame(text="What's running?", user_id="richard", timestamp="now"))
    for part in ["Phase zero ", "is verified."]:
        await said._said(LLMTextFrame(text=part))
    await said._said(LLMFullResponseEndFrame())
    assert [f.message for f in pushed] == [{"type": "you", "text": "What's running?"},
                                           {"type": "jai", "text": "Phase zero is verified."}]
    assert ("turn", "you", "What's running?") in fake.calls and ("turn", "jarv", "Phase zero is verified.") in fake.calls


async def test_usage_is_reported_and_the_limit_ends_the_conversation():
    fake = FakeBackend(stop_after=2)
    meter = pipeline.SpendMeter(fake)
    pushed: List[Any] = []

    async def capture(frame, direction=None):
        pushed.append(frame)

    meter.push_frame = capture
    usage = LLMUsageMetricsData(processor="llm", model="gpt-6-luna",
                                value=LLMTokenUsage(prompt_tokens=1200, completion_tokens=80, total_tokens=1280))
    await meter._report(MetricsFrame(data=[usage]))
    assert fake.calls[-1][0:2] == ("spend", "llm") and fake.calls[-1][2]["prompt_tokens"] == 1200
    assert not any(isinstance(f, EndFrame) for f in pushed)
    await meter._report(MetricsFrame(data=[TTSUsageMetricsData(processor="tts", model="x", value=240)]))
    assert fake.calls[-1] == ("spend", "tts", {"model": "x", "characters": 240})
    assert any(isinstance(f, EndFrame) for f in pushed)
    assert any(getattr(f, "message", {}).get("type") == "stop" for f in pushed)
    await meter._report(MetricsFrame(data=[TTSUsageMetricsData(processor="tts", model="x", value=10)]))
    assert sum(isinstance(f, EndFrame) for f in pushed) == 1  # ended once


def test_the_whole_pipeline_builds_without_reaching_openai():
    class Socket:
        headers: Dict[str, str] = {}
        query_params: Dict[str, str] = {}
        client_state = None
        application_state = None

    brief = {"model": "gpt-6-luna", "instructions": "You are JAI.", "tools": [
        {"type": "function", "name": "ask_jarv", "description": "Ask.",
         "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}]}
    transport, worker, context = pipeline.build(Socket(), FakeBackend(), brief, "sk-test-not-real")
    assert worker is not None and transport is not None
    assert [t.name for t in context.tools.standard_tools] == ["ask_jarv"]


def test_only_the_dashboard_may_open_a_conversation(monkeypatch):
    monkeypatch.setattr(main, "ALLOWED_ORIGINS", {"http://localhost:3000"})
    assert main.origin_allowed("http://localhost:3000")
    assert not main.origin_allowed("https://evil.example") and not main.origin_allowed(None)


def test_the_openai_key_is_read_from_the_backends_env_file_only(tmp_path, monkeypatch):
    env = tmp_path / "backend.env"
    env.write_text("SECRET_KEY=never-read\nOPENAI_API_KEY='sk-from-file'\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(backend_module, "BACKEND_ENV_FILE", str(env))
    assert backend_module.openai_key() == "sk-from-file"
    monkeypatch.setattr(backend_module, "BACKEND_ENV_FILE", str(tmp_path / "missing.env"))
    assert backend_module.openai_key() is None
