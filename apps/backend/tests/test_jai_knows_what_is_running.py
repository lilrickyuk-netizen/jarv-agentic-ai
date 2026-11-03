"""
JAI said no mission was running while the MYCO acceptance mission was between two rounds (status
needs_continuation): its voice counted only running, queued and recovering. Every way JAI answers "what's going
on" now counts a mission as in progress for as long as it is being worked on, and each conversation opens with
what is running and an instruction to check before answering.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.runtime import lifecycle
from app.core.voice import engine, live
from app.models.task import Task
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e4c_voice import _seed


async def _with(status: str, **result):
    from app.models.company_operations import LiveOperationsFeedItem

    async with AsyncTestingSessionLocal() as db:
        owner, ws_id = await _seed(db)
        db.add(Task(id=uuid4(), workspace_id=ws_id, title="Earlier mission", task_type="command",
                    status="completed", priority=5, meta_data={}, result={"response": "All done earlier."}))
        task = Task(id=uuid4(), workspace_id=ws_id, title="Bring MYCO Phase 0 into conformance",
                    task_type="command", status=status, priority=5, meta_data={},
                    result={"response": "Round 1 stopped at its step limit.", **result})
        db.add(task)
        await db.flush()
        now = datetime.now(timezone.utc)
        db.add(LiveOperationsFeedItem(id=uuid4(), workspace_id=ws_id, item_type="tool", severity="info",
                                      title="Tool: run_command", message="pnpm install --frozen-lockfile",
                                      related_task_id=task.id, requires_action=False, created_at=now,
                                      updated_at=now))
        await db.commit()
        mission = await live.run_tool(db, owner, "get_mission", {})
        status = await live.run_tool(db, owner, "get_status", {})
        recent = await live._recent_missions(db, owner)
        opening = await live.situation_block(db, owner)
        return mission, status, recent, opening


@pytest.mark.parametrize("status", [lifecycle.NEEDS_CONTINUATION, lifecycle.RUNNING, lifecycle.PENDING,
                                    lifecycle.QUEUED, "in_progress"])
def test_a_mission_being_worked_on_is_reported_as_in_progress(status):
    mission, reply, recent, opening = asyncio.run(_with(status, continuation_count=2))
    assert mission["in_progress"] is True and mission["title"].startswith("Bring MYCO")
    assert "result" not in mission  # the last round's report is not the result
    assert any("pnpm install" in line for line in mission["latest_activity"])
    assert reply["in_flight"] >= 1 and reply["running"] == ["Bring MYCO Phase 0 into conformance"]
    assert "Bring MYCO Phase 0" in reply["reply"] and "nothing is running" not in reply["reply"]
    current = next(m for m in recent if m["title"].startswith("Bring MYCO"))
    assert current["in_progress"] is True and "last_report" not in current
    assert "Missions in progress:" in opening and "Bring MYCO Phase 0" in opening and "pnpm install" in opening


def test_between_rounds_is_said_plainly():
    mission, _, recent, opening = asyncio.run(_with(lifecycle.NEEDS_CONTINUATION, continuation_count=2))
    assert mission["rounds_done"] == 2 and "next is queued" in mission["note"]
    assert next(m for m in recent if m.get("in_progress"))["between_rounds"] is True
    assert "between rounds, next round queued" in opening


def test_a_finished_mission_is_not_in_progress():
    mission, reply, _, opening = asyncio.run(_with(lifecycle.COMPLETED))
    assert "in_progress" not in mission and mission["result"].startswith("Round 1")
    assert "nothing is running" in reply["reply"]
    assert "No mission is in progress." in opening


def test_jai_checks_before_saying_what_is_running():
    text = live.instructions([])
    assert "before you say whether anything is running" in text and "never answer it from memory" in text
    assert engine.strip_wake("Jay, talk to me")[1] is True
