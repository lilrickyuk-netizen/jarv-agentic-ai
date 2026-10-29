"""Repair 12e-3a: the design's file, command, git, memory and project tools.

Everything real: the toolbox, workspace confinement, the permission gate and
the boundary chain, the filesystem, git, and pytest run as the project's test
command inside a sandbox project.
"""
import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.specialists.coding_agent import CodingAgent
from app.core.agents.specialists.devops import DevOpsAgent
from app.core.agents.toolbox import WORKSPACE_TOOLS, AgentToolbox
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import create_tool, get_registry
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import AsyncTestingSessionLocal

SANDBOX = Path("/tmp/jarv_sandbox")
NEW = ["edit_file", "create_folder", "move_file", "copy_file", "delete_file_with_boundary", "get_file_metadata",
       "detect_workspace_type", "detect_stack", "detect_commands", "find_missing_files", "run_build", "run_tests",
       "check_installed", "get_command_log", "git_create_branch", "git_push_with_boundary",
       "memory_add", "memory_link_to_task"]


def _run(coro):
    return asyncio.run(coro)


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=jarv@test", "-c", "user.name=JARV", "-c", f"safe.directory={root}",
                    *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def project():
    name = f"r12e3a-{uuid4().hex[:8]}"
    root = SANDBOX / name
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (root / "tests" / "test_calc.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'src'))\n"
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'calc'\ndependencies = ['requests>=2']\n\n"
                                         "[tool.pytest.ini_options]\naddopts = '-p no:cacheprovider'\n")
    (root / "package.json").write_text(json.dumps({"name": "calc-web", "scripts": {"build": "tsc", "test": "jest"},
                                                   "dependencies": {"react": "^18.3.0", "next": "14.2.0"}}))
    (root / ".env").write_text("SECRET_TOKEN=do-not-touch\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    yield f"/test_workspaces/{name}", root
    shutil.rmtree(root, ignore_errors=True)


async def _seed(db, host):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="R12e3a", slug=f"r12e3a-{ws_id.hex[:8]}", description="",
                     workspace_type="software", authority_level=5, is_active=True, config={"root_path": host}))
    await db.commit()
    return user_id, ws_id


async def _box(db, host, cls=CodingAgent, level=AuthorityLevel.LEVEL_3_CODE_EXECUTION, **context_extra):
    user_id, ws_id = await _seed(db, host)
    agent = cls(AgentConfig(workspace_id=ws_id, user_id=user_id, authority_level=level, allowed_tools=NEW
                            + ["read_file", "write_file", "list_files", "run_command", "install_package"]))
    context = AgentContext(workspace_id=ws_id, user_id=user_id, db_session=db, metadata={}, **context_extra)
    return await AgentToolbox(agent, context).prepare(), ws_id


@pytest.mark.integration
def test_file_tools_edit_move_copy_and_stay_inside_the_workspace(project):
    host, root = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            box, _ = await _box(db, host)
            return {
                "edit": await box.call("edit_file", {"path": "src/calc.py", "old_text": "return a + b",
                                                     "new_text": "return int(a) + int(b)"}),
                "ambiguous": await box.call("edit_file", {"path": "src/calc.py", "old_text": "(a, b)",
                                                          "new_text": "(x, y)"}),
                "missing": await box.call("edit_file", {"path": "src/calc.py", "old_text": "nope", "new_text": "x"}),
                "secret": await box.call("edit_file", {"path": ".env", "old_text": "SECRET", "new_text": "X"}),
                "folder": await box.call("create_folder", {"path": "src/utils"}),
                "copy": await box.call("copy_file", {"source": "src/calc.py", "destination": "src/utils/calc_copy.py"}),
                "move": await box.call("move_file", {"source": "src/utils/calc_copy.py",
                                                     "destination": "src/utils/calc2.py"}),
                "escape": await box.call("copy_file", {"source": "src/calc.py", "destination": "../stolen.py"}),
                "meta": await box.call("get_file_metadata", {"path": "src/calc.py"}),
            }

    r = _run(run())
    assert r["edit"]["success"] and "int(a) + int(b)" in (root / "src" / "calc.py").read_text()
    assert r["ambiguous"]["success"] is False and "2 times" in r["ambiguous"]["error"]
    assert r["missing"]["success"] is False and r["secret"]["blocked"] is True
    assert (root / ".env").read_text() == "SECRET_TOKEN=do-not-touch\n"
    assert r["folder"]["success"] and r["copy"]["success"] and r["move"]["success"]
    assert (root / "src" / "utils" / "calc2.py").exists() and not (root / "src" / "utils" / "calc_copy.py").exists()
    assert r["escape"]["blocked"] is True and not (root.parent / "stolen.py").exists()
    assert r["meta"]["data"]["type"] == "file" and r["meta"]["data"]["size_bytes"] > 0


