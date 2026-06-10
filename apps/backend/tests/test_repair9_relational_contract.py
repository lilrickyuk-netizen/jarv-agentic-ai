"""
Repair 9 behavioural + migration + API tests: the Design section 17 workspace/
task-centric relational contract for the hard-boundary / approval / checkpoint /
resume models, plus the authenticated, workspace-isolated Richard Boundary API.

These exercise the REAL path against the real async test DB and the REAL Repair-8
workflow. Nothing here mocks database persistence, relationships, the workflow
service, approval validation, resume execution, or authentication identity (auth is
only swapped via the established FastAPI dependency-override test pattern).

The migration tests drive the real Alembic ``upgrade()`` / ``downgrade()`` of the
Repair-9 revision against a SQLite database (the production base migrations require
pgvector, so the Repair-9 revision is applied in isolation over a minimal pre-9
schema — its DDL + backfill logic is the unit under test).
"""
import asyncio
import importlib.util
import json
import os
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select, func, text
from sqlalchemy.orm import sessionmaker

from app.core.richard.workflow import (
    RichardBoundaryWorkflow, COMPLETED, PARTIAL, REJECTED, EXPIRED, WAITING,
)
from app.core.richard.service import RichardBoundaryService, OK, NOT_FOUND, FORBIDDEN
from app.models.boundary import (
    ApprovalWindow, BoundaryApproval, BoundaryReport, ResumeAction,
    RichardBoundaryInput, SafeCheckpoint,
)
from app.models.session import AgentSession

from tests.conftest import AsyncTestingSessionLocal


# --------------------------------------------------------------------------- #
# Seed helpers (real rows, real workflow)
# --------------------------------------------------------------------------- #

async def _seed_user_ws(session, owner_id=None):
    from app.models.user import User
    from app.models.workspace import Workspace
    uid = owner_id or uuid4()
    wid = uuid4()
    session.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io",
                     password_hash="$2b$12$x", is_active=True, is_admin=False))
    session.add(Workspace(id=wid, name="WS", slug=f"ws-{wid.hex[:8]}", description="d",
                          owner_id=uid, is_active=True, workspace_type="test",
                          authority_level=9))
    await session.commit()
    return uid, wid


async def _seed_task(session, wid):
    from app.models.task import Task
    tid = uuid4()
    session.add(Task(id=tid, title="blocked task", description="d", workspace_id=wid,
                     status="pending", priority=5, task_type="test"))
    await session.commit()
    return tid


async def _seed_boundary(session, *, with_task=False, owner_id=None,
                         blocked_agent="research",
                         blocked_desc="delete production database",
                         boundary_type="delete_production_data",
                         dependent_agent="research",
                         dependent_desc="verify the deletion completed"):
    """Create a paused boundary via the real workflow with REAL relational scope."""
    uid, wid = await _seed_user_ws(session, owner_id)
    task_id = await _seed_task(session, wid) if with_task else None
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
        task_id=task_id,
        resume_snapshot={
            "blocked_task": {"task_id": 2, "agent": blocked_agent,
                             "description": blocked_desc,
                             "requested_authority_level": 8},
            "dependent_tasks": [{"task_id": 3, "agent": dependent_agent,
                                 "description": dependent_desc}],
            "completed_task_ids": [1],
            "current_step": "blocked:2",
        })
    return wf, res, uid, wid, sess.id, agent.id, task_id


# =========================================================================== #
# Schema + relationships (tests 1-8)
# =========================================================================== #

@pytest.mark.integration
def test_boundary_report_persists_workspace_task_session_columns():
    """1. BoundaryReport carries real workspace_id / task_id / session_id / created_by."""
    async def run():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            rep = (await s.execute(select(BoundaryReport).where(
                BoundaryReport.id == UUID(res["boundary_report_id"])))).scalar_one()
            return rep.workspace_id, rep.task_id, rep.session_id, rep.created_by, wid, tid, sid, uid
    ws, task, sess_id, created_by, wid, tid, sid, uid = asyncio.run(run())
    assert ws == wid                 # real workspace FK column, not JSON
    assert task == tid               # real task FK column
    assert sess_id == sid
    assert created_by == uid


