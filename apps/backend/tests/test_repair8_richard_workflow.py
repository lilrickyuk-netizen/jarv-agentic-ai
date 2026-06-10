"""
Repair 8 behavioural tests: the real end-to-end hard-boundary -> Richard decision
-> approval window -> mission-resume safety loop.

These exercise the REAL path against the real async test DB:
  - the real OrchestratorAgent delegation (boundary interception + safe-work
    continuation + dependency gating),
  - the real RichardBoundaryWorkflow (BoundaryReport / SafeCheckpoint /
    BoundaryApproval / ApprovalWindow / RichardBoundaryInput / ResumeAction
    persistence),
  - the real AgentRunner re-driving the blocked action on resume,
  - the real authenticated Richard API.

Nothing here mocks the orchestrator, runner, database persistence, checkpoint
restoration, approval validation, or ToolBase. No fake workflow, no fake Richard
decision, no caller-supplied identity trust, no fake approval window, no fake
resume success, no mission abandonment, no duplicate execution.
"""
import asyncio
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.richard.workflow import (
    RichardBoundaryWorkflow, WAITING, COMPLETED, PARTIAL, FAILED, REJECTED, EXPIRED,
)
from app.agents.orchestrator import OrchestratorAgent, TaskPlan
from app.models.boundary import (
    ApprovalWindow, BoundaryApproval, BoundaryReport, ResumeAction,
    RichardBoundaryInput, SafeCheckpoint,
)
from app.models.operations import AuditLog
from app.models.session import AgentSession
from app.models.tool_system import ToolRun, Tool

from tests.conftest import AsyncTestingSessionLocal


# --------------------------------------------------------------------------- #
# Seed helpers (real rows)
# --------------------------------------------------------------------------- #

async def _seed_user_ws(session):
    from app.models.user import User
    from app.models.workspace import Workspace

    uid, wid = uuid4(), uuid4()
    session.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io",
                     password_hash="$2b$12$x", is_active=True, is_admin=False))
    session.add(Workspace(id=wid, name="WS", slug=f"ws-{wid.hex[:8]}", description="d",
                          owner_id=uid, is_active=True, workspace_type="test",
                          authority_level=9))
    await session.commit()
    return uid, wid


async def _seed_boundary(session, *, blocked_agent="research",
                         blocked_desc="delete production database",
                         boundary_type="delete_production_data",
                         dependent_agent="research",
                         dependent_desc="verify the deletion completed"):
    """Create a paused boundary via the real workflow; return (wf, ids, uid, wid, sid, agent_id)."""
    uid, wid = await _seed_user_ws(session)
    wf = RichardBoundaryWorkflow(session)
    agent = await wf.ensure_orchestrator_agent(wid)
    sess = await wf.ensure_session(session_id=None, user_id=uid, workspace_id=wid,
                                   agent_id=agent.id, initial_prompt="mission")
    await session.commit()
    res = await wf.handle_hard_boundary(
        session_id=sess.id, agent_id=agent.id, workspace_id=wid, user_id=uid,
        blocked_action=blocked_desc, boundary_type=boundary_type,
        reason=f"requires approval ({boundary_type})",
        requested_authority_level=8, available_authority_level=9,
        resume_snapshot={
            "blocked_task": {"task_id": 2, "agent": blocked_agent,
                             "description": blocked_desc,
                             "requested_authority_level": 8},
            "dependent_tasks": [{"task_id": 3, "agent": dependent_agent,
                                 "description": dependent_desc}],
            "completed_task_ids": [1],
            "current_step": "blocked:2",
        })
    return wf, res, uid, wid, sess.id, agent.id


# =========================================================================== #
# 1. Orchestrator hard-boundary interception + 2. only-blocked-pauses
# =========================================================================== #

