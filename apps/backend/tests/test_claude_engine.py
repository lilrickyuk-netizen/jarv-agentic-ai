"""
A specialist's mission on the Claude Agent SDK, set up as Claude Code is (command/claude_engine). Real: the role's
toolbox and JAI's permission gate on a real folder, the spreadsheet tools, the mission's record and the test
database. Stood in: the SDK session itself (a scripted Claude), so no test spends provider credit. The stand-in
behaves as Claude Code does: every tool call passes the session's PreToolUse hook first, Claude Code's own tools then
run (Write writes the file, Read reads it), JAI's tools run through the MCP handlers the engine serves, and the
PostToolUse hook follows.
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


class SystemMessage:
    def __init__(self, session_id):
        self.subtype = "init"
        self.data = {"session_id": session_id, "tools": ["Read", "Write"], "skills": ["partner-sourcing"]}


class ResultMessage:
    def __init__(self, subtype="success", cost=0.04, turns=5, session_id="s-1", result="Done."):
        self.subtype, self.total_cost_usd, self.num_turns = subtype, cost, turns
        self.session_id, self.result = session_id, result
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

        async def claude_code(name, args):
            """Claude Code's own tools, as they act once the hooks allow them."""
            folder = Path(session.options.cwd)
            if name in ("Write", "Read", "Edit"):
                path = Path(args["file_path"])
                path = path if path.is_absolute() else folder / path
                if name == "Write":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(args["content"])
                    return {"type": "create", "filePath": str(path)}
                return {"file": {"content": path.read_text()}}
            if name == "WebFetch":
                return {"result": "the page", "code": 200}
            return {}

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
                pre = session.options.hooks["PreToolUse"][0].hooks[0]
                post = session.options.hooks["PostToolUse"][0].hooks[0]
                yield SystemMessage("s-1")
                for number, (name, args) in enumerate(calls):
                    if session.fail_after is not None and number == session.fail_after:
                        raise RuntimeError("the engine process exited")
                    if name in session.options.disallowed_tools:
                        session.denied.append((name, "not in the session"))
                        continue
                    decision = await pre({"tool_name": name, "tool_input": args}, None, None)
                    if decision:
                        session.denied.append((name, decision["hookSpecificOutput"]["permissionDecisionReason"]))
                        continue
                    if name.startswith(PREFIX):
                        answer = await tools[name.removeprefix(PREFIX)].handler(args)
                    else:
                        answer = await claude_code(name, args)
                    session.results.append((name, answer))
                    await post({"tool_name": name, "tool_input": args, "tool_response": answer}, None, None)
                    await asyncio.sleep(0)                           # the real session waits on its pipe here
                yield AssistantMessage(said or "Done.")
                yield ResultMessage(ended, result=said or "Done.")

        sdk.tool = tool
        sdk.create_sdk_mcp_server = lambda name, version, tools: {"name": name, "tools": tools}
        sdk.ClaudeAgentOptions = lambda **kw: SimpleNamespace(**kw)
        sdk.AgentDefinition = lambda **kw: SimpleNamespace(**kw)
        sdk.HookMatcher = lambda matcher=None, hooks=(): SimpleNamespace(matcher=matcher, hooks=list(hooks))
        sdk.ClaudeSDKClient = Client
        return sdk


BOOK = [{"name": "National Chains", "rows": [["Country", "Company", "Website"], ["UK", "Greggs", "greggs.co.uk"]]}]
REQUIREMENTS = [{"id": "R1", "text": "plexecute/partners.xlsx has a National Chains sheet", "status": "open",
                 "source": "the job"}]


def _engine_on(monkeypatch, session, tmp_path):
    monkeypatch.setattr(claude_engine, "enabled", lambda: True)
    monkeypatch.setattr(claude_engine, "api_key", lambda: "test-key")
    monkeypatch.setattr(claude_engine, "sessions_root", lambda: tmp_path / "sessions")
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", session.module())


