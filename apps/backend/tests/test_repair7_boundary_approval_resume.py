"""
Repair 7 behaviour tests: real Boundary, Approval, Checkpoint/Resume tools, plus
ToolContext propagation through the AgentRunner so ToolRun records are created
during normal agent-driven tool execution.

These exercise the REAL path (registry -> ToolBase.execute -> persistence) against
the real async test DB. Nothing here mocks the registry, runner, ToolBase
execution, or the persistence under test. Detection is deterministic and asserted
on real input. No fake records, no silent approval, no fake resume success.
"""
import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.core.tools.registry import get_registry, create_tool
from app.core.tools.base import ToolConfig, ToolContext
from app.core.agents.base import AuthorityLevel, AgentBase, AgentConfig, AgentContext, AgentResult
from app.core.agents.registry import get_registry as get_agent_registry
from app.core.agents.runner import agent_runner

from app.models.boundary import BoundaryReport, BoundaryApproval, SafeCheckpoint, ResumeAction
from app.models.tool_system import ToolRun, Tool
from app.models.session import AgentSession

from tests.conftest import AsyncTestingSessionLocal


def _cfg():
    return ToolConfig(authority_level=AuthorityLevel.LEVEL_10_FULL_AUTONOMY)


async def _seed_parents(session):
    """Create real User/Workspace/Agent/AgentSession rows and return their ids."""
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.agent import Agent

    uid, wid, aid, sid = uuid4(), uuid4(), uuid4(), uuid4()
    session.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io",
                     password_hash="$2b$12$x", is_active=True, is_admin=False))
    session.add(Workspace(id=wid, name="WS", slug=f"ws-{wid.hex[:8]}", description="d",
                          owner_id=uid, is_active=True, workspace_type="test", authority_level=5))
    session.add(Agent(id=aid, name="A", agent_type="test_agent", workspace_id=wid,
                      is_active=True, authority_level=3, allowed_tools=["x"]))
    session.add(AgentSession(id=sid, user_id=uid, workspace_id=wid, agent_id=aid,
                             status="active", messages=[], execution_logs=[]))
    await session.commit()
    return uid, wid, aid, sid


# ===================================================================== #
# Boundary tools
# ===================================================================== #

@pytest.mark.integration
def test_boundary_detect_depends_on_real_input():
    """boundary.detect output is driven by the actual input, not hardcoded."""
    tool = create_tool("boundary.detect", _cfg())

    hit = asyncio.run(tool.execute(
        {"action": "delete production database for the customer"}, ToolContext()))
    clean = asyncio.run(tool.execute(
        {"action": "rename a local variable in a helper file"}, ToolContext()))

    assert hit.success and clean.success
    assert hit.result_data["requires_pause"] is True
    assert hit.result_data["detected_count"] >= 1
    keys = {d["key"] for d in hit.result_data["detected"]}
    assert "delete_production_data" in keys
    # Innocuous input must NOT be flagged as a hard boundary.
    assert clean.result_data["requires_pause"] is False
    assert clean.result_data["detected_count"] == 0


@pytest.mark.integration
def test_boundary_detect_states_coverage_and_rules_checked():
    """Detection honestly reports which rules were checked + coverage limits."""
    tool = create_tool("boundary.detect", _cfg())
    res = asyncio.run(tool.execute({"text": "enter the bank account routing number"}, ToolContext()))
    data = res.result_data
    assert data["rules_checked_count"] >= 20  # all hard-boundary rules evaluated
    assert "bank_details" in {d["key"] for d in data["detected"]}
    assert "deterministic" in data["coverage_limitations"].lower()
    # It must NOT claim certainty of a violation.
    assert "must be paused" in data["coverage_limitations"].lower() or \
           "pause" in data["coverage_limitations"].lower()


