"""
Wave 5, code: JAI's agents read code as an IDE does through Serena's language servers (definitions, callers,
implementations, errors), read-only and confined to the workspace, and a mission that goes round in circles is told
so and asked to change approach (OpenHands' stuck detection). Real: the MCP client's conversation with Serena
(against an httpx MockTransport speaking streamable HTTP), the toolbox and runtime on a sandbox workspace, the
stuck detector, and a whole mission run with a scripted model. No Serena or language server is needed.
"""
import asyncio
import json
import shutil

import httpx
import pytest

from app.core.agents.base import AuthorityLevel
from app.core.agents.specialists.coding_agent import CodingAgent
from app.core.agents.toolbox import CODE_TOOLS, AgentToolbox
from app.core.code import serena
from app.core.command.stuck import StuckDetector
from app.core.config import settings
from app.core.providers import CompletionResponse
from tests.conftest import AsyncTestingSessionLocal
from tests.test_repair12c_agent_tools import _agent, _ctx, _seed, project  # noqa: F401 - project is a fixture


def _run(coro):
    return asyncio.run(coro)


class FakeSerena:
    """Serena's MCP endpoint: a session id on initialize, answers as server-sent events, one project at a time."""

    def __init__(self, forget_after=None):
        self.seen, self.sessions, self.forget_after = [], 0, forget_after

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        session = request.headers.get("mcp-session-id")
        self.seen.append((method, (body.get("params") or {}).get("name"), session,
                          (body.get("params") or {}).get("arguments")))
        assert request.url.path == "/mcp" and "text/event-stream" in request.headers["accept"]
        if method == "initialize":
            self.sessions += 1
            return httpx.Response(200, headers={"mcp-session-id": f"s{self.sessions}", "content-type": "application/json"},
                                  json={"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18"}})
        if method == "notifications/initialized":
            return httpx.Response(202)
        if self.forget_after is not None and len(self.seen) > self.forget_after and session == "s1":
            return httpx.Response(404, text="Session not found")
        name = body["params"]["name"]
        if name == "find_symbol" and body["params"]["arguments"]["name_path_pattern"] == "missing":
            result = {"content": [{"type": "text", "text": "No symbol named missing"}], "isError": True}
        else:
            result = {"content": [{"type": "text", "text": f"{name} answered"}], "isError": False}
        event = "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}) + "\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=event)


def _client(fake):
    return serena.SerenaClient("http://serena:9121", httpx.AsyncClient(transport=httpx.MockTransport(fake)))


def test_serena_is_asked_over_mcp_with_one_session_and_the_project_activated_once():
    fake = FakeSerena()
    code = _client(fake)

    async def run():
        first = await code.call("/host/workspaces/shop", "find_symbol", {"name_path_pattern": "Cart"})
        second = await code.call("/host/workspaces/shop", "get_symbols_overview", {"relative_path": "src/cart.py"})
        other = await code.call("/host/workspaces/blog", "get_symbols_overview", {"relative_path": "app.py"})
        return first, second, other

    first, second, other = _run(run())
    assert (first, second, other) == ("find_symbol answered", "get_symbols_overview answered",
                                      "get_symbols_overview answered")
    methods = [(m, n) for m, n, _, _ in fake.seen]
    assert methods[:2] == [("initialize", None), ("notifications/initialized", None)]
    activations = [args["project"] for m, n, _, args in fake.seen if n == "activate_project"]
    assert activations == ["/host/workspaces/shop", "/host/workspaces/blog"]
    assert all(session == "s1" for m, _, session, _ in fake.seen[1:])


def test_a_forgotten_session_is_started_again_and_a_serena_error_is_reported():
    fake = FakeSerena(forget_after=3)
    code = _client(fake)

    async def run():
        await code.call("/host/workspaces/shop", "find_symbol", {"name_path_pattern": "Cart"})
        answer = await code.call("/host/workspaces/shop", "find_symbol", {"name_path_pattern": "Order"})
        with pytest.raises(serena.CodeUnavailable, match="No symbol named missing"):
            await code.call("/host/workspaces/shop", "find_symbol", {"name_path_pattern": "missing"})
        return answer

    assert _run(run()) == "find_symbol answered"
    assert fake.sessions == 2


