"""
The voice reads JAI's live state before every reply and waits a few seconds for it. On 9 November, with a mission
running, the state took four seconds or more because Mem0 and Graphiti were asked only after everything else, and
every reply became "I can't read the live state just now". They are now asked alongside the rest.
"""
from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from app.core.voice import live
from tests.conftest import AsyncTestingSessionLocal


def test_what_richard_told_jai_is_recalled_while_the_rest_of_the_state_is_gathered(monkeypatch):
    async def slow_facts(db, user_id, text, workspace_id):
        await asyncio.sleep(0.4)
        return {"recent_missions": [], "recent_conversation": ["dropped"]}

    async def slow_recall(text, spaces):
        await asyncio.sleep(0.4)
        return {"what_richard_has_told_me": ["the banner is electric blue"]}

    monkeypatch.setattr(live, "brain_facts", slow_facts)
    monkeypatch.setattr(live, "_recalled", slow_recall)

    async def go():
        async with AsyncTestingSessionLocal() as db:
            started = time.monotonic()
            state = await live.live_context(db, uuid4(), "What colour is the banner?")
            return state, time.monotonic() - started

    state, took = asyncio.run(go())
    assert "electric blue" in state["state"] and "dropped" not in state["state"]
    assert took < 0.7, f"gathered one after the other ({took:.2f}s)"
