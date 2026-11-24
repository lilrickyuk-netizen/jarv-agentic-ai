"""
24 November (audit batch 3): non-development work as a Claude Agent SDK session inside the sandbox.

Real: the Claude Agent SDK and the Claude Code engine it bundles, its PreToolUse and PostToolUse hooks, its Bash and
file tools, the run's configuration folder and skills, the agent user. Stood in: JAI's gateway (a scripted
Anthropic Messages API stream on this machine, so no model is called and nothing is spent) and JAI's backend gate
(an httpx MockTransport that refuses `git push`, as sandbox_policy does, and keeps every record).
"""
import asyncio
import json
import os
import pwd
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sys

import pytest

if "app.server" not in sys.modules:  # run alone: the service takes these out of its environment as it starts
    os.environ.setdefault("OPENHANDS_TOKEN", "sandbox-token-for-tests")
    os.environ.setdefault("JAI_GATEWAY_TOKEN", "gateway-token-must-never-reach-the-shell")
    os.environ.setdefault("WORKSPACE_ROOT", tempfile.mkdtemp(prefix="workspaces-"))

from app import claude_run  # noqa: E402
from app import gate as gates  # noqa: E402
from app import server  # noqa: E402

RUN_TOKEN = "jai-run-the-sessions-own-token-never-in-the-shell"
MODEL = "claude-sonnet-5-5"


def _agent_user() -> str:
    """The unprivileged user Claude Code runs as: the image's own, or one made for this machine's test run."""
    for name in ("openhands", "jaiagent"):
        try:
            pwd.getpwnam(name)
            return name
        except KeyError:
            continue
    pytest.skip("no unprivileged agent user on this machine")