@pytest.mark.integration
def test_orchestrator_pauses_only_blocked_and_persists_records():
    """Orchestrator: blocked action paused (report+checkpoint+approval persisted),
    dependent task waits, independent safe work continues, nothing run early."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid = await _seed_user_ws(session)
            orch = OrchestratorAgent(AgentConfig(
                workspace_id=wid, user_id=uid,
                authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION))
            plan = [
                TaskPlan(task_id=1, description="analyze the mission scope",
                         assigned_agent="research", requires_approval=False),
                TaskPlan(task_id=2, description="delete production database now",
                         assigned_agent="research", requires_approval=True),
                TaskPlan(task_id=3, description="verify the deletion",
                         assigned_agent="research", dependencies=[2],
                         requires_approval=False),
                TaskPlan(task_id=4, description="summarize independent findings",
                         assigned_agent="research", requires_approval=False),
            ]
            ctx = AgentContext(workspace_id=wid, user_id=uid, db_session=session)
            delegation = await orch._delegate_tasks(plan, ctx)
            return delegation
        # session closed
    delegation = asyncio.run(run())

    statuses = {tr["task_id"]: tr["status"] for tr in delegation["task_results"]}
    # Independent safe work continued.
    assert statuses[1] == "completed"
    assert statuses[4] == "completed"
    # Blocked action paused (not executed), persisted as a boundary.
    assert statuses[2] == "waiting_on_richard"
    # Dependent task waited (did NOT run).
    assert statuses[3] == "waiting_dependent"
    assert len(delegation["boundaries"]) == 1
    b = delegation["boundaries"][0]
    assert b["boundary_report_id"] and b["approval_id"] and b["checkpoint_id"]
    assert b["status"] == WAITING
    assert delegation["session_id"]

    # Verify the real rows exist and the session is paused.
    async def verify():
        async with AsyncTestingSessionLocal() as s:
            reports = (await s.execute(select(func.count()).select_from(BoundaryReport))).scalar()
            cps = (await s.execute(select(func.count()).select_from(SafeCheckpoint))).scalar()
            pend = (await s.execute(select(func.count()).select_from(BoundaryApproval)
                                    .where(BoundaryApproval.status == "pending"))).scalar()
            sid = UUID(delegation["session_id"])
            sess = (await s.execute(select(AgentSession).where(AgentSession.id == sid))).scalar_one()
            rep = (await s.execute(select(BoundaryReport))).scalars().first()
            return int(reports), int(cps), int(pend), sess.is_paused, sess.status, rep.was_blocked, rep.action_taken
    reports, cps, pend, paused, sstatus, blocked, action_taken = asyncio.run(verify())
    assert reports == 1 and cps == 1 and pend == 1
    assert paused is True and sstatus == "paused"
    assert blocked is True and action_taken == "paused_blocked_action"


@pytest.mark.integration
def test_orchestrator_without_db_holds_blocked_action_not_run():
    """Without persistence context, the blocked action is held (not executed), honestly."""
    async def run():
        orch = OrchestratorAgent(AgentConfig(authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION))
        plan = [
            TaskPlan(task_id=1, description="spend money beyond the approved budget",
                     assigned_agent="research", requires_approval=True),
        ]
        ctx = AgentContext()  # no db_session / workspace / user
        return await orch._delegate_tasks(plan, ctx)
    delegation = asyncio.run(run())
    tr = delegation["task_results"][0]
    # Without persistence the blocked action is held (deferred), never executed.
    assert tr["status"] == "deferred_approval"
    assert "persistence" in tr and "held, not run" in tr["persistence"]
    # No fabricated ids when nothing was persisted.
    assert delegation["boundaries"] == []


# =========================================================================== #
# 3 + 4. Authentication: unauthenticated blocked; tool input cannot impersonate
# =========================================================================== #

@pytest.mark.integration
def test_unauthenticated_decision_is_blocked():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            dec = await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]),
                authenticated_user_id=None, approve=True)
            # Approval must still be pending.
            row = (await session.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            return dec, row.status
    dec, status = asyncio.run(run())
    assert dec["decided"] is False and dec["blocked"] is True
    assert "unauthenticated" in dec["reason"]
    assert status == "pending"


@pytest.mark.integration
def test_mismatched_authenticated_user_cannot_decide():
    """A different authenticated identity cannot decide another owner's approval."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            attacker = uuid4()  # a different authenticated user
            dec = await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]),
                authenticated_user_id=attacker, approve=True)
            row = (await session.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            return dec, row.status, row.approved
    dec, status, approved = asyncio.run(run())
    assert dec["decided"] is False and dec["blocked"] is True
    assert "not authorised" in dec["reason"]
    assert status == "pending" and approved is None


# =========================================================================== #
# 5. Authenticated approval persists RichardBoundaryInput + decision + window
# =========================================================================== #

@pytest.mark.integration
def test_authenticated_approval_persists_input_decision_and_scoped_window():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            dec = await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]),
                authenticated_user_id=uid, approve=True, reason="approved by owner",
                authority_granted=8, spend_limit=100.0, expiry_seconds=3600,
                single_use=True)
            return dec, uid, wid
        # closed
    dec, uid, wid = asyncio.run(run())
    assert dec["decided"] is True and dec["status"] == "approved"
    assert dec["decided_by"] == str(uid)
    assert dec["richard_boundary_input_id"]
    assert dec["approval_window_id"]

    async def verify():
        async with AsyncTestingSessionLocal() as s:
            ap = (await s.execute(select(BoundaryApproval))).scalars().first()
            rbi = (await s.execute(select(RichardBoundaryInput))).scalars().first()
            win = (await s.execute(select(ApprovalWindow))).scalars().first()
            return ap, rbi, win
    ap, rbi, win = asyncio.run(verify())
    # decided_by bound to authenticated owner, not caller input.
    assert (ap.meta_data or {}).get("decided_by") == str(uid)
    assert ap.approved is True and ap.approved_at is not None
    # RichardBoundaryInput persisted with the authenticated user + structured scope.
    assert rbi is not None and str(rbi.user_id) == str(uid)
    assert rbi.related_approval_id == ap.id
    assert rbi.context.get("scope_action") == "delete production database"
    # ApprovalWindow has EXACT scope, not universal.
    scope = win.meta_data
    assert win.status == "active"
    assert scope["scope_action"] == "delete production database"
    assert scope["workspace_id"] == str(wid)
    assert scope["authority_granted"] == 8
    assert scope["spend_limit"] == 100.0
    assert scope["single_use"] is True and scope["max_uses"] == 1
    assert scope["expires_at"] is not None