@pytest.mark.integration
def test_approval_references_correct_report():
    """2. BoundaryApproval.boundary_report_id points at its report (+ inherits scope)."""
    async def run():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            ap = (await s.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            return ap.boundary_report_id, ap.workspace_id, ap.task_id, wid, tid, res["boundary_report_id"]
    brid, ws, task, wid, tid, report_id = asyncio.run(run())
    assert str(brid) == report_id
    assert ws == wid and task == tid


@pytest.mark.integration
def test_checkpoint_references_correct_task_and_session():
    """3. SafeCheckpoint carries session_id + task_id + report/approval links."""
    async def run():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            cp = (await s.execute(select(SafeCheckpoint).where(
                SafeCheckpoint.id == UUID(res["checkpoint_id"])))).scalar_one()
            return cp.session_id, cp.task_id, cp.workspace_id, cp.boundary_report_id, cp.approval_id, \
                sid, tid, wid, res["boundary_report_id"], res["approval_id"]
    cs, ct, cw, cbr, cap, sid, tid, wid, brid, apid = asyncio.run(run())
    assert cs == sid and ct == tid and cw == wid
    assert str(cbr) == brid and str(cap) == apid


@pytest.mark.integration
def test_richard_input_references_correct_approval_and_report():
    """4. RichardBoundaryInput references the approval AND the report by real columns."""
    async def run():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            rbi = (await s.execute(select(RichardBoundaryInput))).scalars().first()
            return rbi.related_approval_id, rbi.boundary_report_id, rbi.workspace_id, rbi.task_id, \
                res["approval_id"], res["boundary_report_id"], wid, tid
    rel, brid, ws, task, apid, report_id, wid, tid = asyncio.run(run())
    assert str(rel) == apid
    assert str(brid) == report_id
    assert ws == wid and task == tid


@pytest.mark.integration
def test_approval_window_references_correct_decision():
    """5. ApprovalWindow.approval_id references the decision; expires_at is a real column."""
    async def run():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            win = (await s.execute(select(ApprovalWindow))).scalars().first()
            return win.approval_id, win.boundary_report_id, win.workspace_id, win.task_id, \
                win.decided_by, win.expires_at, res["approval_id"], res["boundary_report_id"], wid, tid, uid
    apid, brid, ws, task, decided_by, expires, exp_apid, exp_brid, wid, tid, uid = asyncio.run(run())
    assert str(apid) == exp_apid
    assert str(brid) == exp_brid
    assert ws == wid and task == tid and decided_by == uid
    assert expires is not None        # real expires_at column populated


@pytest.mark.integration
def test_resume_action_references_correct_checkpoint_and_session():
    """6. ResumeAction references checkpoint/session + approval/report/workspace columns."""
    async def run():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            await wf.resume_mission(checkpoint_id=UUID(res["checkpoint_id"]),
                                    authenticated_user_id=uid)
            ra = (await s.execute(select(ResumeAction))).scalars().first()
            return ra.checkpoint_id, ra.session_id, ra.approval_id, ra.boundary_report_id, \
                ra.workspace_id, ra.task_id, res["checkpoint_id"], sid, res["approval_id"], \
                res["boundary_report_id"], wid, tid
    cp, sess_id, apid, brid, ws, task, exp_cp, sid, exp_apid, exp_brid, wid, tid = asyncio.run(run())
    assert str(cp) == exp_cp and sess_id == sid
    assert str(apid) == exp_apid and str(brid) == exp_brid
    assert ws == wid and task == tid


@pytest.mark.integration
def test_cross_workspace_decision_and_access_are_rejected():
    """7. A user cannot read/decide a report in a workspace they do not own."""
    async def run():
        async with AsyncTestingSessionLocal() as s:
            # Owner B's boundary.
            wf, res, owner_b, wid_b, sid, aid, tid = await _seed_boundary(s, with_task=True)
            # Attacker A owns a DIFFERENT workspace.
            attacker, wid_a = await _seed_user_ws(s)
            svc = RichardBoundaryService(s)
            # A cannot read B's case.
            case, access = await svc.get_case(attacker, UUID(res["boundary_report_id"]))
            # A cannot decide B's report.
            dec, dec_access = await svc.submit_decision(
                attacker, UUID(res["boundary_report_id"]), approve=True)
            # A cannot resume B's report.
            rz, rz_access = await svc.resume(attacker, UUID(res["boundary_report_id"]))
            # The approval is untouched.
            ap = (await s.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            return access, dec_access, rz_access, ap.status, ap.approved
    access, dec_access, rz_access, status, approved = asyncio.run(run())
    assert access == FORBIDDEN
    assert dec_access == FORBIDDEN
    assert rz_access == FORBIDDEN
    assert status == "pending" and approved is None    # never crossed workspaces


@pytest.mark.integration
def test_invalid_foreign_keys_fail_honestly():
    """8. Invalid references fail honestly: (a) DB FK enforcement on a new column;
    (b) the workflow returns honest not-found, never a fabricated success."""
    # (a) Real DB-level FK enforcement on the new boundary_report_id column.
    from app.core.database import Base
    import app.models  # noqa: F401  (register all models)
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.agent import Agent

    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_con, _rec):
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    integrity_error = False
    with Session() as s:
        uid, wid = uuid4(), uuid4()
        s.add(User(id=uid, username="z", email="z@z.io", password_hash="$2b$12$x",
                   is_active=True, is_admin=False))
        s.add(Workspace(id=wid, name="W", slug="w", description="d", owner_id=uid,
                        is_active=True, workspace_type="test", authority_level=9))
        agent = Agent(id=uuid4(), name="o", agent_type="core", workspace_id=wid,
                      is_active=True, authority_level=9, allowed_tools=[])
        s.add(agent)
        s.commit()
        sess = AgentSession(id=uuid4(), user_id=uid, workspace_id=wid, agent_id=agent.id,
                            session_type="mission", status="active", messages=[],
                            execution_logs=[])
        s.add(sess)
        s.commit()
        # Valid session/user, but a BOGUS workspace_id (no such workspace). This is
        # one of the new Repair-9 relational columns; under FK enforcement the bad
        # reference must be rejected, not silently accepted.
        bad = ApprovalWindow(
            id=uuid4(), session_id=sess.id, user_id=uid,
            workspace_id=uuid4(),   # <-- references nothing
            window_type="boundary", title="bad", status="active")
        s.add(bad)
        try:
            s.commit()
        except Exception:  # IntegrityError under FK enforcement
            integrity_error = True
            s.rollback()
    eng.dispose()
    assert integrity_error is True

    # (b) Workflow honesty: decisions/resumes on non-existent ids are honest, not faked.
    async def run():
        async with AsyncTestingSessionLocal() as s:
            wf = RichardBoundaryWorkflow(s)
            dec = await wf.record_richard_decision(
                approval_id=uuid4(), authenticated_user_id=uuid4(), approve=True)
            rz = await wf.resume_mission(checkpoint_id=uuid4(), authenticated_user_id=uuid4())
            return dec, rz
    dec, rz = asyncio.run(run())
    assert dec["decided"] is False and "not found" in dec["reason"]
    assert rz["resumed"] is False and "not found" in rz["reason"]


# =========================================================================== #
# Migration (tests 9-12) — drive the real upgrade()/downgrade() on SQLite
# =========================================================================== #

def _load_migration():
    path = os.path.join(
        os.path.dirname(__file__), "..", "alembic", "versions",
        "2026_06_10_0900-r9_boundary_relational_contract.py")
    spec = importlib.util.spec_from_file_location("r9_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_pre9_schema(conn):
    """Minimal PRE-Repair-9 schema: id + JSON source columns + FK target tables."""
    conn.execute(text("CREATE TABLE users (id VARCHAR(32) PRIMARY KEY)"))
    conn.execute(text("CREATE TABLE workspaces (id VARCHAR(32) PRIMARY KEY)"))
    conn.execute(text("CREATE TABLE tasks (id VARCHAR(32) PRIMARY KEY)"))
    conn.execute(text("CREATE TABLE boundary_reports (id VARCHAR(32) PRIMARY KEY, context TEXT)"))
    conn.execute(text("CREATE TABLE boundary_approvals (id VARCHAR(32) PRIMARY KEY, "
                      "action_details TEXT, meta_data TEXT)"))
    conn.execute(text("CREATE TABLE approval_windows (id VARCHAR(32) PRIMARY KEY, meta_data TEXT)"))
    conn.execute(text("CREATE TABLE safe_checkpoints (id VARCHAR(32) PRIMARY KEY, state_snapshot TEXT)"))
    conn.execute(text("CREATE TABLE resume_actions (id VARCHAR(32) PRIMARY KEY, checkpoint_id VARCHAR(32))"))
    conn.execute(text("CREATE TABLE richard_boundary_inputs (id VARCHAR(32) PRIMARY KEY, context TEXT)"))


def _run_migration(mod, func_name, url):
    from alembic.runtime.migration import MigrationContext
    from alembic.operations import Operations
    eng = create_engine(url)
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        ops = Operations(ctx)
        with Operations.context(ctx):
            getattr(mod, func_name)()
        conn.commit()
    eng.dispose()


@pytest.mark.integration
def test_migration_upgrade_creates_columns_indexes_and_fks(tmp_path):
    """9 + 10 + 11. Upgrade adds columns/indexes/FKs and backfills only valid UUIDs."""
    mod = _load_migration()
    db = tmp_path / "mig.db"
    url = f"sqlite:///{db}"
    valid_ws, valid_task, valid_user = str(uuid4()), str(uuid4()), str(uuid4())

    eng = create_engine(url)
    with eng.connect() as conn:
        _build_pre9_schema(conn)
        # Row WITH valid UUIDs in JSON -> should backfill.
        conn.execute(text("INSERT INTO boundary_reports (id, context) VALUES (:id, :c)"),
                     {"id": uuid4().hex, "c": json.dumps(
                         {"workspace_id": valid_ws, "task_id": valid_task, "user_id": valid_user})})
        # Row with INVALID / absent JSON ids -> must NOT be fabricated.
        bad_id = uuid4().hex
        conn.execute(text("INSERT INTO boundary_reports (id, context) VALUES (:id, :c)"),
                     {"id": bad_id, "c": json.dumps({"workspace_id": "not-a-uuid"})})
        conn.commit()
    eng.dispose()

    _run_migration(mod, "upgrade", url)

    eng = create_engine(url)
    with eng.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(boundary_reports)"))]
        assert "workspace_id" in cols and "task_id" in cols and "created_by" in cols
        # Index created (PRAGMA index_list columns: seq, name, unique, origin, partial).
        idx = [r[1] for r in conn.execute(text("PRAGMA index_list(boundary_reports)"))]
        assert any("ix_boundary_reports_workspace_id" == n for n in idx)
        # Foreign key declared.
        fks = list(conn.execute(text("PRAGMA foreign_key_list(boundary_reports)")))
        fk_tables = {row[2] for row in fks}
        assert "workspaces" in fk_tables and "tasks" in fk_tables and "users" in fk_tables
        # expires_at added to approval_windows.
        aw_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(approval_windows)"))]
        assert "expires_at" in aw_cols
        # Backfill: valid UUIDs populated; invalid/absent left NULL (not fabricated).
        rows = list(conn.execute(text(
            "SELECT workspace_id, task_id, created_by FROM boundary_reports "
            "ORDER BY (workspace_id IS NULL)")))
        # The valid row first (non-null workspace), then the bad row (all null).
        good = rows[0]
        assert good[0] is not None and good[1] is not None and good[2] is not None
        nulls = [r for r in rows if r[0] is None]
        assert len(nulls) == 1                      # the invalid row was NOT fabricated
        assert nulls[0] == (None, None, None)
    eng.dispose()


@pytest.mark.integration
def test_migration_downgrade_removes_columns(tmp_path):
    """12. Downgrade drops the Repair-9 columns safely (no data fabrication, no crash)."""
    mod = _load_migration()
    db = tmp_path / "mig_down.db"
    url = f"sqlite:///{db}"
    eng = create_engine(url)
    with eng.connect() as conn:
        _build_pre9_schema(conn)
        conn.execute(text("INSERT INTO boundary_reports (id, context) VALUES (:id, :c)"),
                     {"id": uuid4().hex, "c": json.dumps({"workspace_id": str(uuid4())})})
        conn.commit()
    eng.dispose()

    _run_migration(mod, "upgrade", url)
    _run_migration(mod, "downgrade", url)

    eng = create_engine(url)
    with eng.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(boundary_reports)"))]
        assert "workspace_id" not in cols and "task_id" not in cols and "created_by" not in cols
        aw_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(approval_windows)"))]
        assert "expires_at" not in aw_cols
        # The original row + its JSON source survive the downgrade.
        n = conn.execute(text("SELECT COUNT(*) FROM boundary_reports")).scalar()
        assert n == 1
    eng.dispose()


# =========================================================================== #
# Authenticated, workspace-isolated API (tests 13-25)
# =========================================================================== #

def _auth_as(owner: str):
    from app.main import app
    from app.core.auth import get_current_user_id
    app.dependency_overrides[get_current_user_id] = lambda: owner


def _clear_auth():
    from app.main import app
    from app.core.auth import get_current_user_id
    app.dependency_overrides.pop(get_current_user_id, None)


@pytest.mark.integration
def test_api_requires_authentication(client):
    """13. Unauthenticated report/pending/decision/resume requests are rejected (401)."""
    assert client.get("/api/richard/reports").status_code == 401
    assert client.get("/api/richard/pending").status_code == 401
    assert client.post(f"/api/richard/reports/{uuid4()}/decision",
                       json={"approve": True}).status_code == 401
    assert client.post(f"/api/richard/reports/{uuid4()}/resume").status_code == 401


@pytest.mark.integration
def test_api_owner_lists_pending(client):
    """14. Authenticated owner lists their pending cases."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s)
            return str(uid), res
    owner, res = asyncio.run(seed())
    _auth_as(owner)
    try:
        r = client.get("/api/richard/pending")
        assert r.status_code == 200, r.text
        pend = r.json()
        assert any(p["approval_id"] == res["approval_id"] for p in pend)
    finally:
        _clear_auth()


@pytest.mark.integration
def test_api_report_list_filtered_by_workspace(client):
    """15. The report list only returns reports in workspaces the caller owns."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            # Owner A's report.
            wfa, ra, uid_a, wid_a, *_ = await _seed_boundary(s)
            # Owner B's report (different workspace).
            wfb, rb, uid_b, wid_b, *_ = await _seed_boundary(s)
            return str(uid_a), ra["boundary_report_id"], rb["boundary_report_id"]
    owner_a, report_a, report_b = asyncio.run(seed())
    _auth_as(owner_a)
    try:
        r = client.get("/api/richard/reports")
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()}
        assert report_a in ids           # own workspace report visible
        assert report_b not in ids       # other workspace report NOT leaked
    finally:
        _clear_auth()


@pytest.mark.integration
def test_api_complete_case_returns_real_related_records(client):
    """16. The complete-case endpoint returns the real related records (after resume)."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            await wf.resume_mission(checkpoint_id=UUID(res["checkpoint_id"]),
                                    authenticated_user_id=uid)
            return str(uid), res["boundary_report_id"]
    owner, report_id = asyncio.run(seed())
    _auth_as(owner)
    try:
        r = client.get(f"/api/richard/reports/{report_id}")
        assert r.status_code == 200, r.text
        case = r.json()
        assert case["report"]["id"] == report_id
        assert case["boundary_type"] == "delete_production_data"
        # After resume the state is the report resolution (e.g. resumed_completed).
        assert case["workflow_state"].startswith("resumed")
        assert case["richard_decision"] and case["richard_decision"]["decision"] == "approved"
        assert case["approval_window"] and case["approval_window"]["status"] in ("active", "consumed")
        assert case["checkpoint"] and case["checkpoint"]["can_resume_from"] is True
        assert len(case["resume_history"]) == 1
        # History endpoint also returns the real linked rows.
        h = client.get(f"/api/richard/reports/{report_id}/history")
        assert h.status_code == 200
        hist = h.json()
        assert len(hist["approvals"]) >= 1 and len(hist["resume_actions"]) == 1
    finally:
        _clear_auth()


@pytest.mark.integration
def test_api_decision_ignores_caller_identity_and_uses_real_workflow(client):
    """17 + 18. Decision endpoint binds decided_by to auth user (smuggled fields
    ignored) and the approval is persisted by the REAL workflow (window + input)."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            return str(uid), res
    owner, res = asyncio.run(seed())
    _auth_as(owner)
    try:
        r = client.post(
            f"/api/richard/reports/{res['boundary_report_id']}/decision",
            json={"approve": True, "reason": "ok", "authority_granted": 8,
                  "expiry_seconds": 3600,
                  "decided_by": str(uuid4()), "authorized": True})  # smuggled -> ignored
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["decided"] is True and body["status"] == "approved"
        assert body["decided_by"] == owner
    finally:
        _clear_auth()

    async def verify():
        async with AsyncTestingSessionLocal() as s:
            ap = (await s.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            win = (await s.execute(select(ApprovalWindow))).scalars().first()
            rbi = (await s.execute(select(RichardBoundaryInput))).scalars().first()
            return ap.decided_by, str(ap.id), win, rbi
    decided_by, apid, win, rbi = asyncio.run(verify())
    assert str(decided_by) == owner                      # real column bound to auth user
    assert win is not None and str(win.approval_id) == apid   # real workflow persisted window
    assert rbi is not None and str(rbi.related_approval_id) == apid


@pytest.mark.integration
def test_api_rejection_uses_real_workflow(client):
    """19. Rejection through the API resolves the report via the real workflow; no window."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s)
            return str(uid), res
    owner, res = asyncio.run(seed())
    _auth_as(owner)
    try:
        r = client.post(f"/api/richard/reports/{res['boundary_report_id']}/decision",
                        json={"approve": False, "reason": "not allowed"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "rejected"
    finally:
        _clear_auth()

    async def verify():
        async with AsyncTestingSessionLocal() as s:
            rep = (await s.execute(select(BoundaryReport).where(
                BoundaryReport.id == UUID(res["boundary_report_id"])))).scalar_one()
            wins = (await s.execute(select(func.count()).select_from(ApprovalWindow))).scalar()
            return rep.resolution, int(wins)
    resolution, wins = asyncio.run(verify())
    assert resolution == "rejected_by_richard"
    assert wins == 0


@pytest.mark.integration
def test_api_resume_performs_real_continuation(client):
    """20. The resume endpoint actually re-drives the mission (real ResumeAction)."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            return str(uid), res
    owner, res = asyncio.run(seed())
    _auth_as(owner)
    try:
        r = client.post(f"/api/richard/reports/{res['boundary_report_id']}/resume")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["resumed"] is True and body["status"] in (COMPLETED, PARTIAL)
    finally:
        _clear_auth()

    async def verify():
        async with AsyncTestingSessionLocal() as s:
            ra = (await s.execute(select(ResumeAction))).scalars().all()
            return ra
    ra = asyncio.run(verify())
    assert len(ra) == 1 and ra[0].success is True
    assert ra[0].boundary_report_id is not None    # real relational column populated


@pytest.mark.integration
def test_api_missing_report_returns_404(client):
    """21. A missing report returns 404."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            uid, wid = await _seed_user_ws(s)
            return str(uid)
    owner = asyncio.run(seed())
    _auth_as(owner)
    try:
        r = client.get(f"/api/richard/reports/{uuid4()}")
        assert r.status_code == 404
    finally:
        _clear_auth()


@pytest.mark.integration
def test_api_wrong_workspace_returns_403(client):
    """22. A report in another workspace returns 403 (exists but not owned)."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, owner_b, wid_b, *_ = await _seed_boundary(s)
            attacker, wid_a = await _seed_user_ws(s)
            return str(attacker), res["boundary_report_id"]
    attacker, report_b = asyncio.run(seed())
    _auth_as(attacker)
    try:
        r = client.get(f"/api/richard/reports/{report_b}")
        assert r.status_code == 403
        d = client.post(f"/api/richard/reports/{report_b}/decision", json={"approve": True})
        assert d.status_code == 403
    finally:
        _clear_auth()


@pytest.mark.integration
def test_api_conflicting_finalised_decision_returns_409(client):
    """23. A conflicting decision on an already-finalised approval returns 409."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s)
            return str(uid), res
    owner, res = asyncio.run(seed())
    _auth_as(owner)
    try:
        ok = client.post(f"/api/richard/reports/{res['boundary_report_id']}/decision",
                         json={"approve": True, "authority_granted": 8})
        assert ok.status_code == 200, ok.text
        # Conflicting decision -> 409.
        conflict = client.post(f"/api/richard/reports/{res['boundary_report_id']}/decision",
                               json={"approve": False})
        assert conflict.status_code == 409
        # Identical idempotent repeat is a 200 no-op.
        same = client.post(f"/api/richard/reports/{res['boundary_report_id']}/decision",
                           json={"approve": True})
        assert same.status_code == 200
        assert same.json().get("idempotent") is True
    finally:
        _clear_auth()


@pytest.mark.integration
def test_api_expired_approval_cannot_resume(client):
    """24. Resume under an expired approval window returns 410 and runs nothing."""
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600)
            # Force the window to be expired (real column + meta).
            win = (await s.execute(select(ApprovalWindow))).scalars().first()
            win.expires_at = datetime.utcnow() - timedelta(hours=1)
            meta = dict(win.meta_data or {})
            meta["expires_at"] = (datetime.utcnow() - timedelta(hours=1)).isoformat()
            win.meta_data = meta
            await s.commit()
            return str(uid), res
    owner, res = asyncio.run(seed())
    _auth_as(owner)
    try:
        r = client.post(f"/api/richard/reports/{res['boundary_report_id']}/resume")
        assert r.status_code == 410, r.text
    finally:
        _clear_auth()

    async def verify():
        async with AsyncTestingSessionLocal() as s:
            ra = (await s.execute(select(func.count()).select_from(ResumeAction))).scalar()
            return int(ra)
    assert asyncio.run(verify()) == 0       # nothing executed under expired authority


@pytest.mark.integration
def test_api_sensitive_fields_are_redacted(client):
    """25. Secrets in decision metadata are redacted in the case response."""
    secret = "sk-supersecretkey1234567890abcdef"
    async def seed():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s, with_task=True)
            await wf.record_richard_decision(
                approval_id=UUID(res["approval_id"]), authenticated_user_id=uid,
                approve=True, authority_granted=8, expiry_seconds=3600,
                reason=f"api_key={secret} approved")
            return str(uid), res["boundary_report_id"]
    owner, report_id = asyncio.run(seed())
    _auth_as(owner)
    try:
        r = client.get(f"/api/richard/reports/{report_id}")
        assert r.status_code == 200, r.text
        assert secret not in r.text            # raw secret never returned
    finally:
        _clear_auth()


# =========================================================================== #
# Compatibility (test 26) — legacy operator reaches the real workflow
# =========================================================================== #

@pytest.mark.integration
def test_legacy_operator_delegates_to_real_workflow():
    """26. The legacy RichardOperator facade reaches the real workflow (and is
    deprecated for advisory submit_input)."""
    import warnings
    from app.core.richard.operator import RichardOperator

    async def run():
        async with AsyncTestingSessionLocal() as s:
            wf, res, uid, wid, sid, aid, tid = await _seed_boundary(s)
            op = RichardOperator(s)
            # decide() must persist a real decision via the real workflow.
            dec = await op.decide(approval_id=UUID(res["approval_id"]),
                                  authenticated_user_id=uid, approve=True,
                                  authority_granted=8, expiry_seconds=3600)
            # list_pending() reaches the real data layer (now decided -> empty pending).
            pend_before_decide = await op.get_pending_inputs()  # real workflow list
            ap = (await s.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == UUID(res["approval_id"])))).scalar_one()
            win = (await s.execute(select(ApprovalWindow))).scalars().first()
            return dec, ap.status, ap.decided_by, win, uid, pend_before_decide
    dec, status, decided_by, win, uid, pend = asyncio.run(run())
    assert dec["decided"] is True and dec["status"] == "approved"
    assert status == "approved" and decided_by == uid     # real persistence via workflow
    assert win is not None                                # real ApprovalWindow created
    assert isinstance(pend, list)                         # real list, not a stub sentinel

    # submit_input is advisory + deprecated for real decisions.
    async def dep():
        op = RichardOperator()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await op.submit_input(user_id=uuid4(), input_type="guidance",
                                  situation_description="x", requested_action="y")
            return [issubclass(x.category, DeprecationWarning) for x in w]
    flags = asyncio.run(dep())
    assert any(flags)
