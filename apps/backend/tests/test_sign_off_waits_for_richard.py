"""
A finished mission whose last step is Richard's sign-off ends as one approval on his Approvals page, not as another
round of work. On 9 November the MYCO Phase 0 tidy-up was done and verified, but its last item waited on Richard's
manual review: JAI kept re-running the team and made six commits that only re-proved finished work, and Richard had
no way to give the sign-off.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.core.command import failures, ledger, sign_off
from app.core.command.mission_org import _judged
from app.core.command.service import CommandService

REQS = [{"id": "R1", "text": "Fresh clone verifies", "status": "open"},
        {"id": "R5", "text": "Complete the Phase Acceptance Workflow", "status": "open"},
        {"id": "R6", "text": "Lint passes", "status": "open"}]


def test_what_only_richard_can_do_is_waiting_not_a_failure():
    assert failures.classify("R5: waiting on Richard's §50 manual review and the acceptance tag") == "richard"
    assert failures.classify("Outstanding: Richard §50 manual review") == "richard"
    assert failures.classify("bash: syft: command not found") == "environment"  # unchanged
    assert failures.is_gate("his manual review and creating the acceptance tag")
    assert not failures.is_gate("the unit tests still fail")


def test_the_verifier_can_say_a_requirement_waits_on_richard_but_only_for_a_real_gate():
    verdict = {"success": True, "answer": "R1: done — clone verified twice\n"
                                          "R5: waiting — Richard's §50 manual review and the acceptance tag\n"
                                          "R6: waiting — still need to fix two lint errors"}
    judged = _judged(verdict, REQS)
    assert [w.split(" ", 1)[0] for w in judged["waiting"]] == ["R5"]
    assert [u.split(" ", 1)[0] for u in judged["unmet"]] == ["R6"]  # "waiting" for ordinary work is unfinished work
    assert next(c for c in judged["checks"] if c["requirement"].startswith("R5")).get("waiting") is True


def test_a_ledger_item_blocked_on_richard_is_waiting_and_not_listed_as_a_failure():
    from app.core.workspaces.fs_inspector import SANDBOX_CONTAINER_ROOT

    name = f"sign-off-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    (folder / ".jai").mkdir(parents=True)
    (folder / ".jai" / "ledger.json").write_text(json.dumps({"phase": "Phase 0", "items": [
        {"id": "R1", "text": "Builds", "check": "task build", "passes": True, "blocked": None},
        {"id": "R5", "text": "Acceptance workflow", "check": "task phase -- 00", "passes": False,
         "blocked": {"class": "richard", "error": "", "needs": "Richard's §50 manual review, then the tag"}},
        {"id": "R6", "text": "SBOM", "check": "task sbom", "passes": False, "blocked": None}]}))
    root = f"/test_workspaces/{name}"
    try:
        reqs = ledger.requirements(root, "Carry on with MYCO Phase 0")
        assert [(r["id"], r["status"]) for r in reqs] == [("R1", "done"), ("R5", "waiting"), ("R6", "open")]
        assert [r["status"] for r in sign_off.reopen(reqs)] == ["done", "open", "open"]  # after his approval
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_a_verified_mission_waiting_on_richard_stops_as_one_approval():
    result = {"success": True, "needs_continuation": False,
              "verification": {"verified": True, "unmet": [], "waiting_on_richard": ["R5 Acceptance: Richard's review"]}}
    assert sign_off.waiting(result) == ["R5 Acceptance: Richard's review"]
    assert sign_off.waiting({**result, "success": False}) == []  # unfinished work is never sent to him as a sign-off
    status, failure = CommandService()._derive_status(
        "agent_task", {"waiting_on_richard": sign_off.waiting(result), "agent_success": True}, [], "report")
    assert status == "blocked" and "Approve" in failure["reason"] and "nothing is pushed" in failure["reason"]

    task = SimpleNamespace(meta_data={"operator": "richard"})
    sign_off.mark(task, sign_off.waiting(result))
    assert task.meta_data["boundary_type"] == sign_off.BOUNDARY and task.meta_data["blocked_reason"]
    assert not sign_off.granted(task.meta_data)  # not until he approves it


def test_approving_the_sign_off_carries_the_same_mission_on_to_the_last_step_only():
    meta = {"boundary_type": sign_off.BOUNDARY, "waiting_on_richard": ["R5 Acceptance: Richard's review, then the tag"]}
    meta = sign_off.on_approve({**meta, "approval_grant": {"single_mission": True}})
    assert meta["resume_mode"] == "continuation" and sign_off.granted(meta)
    note, reqs = sign_off.resume([{"id": "R1", "status": "done"}, {"id": "R5", "status": "waiting"}], meta)
    assert sign_off.APPROVED in note and "do not redo" in note and "pushing" in note
    assert [r["status"] for r in reqs] == ["done", "open"]
    assert not sign_off.granted({**meta, "sign_off_used_at": "2026-11-09T10:40:00"})  # used once
    assert sign_off.on_approve({"boundary_type": "spend_money"}).get("resume_mode") is None  # other approvals unchanged


def test_the_builder_and_verifier_are_told_how_to_report_a_step_that_waits_on_richard():
    from app.core.command.mission_org import SPECIALISTS
    from app.core.command.sandbox_engine import builder_method

    assert '"class": "richard"' in builder_method("Carry on with MYCO Phase 0")
    assert "Never re-run or re-record finished work" in builder_method("Carry on with MYCO Phase 0")
    assert "waiting, not open" in SPECIALISTS["verifier"]["standard"]