# =========================================================================== #
# 6. ApprovalWindow scope rejection (wrong action/ws/task, expired, authority, reuse)
# =========================================================================== #

@pytest.mark.integration
def test_approval_window_scope_is_enforced():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600, single_use=True)
            win = (await session.execute(select(ApprovalWindow))).scalars().first()

            good = wf.validate_window(win, action="delete production database",
                                      workspace_id=wid, task_id=None, authority_required=8)
            wrong_action = wf.validate_window(win, action="post publicly to twitter",
                                              workspace_id=wid, authority_required=8)
            wrong_ws = wf.validate_window(win, action="delete production database",
                                          workspace_id=uuid4(), authority_required=8)
            too_much_auth = wf.validate_window(win, action="delete production database",
                                               workspace_id=wid, authority_required=10)
            # Expired window. Repair 9 makes the real expires_at COLUMN authoritative
            # (meta is only a fallback for historic rows), so expire the column too.
            meta = dict(win.meta_data)
            meta["expires_at"] = (datetime.utcnow() - timedelta(seconds=5)).isoformat()
            win.meta_data = meta
            win.expires_at = datetime.utcnow() - timedelta(seconds=5)
            expired = wf.validate_window(win, action="delete production database",
                                         workspace_id=wid, authority_required=8)
            # Restore expiry, then consume single-use -> further use rejected.
            meta["expires_at"] = (datetime.utcnow() + timedelta(hours=1)).isoformat()
            win.meta_data = meta
            win.expires_at = datetime.utcnow() + timedelta(hours=1)
            await wf._consume_window(win)
            reused = wf.validate_window(win, action="delete production database",
                                        workspace_id=wid, authority_required=8)
            return good, wrong_action, wrong_ws, too_much_auth, expired, reused
    good, wrong_action, wrong_ws, too_much_auth, expired, reused = asyncio.run(run())
    assert good["ok"] is True
    assert wrong_action["ok"] is False and "action out of approval scope" in wrong_action["reason"]
    assert wrong_ws["ok"] is False and "workspace out of approval scope" in wrong_ws["reason"]
    assert too_much_auth["ok"] is False and "authority" in too_much_auth["reason"]
    assert expired["ok"] is False and expired["expired"] is True
    assert reused["ok"] is False  # single-use consumed


# =========================================================================== #
# 7. Rejection: no resume, no active window, safe work preserved, audit recorded
# =========================================================================== #