@pytest.mark.integration
def test_boundary_report_create_blocked_without_persistence():
    """Without db_session/agent/session, report.create returns a truthful blocked result."""
    tool = create_tool("boundary.report.create", _cfg())
    res = asyncio.run(tool.execute(
        {"boundary_type": "delete_production_data", "attempted_action": "drop prod db"},
        ToolContext()))  # no db_session
    assert res.success is False
    assert res.result_data["persisted"] is False
    assert res.result_data["blocked"] is True
    assert "db_session" in res.result_data["reason"]


@pytest.mark.integration
def test_boundary_report_create_get_list_persist():
    """report.create persists a real row; get/list read it back; missing -> not found."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            before = int((await session.execute(select(func.count()).select_from(BoundaryReport))).scalar() or 0)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid, workspace_id=wid)

            create = create_tool("boundary.report.create", _cfg())
            cres = await create.execute(
                {"boundary_type": "sign_contract", "attempted_action": "sign vendor agreement",
                 "severity": "high"}, ctx)
            assert cres.success and cres.result_data["persisted"] is True
            rid = cres.result_data["report_id"]

            get = create_tool("boundary.report.get", _cfg())
            gres = await get.execute({"report_id": rid}, ctx)
            assert gres.result_data["found"] is True
            assert gres.result_data["report"]["boundary_type"] == "sign_contract"

            # Missing id -> truthful not-found.
            miss = await get.execute({"report_id": str(uuid4())}, ctx)
            assert miss.result_data["found"] is False

            lst = create_tool("boundary.report.list", _cfg())
            lres = await lst.execute({"session_id": str(sid)}, ctx)
            assert lres.result_data["count"] >= 1
        async with AsyncTestingSessionLocal() as s2:
            after = int((await s2.execute(select(func.count()).select_from(BoundaryReport))).scalar() or 0)
            return before, after
    before, after = asyncio.run(run())
    assert after >= before + 1


@pytest.mark.integration
def test_boundary_recommend_next_action_branches_on_state():
    """recommend_next_action is derived from detection + approval state, not hardcoded."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid,
                              user_id=uid, workspace_id=wid)
            tool = create_tool("boundary.recommend_next_action", _cfg())

            # No boundary -> proceed.
            none = await tool.execute({"action": "format a string in code"}, ctx)
            assert none.result_data["requires_pause"] is False

            # Boundary present, no approval -> pause + request approval.
            pause = await tool.execute({"action": "publish public live release now"}, ctx)
            assert pause.result_data["requires_pause"] is True
            assert "pause" in pause.result_data["recommended_next_action"].lower()

            # Boundary present, with an APPROVED approval -> recommend resume.
            req = create_tool("approval.request", _cfg())
            ares = await req.execute({"approval_type": "live_release",
                                      "action_description": "release"}, ctx)
            apid = ares.result_data["approval_id"]
            grant = create_tool("approval.grant", _cfg())
            await grant.execute({"approval_id": apid, "decided_by": str(uid),
                                 "authorized": True}, ctx)
            approved = await tool.execute({"action": "publish public live release now",
                                           "approval_id": apid}, ctx)
            return none, pause, approved
    none, pause, approved = asyncio.run(run())
    assert "resume" in approved.result_data["recommended_next_action"].lower()


# ===================================================================== #
# Approval tools
# ===================================================================== #

@pytest.mark.integration
def test_approval_request_status_list_pending():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid,
                              user_id=uid, workspace_id=wid)
            req = create_tool("approval.request", _cfg())
            r = await req.execute({"approval_type": "spend", "action_description": "buy domain",
                                   "action_details": {"amount": 12}}, ctx)
            assert r.result_data["persisted"] is True
            apid = r.result_data["approval_id"]

            status = create_tool("approval.status", _cfg())
            s = await status.execute({"approval_id": apid}, ctx)
            assert s.result_data["found"] is True and s.result_data["approval"]["status"] == "pending"

            pend = create_tool("approval.list_pending", _cfg())
            p = await pend.execute({"session_id": str(sid)}, ctx)
            assert p.result_data["count"] >= 1
            return apid
    apid = asyncio.run(run())
    assert apid


