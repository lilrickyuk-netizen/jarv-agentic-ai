"""
ICM-style recall in JAI's own memory: a question that names a period searches that period, old unimportant
memories fade (critical ones and the records JAI must keep never do), and a reworded memory updates the one it
repeats while different facts stay separate. Real memories on PostgreSQL; the embedder is JAI's local one, or a
fixed vector where the test needs two texts to be near-identical.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.jarv_memory import memory_service
from app.core.memory.recall import date_window, fade, same_fact, without_phrase
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair11_memory_learning import _seed

SUNDAY = datetime(2026, 11, 8, 9, 30, tzinfo=timezone.utc)


def test_a_question_that_names_a_period_searches_that_period():
    start, end, phrase = date_window("what did we decide last week about auth", SUNDAY)
    assert (start.date().isoformat(), end.date().isoformat(), phrase) == ("2026-10-26", "2026-11-02", "last week")
    assert without_phrase("what did we decide last week about auth", phrase) == "what did we decide about auth"
    start, end, _ = date_window("errors in the past 3 days", SUNDAY)
    assert start.date().isoformat() == "2026-11-05"
    start, end, _ = date_window("what happened in October", SUNDAY)
    assert start == datetime(2026, 9, 30, 23, tzinfo=timezone.utc)  # midnight, 1 October, London summer time
    assert date_window("notes from December", SUNDAY)[0].year == 2025  # the last December, not the next
    assert date_window("marketing ideas for the launch", SUNDAY) is None
    assert without_phrase("this month", "this month") == ""


def test_old_trivial_memories_fade_and_what_jai_must_keep_never_does():
    old = SUNDAY - timedelta(days=200)
    assert fade(0.2, "task", old, None, SUNDAY) < fade(0.6, "task", old, None, SUNDAY) < 1.0
    assert fade(0.95, "task", old, None, SUNDAY) == 1.0
    assert fade(0.1, "decision", old, None, SUNDAY) == fade(0.1, "boundary", old, None, SUNDAY) == 1.0
    assert fade(0.1, "task", old - timedelta(days=5000), None, SUNDAY) == 0.3  # ranked lower, never lost
    assert fade(0.2, "task", old, SUNDAY - timedelta(hours=1), SUNDAY) > 0.99  # recalling it refreshes it


def test_only_rewordings_of_the_same_fact_are_merged():
    assert same_fact("Auth uses short-lived JWTs refreshed via /auth/refresh",
                     "Auth relies on short-lived JWTs, refreshed through /auth/refresh")
    assert not same_fact("Requirement R1 passed: build ok", "Requirement R2 passed: build ok")
    assert not same_fact("MYCO pins Node 22.11", "MYCO pins Node 24.1")


def _pg(db) -> bool:
    return db.get_bind().dialect.name == "postgresql"


@pytest.mark.integration
def test_recall_by_period_and_fading_on_real_memories():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            if not _pg(db):
                return None
            _, ws, _ = await _seed(db)
            now = datetime.now(timezone.utc)
            older = await memory_service.add(db, "Decided the webhook retry policy: five attempts with backoff.",
                                             memory_type="incident", workspace_id=ws, importance=0.4)
            older.created_at = older.updated_at = now - timedelta(days=400)
            newer = await memory_service.add(db, "Webhook retry policy reviewed again with backoff unchanged.",
                                             memory_type="incident", workspace_id=ws, importance=0.4)
            yesterday = await memory_service.add(db, "Stripe webhook signature check fixed in the billing service.",
                                                 memory_type="incident", workspace_id=ws, importance=0.4)
            yesterday.created_at = now - timedelta(days=1)
            await db.flush()
            ranked = await memory_service.search_scored(db, "webhook retry policy backoff", workspace_id=ws, limit=5,
                                                        touch=False)
            dated = await memory_service.search_scored(db, "the stripe webhook signature fix yesterday", workspace_id=ws,
                                                       limit=5, touch=False)
            return older, newer, yesterday, ranked, dated

    out = asyncio.run(run())
    if out is None:
        pytest.skip("needs PostgreSQL")
    older, newer, yesterday, ranked, dated = out
    order = [h.memory.id for h in ranked]
    assert order.index(newer.id) < order.index(older.id)  # the 400-day-old, low-importance one has faded
    assert dated and dated[0].memory.id == yesterday.id and "from yesterday" in dated[0].reasons


@pytest.mark.integration
def test_a_reworded_memory_updates_the_one_it_repeats_and_different_facts_stay_apart(monkeypatch):
    vector = [1.0] + [0.0] * 1535

    async def same_vector(text):
        return vector, "test:fixed-vector"

    monkeypatch.setattr(memory_service, "_embed", same_vector)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            if not _pg(db):
                return None
            _, ws, _ = await _seed(db)
            first = await memory_service.add(db, "Auth uses short-lived JWTs refreshed via /auth/refresh",
                                             memory_type="decision", workspace_id=ws, importance=0.6)
            reworded = await memory_service.add(db, "Auth relies on short-lived JWTs, refreshed through /auth/refresh",
                                                memory_type="decision", workspace_id=ws, importance=0.8)
            r1 = await memory_service.add(db, "Requirement R1 passed: build ok", memory_type="task", workspace_id=ws)
            r2 = await memory_service.add(db, "Requirement R2 passed: build ok", memory_type="task", workspace_id=ws)
            return first, reworded, r1, r2

    out = asyncio.run(run())
    if out is None:
        pytest.skip("needs PostgreSQL")
    first, reworded, r1, r2 = out
    assert reworded.id == first.id and reworded.version == 2
    assert reworded.content.startswith("Auth relies") and reworded.importance_score == 0.8
    assert reworded.meta_data["previous"][0]["content"].startswith("Auth uses")
    assert r1.id != r2.id  # a different requirement is a different fact