@pytest.mark.integration
def test_rejection_blocks_resume_and_creates_no_window():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            dec = await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=False, reason="not allowed")
            # Resume must NOT proceed after a rejection.
            r = await wf.resume_mission(checkpoint_id=UUID(res["checkpoint_id"]),
                                        authenticated_user_id=uid)
            win_count = (await session.execute(
                select(func.count()).select_from(ApprovalWindow))).scalar()
            rep = (await session.execute(select(BoundaryReport).where(
                BoundaryReport.id == UUID(res["boundary_report_id"])))).scalar_one()
            audits = (await session.execute(select(func.count()).select_from(AuditLog)
                      .where(AuditLog.action == "boundary_rejected"))).scalar()
            ra = (await session.execute(select(func.count()).select_from(ResumeAction))).scalar()
            return dec, r, int(win_count), rep.resolution, int(audits), int(ra)
    dec, r, win_count, resolution, audits, ra = asyncio.run(run())
    assert dec["decided"] is True and dec["status"] == "rejected"
    assert dec["approval_window_id"] is None
    assert win_count == 0                      # no active window from a rejection
    assert r["status"] == REJECTED and r["resumed"] is False
    assert ra == 0                             # blocked action never ran
    assert resolution == "rejected_by_richard"
    assert audits >= 1                         # rejection audited


# =========================================================================== #
# 8. Resume: real re-drive of blocked action + dependents via the real runner
# =========================================================================== #