async def _executor(db, host, task_status=None, task_id=None):
    from app.core.command.tool_runtime import ToolRuntime
    from app.models.task import Task
    from tests.test_repair12e3a_workspace_tools import _seed

    user_id, ws_id = await _seed(db, host)
    if task_status:
        task_id = task_id or uuid4()
        if await db.get(Task, task_id) is None:
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
                               "", tools, budget, 15, 0)


def _folder(monkeypatch, root):
    """The product's folder as the session sees it (the test's folder stands for the container's)."""
    monkeypatch.setattr(ClaudeRoleExecutor, "_folder", lambda self: Path(root))


@pytest.mark.integration
def test_the_session_is_claude_code_with_jais_rules_skills_specialists_and_gate(project, monkeypatch,
                                                                                tmp_path):  # noqa: F811
    host, root = project
    session = Session([([
        ("Bash", {"command": "rm -rf /"}),                                   # not part of the session
        ("TodoWrite", {"todos": [{"content": "Find chains", "status": "in_progress"}]}),
        ("WebFetch", {"url": "https://www.greggs.co.uk/contact", "prompt": "contact details"}),
        ("WebFetch", {"url": "http://169.254.169.254/latest/meta-data", "prompt": "x"}),   # never opened
        ("Write", {"file_path": "plexecute/notes.md", "content": "# Partners\n"}),   # Claude Code's own Write
        ("Write", {"file_path": "/etc/outside.txt", "content": "x"}),        # outside the folder: refused
        (f"{PREFIX}write_spreadsheet", {"path": "plexecute/partners.xlsx", "sheets": BOOK}),   # JAI's own tool
        ("Read", {"file_path": "plexecute/notes.md"}),
        ("Agent", {"subagent_type": "sales", "description": "Draft the first emails", "prompt": "..."}),
    ], "The workbook is built.", "success")])
    _engine_on(monkeypatch, session, tmp_path)
    _folder(monkeypatch, root)

    async def go():
        async with AsyncTestingSessionLocal() as db:
            runner, runtime, tools = await _executor(db, host)
            out = await _loop(runner, tools)
            return runner, runtime, tools, out

    runner, runtime, tools, (summary, success, finished, settled, continuation, last) = _run(go())
    assert finished and success and not settled and summary == "The workbook is built."
    assert (Path(root) / "plexecute" / "notes.md").read_text() == "# Partners\n"
    assert (Path(root) / "plexecute" / "partners.xlsx").exists()
    assert not Path("/etc/outside.txt").exists()
    denied = dict(session.denied)
    assert "Bash" in denied and "outside the product's folder" in denied["Write"]
    assert "not one JAI may open" in denied["WebFetch"]
    record = [(c["tool"], c["success"]) for c in runtime.calls]
    assert ("fetch_url", True) in record
    assert ("write_file", True) in record and ("read_file", True) in record and ("write_file", False) in record
    saved = [c for c in runtime.calls if c["tool"] == "write_file" and c["success"]]
    assert any(str(c["inputs"].get("path", "")).replace("\\", "/").endswith("plexecute/notes.md") for c in saved)
    assert runner.delegated == [{"to": "sales", "what": "Draft the first emails"}]
    assert runner.engine_cost_usd == pytest.approx(0.04) and runner.usage.totals["cached"] == 900
    assert runner.session_id == "s-1" and runner.skills_seen == ["partner-sourcing"]

    options = session.options
    assert options.system_prompt["type"] == "preset" and options.system_prompt["preset"] == "claude_code"
    assert "Partnerships" in options.system_prompt["append"] and "PECR" in options.system_prompt["append"]
    assert options.permission_mode == "dontAsk" and options.model == claude_engine.engine_model()
    assert {"Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", "Skill", "Agent"} <= set(
        options.allowed_tools) and f"{PREFIX}*" in options.allowed_tools
    assert "Bash" in options.disallowed_tools and "Bash" not in options.allowed_tools
    assert options.cwd == str(root) and options.setting_sources == ["user"]
    assert Path(options.env["CLAUDE_CONFIG_DIR"], "skills").is_dir()          # every installed JAI skill links here
    assert options.env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"] == "1" and options.env["ANTHROPIC_API_KEY"]
    assert 0 < options.max_budget_usd <= 2.5 and options.resume is None
    served = {t.name for t in options.mcp_servers["jai"]["tools"]}
    assert "write_spreadsheet" in served and not served & {"finish", "requirement_status", "write_file", "fetch_url"}
    for name, agent in options.agents.items():                       # a colleague never exceeds the lead
        own = {t.removeprefix(PREFIX) for t in agent.tools if t.startswith(PREFIX)}
        assert own <= served, name
        assert "Agent" not in agent.tools and "Bash" not in agent.tools
    assert "sales" in options.agents and "partnerships" not in options.agents
    assert session.prompts[0].startswith("Build the partners workbook")
    assert "WHAT JAI'S INDEPENDENT CHECK WILL LOOK FOR" in session.prompts[0]