def test_serena_that_is_not_running_is_reported_plainly(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(serena.CodeUnavailable, match="could not be reached"):
        _run(_client(refuse).call("/host/workspaces/shop", "find_symbol", {"name_path_pattern": "Cart"}))
    monkeypatch.setattr(settings, "SERENA_URL", "")
    with pytest.raises(serena.CodeUnavailable, match="turned off"):
        serena.client()


def test_jai_asks_only_read_only_questions_with_paths_inside_the_project():
    assert set(serena.TOOLS.values()) == {"get_symbols_overview", "find_symbol", "find_referencing_symbols",
                                          "find_implementations", "get_diagnostics_for_file"}
    assert serena.arguments("code_find_symbol", {"symbol": "Cart/add", "path": "./src/cart.py",
                                                 "include_body": True}) == {
        "name_path_pattern": "Cart/add", "relative_path": "src/cart.py", "include_body": True,
        "substring_matching": True, "depth": 0}
    assert serena.arguments("code_overview", {"path": "src/cart.py"}) == {"relative_path": "src/cart.py", "depth": 1}
    with pytest.raises(serena.CodeUnavailable, match="inside the workspace"):
        serena.arguments("code_overview", {"path": "../other/secret.py"})
    with pytest.raises(serena.CodeUnavailable, match="path of a source file"):
        serena.arguments("code_diagnostics", {})
    with pytest.raises(serena.CodeUnavailable, match="name of the symbol"):
        serena.arguments("code_references", {"path": "src/cart.py"})
    context = open(settings_path("services/serena/jai-context.yml")).read()
    for editing in ("ToolMarkerCanEdit", "execute_shell_command", "write_memory", "serena_repl"):
        assert f"- {editing}" in context


def settings_path(relative):
    from pathlib import Path

    for base in Path(__file__).resolve().parents:
        if (base / relative).exists():
            return base / relative
    pytest.skip(f"{relative} is outside this checkout")


def test_an_agent_reads_code_through_serena_inside_its_workspace_and_it_is_recorded(project, monkeypatch):
    root_host, root, other_host = project
    asked = []

    class Recorder:
        async def call(self, project_path, tool, arguments):
            asked.append((project_path, tool, arguments))
            return "def add(a, b):  # src/app.py line 1"

    monkeypatch.setattr(settings, "SERENA_URL", "http://serena:9121")
    monkeypatch.setattr(serena, "client", lambda: Recorder())

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            agent = _agent(CodingAgent, ws_id, user_id, AuthorityLevel.LEVEL_3_CODE_EXECUTION)
            box = await AgentToolbox(agent, _ctx(db, ws_id, user_id)).prepare()
            found = await box.call("code_find_symbol", {"symbol": "add", "path": "src/app.py", "include_body": True})
            outside = await box.call("code_overview", {"path": f"{other_host}/private.txt"})
            whole = await box.call("code_find_symbol", {"symbol": "add"})
            await db.commit()
            return box.available, found, outside, whole, list(box.runtime.calls)

    available, found, outside, whole, calls = _run(run())
    assert set(CODE_TOOLS) <= set(available)
    assert found["success"] is True and "def add" in found["answer"]
    assert outside.get("blocked") is True and "outside this workspace" in outside["reason"]
    assert whole["success"] is True
    assert len(asked) == 2
    assert asked[0][0] == str(root.resolve()) and asked[0][1] == "find_symbol"
    assert asked[0][2]["relative_path"] == "src/app.py" and asked[0][2]["include_body"] is True
    assert asked[1][2]["relative_path"] == ""
    recorded = [c for c in calls if c.get("tool") == "code_find_symbol"]
    assert len(recorded) == 2 and all(c["success"] for c in recorded)


def test_without_serena_no_agent_is_offered_the_code_tools(project):
    root_host, _, _ = project

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db, root_host)
            agent = _agent(CodingAgent, ws_id, user_id, AuthorityLevel.LEVEL_3_CODE_EXECUTION)
            box = await AgentToolbox(agent, _ctx(db, ws_id, user_id)).prepare()
            return box.available

    assert not set(CODE_TOOLS) & set(_run(run()))


def test_the_code_tools_are_registered_read_only_tools():
    from app.core.safety.permission_policy import get_tool_policy
    from app.core.tools.registry import get_registry

    for name in CODE_TOOLS:
        policy = get_tool_policy(name)
        assert policy.required_authority == 1 and policy.action_type == "read" and not policy.requires_approval, name
        meta = get_registry().get_metadata(name)
        assert meta is not None and meta.is_implemented, name