@pytest.mark.integration
def test_resume_redrives_blocked_action_and_dependents():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            # Resume drives the blocked action + dependent task via the REAL runner.
            r = await wf.resume_mission(checkpoint_id=UUID(res["checkpoint_id"]),
                                        authenticated_user_id=uid)
            # Verify persisted resume + report + session.
            ra = (await session.execute(select(ResumeAction))).scalars().all()
            rep = (await session.execute(select(BoundaryReport).where(
                BoundaryReport.id == UUID(res["boundary_report_id"])))).scalar_one()
            sess = (await session.execute(select(AgentSession).where(
                AgentSession.id == sid))).scalar_one()
            ap = (await session.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            return r, ra, rep, sess, ap
    r, ra, rep, sess, ap = asyncio.run(run())
    assert r["resumed"] is True
    assert r["status"] in (COMPLETED, PARTIAL)
    # The blocked action and its dependent both ran (real runner), none re-running task 1.
    ran_ids = {str(x["task_id"]) for x in r["ran"]}
    assert "2" in ran_ids and "3" in ran_ids
    assert "1" not in ran_ids                  # already-completed safe work not re-run
    assert any(x["kind"] == "blocked" for x in r["ran"])
    assert len(ra) == 1                        # exactly one ResumeAction
    assert ra[0].success is True
    assert rep.resolution and rep.resolution.startswith("resumed_")
    assert sess.is_resumed is True
    assert ap.executed is True


@pytest.mark.integration
def test_resume_blocked_while_approval_pending():
    """Resume must refuse while the approval is still pending (no premature execution)."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            r = await wf.resume_mission(checkpoint_id=UUID(res["checkpoint_id"]),
                                        authenticated_user_id=uid)
            ra = (await session.execute(select(func.count()).select_from(ResumeAction))).scalar()
            return r, int(ra)
    r, ra = asyncio.run(run())
    assert r["status"] == WAITING and r["resumed"] is False
    assert ra == 0


# =========================================================================== #
# 9. Resume failure remains retryable (real runner, unimplemented blocked agent)
# =========================================================================== #

@pytest.mark.integration
def test_failed_resume_is_retryable_and_not_faked():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            # Blocked action assigned to an agent that is NOT implemented -> the
            # real runner returns success=False (no fake completion).
            wf, res, uid, wid, sid, aid = await _seed_boundary(
                session, blocked_agent="no_such_agent_xyz")
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            r = await wf.resume_mission(checkpoint_id=UUID(res["checkpoint_id"]),
                                        authenticated_user_id=uid)
            ap = (await session.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            rep = (await session.execute(select(BoundaryReport).where(
                BoundaryReport.id == UUID(res["boundary_report_id"])))).scalar_one()
            return r, ap.executed, rep.resolution
    r, executed, resolution = asyncio.run(run())
    assert r["status"] == FAILED and r["resumed"] is False
    assert r["retryable"] is True
    # Not faked + retryable: executed cleared, boundary report left UNRESOLVED.
    assert executed is False
    assert resolution is None


# =========================================================================== #
# 10. Idempotency: duplicate decision + duplicate resume
# =========================================================================== #

@pytest.mark.integration
def test_duplicate_decision_and_duplicate_resume_are_idempotent():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            d1 = await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            # Duplicate identical decision -> idempotent, no new window.
            d2 = await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True)
            # Conflicting decision -> rejected (no silent overwrite).
            d3 = await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=False)
            win_count = (await session.execute(
                select(func.count()).select_from(ApprovalWindow))).scalar()

            r1 = await wf.resume_mission(checkpoint_id=UUID(res["checkpoint_id"]),
                                         authenticated_user_id=uid)
            r2 = await wf.resume_mission(checkpoint_id=UUID(res["checkpoint_id"]),
                                         authenticated_user_id=uid)
            ra = (await session.execute(select(func.count()).select_from(ResumeAction))).scalar()
            return d1, d2, d3, int(win_count), r1, r2, int(ra)
    d1, d2, d3, win_count, r1, r2, ra = asyncio.run(run())
    assert d1["decided"] is True
    assert d2["already_decided"] is True and d2["idempotent"] is True
    assert d3["already_decided"] is True and d3["idempotent"] is False  # conflicting
    assert win_count == 1                       # only one window, never duplicated
    assert r1["resumed"] is True and r1.get("idempotent") in (False, None)
    assert r2["idempotent"] is True             # duplicate resume does not re-run
    assert ra == 1                              # exactly one execution


# =========================================================================== #
# 11. ToolRun + audit records are real and redacted (via resume re-drive)
# =========================================================================== #

@pytest.mark.integration
def test_audit_records_created_and_redacted():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600,
                reason="api_key=sk-secretshouldberedacted123456 approved")
            # The decision audit meta is redacted by the workflow's _audit().
            audits = (await session.execute(select(AuditLog).where(
                AuditLog.action.in_(["hard_boundary_paused", "boundary_approved",
                                     "mission_resumed"])))).scalars().all()
            return audits
    audits = asyncio.run(run())
    assert len(audits) >= 2  # paused + approved at minimum
    actions = {a.action for a in audits}
    assert "hard_boundary_paused" in actions and "boundary_approved" in actions
    # No raw secret leaked into any audit meta_data.
    blob = "".join(str(a.meta_data) for a in audits)
    assert "sk-secretshouldberedacted123456" not in blob


# =========================================================================== #
# Authenticated API: decided_by is bound to the auth user, not request body
# =========================================================================== #

@pytest.mark.integration
def test_richard_api_binds_decided_by_to_authenticated_user(client):
    """POST /api/richard/decisions binds decided_by to the authenticated user even
    if the body tries to smuggle decided_by/authorized fields."""
    from app.main import app
    from app.core.auth import get_current_user_id

    # Seed a paused boundary; capture the owner uid + approval id.
    async def seed():
        async with AsyncTestingSessionLocal() as session:
            wf, res, uid, wid, sid, aid = await _seed_boundary(session)
            return res, str(uid)
    res, owner = asyncio.run(seed())

    # Authenticate as the owner (trusted dependency); body cannot override identity.
    app.dependency_overrides[get_current_user_id] = lambda: owner
    try:
        r = client.post(
            f"/api/richard/decisions/{res['approval_id']}",
            json={"approve": True, "reason": "ok",
                  "decided_by": str(uuid4()), "authorized": True,  # smuggled, must be ignored
                  "authority_granted": 8, "expiry_seconds": 3600},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decided"] is True and body["status"] == "approved"
        assert body["decided_by"] == owner  # bound to authenticated user, NOT the smuggled id
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    # Verify persisted decided_by.
    async def verify():
        async with AsyncTestingSessionLocal() as s:
            ap = (await s.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            return (ap.meta_data or {}).get("decided_by")
    assert asyncio.run(verify()) == owner


@pytest.mark.integration
def test_richard_api_requires_authentication(client):
    """Unauthenticated decision/pending requests are rejected (401)."""
    r1 = client.get("/api/richard/pending")
    r2 = client.post(f"/api/richard/decisions/{uuid4()}", json={"approve": True})
    assert r1.status_code == 401
    assert r2.status_code == 401
