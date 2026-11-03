"""
The MYCO acceptance mission did its work in a few rounds, then ran 20: the independent check had 16 steps for nine
requirements and ended with no verdict, each round's report could cite only that round's actions (so its score
swung from 8 of 9 to 0 of 9 with nothing changed), "task verify" timed out at 120 seconds every time, and
"git log --format=%h %s" was refused as a path outside the workspace. These tests hold each fix.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.command.agent_executor import _VERIFIER_SYSTEM, VERIFIER_STEPS, evidence_calls, verifier_steps
from app.core.command.continuation import IDLE_ROUNDS_LIMIT, after_round, round_changed_workspace
from app.core.command.tool_runtime import command_timeout
from app.core.config import settings
from app.core.runtime import lifecycle
from app.core.synthesis.report import build_ledger, check


def _cmd(command, ok=True, code=None):
    code = (0 if ok else 1) if code is None else code
    return {"tool": "run_command", "inputs": {"command": command}, "success": ok, "summary": f"exit={code}",
            "output": {"exit_code": code}}


ROUND_3 = [_cmd("pnpm install --frozen-lockfile"), _cmd("pnpm lint"), _cmd("pnpm test"),
           {"tool": "write_file", "inputs": {"path": ".python-version"}, "success": True, "summary": "wrote 7 bytes"}]
ROUND_4 = [_cmd("pnpm test", ok=False), _cmd("pnpm test")]   # a flaky run, then a pass
ROUND_9 = [{"tool": "read_file", "inputs": {"path": "README.md"}, "success": True, "summary": "read"},
           {"tool": "run_command", "inputs": {"command": "git push"}, "success": False,
            "summary": "paused for approval: git push needs Richard"}]


def test_evidence_from_earlier_rounds_stays_citable():
    trail = evidence_calls(ROUND_3 + ROUND_4, ROUND_9)
    commands = [c["inputs"].get("command") for c in trail if c["tool"] == "run_command"]
    assert "pnpm install --frozen-lockfile" in commands and "pnpm lint" in commands  # proven in round 3
    assert commands.count("pnpm test") == 1 and next(c for c in trail if c["inputs"].get("command") == "pnpm test")["success"]
    assert any(str(c["summary"]).startswith("paused for approval") for c in trail)  # pauses are never merged away
    ledger = build_ledger(trail, [])
    install = next(e for e in ledger if e["target"] == "pnpm install --frozen-lockfile")
    reqs = [{"id": "R1", "text": "locked install passes", "source": "mission", "status": "done", "evidence": ""}]
    report = check({"overall": "x", "items": [{"requirement": "R1", "status": "done", "statement": "installed",
                                               "evidence": [install["id"]]}]}, reqs, ledger, {"unmet": []}, None)
    assert report["items"][0]["status"] == "done"  # round 9's report can still show round 3's proof


def test_the_trail_stays_short_on_a_long_mission():
    earlier = [_cmd("pnpm test") for _ in range(400)] + [_cmd(f"step {i}") for i in range(300)]
    assert len(evidence_calls(earlier, [])) <= 220


def test_the_independent_check_has_steps_for_every_requirement():
    assert verifier_steps(0) == VERIFIER_STEPS and verifier_steps(2) == VERIFIER_STEPS
    assert verifier_steps(9) == 35 and verifier_steps(40) == 48
    assert "git log, git show --stat, git status and git diff" in _VERIFIER_SYSTEM
    assert "call verdict before you run out" in _VERIFIER_SYSTEM


def test_long_project_commands_get_the_long_limit():
    long, short = settings.AGENT_LONG_COMMAND_TIMEOUT_SECONDS, settings.AGENT_COMMAND_TIMEOUT_SECONDS
    assert long >= 600 and short == 120
    for command in ("task verify", "pnpm test", "uv run pytest", "terraform test", "C:\\tools\\task.exe verify"):
        assert command_timeout(command) == long, command
    assert command_timeout("git status") == short and command_timeout("ls docs") == short
    assert command_timeout("some-tool run", "build") == long


@pytest.mark.parametrize("command, refused", [
    ("git log --format=%h %ad %s", False),
    ("git log --format=%h%n%s", False),
    ("date +%Y-%m-%d", False),
    ("type %USERPROFILE%\\secrets.txt", True),
    ("dir %APPDATA%", True),
    ("cat ~/.ssh/id_rsa", True),
    ("echo $HOME", True),
])
def test_format_strings_are_not_mistaken_for_outside_paths(command, refused):
    import shlex

    from app.core.agents.toolbox import AgentToolbox

    if command.startswith("git log --format=%h %ad"):
        command = "git log " + shlex.quote("--format=%h %ad %s")
    reason = AgentToolbox._command_refusal(SimpleNamespace(_resolve_host=lambda v: (v, None)), command)
    assert (reason is not None and "outside the workspace" in reason) is refused, (command, reason)


def test_rounds_that_change_nothing_stop_for_review():
    assert round_changed_workspace(ROUND_3) is True
    assert round_changed_workspace([_cmd("git commit -m 'Correct docs'")]) is True
    assert round_changed_workspace(ROUND_9) is False
    assert round_changed_workspace([{"tool": "write_file", "inputs": {"path": "x"}, "success": False}]) is False
    first = after_round(lifecycle.NEEDS_CONTINUATION, "check not passed", False, 0)
    assert first[0] == lifecycle.NEEDS_CONTINUATION and first[2] == 1
    second = after_round(lifecycle.NEEDS_CONTINUATION, "check not passed", False, first[2])
    assert second[0] == lifecycle.PARTIAL and second[2] == IDLE_ROUNDS_LIMIT and "Richard's review" in second[1]
    # A round that changed something resets the count; a completed mission is never touched.
    assert after_round(lifecycle.NEEDS_CONTINUATION, "r", True, 5) == (lifecycle.NEEDS_CONTINUATION, "r", 0)
    assert after_round(lifecycle.COMPLETED, None, False, 9)[0] == lifecycle.COMPLETED


def test_a_missing_program_is_reported_not_installed_into_the_project():
    import asyncio
    from uuid import uuid4

    from app.core.command.tool_runtime import ToolRuntime
    from tests.conftest import AsyncTestingSessionLocal
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            return await rt.run_command(f"definitely-not-installed-{uuid4().hex[:6]} version", cwd_host=host,
                                        approval_granted=True)

    import shutil
    try:
        out = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if out.get("exit_code") == 127:  # the program was looked up and is not there
        assert "never download or install it into the project folder" in out["stderr"]
        assert "report it as missing" in out["stderr"]
    else:  # refused before running (an unknown program needs approval): it never ran, so nothing was installed
        assert out["success"] is False
