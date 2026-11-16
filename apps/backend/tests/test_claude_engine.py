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


# The first message as JAI's own loop builds it (agent_executor), with what JAI already knows for the job.
FIRST = ("MISSION:\nBuild the partners workbook\n\nApproved workspace root: C:\\Projects\n\n"
         "WHAT JAI ALREADY KNOWS (its memory and verified lessons for this workspace, and source documentation; "
         "check memory against the files before relying on it):\nYOUR PLAYBOOKS FOR THIS JOB (your trade's method: "
         "follow them):\n=== partner-sourcing ===\nList the businesses with their websites, then fill_contacts.\n\n"
         "YOUR OTHER SKILLS (each is a full playbook with reference files; when part of this job is what one of them "
         "is for, open it with read_skill before doing that part):\n- cold-email: first emails\n\n"
         "LESSON: Greggs publishes no email; record its contact page.\n\n"
         "REQUIREMENTS (work from this list; mark each with requirement_status as you finish it):\n- R1: x\n\n"
         "Begin by inspecting what you need, then act.")


def _loop(runner, tools, budget=60):
    return runner._engine_loop("Build the partners workbook", [Message(role="user", content=FIRST)],
                               "", tools, budget, 15, 0)


def options_allowed(session):
    return set(session.options.allowed_tools)


def _folder(monkeypatch, root):
    """The product's folder as the session sees it (the test's folder stands for the container's)."""
    monkeypatch.setattr(ClaudeRoleExecutor, "_folder", lambda self: Path(root))


