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

import httpx
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
    monkeypatch.setattr(claude_run, "COPIES", home / ".jai-copies-test")
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
        # 25 November: the run reports the model that answered, as the session itself said (for the mission card).
        used = run.view()["models_used"]
        assert list(used) == [MODEL] and used[MODEL]["replies"] >= 2
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
    monkeypatch.setattr(claude_run, "COPIES", home / ".jai-copies-test")
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
    monkeypatch.setattr(claude_run, "COPIES", tmp_path / "copies")
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
    monkeypatch.setattr(claude_run, "COPIES", tmp_path / "copies")
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


# ----- 24 November, Richard: full plugins, writable skills, skills' own shell lines through JAI's gate -------------

def _read_only_packs(root: Path) -> Path:
    """The skill packs as the sandbox mounts them: read-only, with Superpowers and ECC as plugin packs."""
    files = {
        "video-agent-skills/skills/short-editing/SKILL.md": "---\nname: short-editing\ndescription: edit\n---\nB",
        "video-agent-skills/skills/short-editing/engine/setup.mjs": "// writes .runtime/ and assets/ here",
        "superpowers/skills/brainstorming/SKILL.md": "---\nname: brainstorming\ndescription: b\n---\nB",
        "superpowers/skills/writing-plans/SKILL.md": "---\nname: writing-plans\ndescription: w\n---\nB",
        "superpowers/agents/code-reviewer.md": "agent", "superpowers/commands/brainstorm.md": "command",
        "superpowers/hooks/hooks.json": "{}",
        "ecc/skills/continuous-learning-v2/SKILL.md": "---\nname: continuous-learning-v2\ndescription: l\n---\nB",
        "ecc/skills/video-editing/SKILL.md": "---\nname: video-editing\ndescription: v\n---\nB",
        "ecc/agents/planner.md": "agent", "ecc/agents/flagged.md": "agent", "ecc/hooks/hooks.json": "{}",
        "ecc/scripts/hooks/observe-runner.js": "// ECC", "ecc/.jai-blocked-parts": "agents/flagged.md\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    return root


PLUGINS = [{"name": "superpowers", "title": "Superpowers", "publisher": "obra", "commit": "22f0b46",
            "parts": ["agents", "commands", "hooks"], "root": "skills", "whole_root": True, "skills": []},
           {"name": "ecc", "title": "ECC", "publisher": "affaan-m", "commit": "d2ef268",
            "parts": ["agents", "commands", "hooks", "scripts"], "root": "skills",
            "skills": ["ecc/skills/continuous-learning-v2", "ecc/skills/video-editing"]}]


def test_each_mission_gets_a_writable_copy_and_the_packs_stay_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_run, "SESSIONS", tmp_path / "sessions")
    monkeypatch.setattr(claude_run, "COPIES", tmp_path / "copies")
    packs = _read_only_packs(tmp_path / "packs")
    folder = ["video-agent-skills/skills/short-editing"]
    try:
        config = claude_run.prepare_config("run-copy-0001", folder, packs, set(), owner=None, mission_id="m1")
        skill = (config / "skills" / "short-editing").resolve()
        assert str(skill).startswith(str(tmp_path / "copies" / "m1"))
        (skill / ".runtime").mkdir()                       # a skill's own setup files can be written
        (skill / "engine" / "setup.mjs").write_text("changed in the copy")
        again = claude_run.prepare_config("run-copy-0002", folder, packs, set(), owner=None, mission_id="m1")
        assert ((again / "skills" / "short-editing").resolve() / ".runtime").is_dir()   # kept for the next round
        other = claude_run.prepare_config("run-copy-0003", folder, packs, set(), owner=None, mission_id="m2")
        assert not ((other / "skills" / "short-editing").resolve() / ".runtime").exists()  # each mission its own
        assert (packs / "video-agent-skills/skills/short-editing/engine/setup.mjs").read_text().startswith("//")
    finally:
        for path in packs.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)