@pytest.mark.integration
def test_approval_grant_requires_explicit_authorised_context():
    """grant/reject must have authorized=True AND decided_by; otherwise blocked, no change."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid,
                              user_id=uid, workspace_id=wid)
            req = create_tool("approval.request", _cfg())
            apid = (await req.execute({"approval_type": "spend",
                                       "action_description": "x"}, ctx)).result_data["approval_id"]

            grant = create_tool("approval.grant", _cfg())
            # Unauthorised: authorized defaults False -> blocked, no silent approval.
            blocked = await grant.execute({"approval_id": apid, "decided_by": str(uid)}, ctx)
            assert blocked.success is False and blocked.result_data["blocked"] is True

            # Missing decided_by even with authorized -> blocked.
            blocked2 = await grant.execute({"approval_id": apid, "authorized": True,
                                            "decided_by": ""}, ctx)
            assert blocked2.result_data.get("blocked") is True
        # State unchanged: still pending.
        async with AsyncTestingSessionLocal() as s2:
            row = (await s2.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == __import__("uuid").UUID(apid)))).scalar_one_or_none()
            return row
    row = asyncio.run(run())
    assert row is not None and row.status == "pending" and row.approved is None


@pytest.mark.integration
def test_approval_grant_and_reject_persist_decider():
    """A properly authorised grant persists status + decider; second decision is idempotent."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid,
                              user_id=uid, workspace_id=wid)
            req = create_tool("approval.request", _cfg())
            apid = (await req.execute({"approval_type": "spend",
                                       "action_description": "x"}, ctx)).result_data["approval_id"]
            grant = create_tool("approval.grant", _cfg())
            g = await grant.execute({"approval_id": apid, "decided_by": str(uid),
                                     "authorized": True, "response_message": "ok"}, ctx)
            assert g.success and g.result_data["decided"] is True and g.result_data["status"] == "approved"

            # Idempotent: a second decision does not silently overwrite.
            again = await grant.execute({"approval_id": apid, "decided_by": str(uid),
                                         "authorized": True}, ctx)
            assert again.result_data.get("already_decided") is True
        async with AsyncTestingSessionLocal() as s2:
            row = (await s2.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == __import__("uuid").UUID(apid)))).scalar_one_or_none()
            return row
    row = asyncio.run(run())
    assert row.status == "approved" and row.approved is True
    assert (row.meta_data or {}).get("decided_by")
    assert row.approved_at is not None


@pytest.mark.integration
def test_approval_reject_path():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid,
                              user_id=uid, workspace_id=wid)
            req = create_tool("approval.request", _cfg())
            apid = (await req.execute({"approval_type": "spend",
                                       "action_description": "x"}, ctx)).result_data["approval_id"]
            reject = create_tool("approval.reject", _cfg())
            r = await reject.execute({"approval_id": apid, "decided_by": str(uid),
                                      "authorized": True}, ctx)
            assert r.result_data["status"] == "rejected"
        async with AsyncTestingSessionLocal() as s2:
            row = (await s2.execute(select(BoundaryApproval).where(
                BoundaryApproval.id == __import__("uuid").UUID(apid)))).scalar_one_or_none()
            return row
    row = asyncio.run(run())
    assert row.status == "rejected" and row.approved is False


# ===================================================================== #
# Checkpoint / resume tools
# ===================================================================== #

@pytest.mark.integration
def test_checkpoint_create_and_get():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid, workspace_id=wid)
            cc = create_tool("checkpoint.create", _cfg())
            c = await cc.execute({"checkpoint_name": "before-release",
                                  "state_snapshot": {"current_step": "step3",
                                                     "pending_steps": ["s4", "s5"]},
                                  "variables": {"k": "v"},
                                  "resume_actions_available": ["restore", "continue"]}, ctx)
            assert c.result_data["persisted"] is True
            cid = c.result_data["checkpoint_id"]

            cg = create_tool("checkpoint.get", _cfg())
            g = await cg.execute({"checkpoint_id": cid}, ctx)
            assert g.result_data["found"] is True
            miss = await cg.execute({"checkpoint_id": str(uuid4())}, ctx)
            assert miss.result_data["found"] is False
            return cid
    cid = asyncio.run(run())
    assert cid


