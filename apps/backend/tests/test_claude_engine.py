"""
A specialist's mission on the Claude Agent SDK (command/claude_engine). Real: the role's toolbox and permission gate on
a real folder, the spreadsheet tools, the requirement list, the mission's record and the test database. Stood in: the
SDK session itself (a scripted Claude), so no test spends provider credit. The stand-in calls JAI's tools exactly as
the SDK does, through the MCP handlers the engine gives it, after the PreToolUse hook the engine gives it.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.command import claude_engine
from app.core.command.claude_engine import PREFIX, ClaudeRoleExecutor
from app.core.providers import Message
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12e3a_workspace_tools import project  # noqa: F401


def _run(coro):
    return asyncio.run(coro)


class TextBlock:
    def __init__(self, text):
        self.text = text


class AssistantMessage:
    def __init__(self, text):
        self.content = [TextBlock(text)]
        self.parent_tool_use_id = None


class ResultMessage:
    def __init__(self, subtype="success", cost=0.04, turns=5):
        self.subtype, self.total_cost_usd, self.num_turns = subtype, cost, turns
        self.usage = {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 900,
                      "cache_creation_input_tokens": 10}


class Session:
    """A scripted Claude: each turn is a list of (tool, input) calls, then what it says, then how the turn ends."""

    def __init__(self, turns, fail_at_start=False, fail_after=None):
        self.turns, self.fail_at_start, self.fail_after = list(turns), fail_at_start, fail_after
        self.options, self.prompts, self.results, self.denied, self.interrupted = None, [], [], [], False

    def module(self):
        sdk = types.ModuleType("claude_agent_sdk")
        session = self

        def tool(name, description, schema):
            def wrap(handler):
                return SimpleNamespace(name=name, description=description, input_schema=schema, handler=handler)
            return wrap

        class Client:
            def __init__(self, options):
                session.options = options

            async def __aenter__(self):
                if session.fail_at_start:
                    raise RuntimeError("Claude Code not found")
                return self

            async def __aexit__(self, *exc):
                return False

            async def query(self, prompt):
                session.prompts.append(prompt)

            async def interrupt(self):
                session.interrupted = True

            async def receive_response(self):
                calls, said, ended = session.turns.pop(0) if session.turns else ([], "", "success")
                tools = {t.name: t for t in session.options.mcp_servers["jai"]["tools"]}
                guard = session.options.hooks["PreToolUse"][0].hooks[0]
                for number, (name, args) in enumerate(calls):
                    if session.fail_after is not None and number == session.fail_after:
                        raise RuntimeError("the engine process exited")
                    decision = await guard({"tool_name": name, "tool_input": args}, None, None)
                    if decision:
                        session.denied.append((name, decision["hookSpecificOutput"]["permissionDecisionReason"]))
                        continue
                    if not name.startswith(PREFIX):
                        continue                                     # Claude Code's own (a colleague, a skill)
                    session.results.append((name, await tools[name.removeprefix(PREFIX)].handler(args)))
                    await asyncio.sleep(0)                           # the real session waits on its pipe here
                yield AssistantMessage(said)
                yield ResultMessage(ended)

        sdk.tool = tool
        sdk.create_sdk_mcp_server = lambda name, version, tools: {"name": name, "tools": tools}
        sdk.ClaudeAgentOptions = lambda **kw: SimpleNamespace(**kw)
        sdk.AgentDefinition = lambda **kw: SimpleNamespace(**kw)
        sdk.HookMatcher = lambda matcher=None, hooks=(): SimpleNamespace(matcher=matcher, hooks=list(hooks))
        sdk.ClaudeSDKClient = Client
        return sdk


BOOK = [{"name": "National Chains", "rows": [["Country", "Company", "Website"], ["UK", "Greggs", "greggs.co.uk"]]}]
REQUIREMENTS = [{"id": "R1", "text": "plexecute/partners.xlsx has a National Chains sheet", "status": "open",
                 "source": "the job"},
                {"id": "R2", "text": "Every row has a website", "status": "open", "source": "the job"}]


def _engine_on(monkeypatch, session):
    monkeypatch.setattr(claude_engine, "enabled", lambda: True)
    monkeypatch.setattr(claude_engine, "api_key", lambda: "test-key")
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", session.module())


async def _executor(db, host, task_status=None):
    from app.core.command.tool_runtime import ToolRuntime
    from app.models.task import Task
    from tests.test_repair12e3a_workspace_tools import _seed

    user_id, ws_id = await _seed(db, host)
    task_id = None
    if task_status:
        task_id = uuid4()
        db.add(Task(id=task_id, workspace_id=ws_id, title="m", description="m", task_type="command",
                    status=task_status, priority=5))
        await db.commit()
    runtime = ToolRuntime(db, ws_id, task_id, operator="agent:partnerships", authority_level=3, user_id=user_id)
    runner = ClaudeRoleExecutor(runtime, "gpt-6-luna", host, role="partnerships")
    tools = await runner._prepare_tools()
    from app.core.command.requirements import STATUS_TOOL

    runner.requirements = [dict(r) for r in REQUIREMENTS]
    return runner, runtime, tools + [STATUS_TOOL]


def _loop(runner, tools, budget=60):
    return runner._engine_loop("Build the partners workbook", [Message(role="user", content="MISSION: build it")],
                               runner._system_prompt(True), tools, budget, 15, 0)


@pytest.mark.integration
def test_the_work_runs_on_the_engine_through_jais_own_tools_gates_and_checklist(project, monkeypatch):  # noqa: F811
    host, root = project
    session = Session([([
        ("Agent", {"subagent_type": "sales", "description": "Draft the first emails"}),   # a colleague
        ("Bash", {"command": "rm -rf /"}),                                   # Claude Code's shell: refused
        (f"{PREFIX}write_spreadsheet", {"path": "plexecute/partners.xlsx", "sheets": BOOK}),
        (f"{PREFIX}write_file", {"path": "../../outside.txt", "content": "x"}),   # outside the folder: JAI refuses
        (f"{PREFIX}requirement_status", {"id": "R1", "status": "done", "evidence": "wrote the sheet"}),
        (f"{PREFIX}requirement_status", {"id": "R2", "status": "done", "evidence": "check_spreadsheet: 1 of 1"}),
        (f"{PREFIX}finish", {"summary": "The workbook is built.", "success": True}),
    ], "Done.", "success")])
    _engine_on(monkeypatch, session)

    async def go():
        async with AsyncTestingSessionLocal() as db:
            runner, runtime, tools = await _executor(db, host)
            out = await _loop(runner, tools)
            return runner, runtime, tools, out

    runner, runtime, tools, (summary, success, finished, settled, continuation, last) = _run(go())
    assert finished and success and not settled and summary == "The workbook is built."
    assert (Path(root) / "plexecute" / "partners.xlsx").exists()
    assert not (Path(root).parent.parent / "outside.txt").exists()
    assert session.denied and session.denied[0][0] == "Bash" and "not one of JAI's tools" in session.denied[0][1]
    outside = dict(session.results)[f"{PREFIX}write_file"]
    assert outside["is_error"] is True
    assert runner.delegated == [{"to": "sales", "what": "Draft the first emails"}]
    assert [r["status"] for r in runner.requirements] == ["done", "done"]
    saves = [c for c in runtime.calls if c.get("tool") == "write_file" and c.get("success")]   # every save is a
    assert saves and "partners.xlsx" in str(saves[-1].get("inputs"))                              # file write
    assert any(c.name == "write_spreadsheet" and c.success for c in runner.toolbox.calls)           # JAI's trail
    assert runner.iterations == 5 and runner.engine_cost_usd == pytest.approx(0.04)
    assert runner.usage.cost_usd == pytest.approx(0.04) and runner.usage.totals["cached"] == 900
    # The session itself: JAI's tools only, its skills, its colleagues, no shell, and the allowance.
    options = session.options
    assert options.permission_mode == "dontAsk" and options.model == claude_engine.engine_model()
    assert f"{PREFIX}*" in options.allowed_tools and "Bash" not in options.allowed_tools
    assert {"Bash", "Write", "Edit", "WebSearch", "WebFetch"} <= set(options.disallowed_tools)
    assert options.env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"] == "1" and options.env["ANTHROPIC_API_KEY"]
    assert 0 < options.max_budget_usd <= 2.5 and options.max_turns == 60 + claude_engine.EXTRA_TURNS
    lead = {t["name"] for t in tools}
    for name, agent in options.agents.items():                       # a colleague never exceeds the lead
        own = {t.removeprefix(PREFIX) for t in agent.tools if t.startswith(PREFIX)}
        assert own <= lead - {"finish", "requirement_status"}, name
    assert "sales" in options.agents and "partnerships" not in options.agents
    assert "MISSION: build it" in session.prompts[0]


@pytest.mark.integration
def test_a_cancelled_mission_is_stopped_at_its_next_tool_call(project, monkeypatch):  # noqa: F811
    host, root = project
    session = Session([([(f"{PREFIX}write_spreadsheet", {"path": "plexecute/late.xlsx", "sheets": BOOK})],
                        "", "success")])
    _engine_on(monkeypatch, session)

    async def go():
        async with AsyncTestingSessionLocal() as db:
            runner, runtime, tools = await _executor(db, host, task_status="cancelled")
            out = await _loop(runner, tools)
            return runtime, out

    runtime, (summary, success, finished, *_rest) = _run(go())
    assert not (Path(root) / "plexecute" / "late.xlsx").exists()       # nothing written after the cancel
    assert "cancelled" in summary and session.interrupted
    assert dict(session.results)[f"{PREFIX}write_spreadsheet"]["is_error"] is True


@pytest.mark.integration
def test_a_reply_in_words_with_work_open_sends_the_engine_back_to_work(project, monkeypatch):  # noqa: F811
    host, _ = project
    session = Session([
        ([], "I will now build the workbook.", "success"),
        ([(f"{PREFIX}requirement_status", {"id": "R1", "status": "done", "evidence": "x"}),
          (f"{PREFIX}requirement_status", {"id": "R2", "status": "done", "evidence": "y"}),
          (f"{PREFIX}finish", {"summary": "Built.", "success": True})], "", "success")])
    _engine_on(monkeypatch, session)

    async def go():
        async with AsyncTestingSessionLocal() as db:
            runner, _, tools = await _executor(db, host)
            return await _loop(runner, tools)

    summary, success, finished, *_ = _run(go())
    assert finished and success and summary == "Built."
    assert len(session.prompts) == 2 and session.prompts[1].startswith("[A REPLY IN WORDS DOES NOT DO THE WORK]")


@pytest.mark.integration
def test_the_allowance_and_the_turn_limit_end_the_session_and_say_so(project, monkeypatch):  # noqa: F811
    host, _ = project
    for ended, expect in (("error_max_budget_usd", "spending allowance"), ("error_max_turns", "")):
        session = Session([([(f"{PREFIX}list_files", {"path": "."})], "", ended)])
        _engine_on(monkeypatch, session)

        async def go():
            async with AsyncTestingSessionLocal() as db:
                runner, _, tools = await _executor(db, host)
                return runner, await _loop(runner, tools)

        runner, (summary, success, finished, *_) = _run(go())
        assert not finished                                            # the mission carries on in its next round
        assert expect in summary and runner.capped is (ended == "error_max_budget_usd")


@pytest.mark.integration
def test_without_the_engine_jais_own_loop_runs_the_mission(project, monkeypatch):  # noqa: F811
    host, _ = project

    async def go(session=None, key="test-key", on=True):
        monkeypatch.setattr(claude_engine, "enabled", lambda: on)
        monkeypatch.setattr(claude_engine, "api_key", lambda: key)
        if session is None:
            monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)   # not installed
        else:
            monkeypatch.setitem(sys.modules, "claude_agent_sdk", session.module())
        async with AsyncTestingSessionLocal() as db:
            runner, _, tools = await _executor(db, host)
            return await _loop(runner, tools), runner

    assert _run(go())[0] is None                                       # the SDK is not installed
    assert _run(go(Session([]), key=""))[0] is None                    # no Anthropic key
    assert _run(go(Session([]), on=False))[0] is None                  # MISSION_ENGINE=jai
    assert _run(go(Session([], fail_at_start=True)))[0] is None        # Claude Code could not start
    stopped, runner = _run(go(Session([([(f"{PREFIX}list_files", {"path": "."}),
                                         (f"{PREFIX}list_files", {"path": "."})], "", "success")], fail_after=1)))
    assert stopped is not None and stopped[2] is False                # stopped mid-way: carried on, not lost
    assert "Claude engine stopped" in stopped[0] and runner.iterations == 1


def test_the_engine_is_off_in_tests_and_chosen_for_role_missions_when_on(monkeypatch):
    from app.core.config import settings

    assert claude_engine.enabled() is False                            # tests never spend provider credit
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "MISSION_ENGINE", "claude")
    assert claude_engine.enabled() is True
    monkeypatch.setattr(settings, "MISSION_ENGINE", "jai")
    assert claude_engine.enabled() is False
    assert issubclass(ClaudeRoleExecutor, claude_engine.RoleExecutor)
