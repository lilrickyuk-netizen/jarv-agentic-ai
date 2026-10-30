"""Repair 12c: specialist agents work through real, confined, logged tools.

The model is scripted (a fake router) so tests are deterministic and never
spend provider credit; everything else is real: the toolbox, the workspace
runtime, the permission policy, the filesystem, command execution, and the
database records.
"""
import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.registry import get_registry
from app.core.agents.specialists.coding_agent import CodingAgent
from app.core.agents.specialists.documentation import DocumentationAgent
from app.core.agents.specialists.verifier import VerifierAgent
from app.core.agents.toolbox import AgentToolbox, effective_authority
from app.core.config import settings
from app.models.operations import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal

SANDBOX = Path("/tmp/jarv_sandbox")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def project():
    name = f"r12c-{uuid4().hex[:8]}"
    root = SANDBOX / name
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (root / ".env").write_text("OPENAI_API_KEY=sk-should-never-be-read-0123456789abcdef\n")
    other = SANDBOX / f"{name}-other"
    other.mkdir(parents=True)
    (other / "private.txt").write_text("another project's data")
    yield f"/test_workspaces/{name}", root, f"/test_workspaces/{name}-other"
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(other, ignore_errors=True)


async def _seed(db, root_host, authority=5):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="R12c", slug=f"r12c-{ws_id.hex[:8]}",
                     description="", workspace_type="test", authority_level=authority, is_active=True,
                     config={"root_path": root_host} if root_host else {}))
    await db.commit()
    return user_id, ws_id


def _agent(cls, ws_id, user_id, level=AuthorityLevel.LEVEL_3_CODE_EXECUTION):
    return cls(AgentConfig(workspace_id=ws_id, user_id=user_id, authority_level=level))


def _ctx(db, ws_id, user_id, **meta):
    return AgentContext(workspace_id=ws_id, user_id=user_id, db_session=db, metadata=meta)


