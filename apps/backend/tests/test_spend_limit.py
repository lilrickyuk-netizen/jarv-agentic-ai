"""
Wave 1, cost control: everything JAI spends on AI in a London day is measured (text models through the router,
the live voice from each reply's usage), and at DAILY_SPEND_LIMIT_USD JAI stops spending: the router refuses
calls with SpendLimitReached (so a running mission pauses rather than failing) and the live voice is refused or
ended. A limit of 0 turns the cap off; the meter keeps counting.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.core import spend
from app.core.config import settings
from app.core.providers import CompletionRequest, CompletionResponse, Message


@pytest.fixture(autouse=True)
def _a_fresh_day():
    """Each test starts today's total at nothing (the test Redis may be shared between tests)."""
    async def clear():
        await (await spend._redis()).delete(spend.key())

    asyncio.run(clear())
    yield


def test_a_voice_reply_is_priced_from_its_audio_and_text_tokens():
    usage = {"input_token_details": {"audio_tokens": 600, "text_tokens": 2000, "cached_tokens": 1500,
                                     "cached_tokens_details": {"text_tokens": 1500, "audio_tokens": 0}},
             "output_token_details": {"audio_tokens": 1200, "text_tokens": 100}}
    # 600 audio in at $32, 500 uncached text at $4, 1500 cached at $0.40, 1200 audio out at $64, 100 text out at $16
    expected = (600 * 32 + 500 * 4 + 1500 * 0.40 + 1200 * 64 + 100 * 16) / 1_000_000
    assert spend.realtime_cost("gpt-realtime", usage) == pytest.approx(expected)
    assert spend.realtime_cost("gpt-realtime-2.1-mini", usage) < spend.realtime_cost("gpt-realtime", usage) / 2
    assert spend.realtime_cost("some-new-realtime", usage) == pytest.approx(expected)  # unlisted: flagship price


def test_a_text_call_is_priced_from_jais_price_table():
    cost = spend.text_cost("gpt-6-luna", {"prompt_tokens": 1_000_000, "completion_tokens": 100_000, "cached_tokens": 0})
    assert cost == pytest.approx(0.10 + 0.05)
    assert spend.text_cost("unlisted-model", {"prompt_tokens": 10}) is None


def test_the_london_day_decides_which_total_a_call_goes_to():
    assert spend.day(datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc)) == "2026-11-03"  # GMT in November
    assert spend.day(datetime(2026, 7, 3, 23, 30, tzinfo=timezone.utc)) == "2026-07-04"   # BST in July


def test_spending_is_totalled_and_the_limit_stops_more(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_SPEND_LIMIT_USD", 1.0)

    async def run():
        await spend.record("text", 0.40)
        await spend.record("voice", 0.35)
        before = await spend.today()
        await spend.check()  # 0.75 of 1.00: allowed
        await spend.record("voice", 0.30)
        after = await spend.today()
        try:
            await spend.check()
        except spend.SpendLimitReached as exc:
            return before, after, str(exc)
        return before, after, None

    before, after, refused = asyncio.run(run())
    assert before["total_usd"] == pytest.approx(0.75) and before["remaining_usd"] == pytest.approx(0.25)
    assert after["voice_usd"] == pytest.approx(0.65) and after["calls"] == 3 and after["limit_reached"] is True
    assert refused and "Today's AI spending limit is reached: $1.05 of $1.00" in refused


def test_a_limit_of_zero_measures_but_never_stops(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_SPEND_LIMIT_USD", 0)

    async def run():
        await spend.record("text", 50.0)
        await spend.check()
        return await spend.today()

    state = asyncio.run(run())
    assert state["total_usd"] == pytest.approx(50.0) and state["limit_usd"] is None and not state["limit_reached"]


def test_the_router_counts_each_call_and_refuses_at_the_limit(monkeypatch):
    from app.core.providers.router import ModelRouter

    monkeypatch.setattr(settings, "DAILY_SPEND_LIMIT_USD", 0.20)

    class Provider:
        provider_name = "openai"
        calls = 0

        async def complete(self, request):
            Provider.calls += 1
            return CompletionResponse(id="r", model="gpt-6-luna", content="ok", tool_calls=[],
                                      usage={"prompt_tokens": 1_000_000, "completion_tokens": 0})

        def estimate_cost(self, request, response):
            return 0.0

    router = ModelRouter.__new__(ModelRouter)
    router.providers = {"openai": Provider()}
    router._resting_until = {}
    monkeypatch.setattr(router, "plan", lambda model: [("openai", model)])
    request = CompletionRequest(model="gpt-6-luna", messages=[Message(role="user", content="hi")])

    async def run():
        await router.complete(request)          # $0.10
        await router.complete(request)          # $0.20: the limit is now reached
        try:
            await router.complete(request)
        except spend.SpendLimitReached as exc:
            return await spend.today(), exc
        return await spend.today(), None

    state, refused = asyncio.run(run())
    assert Provider.calls == 2 and refused is not None   # the third call never reached the provider
    assert state["text_usd"] == pytest.approx(0.20) and state["calls"] == 2


def test_the_live_voice_is_ended_and_refused_at_the_limit(monkeypatch):
    from app.core.voice import live

    monkeypatch.setattr(settings, "DAILY_SPEND_LIMIT_USD", 0.05)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(settings, "OPENAI_REALTIME_MODEL", "gpt-realtime")
    reply = {"input_token_details": {"audio_tokens": 600}, "output_token_details": {"audio_tokens": 1200}}

    async def run():
        first = await live.record_usage(reply)     # about $0.096: over $0.05
        try:
            await live.create_session(None, None)   # refused before anything else is touched
        except live.LiveUnavailable as exc:
            return first, str(exc)
        return first, None

    first, refused = asyncio.run(run())
    assert first["stop"] is True and "spending limit is reached" in first["reason"]
    assert refused and "live conversation cannot start" in refused
