"""
A new mission carries on from the last unfinished one in its workspace (real Task rows): its requirements with
their statuses and evidence, and where it left off; a mission about new work, or after a verified one, starts fresh.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.core.command.resume import carried, last_state, wants_to_carry_on
from app.models.task import Task
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair11_memory_learning import _seed

PHASE0 = ("Carry on building MYCO from Phase 0 where the last mission left off. Complete Phase 0 using the spec's "
          "Phase Acceptance Workflow. Do not start Phase 1.")
EARLIER = {
    "response": "Stopped: P2 ran out of budget.",
    "requirements": [
        {"id": "R1", "text": "Monorepo with pnpm workspaces", "status": "done", "evidence": "pnpm -r build passed"},
        {"id": "R2", "text": "task verify passes from a fresh clone", "status": "open", "evidence": ""},
        {"id": "R3", "text": "SBOM with Syft 1.52.0", "status": "waiting", "evidence": ""}],
    "verification": {"verified": False, "unmet": ["R2: fresh clone fails at task sbom"]},
    "team": {"packages": [
        {"id": "P1", "role": "Senior Software Engineer", "title": "Workspace layout", "success": True,
         "summary": "pnpm workspaces and tsconfig set up"},
        {"id": "P2", "role": "DevOps Engineer", "title": "Supply-chain checks", "success": False,
         "summary": "stopped at its spending limit"}]},
}


def test_a_brief_that_says_carry_on_or_names_the_same_phase_carries_on():
    assert wants_to_carry_on(PHASE0, "Build MYCO Phase 0")
    assert wants_to_carry_on("Complete Phase 0 of MYCO", "Build MYCO Phase 0")
    assert not wants_to_carry_on("Make a launch video for Plexecute 2", "Build MYCO Phase 0")


def test_done_work_keeps_its_evidence_and_the_rest_is_open_again():
    task = Task(id=uuid4(), title="Phase 0", task_type="command", workspace_id=uuid4(), status="failed")
    out = carried(EARLIER["requirements"], task)
    assert [r["status"] for r in out] == ["done", "open", "open"]
    assert out[0]["evidence"].endswith("pnpm -r build passed") and "mission" in out[0]["evidence"]


def test_a_new_mission_takes_over_the_last_unfinished_ones_state():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws, _ = await _seed(db)
            earlier = Task(id=uuid4(), title="MYCO Phase 0", description="Build MYCO Phase 0", task_type="command",
                           workspace_id=ws, status="failed", result=EARLIER,
                           error_message="Agent reached maximum budget limit ($6.0000)")
            current = Task(id=uuid4(), title="Carry on", description=PHASE0, task_type="command", workspace_id=ws,
                           status="running")
            db.add_all([earlier, current])
            await db.commit()
            resumed = await last_state(db, ws, current.id, PHASE0)
            fresh = await last_state(db, ws, current.id, "Make a launch video for Plexecute 2")
            earlier.result = {**EARLIER, "verification": {"verified": True, "unmet": []}}
            await db.commit()
            after_verified = await last_state(db, ws, current.id, PHASE0)
            return earlier.id, resumed, fresh, after_verified

    earlier_id, resumed, fresh, after_verified = asyncio.run(run())
    assert resumed["task_id"] == str(earlier_id)
    assert {r["id"]: r["status"] for r in resumed["requirements"]} == {"R1": "done", "R2": "open", "R3": "open"}
    known = resumed["known"]
    assert "WHERE THE LAST MISSION LEFT OFF" in known and "do not redo finished work" in known
    assert "Requirements done (1): R1" in known and "Still open (2): R2, R3" in known
    assert "P2 DevOps Engineer — Supply-chain checks: stopped" in known and "fresh clone fails" in known
    assert "maximum budget limit" in known
    assert fresh is None and after_verified is None


def test_a_cancelled_mission_is_carried_on_from_its_live_progress_past_other_work_in_the_workspace():
    """8 November: MYCO missions run in the Command Center workspace were cancelled, so they saved no final
    record, and newer unrelated commands sat in between."""
    from app.core.command import progress

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws, _ = await _seed(db)
            myco = Task(id=uuid4(), title="MYCO Phase 0", task_type="command", workspace_id=ws, status="cancelled",
                        description=r"Build MYCO Phase 0. The MYCO workspace folder is C:\Users\lilri\Projects\MYCO.")
            other = Task(id=uuid4(), title="Acceptance", task_type="command", workspace_id=ws, status="failed",
                         description=r"Fix the calculator in C:\Users\lilri\Projects\_jai_acceptance",
                         result={"requirements": [{"id": "R1", "text": "calc", "status": "open", "source": "mission"}]})
            chat = Task(id=uuid4(), title="Explain the upgrades", task_type="command", workspace_id=ws,
                        status="cancelled", description="Explain all the upgrades JAI has had")
            db.add_all([myco, other, chat])
            await db.commit()
            await progress.save(myco.id, {"requirements": {"total": 2, "items": [
                {"id": "R1", "text": "pnpm workspaces", "status": "done", "evidence": "pnpm -r build passed"},
                {"id": "R2", "text": "task verify from a fresh clone", "status": "open", "evidence": ""}]},
                "team": {"packages": [{"id": "P1", "role": "DevOps Engineer", "title": "CI", "success": False,
                                       "summary": "stopped at its spending limit"}]}})
            brief = PHASE0 + r" The MYCO workspace folder is C:\Users\lilri\Projects\MYCO."
            return myco.id, await last_state(db, ws, uuid4(), brief)

    myco_id, resumed = asyncio.run(run())
    assert resumed and resumed["task_id"] == str(myco_id)  # past the acceptance work and the chat
    assert {r["id"]: r["status"] for r in resumed["requirements"]} == {"R1": "done", "R2": "open"}
    assert all(r["source"] == "mission" for r in resumed["requirements"])
    assert "P1 DevOps Engineer — CI: stopped" in resumed["known"]
