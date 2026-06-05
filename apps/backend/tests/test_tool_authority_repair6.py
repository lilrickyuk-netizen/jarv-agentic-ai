"""
Repair 6 behaviour tests: tool approval enforcement, ToolRun logging, secret
redaction, and registry of real infrastructure tools.

Only the provider boundary is not involved here; these tests exercise the real
tool execution path (registry -> ToolBase.execute) and the real test DB
(AsyncSession from conftest).
"""
import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.core.security import redact_secrets, REDACTED
from app.core.tools.registry import get_registry, create_tool
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.run_logging import write_tool_run
from app.core.agents.base import AuthorityLevel
from app.models.tool_system import ToolRun

# Async session bound to the same file test DB as the rest of the suite.
from tests.conftest import AsyncTestingSessionLocal


def _cfg():
    return ToolConfig(authority_level=AuthorityLevel.LEVEL_10_FULL_AUTONOMY)


# ---------------- Approval enforcement ----------------

@pytest.mark.integration
def test_requires_approval_tool_blocked_without_approval(tmp_path):
    """A requires_approval tool (file_delete) is blocked and does NOT act."""
    target = tmp_path / "keep.txt"
    target.write_text("important")

    tool = create_tool("file_delete", _cfg())
    assert tool is not None and tool.requires_approval is True

    ctx = ToolContext()  # no approval
    res = asyncio.run(tool.execute({"path": str(target), "missing_ok": False}, ctx))

    assert res.success is False
    assert res.result_data.get("blocked") is True
    assert res.result_data.get("requires_approval") is True
    assert res.result_data.get("tool") == "file_delete"
    assert res.result_data.get("recommended_next_action")
    # Underlying action did NOT happen: the file still exists.
    assert target.exists(), "blocked tool must not perform its action"


@pytest.mark.integration
def test_requires_approval_tool_executes_with_approval(tmp_path):
    """With an explicit approval, the requires_approval tool runs for real."""
    target = tmp_path / "delete_me.txt"
    target.write_text("bye")

    tool = create_tool("file_delete", _cfg())
    ctx = ToolContext(approval_granted=True)
    res = asyncio.run(tool.execute({"path": str(target), "missing_ok": False}, ctx))

    assert res.result_data.get("blocked", False) is False
    assert res.success is True
    # The real action happened.
    assert not target.exists(), "approved file_delete should actually delete"


@pytest.mark.integration
def test_non_approval_tool_executes_normally(tmp_path):
    """A tool that does not require approval still executes without approval."""
    f = tmp_path / "read_me.txt"
    f.write_text("hello world")

    tool = create_tool("file_read", _cfg())
    assert tool.requires_approval is False

    res = asyncio.run(tool.execute({"path": str(f)}, ToolContext()))
    assert res.success is True
    assert res.result_data.get("blocked", False) is False


@pytest.mark.integration
def test_approved_tools_allowlist_permits_execution(tmp_path):
    """approved_tools allowlist is honoured as a valid approval signal."""
    target = tmp_path / "x.txt"
    target.write_text("x")
    tool = create_tool("file_delete", _cfg())
    ctx = ToolContext(approved_tools=["file_delete"])
    res = asyncio.run(tool.execute({"path": str(target), "missing_ok": False}, ctx))
    assert res.result_data.get("blocked", False) is False
    assert res.success is True


# ---------------- ToolRun logging ----------------

async def _toolrun_count(session) -> int:
    result = await session.execute(select(func.count()).select_from(ToolRun))
    return int(result.scalar() or 0)


@pytest.mark.integration
def test_toolrun_logged_when_session_available(tmp_path):
    """A real ToolRun row is written when a db session + agent_id are present."""
    f = tmp_path / "r.txt"
    f.write_text("data")
    agent_id = uuid4()

    async def run():
        async with AsyncTestingSessionLocal() as session:
            before = await _toolrun_count(session)
            tool = create_tool("file_read", _cfg())
            ctx = ToolContext(db_session=session, agent_id=agent_id)
            res = await tool.execute({"path": str(f)}, ctx)
            assert res.success is True
            assert res.metadata.get("tool_run_logged") is True
        # Verify via a fresh session that the row persisted.
        async with AsyncTestingSessionLocal() as s2:
            after = await _toolrun_count(s2)
            rows = (await s2.execute(select(ToolRun).where(ToolRun.agent_id == agent_id))).scalars().all()
            return before, after, rows

    before, after, rows = asyncio.run(run())
    assert after >= before + 1
    assert any(r.status == "success" for r in rows)


