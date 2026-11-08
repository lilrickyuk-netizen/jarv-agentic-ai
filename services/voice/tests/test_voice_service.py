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
    async def context(self, text):
        return {"state": "No mission is in progress."}

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
    assert update.messages[0]["content"].startswith("Something new has happened in your work (Richard did not say "
                                                   "this): Mission blocked")
    assert "first person" in update.messages[0]["content"]
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

    brief = {"model": "gpt-6-luna", "instructions": "You are JAI.", "tts_engine": "kokoro", "tts_voice": "bm_george", "tools": [
        {"type": "function", "name": "ask_jarv", "description": "Ask.",
         "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}]}
    transport, worker, context = pipeline.build(Socket(), FakeBackend(), brief, "sk-test-not-real")
    assert worker is not None and transport is not None
    assert [t.name for t in context.tools.standard_tools] == ["ask_jarv"]


def test_jai_speaks_british_english_with_a_british_voice_on_this_computer():
    """Kokoro's model and voices are in the image: a British voice speaks a sentence with no network."""
    kokoro = pipeline.kokoro_engine()
    names = set(kokoro.get_voices()) if hasattr(kokoro, "get_voices") else set(kokoro.voices)
    assert {"bm_george", "bm_daniel", "bf_emma"} <= names
    samples, rate = kokoro.create("Good evening, Richard. Phase zero is verified.", voice="bm_george", lang="en-gb")
    assert rate == 24000 and len(samples) > rate  # over a second of speech
    tts, local = pipeline.speech({"tts_engine": "kokoro", "tts_voice": "bm_george"}, "sk-test-not-real")
    assert local is True and type(tts).__name__ == "KokoroTTSService"
    tts, local = pipeline.speech({"tts_engine": "openai", "tts_voice": "fable"}, "sk-test-not-real")
    assert local is False and type(tts).__name__ == "OpenAITTSService"


async def test_a_voice_on_this_computer_is_not_charged():
    fake = FakeBackend()
    meter = pipeline.SpendMeter(fake, local_voice=True)

    async def capture(frame, direction=None):
        pass

    meter.push_frame = capture
    await meter._report(MetricsFrame(data=[TTSUsageMetricsData(processor="tts", model="kokoro", value=500)]))
    assert not fake.calls


def test_the_voice_is_loaded_once_and_shared_by_every_conversation():
    first = pipeline.speech({"tts_engine": "kokoro", "tts_voice": "bm_george"}, "sk-test-not-real")[0]
    second = pipeline.speech({"tts_engine": "kokoro", "tts_voice": "bf_emma"}, "sk-test-not-real")[0]
    assert first._kokoro is second._kokoro is pipeline.kokoro_engine()
    assert pipeline.warm_up() in ("gpu", "cpu") and pipeline.kokoro_device() in ("gpu", "cpu")


async def test_the_voice_says_its_name_as_jay_and_never_reads_out_links():
    spoken = pipeline.SpokenText()
    assert await spoken.filter("JAI has finished. JAI's report is at https://x.example/a?b=1.") == \
        "Jay has finished. Jay's report is at the link on your screen"
    assert await spoken.filter("JAIL and MYJAI stay as they are.") == "JAIL and MYJAI stay as they are."


async def test_the_natural_voice_is_used_when_it_is_up_and_kokoro_when_it_is_not(monkeypatch):
    import httpx

    monkeypatch.setattr(pipeline, "CHATTERBOX_URL", "http://chatterbox:8770")
    monkeypatch.setattr(pipeline, "chatterbox_ready", lambda timeout=1.5: True)
    tts, local = pipeline.speech({"tts_engine": "chatterbox", "tts_voice": "george"}, "sk-test-not-real")
    assert local is True and type(tts).__name__ == "ChatterboxTTSService"

    sent = []

    def answer(request):
        sent.append(request)
        return httpx.Response(200, content=b"\x01\x00" * 24000, headers={"X-Sample-Rate": "24000"})

    tts._client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    tts._sample_rate = 24000  # as the running pipeline sets it
    tts.start_tts_usage_metrics = lambda text: _nothing()
    tts.stop_ttfb_metrics = lambda: _nothing()
    frames = [f async for f in tts.run_tts("Good evening, Richard.", "ctx-1")]
    audio = b"".join(getattr(f, "audio", b"") for f in frames)
    assert json.loads(sent[0].content) == {"text": "Good evening, Richard.", "voice": "george"}
    assert len(audio) >= 40000 and not any(type(f).__name__ == "ErrorFrame" for f in frames)

    monkeypatch.setattr(pipeline, "chatterbox_ready", lambda timeout=1.5: False)
    fallback, local = pipeline.speech({"tts_engine": "chatterbox", "tts_voice": "george", "fallback_voice": "bm_george"},
                                      "sk-test-not-real")
    assert local is True and type(fallback).__name__ == "KokoroTTSService"


async def _nothing():
    return None


async def test_every_reply_is_given_jais_live_state_just_before_richards_words():
    from pipecat.processors.aggregators.llm_context import LLMContext

    class Brain(FakeBackend):
        def __init__(self):
            super().__init__()
            self.asked = []
            self.state = "MYCO Phase 0: round 3, 8 of 9 requirements done."

        async def context(self, text):
            self.asked.append(text)
            return {"state": self.state}

    brain = Brain()
    relay = pipeline.BrainContext(brain)
    context = LLMContext(messages=[{"role": "assistant", "content": "Evening."},
                                   {"role": "user", "content": "How is the MYCO build going?"}])
    await relay.refresh(context)
    messages = context.get_messages()
    assert brain.asked == ["How is the MYCO build going?"]
    assert messages[1]["content"].startswith(pipeline.STATE_MARK) and "8 of 9" in messages[1]["content"]
    assert messages[2]["content"] == "How is the MYCO build going?"

    brain.state = "MYCO Phase 0: finished, 9 of 9 done."
    context.add_message({"role": "assistant", "content": "Round three."})
    context.add_message({"role": "user", "content": "And now?"})
    await relay.refresh(context)
    states = [m for m in context.get_messages() if str(m["content"]).startswith(pipeline.STATE_MARK)]
    assert len(states) == 1 and "9 of 9" in states[0]["content"]          # replaced, never piled up
    assert context.get_messages()[-1]["content"] == "And now?" and brain.asked[-1] == "And now?"


async def test_the_live_state_survives_openai_specific_entries_and_never_stops_a_reply():
    """After a tool call the context holds OpenAI-specific items (reasoning, function calls) that are not plain
    messages; on Richard's computer one stopped every reply that followed."""
    from pipecat.processors.aggregators.llm_context import LLMContext, LLMSpecificMessage

    class Brain(FakeBackend):
        async def context(self, text):
            return {"state": f"asked about: {text}"}

    relay = pipeline.BrainContext(Brain())
    context = LLMContext(messages=[{"role": "user", "content": "Do you know you've been upgraded today?"},
                                   LLMSpecificMessage(llm="openai", message={"type": "reasoning", "summary": []}),
                                   {"role": "assistant", "content": "Let me check."},
                                   {"role": "user", "content": "What upgrades have you had?"}])
    await relay.refresh(context)
    messages = context.get_messages()
    assert any(isinstance(m, LLMSpecificMessage) for m in messages)              # kept as it was
    state = [m for m in messages if isinstance(m, dict) and str(m.get("content")).startswith(pipeline.STATE_MARK)]
    assert len(state) == 1 and "What upgrades have you had?" in state[0]["content"]
    assert messages[-1]["content"] == "What upgrades have you had?"

    class Broken(FakeBackend):
        async def context(self, text):
            raise RuntimeError("backend restarting")

    stalled = pipeline.BrainContext(Broken())
    quiet = LLMContext(messages=[{"role": "user", "content": "Jay?"}])
    assert await stalled.refresh_safely(quiet) is False   # logged, not raised: the reply still goes ahead
    assert quiet.get_messages()[-1]["content"] == "Jay?"


async def test_a_state_that_cannot_be_read_is_never_passed_off_as_current():
    """8 November: after his sign-in expired, every lookup failed and the voice repeated minutes-old progress."""
    from pipecat.processors.aggregators.llm_context import LLMContext

    class Expiring(FakeBackend):
        def __init__(self):
            super().__init__()
            self.answer = {"state": "Video: 4 of 9 packages done."}

        async def context(self, text):
            return self.answer

    brain = Expiring()
    relay = pipeline.BrainContext(brain)
    context = LLMContext(messages=[{"role": "user", "content": "How is the mission going?"}])
    await relay.refresh(context)
    brain.answer = {"error": "Invalid authentication credentials"}
    context.add_message({"role": "assistant", "content": "Four of nine."})
    context.add_message({"role": "user", "content": "And now?"})
    await relay.refresh(context)
    state = next(m for m in context.get_messages() if str(m["content"]).startswith(pipeline.STATE_MARK))
    assert "could not read JAI's live state" in state["content"] and "Invalid authentication" in state["content"]
    assert "do not present anything below as current" in state["content"] and "4 of 9" in state["content"]


async def test_the_conversation_carries_on_as_its_session_token():
    import httpx

    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(base_url="http://backend", transport=httpx.MockTransport(handler),
                               headers={"Authorization": "Bearer sign-in"})
    from app.backend import Backend

    backend = Backend("sign-in", client=client)
    await backend.tool("get_status", {})
    backend.use_session("voice-session")
    await backend.tool("get_status", {})
    backend.use_session(None)  # an older backend gives none: the sign-in stays
    await backend.tool("get_status", {})
    assert seen == ["Bearer sign-in", "Bearer voice-session", "Bearer voice-session"]
    await client.aclose()


def test_a_sentence_is_spoken_in_phrases_the_first_one_short():
    assert pipeline.phrases("Yes.") == ["Yes."]
    first, *rest = pipeline.phrases("At two thirty-five, I gained live system context before each reply, direct "
                                    "access to my tools, current web research, and improved speech handling.")
    assert first == "At two thirty-five," and rest and all(len(p.split()) >= 3 for p in rest)
    assert pipeline.phrases("It cost 1,500 pounds, which is a lot.") == ["It cost 1,500 pounds, which is a lot."]
    long = pipeline.phrases("word " * 60)
    assert len(long[0].split()) <= pipeline.FIRST_PHRASE_WORDS and " ".join(long).split() == ["word"] * 60


async def test_the_natural_voice_speaks_phrase_by_phrase(monkeypatch):
    import httpx

    asked = []

    def chatterbox(request):
        asked.append(json.loads(request.content)["text"])
        return httpx.Response(200, content=b"\x01\x00" * 4800)

    tts = pipeline.ChatterboxTTSService(base_url="http://chatterbox:8770", voice="george",
                                        client=httpx.AsyncClient(transport=httpx.MockTransport(chatterbox)))

    async def no_metrics(*a, **k):
        return None

    monkeypatch.setattr(tts, "start_tts_usage_metrics", no_metrics)
    monkeypatch.setattr(tts, "stop_ttfb_metrics", no_metrics)

    async def frames(audio, in_sample_rate, context_id):
        async for piece in audio:
            yield piece

    monkeypatch.setattr(tts, "_stream_audio_frames_from_iterator", frames)
    out = [f async for f in tts.run_tts("Since this morning, I've had several upgrades to how I work.", "c1")]
    assert asked == ["Since this morning,", "I've had several upgrades to how I work."] and len(out) == 2


async def test_the_live_state_is_fetched_while_the_turn_is_still_being_judged():
    import asyncio

    from pipecat.processors.aggregators.llm_context import LLMContext

    class Brain(FakeBackend):
        def __init__(self):
            super().__init__()
            self.asked = []

        async def context(self, text):
            self.asked.append(text)
            await asyncio.sleep(0)
            return {"state": f"for: {text}"}

    brain = Brain()
    relay = pipeline.BrainContext(brain)
    relay.prefetch("How is MYCO going?")                # as soon as the words are transcribed
    context = LLMContext(messages=[{"role": "user", "content": "How is MYCO going?"}])
    await relay.refresh(context)
    assert brain.asked == ["How is MYCO going?"]        # one lookup, started early, used
    assert "for: How is MYCO going?" in context.get_messages()[0]["content"]
    relay.prefetch("Something else entirely")
    await relay.refresh(LLMContext(messages=[{"role": "user", "content": "What day is it?"}]))
    assert brain.asked[-1] == "What day is it?"         # a stale early lookup is not used


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


def test_fish_audio_speaks_in_the_british_voice_with_its_key_and_kokoro_without(monkeypatch):
    """Upgrade 7: Fish Audio is a selectable voice; its key is read from the backend's .env, its characters are
    charged, and with no key the conversation still speaks, in Kokoro's British voice."""
    from app import backend

    monkeypatch.setattr(pipeline, "fish_key", lambda: "fish-test-key-not-real")
    tts, local = pipeline.speech({"tts_engine": "fish", "tts_voice": "612b878b113047d9a770c069c8b4fdfe",
                                  "tts_model": "s2.1-pro", "fallback_voice": "bm_george"}, "sk-test-not-real")
    assert local is False and type(tts).__name__ == "FishAudioTTSService"
    assert tts._settings.voice == "612b878b113047d9a770c069c8b4fdfe" and tts._settings.model == "s2.1-pro"

    monkeypatch.setattr(pipeline, "fish_key", lambda: None)
    fallback, local = pipeline.speech({"tts_engine": "fish", "fallback_voice": "bm_george"}, "sk-test-not-real")
    assert local is True and type(fallback).__name__ == "KokoroTTSService"

    with pytest.raises(ValueError):
        backend.backend_key("ANTHROPIC_API_KEY")  # the voice service reads only its own two keys


def test_the_fish_key_is_read_from_the_backends_env_file(tmp_path, monkeypatch):
    from app import backend

    env = tmp_path / "backend.env"
    env.write_text("OPENAI_API_KEY=sk-a\nFISH_API_KEY='fish-b'\nANTHROPIC_API_KEY=never-read\n")
    monkeypatch.setattr(backend, "BACKEND_ENV_FILE", str(env))
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert backend.fish_key() == "fish-b" and backend.openai_key() == "sk-a"


def test_a_sentence_jai_has_just_said_is_not_said_again():
    """8 November: "MYCO has restarted under your expanded brief.MYCO has restarted under your expanded brief." """
    now = [1000.0]
    guard = pipeline.RepeatGuard(clock=lambda: now[0])
    out = []
    for piece in ["MYCO has restarted ", "under your expanded brief.", "MYCO has restarted under your ",
                  "expanded brief. Eight of ", "nineteen requirements are done. It costs 1.", "5 dollars."]:
        out += guard.handle(LLMTextFrame(text=piece))
    out += guard.handle(LLMFullResponseEndFrame())
    said = "".join(f.text for f in out if isinstance(f, LLMTextFrame))
    assert said == ("MYCO has restarted under your expanded brief. Eight of nineteen requirements are done. "
                    "It costs 1.5 dollars.")
    assert isinstance(out[-1], LLMFullResponseEndFrame)
    # Short replies may repeat ("Yes."), and after the window the same news may be said again.
    assert [f.text for f in guard.handle(LLMTextFrame(text="Yes. Yes. "))] == ["Yes. ", "Yes. "]
    now[0] += pipeline.REPEAT_WINDOW_SECONDS + 1
    again = guard.handle(LLMTextFrame(text="MYCO has restarted under your expanded brief. "))
    assert [f.text for f in again] == ["MYCO has restarted under your expanded brief. "]