def test_superpowers_and_ecc_come_in_as_full_plugins_with_their_skills_from_the_copies(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_run, "SESSIONS", tmp_path / "sessions")
    monkeypatch.setattr(claude_run, "COPIES", tmp_path / "copies")
    packs = _read_only_packs(tmp_path / "packs")
    try:
        config = claude_run.prepare_config("run-plug-0001", [], packs, set(), owner=None, mission_id="m1",
                                           plugins=PLUGINS)
        listed = json.loads((config / "plugins.json").read_text())
        assert [Path(p["path"]).name for p in listed] == ["superpowers", "ecc"]
        sp, ecc = config / "plugins" / "superpowers", config / "plugins" / "ecc"
        assert (sp / ".claude-plugin" / "plugin.json").is_file() and (sp / "hooks" / "hooks.json").is_file()
        assert (sp / "agents" / "code-reviewer.md").is_file() and (sp / "commands" / "brainstorm.md").is_file()
        assert {p.name for p in (sp / "skills").iterdir()} == {"brainstorming", "writing-plans"}  # the whole workflow
        assert (ecc / "agents" / "planner.md").is_file() and not (ecc / "agents" / "flagged.md").exists()
        assert (ecc / "scripts" / "hooks" / "observe-runner.js").is_file()
        assert {p.name for p in (ecc / "skills").iterdir()} == {"continuous-learning-v2", "video-editing"}
        assert str((ecc / "skills" / "video-editing").resolve()).startswith(str(tmp_path / "copies"))
    finally:
        for path in packs.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)


def test_eccs_learning_goes_to_jais_one_store_across_missions(tmp_path, monkeypatch):
    user = _agent_user()
    monkeypatch.setattr(claude_run, "AGENT_USER", user)
    monkeypatch.setattr(claude_run, "LEARNED", tmp_path / "learned")
    request = server.RunRequest(run_id="run-ecc-env", workspace="/tmp", brief="b", model=MODEL, engine="claude",
                                model_token=RUN_TOKEN, light_model="claude-haiku-5-5")
    env = claude_run.ecc_env(request)
    assert env["CLV2_HOMUNCULUS_DIR"] == str(tmp_path / "learned" / "homunculus")
    assert env["ECC_AGENT_DATA_HOME"] == str(tmp_path / "learned" / "ecc")
    assert env["CLAUDE_CODE_ENTRYPOINT"] == "sdk-ts" and env["ECC_OBSERVER_MODEL"] == "claude-haiku-5-5"
    assert json.loads(Path(env["CLV2_CONFIG"]).read_text())["observer"]["enabled"] is True
    if os.geteuid() == 0:  # ECC's hooks write there as the agent user
        uid = pwd.getpwnam(user).pw_uid
        assert all(p.stat().st_uid == uid for p in (tmp_path / "learned", tmp_path / "learned" / "homunculus",
                                                     Path(env["CLV2_CONFIG"])))
    off = claude_run.ecc_env(server.RunRequest(run_id="run-ecc-off", workspace="/tmp", brief="b", model=MODEL,
                                               engine="claude", model_token=RUN_TOKEN, ecc_learning=False))
    assert off == {"ECC_HOOK_PROFILE": "minimal", "ECC_SKIP_OBSERVE": "1"}