@pytest.mark.integration
def test_toolrun_blocked_status_logged(tmp_path):
    """A blocked (requires-approval) execution logs a ToolRun with status=blocked."""
    target = tmp_path / "k.txt"
    target.write_text("k")
    agent_id = uuid4()

    async def run():
        async with AsyncTestingSessionLocal() as session:
            tool = create_tool("file_delete", _cfg())
            ctx = ToolContext(db_session=session, agent_id=agent_id)  # no approval
            res = await tool.execute({"path": str(target), "missing_ok": False}, ctx)
            assert res.result_data.get("blocked") is True
            assert res.metadata.get("tool_run_logged") is True
        async with AsyncTestingSessionLocal() as s2:
            rows = (await s2.execute(select(ToolRun).where(ToolRun.agent_id == agent_id))).scalars().all()
            return rows

    rows = asyncio.run(run())
    assert any(r.status == "blocked" for r in rows)
    assert target.exists()  # still not deleted


@pytest.mark.integration
def test_no_session_does_not_crash_and_marks_not_logged(tmp_path):
    """Without a db session, execution succeeds and tool_run_logged is False."""
    f = tmp_path / "n.txt"
    f.write_text("n")
    tool = create_tool("file_read", _cfg())
    res = asyncio.run(tool.execute({"path": str(f)}, ToolContext()))  # no db_session
    assert res.success is True
    assert res.metadata.get("tool_run_logged") is False


# ---------------- Secret redaction ----------------

@pytest.mark.unit
def test_redaction_masks_common_secret_forms():
    payload = {
        "api_key": "sk-ABCDEFGHIJKLMNOP1234567890",
        "Authorization": "Bearer abcdef1234567890token",
        "password": "S3cr3tPassw0rd!",
        "database_url": "postgresql://user:supersecret@db:5432/app",
        "jwt": "eyJhbGciOiJI.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----",
        "note": "this is a normal non-secret note",
        "count": 42,
    }
    out = redact_secrets(payload)
    blob = json.dumps(out)

    # Sensitive values redacted (by key and/or pattern).
    assert out["api_key"] == REDACTED
    assert out["Authorization"] == REDACTED
    assert out["password"] == REDACTED
    assert out["database_url"] == REDACTED
    assert out["jwt"] == REDACTED
    assert out["private_key"] == REDACTED
    # Raw secret material must not survive anywhere in the output.
    for raw in ("supersecret", "S3cr3tPassw0rd!", "sk-ABCDEFGHIJKLMNOP1234567890",
                "abcdef1234567890token", "BEGIN RSA PRIVATE KEY"):
        assert raw not in blob, f"raw secret {raw!r} leaked"
    # Non-secret context preserved for debugging.
    assert out["note"] == "this is a normal non-secret note"
    assert out["count"] == 42


@pytest.mark.integration
def test_toolrun_input_is_redacted():
    """Secrets in tool input are redacted before being stored in ToolRun."""
    agent_id = uuid4()
    from datetime import datetime

    async def run():
        async with AsyncTestingSessionLocal() as session:
            ok = await write_tool_run(
                session,
                tool_name="redaction_probe_tool",
                tool_group="test",
                description="probe",
                input_schema_json={},
                output_schema_json={},
                minimum_authority_level=1,
                requires_approval=False,
                status="success",
                success=True,
                input_data={"api_key": "sk-LEAKED1234567890ABCDEF", "x": "ok"},
                output_data={"token": "Bearer LEAKEDtoken1234567890"},
                error_message=None,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                authority_level_used=1,
                agent_id=agent_id,
            )
            assert ok is True
        async with AsyncTestingSessionLocal() as s2:
            row = (await s2.execute(select(ToolRun).where(ToolRun.agent_id == agent_id))).scalars().first()
            return row

    row = asyncio.run(run())
    assert row is not None
    stored = json.dumps(row.input_params) + json.dumps(row.output_result)
    assert "sk-LEAKED1234567890ABCDEF" not in stored
    assert "LEAKEDtoken1234567890" not in stored
    assert REDACTED in stored
    # Non-secret input preserved.
    assert row.input_params.get("x") == "ok"


# ---------------- Registry ----------------

@pytest.mark.integration
def test_real_infrastructure_tools_registered_and_creatable():
    registry = get_registry()
    for name in ("ssl_check", "dns_verify", "resource_metrics", "cost_estimate"):
        assert registry.is_implemented(name), f"{name} should be registered+implemented"
        tool = create_tool(name, _cfg())
        assert tool is not None and tool.name == name


@pytest.mark.integration
def test_missing_design_tools_not_faked():
    """Design tool groups with no real implementation are NOT registered as fake."""
    registry = get_registry()
    # These design-named tools have no real implementation in this repo and must
    # not be silently registered with fake behaviour.
    for name in ("spawn_sub_agent", "transcribe_voice", "detect_hard_boundary",
                 "create_boundary_report", "deploy_production_with_boundary"):
        assert not registry.is_implemented(name), f"{name} must not be a fake registered tool"