@pytest.mark.integration
def test_the_review_goes_back_to_the_agent_once_and_what_is_left_is_reported(project, monkeypatch,
                                                                            tmp_path):  # noqa: F811
    host, root = project
    session = Session([
        ([(f"{PREFIX}write_spreadsheet", {"path": "plexecute/partners.xlsx", "sheets": BOOK})], "Built.", "success"),
        ([(f"{PREFIX}write_spreadsheet", {"path": "plexecute/partners.xlsx", "sheets": BOOK})], "Fixed the site.",
         "success")])
    _engine_on(monkeypatch, session, tmp_path)
    _folder(monkeypatch, root)
    verdicts = [{"verified": False, "unmet": ["R1: Greggs's website is not its own address"], "checks": []},
                {"verified": True, "unmet": [], "checks": []}]
    seen = []

    async def verify(self, mission, summary, settled=False):
        seen.append(summary)
        return dict(verdicts[len(seen) - 1])

    monkeypatch.setattr(claude_engine.RoleExecutor, "verify", verify)

    async def go():
        async with AsyncTestingSessionLocal() as db:
            runner, _, tools = await _executor(db, host)
            runner._verify_on = True
            out = await _loop(runner, tools)
            after = await runner.verify("Build the partners workbook", out[0])     # the check after the session
            return runner, out, after

    runner, (summary, success, finished, settled, *_), after = _run(go())
    assert finished and settled and summary == "Fixed the site."           # what is left is reported, not re-run
    assert len(session.prompts) == 2 and "Greggs's website is not its own address" in session.prompts[1]
    assert seen == ["Built.", "Fixed the site."] and after["verified"] is True   # the fix is checked afresh


@pytest.mark.integration
def test_work_the_review_accepts_ends_with_no_more_turns(project, monkeypatch, tmp_path):  # noqa: F811
    host, root = project
    session = Session([([(f"{PREFIX}write_spreadsheet", {"path": "plexecute/partners.xlsx", "sheets": BOOK})],
                        "Built.", "success")])
    _engine_on(monkeypatch, session, tmp_path)
    _folder(monkeypatch, root)
    seen = []

    async def verify(self, mission, summary, settled=False):
        seen.append(summary)
        return {"verified": True, "unmet": [], "checks": []}

    monkeypatch.setattr(claude_engine.RoleExecutor, "verify", verify)

    async def go():
        async with AsyncTestingSessionLocal() as db:
            runner, _, tools = await _executor(db, host)
            runner._verify_on = True
            out = await _loop(runner, tools)
            return out, await runner.verify("m", out[0])

    (summary, success, finished, settled, *_), after = _run(go())
    assert finished and success and not settled and len(session.prompts) == 1
    assert after["verified"] and seen == ["Built."]                        # the one check stands