def test_a_skills_own_shell_lines_run_as_it_loads_through_jais_gate(monkeypatch, gateway):
    """Real Claude Code: the Skill tool opens a skill with two inline lines. JAI runs the allowed one as the agent
    user and puts its output in the skill; the refused one (a push) never runs. Claude Code's own runner stays off,
    so nothing in a skill runs outside JAI's gate. The plugins load with the session."""
    import httpx

    user = _agent_user()
    monkeypatch.setattr(claude_run, "AGENT_USER", user)
    home = Path(pwd.getpwnam(user).pw_dir)
    monkeypatch.setattr(claude_run, "SESSIONS", home / ".jai-claude-test")
    monkeypatch.setattr(claude_run, "COPIES", home / ".jai-copies-test")
    monkeypatch.setenv("JAI_AGENT_HOME", str(home))
    packs = Path(tempfile.mkdtemp(prefix="packs-"))
    skill = packs / "demo" / "skills" / "probe"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: probe\ndescription: probe\n---\nWho: !`whoami > who.txt && "
                                    "echo LOADED-OK`\nPush: !`git push origin main`\n```\n!`echo in-a-fence`\n```\n")
    for path in (packs, *packs.rglob("*")):
        path.chmod(0o755 if path.is_dir() else 0o644)
    folder = Path(tempfile.mkdtemp(prefix="mission-", dir=os.environ["WORKSPACE_ROOT"]))
    shutil.chown(folder, user, user)
    Gateway.script = [([{"type": "tool_use", "id": "toolu_1", "name": "Skill", "input": {"skill": "probe"}}],
                       "tool_use"), ([{"type": "text", "text": "R1: done"}], "end_turn")]
    seen_skill = []
    original = Gateway.do_POST

    def watch(self):
        import io

        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        seen_skill.append(raw.decode("utf-8", "replace"))
        self.rfile = io.BytesIO(raw)
        original(self)

    monkeypatch.setattr(Gateway, "do_POST", watch)
    backend = Backend()
    gate = gates.Gate("http://backend", "t", "run-claude-inline", transport=httpx.MockTransport(backend))
    request = server.RunRequest(run_id="run-claude-inline", workspace=str(folder), brief="Use probe.", model=MODEL,
                                provider="anthropic", engine="claude", jai_tools=False, model_token=RUN_TOKEN,
                                max_iterations=10, max_cost_usd=1.0, skills=["demo/skills/probe"],
                                mission_id="mission-inline")
    run = server.Run(request, gate)
    try:
        asyncio.run(claude_run.execute(run, gate, server.ENGINEERING_RULES, gateway, "t", packs, set()))
        assert run.status == "finished", run.error
        assert (folder / "who.txt").read_text().strip() == user          # ran, as the agent user
        commands = [c["command"] for c in backend.checks]
        assert commands == ["whoami > who.txt && echo LOADED-OK", "git push origin main"]  # both asked of JAI
        assert any(r.get("refused") and r["command"] == "git push origin main" for r in backend.records)
        told = [b for b in seen_skill if "JAI ran the shell lines of the skill probe" in b]
        assert told and "LOADED-OK" in told[-1] and "[not run: Not run: pushing" in told[-1]   # Claude was told
        assert "in-a-fence" not in told[-1]                                 # a line in a code fence is left alone
        assert "LOADED-OK" not in told[-1].split("JAI ran the shell lines")[0]  # Claude Code's own runner stayed off
        assert (packs / "demo" / "skills" / "probe" / "SKILL.md").read_text().count("!`") == 3  # original untouched
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(home / ".jai-claude-test", ignore_errors=True)
        shutil.rmtree(home / ".jai-copies-test", ignore_errors=True)


def test_a_session_can_open_a_full_size_still(monkeypatch, gateway):
    """24 November: episode 2 stopped twice at the first still the designer opened. Claude Code's Read tool returns a
    picture as one message, and a 1080x1920 still is over the SDK's 1 MB default (CLIJSONDecodeError). Real Claude
    Code opens a 1080x1920 PNG of about 4 MB and the session finishes."""
    import subprocess

    still = Path(tempfile.mkdtemp(prefix="still-")) / "still.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "nullsrc=s=1080x1920,geq=random(1)*255:128:128",
                    "-frames:v", "1", str(still)], check=True)
    os.chmod(still.parent, 0o755)
    os.chmod(still, 0o644)
    assert still.stat().st_size > 2 * 1024 * 1024
    script = [([{"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": str(still)}}], "tool_use"),
              ([{"type": "text", "text": "R1: done, the still looks right."}], "end_turn")]
    run, backend, folder, home = _session(monkeypatch, gateway, script)
    try:
        assert run.status == "finished", (run.status, run.error)
        assert "R1: done" in run.final_message
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(still.parent, ignore_errors=True)
        shutil.rmtree(home / ".jai-claude-test", ignore_errors=True)


def test_an_openhands_run_reports_the_models_its_own_metrics_name(tmp_path):
    """25 November: the mission card names the model that ran, from the engine's own account. For an OpenHands run
    that is its conversation's metrics, per model (the provider prefix taken off)."""
    from types import SimpleNamespace

    def metrics(name, cost, replies):
        return SimpleNamespace(model_name=name, accumulated_cost=cost, token_usages=[object()] * replies,
                               accumulated_token_usage=None)

    request = server.RunRequest(run_id="run-oh-models", workspace=str(tmp_path), brief="b", model=MODEL,
                                provider="anthropic", max_iterations=5, max_cost_usd=1.0)
    run = server.Run(request, gates.Gate("http://backend", "t", "run-oh-models",
                                         transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    stats = SimpleNamespace(usage_to_metrics={"agent": metrics("anthropic/claude-sonnet-5-5", 0.42, 7),
                                              "condenser": metrics("anthropic/claude-haiku-5-5", 0.01, 2)},
                            get_combined_metrics=lambda: metrics("x", 0.43, 9))
    run.conversation = SimpleNamespace(conversation_stats=stats)
    used = run.view()["models_used"]
    assert used == {"claude-sonnet-5-5": {"replies": 7, "cost_usd": 0.42},
                    "claude-haiku-5-5": {"replies": 2, "cost_usd": 0.01}}