@pytest.mark.integration
def test_resume_plan_uses_real_checkpoint_and_blocks_on_pending_approval():
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid,
                              user_id=uid, workspace_id=wid)
            cc = create_tool("checkpoint.create", _cfg())
            cid = (await cc.execute({"checkpoint_name": "cp",
                                     "state_snapshot": {"pending_steps": ["finish"]},
                                     "resume_actions_available": ["restore"]},
                                    ctx)).result_data["checkpoint_id"]

            plan = create_tool("resume.plan", _cfg())
            ok = await plan.execute({"checkpoint_id": cid}, ctx)
            assert ok.result_data["can_resume"] is True
            assert any("restore" in s for s in ok.result_data["plan_steps"])

            # Add a pending approval for the session -> plan must block on it.
            req = create_tool("approval.request", _cfg())
            await req.execute({"approval_type": "spend", "action_description": "x"}, ctx)
            blocked = await plan.execute({"checkpoint_id": cid}, ctx)
            assert blocked.result_data["can_resume"] is False
            assert blocked.result_data["blocked_on_approvals"]

            # Missing checkpoint -> truthful not-found.
            miss = await plan.execute({"checkpoint_id": str(uuid4())}, ctx)
            assert miss.result_data["can_resume"] is False
            return True
    assert asyncio.run(run())