def _sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _message(blocks, stop):
    events = [{"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": MODEL, "content": [], "stop_reason": None,
        "stop_sequence": None, "usage": {"input_tokens": 100, "output_tokens": 1, "cache_read_input_tokens": 0,
                                         "cache_creation_input_tokens": 0}}}]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            events += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                       {"type": "content_block_delta", "index": i,
                        "delta": {"type": "text_delta", "text": block["text"]}},
                       {"type": "content_block_stop", "index": i}]
        else:
            events += [{"type": "content_block_start", "index": i, "content_block": {
                "type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}},
                {"type": "content_block_delta", "index": i,
                 "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}},
                {"type": "content_block_stop", "index": i}]
    events += [{"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 20}}, {"type": "message_stop"}]
    return _sse(events)


class Gateway(BaseHTTPRequestHandler):
    """JAI's gateway as Claude Code sees it: the main conversation is scripted by how many tool results it has."""
    script = []
    seen = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        Gateway.seen.append({"path": self.path, "auth": self.headers.get("authorization"),
                             "tools": [t.get("name") for t in body.get("tools") or []]})
        if "count_tokens" in self.path:
            payload = json.dumps({"input_tokens": 10}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        names = {t.get("name") for t in body.get("tools") or []}
        if "Bash" in names:
            results = sum(1 for m in body.get("messages") or [] if m.get("role") == "user"
                          for c in (m.get("content") if isinstance(m.get("content"), list) else [])
                          if isinstance(c, dict) and c.get("type") == "tool_result")
            step = Gateway.script[min(results, len(Gateway.script) - 1)]
            payload = _message(*step)
        else:  # Claude Code's own small background calls
            payload = _message([{"type": "text", "text": "ok"}], "end_turn")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class Backend:
    """JAI's backend gate: refuses `git push` (as sandbox_policy does), allows the rest, keeps every record."""

    def __init__(self):
        self.checks, self.records = [], []

    def __call__(self, request):
        import httpx

        body = json.loads(request.content)
        if request.url.path.endswith("/check"):
            self.checks.append(body)
            refused = "git push" in str(body.get("command") or "")
            return httpx.Response(200, json={"allow": not refused,
                                             "reason": "Not run: pushing to a remote waits for Richard's approval."
                                             if refused else ""})
        self.records.append(body)
        return httpx.Response(200, json={"recorded": True})


@pytest.fixture()
def gateway():
    Gateway.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def _session(monkeypatch, gateway_url, script, skills=()):
    import httpx

    user = _agent_user()
    monkeypatch.setattr(claude_run, "AGENT_USER", user)
    home = Path(pwd.getpwnam(user).pw_dir)
    monkeypatch.setattr(claude_run, "SESSIONS", home / ".jai-claude-test")
    monkeypatch.setenv("JAI_AGENT_HOME", str(home))
    folder = Path(tempfile.mkdtemp(prefix="mission-", dir=os.environ["WORKSPACE_ROOT"]))
    os.chmod(os.environ["WORKSPACE_ROOT"], 0o755)
    shutil.chown(folder, user, user)
    Gateway.script = script
    backend = Backend()
    run_id = f"run-claude-{os.urandom(3).hex()}"
    gate = gates.Gate("http://backend", "sandbox-token-for-tests", run_id, transport=httpx.MockTransport(backend))
    request = server.RunRequest(run_id=run_id, workspace=str(folder), brief="Write done.txt, then push.",
                                model=MODEL, provider="anthropic", engine="claude", jai_tools=False,
                                model_token=RUN_TOKEN, max_iterations=20, max_cost_usd=1.0, skills=list(skills))
    run = server.Run(request, gate)
    root = Path(tempfile.mkdtemp(prefix="skills-"))
    asyncio.run(claude_run.execute(run, gate, server.ENGINEERING_RULES, gateway_url, "sandbox-token-for-tests",
                                   root, set()))
    return run, backend, folder, home


def test_a_claude_session_runs_gated_commands_as_the_agent_user_without_any_token(monkeypatch, gateway):
    script = [
        ([{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {
            "command": "whoami > who.txt; env > env.txt; echo done > done.txt", "description": "write files"}}],
         "tool_use"),
        ([{"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {
            "command": "git push origin main", "description": "push"}}], "tool_use"),
        ([{"type": "text", "text": "R1: done — done.txt\nR2: waiting — pushing needs Richard."}], "end_turn"),
    ]
    run, backend, folder, home = _session(monkeypatch, gateway, script)
    try:
        assert run.status == "finished", (run.status, run.error)
        assert "R1: done" in run.final_message and run.steps == 2
        assert (folder / "done.txt").read_text().strip() == "done"
        assert (folder / "who.txt").read_text().strip() == claude_run.AGENT_USER  # never root
        shell_env = (folder / "env.txt").read_text()
        # JAI's own tokens never reach the shell; the session's run token may (the gateway holds it to this run's
        # allowance and refuses it once the run ends: apps/backend/tests/test_audit_batch3.py).
        for secret in ("sandbox-token-for-tests", "gateway-token-must-never-reach-the-shell"):
            assert secret not in shell_env
        # JAI's gate decided both commands; the push was refused and recorded, and never ran.
        commands = [c["command"] for c in backend.checks if c["tool"] == "terminal"]
        assert commands[0].startswith("whoami") and commands[1] == "git push origin main"
        refused = [r for r in backend.records if r.get("refused")]
        assert len(refused) == 1 and refused[0]["command"] == "git push origin main"
        assert any(r.get("ok") and r["command"].startswith("whoami") for r in backend.records)
        # The model was reached through JAI's gateway with this run's token only.
        assert {s["auth"] for s in Gateway.seen if "messages" in s["path"]} == {f"Bearer {RUN_TOKEN}"}
        assert run.cost_usd >= 0 and run.tokens["output"] > 0
        assert run.tools_used.get("Bash") == 1  # the refused one never ran
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(home / ".jai-claude-test", ignore_errors=True)


def test_files_outside_the_workspace_are_refused_by_the_same_gate(monkeypatch, gateway):
    outside = "/etc/hostname"
    script = [
        ([{"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": outside}}], "tool_use"),
        ([{"type": "text", "text": "Could not read it."}], "end_turn"),
    ]

    class Refusing(Backend):
        def __call__(self, request):
            import httpx

            body = json.loads(request.content)
            if request.url.path.endswith("/check") and body.get("tool") == "file_editor":
                self.checks.append(body)
                return httpx.Response(200, json={"allow": False, "reason": f"Not done: {body['path']} is outside "
                                                                         "this mission's workspace."})
            return super().__call__(request)

    import httpx

    user = _agent_user()
    monkeypatch.setattr(claude_run, "AGENT_USER", user)
    home = Path(pwd.getpwnam(user).pw_dir)
    monkeypatch.setattr(claude_run, "SESSIONS", home / ".jai-claude-test")
    monkeypatch.setenv("JAI_AGENT_HOME", str(home))
    folder = Path(tempfile.mkdtemp(prefix="mission-", dir=os.environ["WORKSPACE_ROOT"]))
    shutil.chown(folder, user, user)
    Gateway.script = script
    backend = Refusing()
    gate = gates.Gate("http://backend", "t", "run-claude-files", transport=httpx.MockTransport(backend))
    request = server.RunRequest(run_id="run-claude-files", workspace=str(folder), brief="Read /etc/hostname.",
                                model=MODEL, provider="anthropic", engine="claude", jai_tools=False,
                                model_token=RUN_TOKEN, max_iterations=10, max_cost_usd=1.0)
    run = server.Run(request, gate)
    try:
        asyncio.run(claude_run.execute(run, gate, server.ENGINEERING_RULES, gateway, "t",
                                       Path(tempfile.mkdtemp()), set()))
        assert run.status == "finished"
        assert [c["path"] for c in backend.checks] == [outside]
        assert any(r.get("refused") and r["path"] == outside for r in backend.records)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(home / ".jai-claude-test", ignore_errors=True)


def test_the_runs_configuration_links_its_skills_and_turns_skill_shell_lines_off(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_run, "SESSIONS", tmp_path / "sessions")
    packs = tmp_path / "packs"
    for folder in ("superpowers/skills/verification-before-completion", "ecc/skills/video-editing",
                   "ecc/skills/flagged"):
        (packs / folder).mkdir(parents=True)
        (packs / folder / "SKILL.md").write_text(f"---\nname: {folder.rsplit('/', 1)[1]}\n---\nBody")
    config = claude_run.prepare_config("run-x", ["superpowers/skills/verification-before-completion",
                                                 "ecc/skills/video-editing", "ecc/skills/flagged", "../../etc"],
                                       packs, {"ecc/skills/flagged"}, owner=None)
    assert sorted(p.name for p in (config / "skills").iterdir()) == ["verification-before-completion",
                                                                     "video-editing"]
    assert json.loads((config / "settings.json").read_text())["disableSkillShellExecution"] is True
    assert "/etc/profile.d/jai-*.sh" in (config / "shell-env.sh").read_text()


def test_the_session_has_claude_codes_tools_the_scrub_and_the_backends_limits():
    request = server.RunRequest(run_id="run-claude-opts", workspace="/tmp", brief="b", model=MODEL,
                                engine="claude", model_token=RUN_TOKEN, api_timeout_ms=180000, max_retries=3,
                                light_model="claude-haiku-5-5", max_iterations=50, max_cost_usd=2.0)
    env = claude_run.session_env(request, Path("/home/openhands/.jai-claude/run-claude-opts"), "http://backend:8000")
    assert env["ANTHROPIC_BASE_URL"] == "http://backend:8000/api/gateway/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == RUN_TOKEN and env["ANTHROPIC_API_KEY"] == ""
    assert "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB" not in env  # its Bash sandbox would block the studio's tools
    assert env["CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR"] == "1"
    assert env["API_TIMEOUT_MS"] == "180000" and env["CLAUDE_CODE_MAX_RETRIES"] == "3"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "claude-haiku-5-5"
    assert "Bash" in claude_run.TOOLS and "Skill" in claude_run.TOOLS
    assert "invoke_skill" not in claude_run.rules_for_claude(server.ENGINEERING_RULES)


def test_every_skill_is_listed_its_trade_in_full_the_rest_by_name_and_the_budget_fits(tmp_path, monkeypatch):
    """Richard, 24 November: every installed skill in sandbox sessions, listed like the business path."""
    monkeypatch.setattr(claude_run, "SESSIONS", tmp_path / "sessions")
    packs = tmp_path / "packs"
    folders = ["marketingskills/skills/video", "ecc/skills/video-editing", "superpowers/skills/test-driven-development"]
    for folder in folders:
        (packs / folder).mkdir(parents=True)
        name = folder.rsplit("/", 1)[1]
        (packs / folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {'x' * 400}\n---\nBody")
    config = claude_run.prepare_config("run-all", folders, packs, set(), owner=None, in_full=["video"])
    settings = json.loads((config / "settings.json").read_text())
    assert sorted(p.name for p in (config / "skills").iterdir()) == ["test-driven-development", "video",
                                                                     "video-editing"]
    assert settings["skillOverrides"] == {"video-editing": "name-only", "test-driven-development": "name-only"}
    request = server.RunRequest(run_id="run-all-skills", workspace="/tmp", brief="b", model=MODEL, engine="claude",
                                model_token=RUN_TOKEN, skills=folders, skills_in_full=["video"])
    budget = int(claude_run.session_env(request, config, "http://backend:8000")["SLASH_COMMAND_TOOL_CHAR_BUDGET"])
    assert budget >= 400 + claude_run.LISTING_SPARE