class ScriptedRouter:
    """Returns pre-written model turns; records the tools it was offered."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.offered = []
        self.systems = []

    async def complete(self, request):
        self.offered.append([t["name"] for t in (request.tools or [])])
        self.systems.append(request.system or "")
        turn = self.turns.pop(0) if self.turns else {"content": "done"}
        calls = [{"id": f"call-{i}-{len(self.turns)}", "function": {"name": n, "arguments": json.dumps(a)}}
                 for i, (n, a) in enumerate(turn.get("tools", []))]
        return SimpleNamespace(content=turn.get("content", ""), tool_calls=calls,
                               usage={"total_tokens": 10}, provider="test", model="test")


# ----- authority -------------------------------------------------------------------

def test_effective_authority_never_exceeds_workspace_or_reaches_live_release():
    assert effective_authority(3, 5) == 3
    assert effective_authority(9, 4) == 4
    assert effective_authority(10, 7) == 6
    assert effective_authority(0, None) == 1


def test_every_agent_declares_only_registered_tools_it_has_authority_for():
    # The existing wiring test checks this for all 31; spot-check the tool-mode agents here.
    from app.core.tools.registry import get_registry as tools

    for name in ("coding_agent", "debugging_agent", "verifier", "qa", "documentation", "devops", "security"):
        meta = get_registry().get_metadata(name)
        for tool in meta.default_tools:
            tmeta = tools().get_metadata(tool)
            assert tmeta is not None and tmeta.is_implemented, (name, tool)
            assert tmeta.required_authority_level <= meta.required_authority_level, (name, tool)


# ----- toolbox confinement -----------------------------------------------------------

@pytest.mark.integration
def test_toolbox_confines_files_commands_and_registry_paths_to_the_workspace(project):
    root_host, root, other_host = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            agent = _agent(CodingAgent, ws_id, user_id)
            box = await AgentToolbox(agent, _ctx(db, ws_id, user_id)).prepare()
            results = {
                "available": box.available,
                "read_rel": await box.call("file_read", {"path": "src/app.py"}),
                "read_outside": await box.call("read_file", {"path": "/etc/passwd"}),
                "read_traversal": await box.call("read_file", {"path": "../" + Path(other_host).name + "/private.txt"}),
                "read_other_ws": await box.call("read_file", {"path": other_host + "/private.txt"}),
                "read_secret": await box.call("read_file", {"path": ".env"}),
                "write": await box.call("write_file", {"path": "src/util.py", "content": "X = 1\n"}),
                "search": await box.call("search_files", {"pattern": "*.py", "contains": "return a + b"}),
                "search_secret": await box.call("search_files", {"contains": "sk-should-never"}),
                "ls": await box.call("run_command", {"command": "ls src"}),
                "cat_outside": await box.call("run_command", {"command": "cat /etc/passwd"}),
                "inline_code": await box.call("run_command", {"command": "python3 -c print(1)"}),
                "dangerous": await box.call("run_command", {"command": "rm -rf src"}),
                "analyze_outside": await box.call("analyze_code", {"path": "/etc"}),
                "not_offered": await box.call("git_push", {"repo_path": "."}),
            }
            await db.commit()
            audit = (await db.execute(select(AuditLog.action).where(
                AuditLog.action_category == "tool_execution"))).scalars().all()
            return results, box.calls, audit

    results, calls, audit = _run(run())
    assert {"read_file", "write_file", "run_command", "search_files", "git_status"} <= set(results["available"])
    assert "git_push" not in results["available"]
    assert results["read_rel"]["success"] and "return a + b" in results["read_rel"]["data"]["content"]
    for key in ("read_outside", "read_traversal", "read_other_ws", "cat_outside", "inline_code",
                "analyze_outside", "not_offered"):
        assert results[key]["success"] is False and results[key].get("blocked"), key
    assert results["read_secret"]["data"]["redacted"] is True
    assert "sk-should-never" not in json.dumps(results["read_secret"])
    assert results["write"]["success"] and (root / "src" / "util.py").read_text() == "X = 1\n"
    assert [m["path"].endswith("app.py") for m in results["search"]["matches"]] == [True]
    assert results["search_secret"]["matches"] == []
    assert results["ls"]["success"] and "app.py" in results["ls"]["stdout"]
    assert results["dangerous"]["success"] is False and (root / "src" / "app.py").exists()
    assert len(calls) == 14
    assert "tool:write_file" in audit and "tool:run_command" in audit


@pytest.mark.integration
def test_workspace_without_a_registered_folder_gets_no_filesystem_tools():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, None)
            box = await AgentToolbox(_agent(CodingAgent, ws_id, user_id), _ctx(db, ws_id, user_id)).prepare()
            return box.available, await box.call("read_file", {"path": "README.md"})

    available, refused = _run(run())
    assert not ({"read_file", "write_file", "run_command"} & set(available))
    assert "memory_search" in available
    assert refused["blocked"] is True


@pytest.mark.integration
def test_low_authority_agent_is_not_offered_commands(project):
    root_host, _, _ = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            agent = _agent(DocumentationAgent, ws_id, user_id, AuthorityLevel.LEVEL_2_FILE_OPERATIONS)
            box = await AgentToolbox(agent, _ctx(db, ws_id, user_id)).prepare()
            return box.available

    available = _run(run())
    assert "write_file" in available and "run_command" not in available


# ----- tool loop and agents -------------------------------------------------------------

@pytest.mark.integration
def test_coding_agent_writes_verifies_and_reports_through_execute(project, monkeypatch):
    root_host, root, _ = project
    router = ScriptedRouter([
        {"tools": [("file_read", {"path": "src/app.py"})]},
        {"tools": [("write_file", {"path": "src/app.py",
                                   "content": "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"})]},
        {"tools": [("run_command", {"command": "python3 -m py_compile src/app.py"})]},
        {"tools": [("finish", {"summary": "Added sub(); compiled cleanly.", "success": True,
                               "outputs": ["src/app.py"]})]},
    ])
    monkeypatch.setattr("app.core.providers.get_router", lambda: router)
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "test-key-not-real")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            agent = _agent(CodingAgent, ws_id, user_id)
            return await agent.execute(
                {"task": "Add a sub(a, b) function to src/app.py", "language": "python"},
                _ctx(db, ws_id, user_id, tools_enabled=True))

    result = _run(run())
    assert result.success is True, result.error_message
    assert "def sub(a, b)" in (root / "src" / "app.py").read_text()
    assert set(result.tools_used) == {"read_file", "write_file", "run_command"}
    assert result.result_data["outputs"] == ["src/app.py"]
    assert result.result_data["mode"] == "tools"
    offered = router.offered[0]
    assert "write_file" in offered and "finish" in offered and "git_push" not in offered
    assert "Workspace folder: " + root_host in router.systems[0]


@pytest.mark.integration
def test_unfinished_or_approval_waiting_tasks_are_not_reported_as_success(project, monkeypatch):
    root_host, _, _ = project
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "test-key-not-real")

    async def run(turns):
        monkeypatch.setattr("app.core.providers.get_router", lambda: ScriptedRouter(turns))
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            agent = _agent(VerifierAgent, ws_id, user_id)
            return await agent.execute({"code_to_verify": "src/app.py compiles"},
                                       _ctx(db, ws_id, user_id, tools_enabled=True))

    gave_up = _run(run([{"tools": [("read_file", {"path": "src/app.py"})]},
                        {"content": "Looks fine to me."}]))
    assert gave_up.success is False
    assert gave_up.result_data["summary"] == "Looks fine to me."

    blocked = _run(run([{"tools": [("run_command", {"command": "rm -rf src"})]},
                        {"tools": [("finish", {"summary": "Verified.", "success": True})]}]))
    assert blocked.result_data["blocked_actions"] == ["run_command"]


@pytest.mark.integration
def test_tool_mode_is_off_in_tests_unless_requested_and_keys_are_blank():
    import os

    assert os.environ.get("OPENAI_API_KEY") == "" and not settings.OPENAI_API_KEY

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, None)
            agent = _agent(CodingAgent, ws_id, user_id)
            return agent.tools_enabled(_ctx(db, ws_id, user_id))

    assert _run(run()) is False


@pytest.mark.integration
def test_cut_off_arguments_are_reported_and_long_files_are_written_in_parts(project, monkeypatch):
    """A whole document written in one write_file hit the 4,096-token output limit; the cut-off arguments
    were read as {} and the write was refused as a write to the workspace folder itself. The model now has
    room (AGENT_MAX_OUTPUT_TOKENS), is told plainly when its arguments were cut off, and can append parts."""
    root_host, root, _ = project

    class Router(ScriptedRouter):
        async def complete(self, request):
            self.max_tokens = getattr(self, "max_tokens", []) + [request.max_tokens]
            if not getattr(self, "sent_broken", False):
                self.sent_broken = True
                self.offered.append([t["name"] for t in (request.tools or [])])
                return SimpleNamespace(content="", usage={"total_tokens": 10}, provider="test", model="test",
                                       tool_calls=[{"id": "call-cut", "function": {
                                           "name": "write_file",
                                           "arguments": '{"path": "docs/architecture.md", "content": "# MYCO arch'}}])
            self.last_results = [b for m in request.messages if isinstance(m.content, list)
                                 for b in m.content if isinstance(b, dict) and b.get("type") == "tool_result"]
            return await super().complete(request)

    router = Router([
        {"tools": [("write_file", {"path": "docs/architecture.md", "content": "# MYCO architecture\n\nPart one.\n"})]},
        {"tools": [("write_file", {"path": "docs/architecture.md", "content": "Part two.\n", "append": True})]},
        {"tools": [("finish", {"summary": "Wrote docs/architecture.md in two parts.", "success": True,
                               "outputs": ["docs/architecture.md"]})]},
    ])
    monkeypatch.setattr("app.core.providers.get_router", lambda: router)
    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "test-key-not-real")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            agent = _agent(DocumentationAgent, ws_id, user_id)
            return await agent.execute({"task": "Write docs/architecture.md"},
                                       _ctx(db, ws_id, user_id, tools_enabled=True))

    result = _run(run())
    assert result.success is True, result.error_message
    assert (root / "docs" / "architecture.md").read_text() == "# MYCO architecture\n\nPart one.\nPart two.\n"
    first_result = router.last_results[0]
    assert first_result["tool_use_id"] == "call-cut" and "cut off" in first_result["content"]
    assert set(router.max_tokens) == {settings.AGENT_MAX_OUTPUT_TOKENS}