@pytest.mark.integration
def test_delete_pauses_for_approval_and_runs_once_approved(project):
    host, root = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            box, _ = await _box(db, host)
            paused = await box.call("delete_file_with_boundary", {"path": "src/calc.py", "reason": "obsolete"})
            approved_box, _ = await _box(db, host, approval_granted=True)
            deleted = await approved_box.call("delete_file_with_boundary", {"path": "src/calc.py", "reason": "obsolete"})
            root_refused = await approved_box.call("delete_file_with_boundary", {"path": ".", "reason": "everything"})
            return paused, deleted, root_refused

    paused, deleted, root_refused = _run(run())
    assert paused["success"] is False and paused["requires_approval"] is True
    assert deleted["success"] and not (root / "src" / "calc.py").exists()
    assert root_refused["blocked"] is True and root.exists()


@pytest.mark.integration
def test_project_detection_and_the_projects_own_commands(project):
    host, root = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            box, ws_id = await _box(db, host)
            out = {name: await box.call(name, {}) for name in
                   ("detect_workspace_type", "detect_stack", "detect_commands", "find_missing_files")}
            out["tests"] = await box.call("run_tests", {"command": "python -m pytest -q"})
            out["installed"] = await box.call("check_installed", {"name": "react"})
            out["log"] = await box.call("get_command_log", {"limit": 5})
            await db.commit()
            return out

    r = _run(run())
    assert r["detect_workspace_type"]["data"]["workspace_type"] == "web_frontend"
    stack = r["detect_stack"]["data"]["stack"]
    assert {"node", "nextjs", "react", "python"} <= set(stack)
    commands = r["detect_commands"]["data"]["commands"]
    assert commands["build"] == "npm run build" and commands["test"] == "npm test"
    missing = {m["file"] for m in r["find_missing_files"]["data"]["missing"]}
    assert {"README.md", ".gitignore", ".env.example"} <= missing
    assert r["tests"]["success"] and "1 passed" in r["tests"]["stdout"]
    assert r["installed"]["data"]["declared"]["range"] == "^18.3.0" and r["installed"]["data"]["installed"] is None
    assert any("pytest" in c["command"] for c in r["log"]["commands"])


@pytest.mark.integration
def test_git_branch_and_push_gate(project):
    host, root = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            box, _ = await _box(db, host, cls=DevOpsAgent, level=AuthorityLevel.LEVEL_7_DEPLOYMENT)
            branch = await box.call("git_create_branch", {"name": "feature/login"})
            bad = await box.call("git_create_branch", {"name": "--force"})
            push = await box.call("git_push_with_boundary", {"remote": "origin"})
            return branch, bad, push

    branch, bad, push = _run(run())
    head = subprocess.run(["git", "-c", f"safe.directory={root}", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
                          capture_output=True, text=True).stdout.strip()
    assert branch["success"] and head == "feature/login"
    assert bad["success"] is False
    assert push["success"] is False and push["requires_approval"] is True


def test_every_workspace_tool_is_in_the_registry_under_its_design_name():
    registry = get_registry()
    for name in WORKSPACE_TOOLS:
        meta = registry.get_metadata(name)
        assert meta is not None and meta.is_implemented, name
    assert create_tool("delete_file_with_boundary", ToolConfig()).requires_approval is True
    assert create_tool("git_push_with_boundary", ToolConfig()).requires_approval is True
    assert registry.get_metadata("git_status").category == "git"  # existing tools keep their implementation


@pytest.mark.integration
def test_registry_call_runs_through_the_confined_toolbox(project):
    host, root = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_id = await _seed(db, host)
            tool = create_tool("edit_file", ToolConfig(authority_level=AuthorityLevel.LEVEL_3_CODE_EXECUTION))
            ok = await tool.execute({"path": "src/calc.py", "old_text": "a - b", "new_text": "a - b  # checked"},
                                    ToolContext(workspace_id=ws_id, db_session=db))
            outside = await tool.execute({"path": "/etc/hosts", "old_text": "localhost", "new_text": "x"},
                                         ToolContext(workspace_id=ws_id, db_session=db))
            return ok, outside

    ok, outside = _run(run())
    assert ok.success and "# checked" in (root / "src" / "calc.py").read_text()
    assert outside.success is False