# ----- going round in circles --------------------------------------------------------------------------------------

def test_the_same_failure_three_times_is_noticed_once():
    stuck = StuckDetector()
    failed = {"success": False, "error": "npm ERR! missing script: build"}
    assert stuck.observe("run_build", {}, failed) is None
    assert stuck.observe("run_build", {}, failed) is None
    nudge = stuck.observe("run_build", {}, failed)
    assert nudge.startswith("[STUCK]") and "missing script: build" in nudge and "web_search" in nudge
    assert stuck.observe("run_build", {}, failed) is None  # a new loop has to build up again


def test_the_same_result_four_times_and_two_actions_swapping_are_noticed():
    stuck = StuckDetector()
    same = {"success": True, "content": "hello"}
    assert [stuck.observe("read_file", {"path": "a.py"}, same) for _ in range(3)] == [None] * 3
    assert "same result" in stuck.observe("read_file", {"path": "a.py"}, same)

    swap = StuckDetector()
    said = [swap.observe(*(("read_file", {"path": "a.py"}, same) if i % 2 == 0 else
                           ("list_files", {"path": "."}, {"success": True, "files": ["a.py"]}))) for i in range(6)]
    assert said[:5] == [None] * 5 and "back and forth" in said[5]


def test_real_progress_is_never_called_stuck():
    stuck = StuckDetector()
    for i in range(12):
        assert stuck.observe("read_file", {"path": f"src/part{i}.py"}, {"success": True, "content": str(i)}) is None
    # Polling the same thing while its answer changes is progress too.
    for i in range(6):
        assert stuck.observe("run_tests", {}, {"success": False, "error": f"{6 - i} failing"}) is None


class _LoopingRouter:
    """The mission reads a file that does not exist three times, then finishes; the Verifier accepts."""

    def __init__(self):
        self.mission_messages = []
        self.turns = [[("read_file", {"path": "src/missing.py"})]] * 3 + [
            [("finish", {"summary": "Gave the missing file up.", "success": True})]]

    async def complete(self, request):
        system = request.system or ""
        if system.startswith("You are JAI's requirements analyst"):
            calls = [("record_requirements", {"requirements": []})]
        elif system.startswith("You are JAI's Verifier Agent"):
            calls = [("verdict", {"verified": True, "unmet": [], "checks": []})]
        else:
            self.mission_messages = list(request.messages)
            calls = self.turns.pop(0) if self.turns else [("finish", {"summary": "x", "success": True})]
        return CompletionResponse(id="r", model="test", content="", usage={"total_tokens": 3}, tool_calls=[
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(calls)])


@pytest.mark.integration
def test_a_mission_going_round_in_circles_is_told_to_change_approach(monkeypatch):
    from app.core.command import agent_executor
    from app.core.command.agent_executor import AgentExecutor
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    router = _LoopingRouter()
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            return await AgentExecutor(rt, "test-model", host).run("Tidy src/missing.py.", max_continuations=0)

    try:
        result = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    told = [block["text"] for m in router.mission_messages if isinstance(m.content, list)
            for block in m.content if block.get("type") == "text" and block.get("text", "").startswith("[STUCK]")]
    assert len(told) == 1 and "read_file" in told[0]
    assert result["stuck_loops"] == 1


def test_a_note_sent_with_tool_results_reaches_the_model_after_them():
    from app.core.providers.base import CompletionRequest, Message
    from app.core.providers.openai import _openai_messages_from_blocks, _responses_input

    blocks = [{"type": "tool_result", "tool_use_id": "c1", "content": "{\"success\": false}"},
              {"type": "text", "text": "[STUCK] You are going round in circles."}]
    request = CompletionRequest(model="gpt-6-luna", messages=[
        Message(role="user", content="Tidy src/missing.py."),
        Message(role="assistant", content=[{"type": "tool_use", "id": "c1", "name": "read_file",
                                            "input": {"path": "src/missing.py"}}]),
        Message(role="user", content=blocks)])
    _, items = _responses_input(request)
    kinds = [item.get("type") or item.get("role") for item in items]
    assert kinds == ["user", "function_call", "function_call_output", "user"]
    assert items[-1]["content"].startswith("[STUCK]")
    chat = _openai_messages_from_blocks("user", blocks)
    assert [m["role"] for m in chat] == ["tool", "user"]