@pytest.mark.integration
def test_a_cancelled_mission_is_stopped_at_its_next_call(project, monkeypatch, tmp_path):  # noqa: F811
    host, root = project
    session = Session([([("Write", {"file_path": "plexecute/late.md", "content": "x"}),
                         (f"{PREFIX}write_spreadsheet", {"path": "plexecute/late.xlsx", "sheets": BOOK})],
                        "", "success")])
    _engine_on(monkeypatch, session, tmp_path)
    _folder(monkeypatch, root)

    async def go():
        async with AsyncTestingSessionLocal() as db:
            runner, runtime, tools = await _executor(db, host, task_status="cancelled")
            return await _loop(runner, tools)

    summary, success, finished, *_ = _run(go())
    assert not (Path(root) / "plexecute" / "late.md").exists()
    assert not (Path(root) / "plexecute" / "late.xlsx").exists()
    assert "cancelled" in summary and session.interrupted and len(session.denied) == 2


@pytest.mark.integration
def test_a_round_cut_short_carries_on_in_the_same_session(project, monkeypatch, tmp_path):  # noqa: F811
    host, root = project
    task_id = uuid4()
    for ended in ("error_max_turns", "error_max_budget_usd"):
        session = Session([([("Write", {"file_path": "plexecute/a.md", "content": "x"})], "", ended)])
        _engine_on(monkeypatch, session, tmp_path)
        _folder(monkeypatch, root)

        async def go():
            async with AsyncTestingSessionLocal() as db:
                runner, _, tools = await _executor(db, host, task_status="running", task_id=uuid4())
                return runner, await _loop(runner, tools)

        runner, (summary, success, finished, *_) = _run(go())
        assert not finished and runner.capped is (ended == "error_max_budget_usd")
        if runner.capped:
            assert "spending allowance" in summary

    first = Session([([("Write", {"file_path": "plexecute/a.md", "content": "x"})], "", "error_max_turns")])
    second = Session([([], "Finished.", "success")])
    for session in (first, second):
        _engine_on(monkeypatch, session, tmp_path)
        _folder(monkeypatch, root)

        async def go():
            async with AsyncTestingSessionLocal() as db:
                runner, _, tools = await _executor(db, host, task_status="running", task_id=task_id)
                return await _loop(runner, tools)

        out = _run(go())
    assert first.options.resume is None and second.options.resume == "s-1"
    assert second.prompts == ["Carry on with the mission from where you stopped."] and out[2] is True


@pytest.mark.integration
def test_without_the_engine_jais_own_loop_runs_the_mission(project, monkeypatch, tmp_path):  # noqa: F811
    host, root = project

    async def go(session=None, key="test-key", on=True):
        monkeypatch.setattr(claude_engine, "enabled", lambda: on)
        monkeypatch.setattr(claude_engine, "api_key", lambda: key)
        monkeypatch.setattr(claude_engine, "sessions_root", lambda: tmp_path / "sessions")
        _folder(monkeypatch, root)
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", None if session is None else session.module())
        async with AsyncTestingSessionLocal() as db:
            runner, _, tools = await _executor(db, host)
            return await _loop(runner, tools), runner

    assert _run(go())[0] is None                                       # the SDK is not installed
    assert _run(go(Session([]), key=""))[0] is None                    # no Anthropic key
    assert _run(go(Session([]), on=False))[0] is None                  # MISSION_ENGINE=jai
    assert _run(go(Session([], fail_at_start=True)))[0] is None        # Claude Code could not start
    stopped, runner = _run(go(Session([([("Write", {"file_path": "plexecute/b.md", "content": "x"}),
                                         ("Write", {"file_path": "plexecute/c.md", "content": "y"})], "",
                                        "success")], fail_after=1)))
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
    assert "Bash" in claude_engine.REMOVED and "Write" in claude_engine.OWN_TOOLS