@pytest.mark.integration
def test_resume_execute_real_restoration_and_blocked_paths():
    """resume.execute restores real session state; blocks truthfully when it cannot."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            uid, wid, aid, sid = await _seed_parents(session)
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=sid,
                              user_id=uid, workspace_id=wid)
            cc = create_tool("checkpoint.create", _cfg())
            cid = (await cc.execute({"checkpoint_name": "cp",
                                     "state_snapshot": {"current_step": "step9"},
                                     "variables": {"restored_key": "restored_value"}},
                                    ctx)).result_data["checkpoint_id"]

            rexec = create_tool("resume.execute", _cfg())

            # Missing checkpoint -> blocked, not fake success.
            miss = await rexec.execute({"checkpoint_id": str(uuid4())}, ctx)
            assert miss.success is False and miss.result_data["blocked"] is True
            assert miss.result_data["restored"] is False

            # Real restoration into the existing session.
            ok = await rexec.execute({"checkpoint_id": cid, "executed_by": str(uid)}, ctx)
            assert ok.success is True and ok.result_data["restored"] is True
            assert "restored_key" in ok.result_data["restored_variables"]
            assert ok.result_data.get("limitation")  # honest limitation documented
            rid = ok.result_data["resume_action_id"]
        async with AsyncTestingSessionLocal() as s2:
            # Session row was really updated.
            srow = (await s2.execute(select(AgentSession).where(AgentSession.id == sid))).scalar_one_or_none()
            arow = (await s2.execute(select(ResumeAction).where(
                ResumeAction.id == __import__("uuid").UUID(rid)))).scalar_one_or_none()
            return srow, arow
    srow, arow = asyncio.run(run())
    assert srow is not None and srow.is_resumed is True
    assert srow.variables.get("restored_key") == "restored_value"
    assert srow.current_step == "step9"
    assert arow is not None and arow.success is True


@pytest.mark.integration
def test_resume_execute_blocked_when_no_session_row():
    """If the checkpoint's session row doesn't exist, resume.execute blocks truthfully."""
    async def run():
        async with AsyncTestingSessionLocal() as session:
            # No AgentSession row created for this session_id.
            uid, wid, aid = uuid4(), uuid4(), uuid4()
            orphan_sid = uuid4()
            ctx = ToolContext(db_session=session, agent_id=aid, session_id=orphan_sid, user_id=uid)
            cc = create_tool("checkpoint.create", _cfg())
            cid = (await cc.execute({"checkpoint_name": "cp",
                                     "state_snapshot": {}, "variables": {}}, ctx)).result_data["checkpoint_id"]
            rexec = create_tool("resume.execute", _cfg())
            res = await rexec.execute({"checkpoint_id": cid}, ctx)
            return res
    res = asyncio.run(run())
    assert res.success is False and res.result_data["blocked"] is True
    assert "no agent_session" in res.result_data["reason"]


# ===================================================================== #
# ToolContext propagation through the AgentRunner (normal execution path)
# ===================================================================== #

class _Repair7ProbeAgent(AgentBase):
    """A real agent that, in its run(), uses the normal execute_tool path.

    It is registered in the real agent registry for the propagation test so the
    full AgentRunner -> AgentContext -> execute_tool -> ToolBase.execute -> ToolRun
    path is exercised without mocking.
    """

    @property
    def name(self) -> str:
        return "repair7_probe_agent"

    @property
    def role(self) -> str:
        return "Repair 7 tool-execution probe"

    @property
    def input_schema(self):
        from pydantic import BaseModel

        class _In(BaseModel):
            task: str = ""
        return _In

    @property
    def output_schema(self):
        from pydantic import BaseModel

        class _Out(BaseModel):
            ok: bool = True
        return _Out

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def default_tools(self):
        return ["boundary.detect"]

    async def run(self, input_data, context: AgentContext) -> AgentResult:
        tool_result = await self.execute_tool(
            "boundary.detect", {"action": input_data.get("task", "")}, context)
        return self.create_result(
            success=True,
            result_data={"tool_logged": tool_result.metadata.get("tool_run_logged"),
                         "detected": tool_result.result_data.get("detected_count")},
            output_text="probe complete",
        )


@pytest.mark.integration
def test_agentrunner_threads_db_session_and_creates_toolrun():
    """A normal agent-driven tool execution (via run_agent w/ db) writes a ToolRun."""
    areg = get_agent_registry()
    areg.register(_Repair7ProbeAgent, category="core")
    try:
        async def run():
            async with AsyncTestingSessionLocal() as session:
                wid = uuid4()
                before = int((await session.execute(select(func.count()).select_from(ToolRun))).scalar() or 0)
                result = await agent_runner.run_agent(
                    "repair7_probe_agent",
                    "delete production database",
                    workspace_id=wid,
                    db=session,
                    session_id=uuid4(),
                )
                assert result["success"] is True
            async with AsyncTestingSessionLocal() as s2:
                after = int((await s2.execute(select(func.count()).select_from(ToolRun))).scalar() or 0)
                # The ToolRun is linked to the real boundary.detect catalog tool.
                rows = (await s2.execute(
                    select(ToolRun).join(Tool, ToolRun.tool_id == Tool.id)
                    .where(Tool.tool_name == "boundary.detect"))).scalars().all()
                return before, after, rows
        before, after, rows = asyncio.run(run())
        assert after >= before + 1
        assert any(r.status == "success" for r in rows)
    finally:
        areg._agents.pop("repair7_probe_agent", None)


@pytest.mark.integration
def test_no_session_agent_tool_execution_does_not_crash():
    """execute_tool without a db_session still runs the tool and marks not-logged."""
    cfg = AgentConfig(agent_id=uuid4(), authority_level=AuthorityLevel.LEVEL_10_FULL_AUTONOMY,
                      allowed_tools=["boundary.detect"])
    agent = _Repair7ProbeAgent(cfg)

    async def run():
        ctx = AgentContext(workspace_id=uuid4())  # no db_session
        return await agent.run({"task": "rename a variable"}, ctx)
    res = asyncio.run(run())
    assert res.success is True
    assert res.result_data["tool_logged"] is False