@pytest.mark.integration
def test_the_session_is_claude_code_with_jais_rules_skills_specialists_and_gate(project, monkeypatch,
                                                                                tmp_path):  # noqa: F811
    host, root = project
    session = Session([([
        ("Bash", {"command": "rm -rf /"}),                                   # not part of the session
        ("ToolSearch", {"query": "select:mcp__jai__fill_contacts"}),       # loading a tool: never refused
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
    assert "Bash" in denied and "outside the product's folder" in denied["Write"] and "ToolSearch" not in denied
    assert "ToolSearch" in options_allowed(session)
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
    # What JAI's own loop gives a specialist reaches the session: the chosen skills' playbooks, its other skills
    # (opened with Claude Code's Skill tool) and JAI's lessons (16 November: 0 skills used in 308 tool calls).
    first = session.prompts[0]
    assert "=== partner-sourcing ===" in first and "then fill_contacts" in first
    assert "cold-email" in first and "open it with the Skill tool" in first and "read_skill" not in first
    assert "Greggs publishes no email" in first and "mark each with requirement_status" not in first


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


def _packs(root: Path) -> Path:
    """Superpowers and ECC cloned as scripts/skill-packs.sh clones them, with one ECC agent AgentShield blocked."""
    sp, ecc = root / "superpowers", root / "ecc"
    for folder in (sp / "skills" / "brainstorming", sp / "skills" / "writing-plans", sp / "agents", sp / "commands",
                   sp / "hooks", ecc / "skills" / "fastapi-patterns", ecc / "skills" / "not-chosen", ecc / "agents",
                   ecc / "commands", ecc / "hooks", ecc / "scripts" / "hooks",
                   ecc / "skills" / "continuous-learning-v2" / "hooks"):
        folder.mkdir(parents=True, exist_ok=True)
    for skill in (sp / "skills" / "brainstorming", sp / "skills" / "writing-plans", ecc / "skills" / "fastapi-patterns",
                  ecc / "skills" / "not-chosen", ecc / "skills" / "continuous-learning-v2"):
        (skill / "SKILL.md").write_text("---\nname: x\n---\n")
    (sp / "agents" / "code-reviewer.md").write_text("agent")
    (sp / "commands" / "brainstorm.md").write_text("command")
    (sp / "hooks" / "hooks.json").write_text("{}")
    (ecc / "agents" / "planner.md").write_text("agent")
    (ecc / "agents" / "flagged.md").write_text("agent")
    (ecc / "hooks" / "hooks.json").write_text("{}")
    (ecc / "scripts" / "hooks" / "observe-runner.js").write_text("// ECC's")
    (ecc / "skills" / "continuous-learning-v2" / "hooks" / "observe.sh").write_text("# ECC's")
    (ecc / ".jai-blocked-parts").write_text("agents/flagged.md\n")
    return root


def test_superpowers_and_ecc_load_as_the_plugins_their_authors_ship(tmp_path, monkeypatch):
    from app.core.knowledge import skill_packs

    packs = _packs(tmp_path / "packs")
    monkeypatch.setattr(skill_packs, "packs_dir", lambda: packs)
    runner = SimpleNamespace(_plugins_on_disk=ClaudeRoleExecutor._plugins_on_disk)
    config = tmp_path / "config"
    plugins = {Path(p["path"]).name: Path(p["path"]) for p in ClaudeRoleExecutor._plugins(runner, config)}
    assert set(plugins) == {"superpowers", "ecc"}
    sp, ecc = plugins["superpowers"], plugins["ecc"]
    assert (sp / ".claude-plugin" / "plugin.json").is_file() and (sp / "hooks" / "hooks.json").is_file()
    assert (sp / "agents" / "code-reviewer.md").is_file() and (sp / "commands" / "brainstorm.md").is_file()
    assert {p.name for p in (sp / "skills").iterdir()} == {"brainstorming", "writing-plans"}   # the whole workflow
    assert (ecc / "agents" / "planner.md").is_file() and not (ecc / "agents" / "flagged.md").exists()
    # ECC's hooks and the scripts they run, and its learning skill whose observe.sh the hooks call
    assert (ecc / "hooks" / "hooks.json").is_file() and (ecc / "scripts" / "hooks" / "observe-runner.js").is_file()
    assert (ecc / "skills" / "continuous-learning-v2" / "hooks" / "observe.sh").is_file()
    assert {p.name for p in (ecc / "skills").iterdir()} == {"fastapi-patterns", "continuous-learning-v2"}  # chosen
    assert skill_packs.plugin_parts("ecc") == ["agents", "commands", "hooks", "scripts"]
    assert skill_packs.plugin_parts("superpowers") == ["agents", "commands", "hooks"]
    assert skill_packs.plugin_parts("marketingskills") == []


def test_ecc_learning_runs_through_eccs_own_switches(tmp_path, monkeypatch):
    """ECC's learning system is configured, never rewritten: only the switches ECC's own scripts read."""
    import json as _json

    from app.core.config import settings

    monkeypatch.setattr(settings, "ECC_LEARNING_DIR", str(tmp_path / "learned"))
    env = claude_engine.ecc_learning_env(tmp_path / "Projects" / "pubs")
    assert env["CLAUDE_CODE_ENTRYPOINT"] == "sdk-ts"           # an entrypoint ECC's observe.sh records
    assert env["CLV2_HOMUNCULUS_DIR"] == str(tmp_path / "learned" / "homunculus")
    assert env["ECC_AGENT_DATA_HOME"] == str(tmp_path / "learned" / "ecc")
    assert "stop:format-typecheck" in env["ECC_DISABLED_HOOKS"] and "pre:observe" not in env["ECC_DISABLED_HOOKS"]
    assert _json.loads(Path(env["CLV2_CONFIG"]).read_text())["observer"]["enabled"] is True
    assert env["OBSERVER_MAX_IDLE_SECONDS"] == "0"            # a mission runs unattended at any hour
    monkeypatch.setattr(settings, "ECC_LEARNING_ENABLED", False)
    assert claude_engine.ecc_learning_env(None) == {"ECC_HOOK_PROFILE": "minimal", "ECC_SKIP_OBSERVE": "1"}


def test_with_the_engine_on_every_model_call_of_a_mission_is_claude(monkeypatch):
    from app.core import config
    from app.core.config import settings

    assert config.missions_on_claude() is False                     # tests keep the models they name
    assert config.light_model() == settings.LIGHT_MODEL
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "MISSION_ENGINE", "claude")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(settings, "ROLE_AGENT_MODEL", "gpt-6-luna")
    monkeypatch.setattr(settings, "LIGHT_MODEL", "gpt-6-luna")
    assert config.missions_on_claude() is True
    assert config.mission_model() == settings.CLAUDE_ENGINE_MODEL and config.light_model().startswith("claude")
    from app.core.providers.router import tiered

    monkeypatch.setattr(settings, "MODEL_TIERS_ENABLED", True)
    assert tiered("claude-haiku-5-5").startswith("claude")
    monkeypatch.setattr(settings, "MISSION_ENGINE", "jai")
    assert config.missions_on_claude() is False and config.mission_model() == "gpt-6-luna"


def test_an_independent_check_that_never_answers_reports_the_work_unchecked(monkeypatch):
    from app.core.config import settings

    from app.core.command.agent_executor import AgentExecutor

    async def hangs(mission, summary, settled=False):
        await asyncio.sleep(30)

    monkeypatch.setattr(settings, "VERIFIER_MAX_SECONDS", 0.05)
    runner = SimpleNamespace(verify=hangs, runtime=SimpleNamespace(task_id=None))
    verdict = _run(AgentExecutor.verify_in_time(runner, "m", "done"))
    assert verdict["verified"] is False and verdict["timed_out"] is True
    assert "saved but unchecked" in verdict["unmet"][0]


def test_claude_5_models_are_sent_no_temperature():
    from app.core.providers.base import CompletionRequest, Message as Msg
    from app.core.providers.claude import ClaudeProvider, rejects_sampling

    for model in ("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-2", "claude-opus-4-7"):
        assert rejects_sampling(model), model
    for model in ("claude-sonnet-4-5", "claude-haiku-4-5", "claude-3-5-sonnet"):
        assert not rejects_sampling(model), model
    provider = ClaudeProvider.__new__(ClaudeProvider)
    sent = provider._convert_request(CompletionRequest(model="claude-sonnet-5-5", temperature=0.0, max_tokens=10,
                                                       messages=[Msg(role="user", content="hi")]))
    assert "temperature" not in sent and "top_p" not in sent


def test_every_list_building_specialist_has_the_open_data_prospecting_workflow():
    from app.core.command.role_mission import FINDING_TOOLS, role_tools

    for role in ("partnerships", "marketing", "growth", "business", "research", "sales"):
        mine = set(role_tools(role))
        assert set(FINDING_TOOLS) <= mine, role                     # 15 November: the Sales Lead's alone
        assert "approve_and_send_outreach" not in mine and not any("send" in t for t in mine), role


def test_the_voice_reads_memories_without_writing_so_a_running_mission_never_holds_it(monkeypatch):
    from app.core.jarv_memory import memory_service
    from app.core.voice import live

    asked = []

    async def search_scored(db, query, **kwargs):
        asked.append(kwargs)
        return []

    async def workspaces(db, user_id):
        return [SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(memory_service, "search_scored", search_scored)
    monkeypatch.setattr(live, "_workspaces", workspaces)
    assert _run(live._memories(None, uuid4(), "how's the mission going?", None)) == []
    assert asked and all(kwargs.get("touch") is False for kwargs in asked)   # 15 November: 30 s behind a lock


@pytest.mark.integration
def test_a_path_as_claude_code_gives_it_is_the_workspace_folder_not_a_folder_inside_it(project):  # noqa: F811
    host, root = project

    async def go():
        async with AsyncTestingSessionLocal() as db:
            runner, _, _ = await _executor(db, host)
            box = runner.toolbox
            container = str(box.root_container).rstrip("/")
            return box, box._resolve_host(f"{container}/plexecute/partners.xlsx"), box._resolve_host("plexecute/partners.xlsx")

    box, (by_container, refused), (by_relative, _) = _run(go())
    assert refused is None and by_container == by_relative        # 15 November: written to <root>/host/workspaces/...


def test_each_contact_detail_gets_its_own_source_column():
    from app.core.agents.workspace_ops import contact_columns, write_contacts

    header = ["company", "website", "published phone", "phone source URL", "published email", "email source URL",
              "contact or partnership page URL", "that page's source URL", "still to check", "date checked"]
    columns = contact_columns(header)
    assert {k: header[v] for k, v in columns.items()} == {
        "website": "website", "phone": "published phone", "phone_source": "phone source URL",
        "email": "published email", "email_source": "email source URL", "channel": "contact or partnership page URL",
        "channel_source": "that page's source URL", "gaps": "still to check", "date": "date checked"}
    row = ["Greggs", "https://www.greggs.co.uk", "", "", "", "", "", "", "", ""]
    found = {"ok": True, "phone": "0191 281 7721", "email": "hello@greggs.co.uk",
             "phones": [{"value": "0191 281 7721", "source": "https://www.greggs.co.uk/contact"}],
             "emails": [{"value": "hello@greggs.co.uk", "source": "https://www.greggs.co.uk/help"}],
             "partnership_page": "https://www.greggs.co.uk/partners"}
    filled = write_contacts(row, columns, found, "2026-11-15")
    assert set(filled) == {"phone", "email", "channel"}
    assert row[3] == "https://www.greggs.co.uk/contact" and row[5] == "https://www.greggs.co.uk/help"
    assert row[7] == "https://www.greggs.co.uk/partners" and row[9] == "2026-11-15"


def test_a_requirement_the_independent_check_found_met_with_evidence_is_marked_done():
    """16 November, mission 6f10b402: the check confirmed four of eight requirements with evidence and the card still
    said "0 requirements done", because the engine's session has no requirement_status tool."""
    requirements = [{"id": f"R{i}", "text": f"requirement {i}", "status": "open"} for i in (1, 2, 3, 10)]
    checks = [{"requirement": "R1: partners.xlsx exists", "met": True, "evidence": "50 rows in sheet Partners"},
              {"requirement": "R2", "met": True, "evidence": ""},                     # no evidence: not done
              {"requirement": "R3", "met": False, "evidence": "Zizzi's phone is one digit short"},
              {"requirement": "r10 every source", "met": True, "evidence": "50 of 50 on their own site"}]
    assert claude_engine.mark_met(requirements, checks) == 2
    assert [r["status"] for r in requirements] == ["done", "open", "open", "done"]   # R1 never marks R10
    assert requirements[0]["evidence"] == "50 rows in sheet Partners"
    assert requirements[0]["checked_by"] == "JAI's independent check"
    assert claude_engine.mark_met(requirements, None) == 2 and claude_engine.mark_met(None, checks) == 0


def test_the_briefing_jais_own_loop_builds_is_taken_whole_and_nothing_else():
    known = claude_engine.briefing([Message(role="user", content=FIRST)])
    assert known.startswith("YOUR PLAYBOOKS FOR THIS JOB") and known.endswith("record its contact page.")
    assert "REQUIREMENTS" not in known and "Begin by" not in known and "the Skill tool" in known
    assert claude_engine.briefing([Message(role="user", content="MISSION: build it")]) == ""
    assert claude_engine.briefing([]) == "" and claude_engine.briefing(None) == ""
