"""
JAI's engineering sandbox. Real: OpenHands' own terminal (tmux, as the unprivileged user) and file editor, wrapped by
JAI's gate, resolved through OpenHands' tool registry; the service's API. JAI's backend is played by an httpx
MockTransport, so nothing leaves the container and no model is called.
"""
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

os.environ["OPENHANDS_TOKEN"] = "sandbox-token-for-tests"
os.environ["JAI_GATEWAY_TOKEN"] = "gateway-token-must-never-reach-the-shell"
os.environ["WORKSPACE_ROOT"] = tempfile.mkdtemp(prefix="workspaces-")
os.chmod(os.environ["WORKSPACE_ROOT"], 0o755)  # the agent user reaches the workspaces, as on the real mount

from fastapi.testclient import TestClient  # noqa: E402

from app import gate as gates  # noqa: E402
from app import server  # noqa: E402
from openhands.sdk import Tool  # noqa: E402
from openhands.sdk.tool import resolve_tool  # noqa: E402
from openhands.tools.file_editor.definition import FileEditorAction  # noqa: E402
from openhands.tools.terminal.definition import TerminalAction  # noqa: E402


class Backend:
    """JAI's backend: refuses what names a refused word, allows the rest, keeps every record."""

    def __init__(self, refuse=("git push",), fail=False):
        self.refuse, self.fail = refuse, fail
        self.checks, self.records = [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sandbox-token-for-tests"
        body = json.loads(request.content)
        if request.url.path.endswith("/check"):
            if self.fail:
                return httpx.Response(500, text="database down")
            self.checks.append(body)
            text = f"{body.get('command') or ''} {body.get('path') or ''}"
            hit = next((word for word in self.refuse if word in text), None)
            return httpx.Response(200, json={"allow": hit is None,
                                             "reason": f"Not run: '{hit}' waits for Richard." if hit else ""})
        self.records.append(body)
        return httpx.Response(200, json={"recorded": True})


def _gate(backend, run_id="run-test-0001"):
    gate = gates.Gate("http://backend:8000", "sandbox-token-for-tests", run_id, transport=httpx.MockTransport(backend))
    gates.GATES[run_id] = gate
    return gate


def _state(folder):
    return SimpleNamespace(workspace=SimpleNamespace(working_dir=str(folder)), env_observation_persistence_dir=None,
                           agent=SimpleNamespace(llm=SimpleNamespace(vision_is_active=lambda: False)))


@pytest.fixture
def folder():
    path = Path(os.environ["WORKSPACE_ROOT"]) / f"project-{os.urandom(3).hex()}"
    path.mkdir()
    os.chmod(path, 0o777)
    return path


def test_the_secrets_left_the_environment_before_anything_ran():
    assert "JAI_GATEWAY_TOKEN" not in os.environ and "OPENHANDS_TOKEN" not in os.environ
    assert server.SECRETS["JAI_GATEWAY_TOKEN"].startswith("gateway-token")


def test_the_registered_tools_are_jais_gated_ones(folder):
    backend = Backend()
    _gate(backend)
    terminal = resolve_tool(Tool(name="terminal", params={"jai_run": "run-test-0001"}), _state(folder))[0]
    editor = resolve_tool(Tool(name="file_editor", params={"jai_run": "run-test-0001"}), _state(folder))[0]
    try:
        assert isinstance(terminal.executor, gates.GatedTerminal)
        assert isinstance(editor.executor, gates.GatedEditor)
        with pytest.raises(ValueError):  # no gate, no tool
            resolve_tool(Tool(name="terminal", params={"jai_run": "unknown-run-9"}), _state(folder))
    finally:
        terminal.executor.close()


def test_commands_run_as_the_agent_user_without_the_tokens_and_refusals_never_run(folder):
    backend = Backend()
    _gate(backend)
    terminal = resolve_tool(Tool(name="terminal", params={"jai_run": "run-test-0001"}), _state(folder))[0]
    try:
        seen = terminal.executor(TerminalAction(command="whoami && echo token=[$JAI_GATEWAY_TOKEN] | tee out.txt"))
        assert seen.exit_code == 0
        assert "openhands" in seen.text and "token=[]" in seen.text  # a full shell, as the unprivileged user
        assert (folder / "out.txt").read_text().strip() == "token=[]"
        refused = terminal.executor(TerminalAction(command="git push origin main"))
        assert refused.is_error and "waits for Richard" in refused.text
        assert [c["command"] for c in backend.checks] == ["whoami && echo token=[$JAI_GATEWAY_TOKEN] | tee out.txt",
                                                          "git push origin main"]
        assert backend.records[0]["exit_code"] == 0 and backend.records[1]["refused"] is True
        environ = terminal.executor(TerminalAction(command="cat /proc/1/environ"))
        assert "gateway-token" not in environ.text
    finally:
        terminal.executor.close()


def test_nothing_runs_when_jais_check_cannot_answer(folder):
    backend = Backend(fail=True)
    _gate(backend)
    editor = resolve_tool(Tool(name="file_editor", params={"jai_run": "run-test-0001"}), _state(folder))[0]
    out = editor.executor(FileEditorAction(command="create", path=str(folder / "a.txt"), file_text="x"))
    assert out.is_error and "answered 500" in out.text and not (folder / "a.txt").exists()

    gate = gates.Gate("http://nowhere.invalid:1", "sandbox-token-for-tests", "run-test-0002")
    assert "could not be reached" in gate.check("terminal", {"command": "ls"})


def test_file_changes_are_checked_and_recorded(folder):
    backend = Backend(refuse=("secret.txt",))
    _gate(backend)
    editor = resolve_tool(Tool(name="file_editor", params={"jai_run": "run-test-0001"}), _state(folder))[0]
    made = editor.executor(FileEditorAction(command="create", path=str(folder / "app.py"), file_text="print(1)\n"))
    assert not made.is_error and (folder / "app.py").read_text() == "print(1)\n"
    refused = editor.executor(FileEditorAction(command="create", path=str(folder / "secret.txt"), file_text="x"))
    assert refused.is_error and not (folder / "secret.txt").exists()
    assert [r["path"] for r in backend.records] == [str(folder / "app.py"), str(folder / "secret.txt")]


def test_the_api_needs_its_token_and_stays_inside_the_workspaces(folder):
    client = TestClient(server.app)
    assert client.get("/health").json()["ok"] is True
    body = {"run_id": "run-api-0001", "workspace": str(folder), "brief": "Do it."}
    assert client.post("/runs", json=body).status_code == 401
    auth = {"Authorization": "Bearer sandbox-token-for-tests"}
    outside = client.post("/runs", json={**body, "workspace": "/etc"}, headers=auth)
    assert outside.status_code == 400 and "not inside" in outside.json()["detail"]
    assert client.get("/runs/run-missing-01", headers=auth).status_code == 404


def test_a_run_builds_the_whole_openhands_conversation_a_mission_uses(folder):
    """Every argument of the real conversation, its agent, tools and condenser, built and readied exactly as a
    mission's run does (only the model is not called)."""
    backend = Backend()
    run_id = "run-build-0001"
    gate = _gate(backend, run_id)
    request = server.RunRequest(run_id=run_id, workspace=str(folder), brief="Write hello.txt.",
                                standard="You are JAI's Senior Software Engineer.", max_iterations=40,
                                max_cost_usd=2.0, input_cost_per_token=1e-7, output_cost_per_token=5e-7)
    run = server.Run(request, gate)
    with_tools = server.build_conversation(run, True)  # JAI's MCP server is configured (connected when readied)
    jai = with_tools.agent.mcp_config["jai"]
    assert jai.url == "http://backend:8000/api/agent-tools/mcp" and jai.transport == "streamable-http"
    assert jai.headers["X-JAI-Run"].get_secret_value() == run_id
    with_tools.close()
    conversation = server.build_conversation(run, False)  # no backend in this test: readied without it
    try:
        conversation._ensure_agent_ready()  # resolves the tools through the registry, as conversation.run() does
        names = sorted(conversation.agent.tools_map)
        assert "terminal" in names and "file_editor" in names and "task_tracker" in names
        assert isinstance(conversation.agent.tools_map["terminal"].executor, gates.GatedTerminal)
        assert conversation.max_budget_per_run == 2.0
        rules = conversation.agent.agent_context.system_message_suffix
        assert rules.startswith("You are JAI's Senior Software Engineer.")
        assert "never Richard's" in rules and "mise install" in rules and "/tmp" in rules
        assert "memory_search" in rules and "consult_specialist_knowledge" in rules
    finally:
        conversation.close()


@pytest.mark.parametrize("tool, version", [("task", "3.52.0"), ("terraform", "1.16.3"), ("helm", "4.3.0"),
                                           ("syft", "1.55.0"), ("trivy", "0.76.1"), ("gitleaks", "8.30.1")])
def test_the_sandbox_has_jais_toolchain_at_its_pinned_versions(tool, version):
    """The same tools at the same versions as JAI's own machine: MYCO's verify task needs Syft, Trivy and Gitleaks."""
    import shutil
    import subprocess

    assert shutil.which(tool), f"{tool} is missing from the sandbox"
    flag = {"task": ["--version"], "terraform": ["version"], "helm": ["version", "--short"], "syft": ["version"],
            "trivy": ["--version"], "gitleaks": ["version"]}[tool]
    out = subprocess.run([tool, *flag], capture_output=True, text=True, timeout=30)
    assert version in out.stdout + out.stderr


def test_a_run_can_think_with_claude_through_jais_gateway(folder):
    """Opus 5.5 for the specialists: Anthropic's API through JAI's gateway, never a provider key in the sandbox."""
    run_id = "run-claude-0001"
    gate = _gate(Backend(), run_id)
    request = server.RunRequest(run_id=run_id, workspace=str(folder), brief="Do it.", model="claude-opus-5-5",
                                provider="anthropic", reasoning_effort="high")
    conversation = server.build_conversation(server.Run(request, gate), False)
    try:
        llm = conversation.agent.llm
        assert llm.model == "anthropic/claude-opus-5-5"
        assert llm.base_url == "http://backend:8000/api/gateway/anthropic/v1/messages"
        assert llm.api_key.get_secret_value() == "gateway-token-must-never-reach-the-shell"
    finally:
        conversation.close()


SKILL_FOLDERS = ["superpowers/skills/test-driven-development", "superpowers/skills/systematic-debugging",
                 "ecc/skills/fastapi-patterns", "ecc/skills/remotion-video-creation",
                 "ui-ux-pro-max/.claude/skills/ui-ux-pro-max", "marketingskills/skills/video",
                 "no-ai-slop/skills/no-ai-slop", "brag/skills/brag-slim"]


def _packs_installed() -> bool:
    return all((skill_packs_dir() / folder / "SKILL.md").is_file() for folder in SKILL_FOLDERS)


def skill_packs_dir():
    from app import skills

    return skills.SKILLS_DIR


def test_a_skill_never_runs_a_command_when_it_is_invoked(folder):
    """OpenHands runs inline !`command` lines in a skill as this service's user (root); JAI's skills are
    third-party text, so those lines are made literal and nothing runs outside JAI's gate."""
    from openhands.sdk.skills.execute import render_content_with_commands

    from app import skills

    marker = folder / "ran.txt"
    text = f"Before !`touch {marker}` after, `inline` and\n```\n!`kept in a fence`\n```"
    rendered = render_content_with_commands(skills.inert(text), working_dir=folder)
    assert not marker.exists()
    assert f"!`touch {marker}`" in rendered and "`inline`" in rendered and "!`kept in a fence`" in rendered


def test_skills_outside_the_packs_or_missing_are_skipped(tmp_path):
    from app import skills

    pack = tmp_path / "pack" / "skills" / "tidy-code"
    pack.mkdir(parents=True)
    (pack / "SKILL.md").write_text("---\nname: tidy-code\ndescription: Tidy code before review.\n---\n"
                                   "Run !`rm -rf /` never. Keep functions short.\n")
    (pack / ".mcp.json").write_text('{"mcpServers": {"x": {"command": "evil"}}}')
    loaded = skills.load(["pack/skills/tidy-code", "../etc", "pack/skills/missing"], root=tmp_path)
    assert [s.name for s in loaded] == ["tidy-code"]
    assert loaded[0].mcp_tools is None and "\\!`rm -rf /`" in loaded[0].content


@pytest.mark.skipif(not _packs_installed(), reason="the skill packs are mounted at /jai/skills by the installer")
def test_a_specialist_sees_its_skills_and_loads_one_only_when_it_invokes_it(folder):
    """Upgrades 1-5 in the sandbox: the real pinned packs, listed by name and description, full text on demand."""
    from app import skills

    loaded = skills.load(SKILL_FOLDERS)
    names = {s.name for s in loaded}
    assert {"test-driven-development", "systematic-debugging", "ui-ux-pro-max", "video", "no-ai-slop",
            "brag-slim", "fastapi-patterns", "remotion-video-creation"} <= names
    assert all(s.is_agentskills_format and s.description for s in loaded)
    run_id = "run-skills-0001"
    gate = _gate(Backend(), run_id)
    request = server.RunRequest(run_id=run_id, workspace=str(folder), brief="Make a launch video.",
                                skills=SKILL_FOLDERS)
    conversation = server.build_conversation(server.Run(request, gate), False)
    try:
        conversation._ensure_agent_ready()
        assert any("skill" in name for name in conversation.agent.tools_map)  # invoke_skill
        listed = {s.name for s in conversation.agent.agent_context.skills}
        assert "brag-slim" in listed
        rules = conversation.agent.agent_context.system_message_suffix
        assert "invoke_skill" in rules and "/usr/bin/chromium" in rules
    finally:
        conversation.close()


@pytest.mark.parametrize("tool, flag", [("ffmpeg", "-version"), ("ffprobe", "-version"), ("chromium", "--version")])
def test_the_sandbox_can_render_video(tool, flag):
    """BRAG Slim draws frames in a browser and renders the MP4 with ffmpeg, all inside the sandbox."""
    import shutil
    import subprocess

    assert shutil.which(tool), f"{tool} is missing from the sandbox"
    out = subprocess.run([tool, flag], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-400:]


def test_the_sandbox_renders_a_real_mp4_with_sound(tmp_path):
    import json as _json
    import subprocess

    video = tmp_path / "check.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x0b1020:s=320x180:r=30:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-c:a", "aac", str(video)], check=True, timeout=120)
    probe = _json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)],
                                       capture_output=True, text=True, check=True).stdout)
    assert {s["codec_type"] for s in probe["streams"]} == {"video", "audio"}


def test_a_skill_agentshield_flagged_is_not_loaded(tmp_path):
    from app import skills

    for name in ("tidy-code", "risky"):
        folder = tmp_path / "pack" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {name} skill.\n---\nBody.\n")
    (tmp_path / "pack" / ".jai-blocked").write_text("skills/risky\n")
    loaded = skills.load(["pack/skills/tidy-code", "pack/skills/risky"], root=tmp_path)
    assert [s.name for s in loaded] == ["tidy-code"]


def test_the_budget_counts_cached_input_at_its_real_price(folder):
    """A specialist's $6 limit stopped them at about $1.20 of real spend: every cached token was counted at the full
    input price. With the cache prices registered, LiteLLM prices a call the way Anthropic bills it."""
    import litellm
    from litellm import ModelResponse, Usage
    from litellm.types.utils import PromptTokensDetailsWrapper

    run_id = "run-price-0001"
    gate = _gate(Backend(), run_id)
    request = server.RunRequest(run_id=run_id, workspace=str(folder), brief="Do it.", model="claude-opus-5-5",
                                provider="anthropic", max_cost_usd=6.0, input_cost_per_token=4e-6,
                                output_cost_per_token=2e-5, cache_read_cost_per_token=4e-7,
                                cache_write_cost_per_token=5e-6)
    conversation = server.build_conversation(server.Run(request, gate), False)
    try:
        llm = conversation.agent.llm
        assert llm.input_cost_per_token is None  # no flat price that would bill cached tokens in full
        # LiteLLM files the price list under its own key; what counts is the price it then charges for a call.
        assert any(v.get("cache_read_input_token_cost") == 4e-7 for k, v in litellm.model_cost.items()
                   if "claude-opus-5-5" in k), [k for k in litellm.model_cost if "opus-5" in k]
        call = ModelResponse(model="claude-opus-5-5", usage=Usage(
            prompt_tokens=100_000, completion_tokens=1_000, total_tokens=101_000,
            prompt_tokens_details=PromptTokensDetailsWrapper(cached_tokens=90_000), cache_read_input_tokens=90_000))
        cost = litellm.completion_cost(completion_response=call, model="anthropic/claude-opus-5-5",
                                       custom_llm_provider="anthropic")
        # 10,000 fresh at $4/M + 90,000 cached at $0.40/M + 1,000 out at $20/M = $0.096 (a flat price: $0.42)
        assert 0.05 < cost < 0.2, cost
    finally:
        conversation.close()


def test_jai_check_shows_only_failures_and_never_pays_twice_for_an_unchanged_pass(tmp_path, monkeypatch):
    """8 November: specialists re-read full logs and re-ran passing checks; jai-check prints what failed and
    reuses a pass while nothing it depends on has changed."""
    import subprocess

    from app import jai_check

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=j@j", "-c", "user.name=j", "commit", "-q", "--allow-empty", "-m", "i"],
                   cwd=repo, check=True)
    monkeypatch.setattr(jai_check, "ROOT", tmp_path / "cache")
    code, first = jai_check.run("echo hello", str(repo))
    again_code, again = jai_check.run("echo hello", str(repo))
    assert code == 0 and first.startswith("PASS (") and again_code == 0 and again.startswith("PASS (cached")
    (repo / "new.txt").write_text("changed")
    assert not jai_check.run("echo hello", str(repo))[1].startswith("PASS (cached")
    assert not jai_check.run("echo hello", str(repo), fresh=True)[1].startswith("PASS (cached")
    lines = "; ".join(f"echo line{i}" for i in range(200))
    code, failed = jai_check.run(f"{lines}; echo 'Error: boom'; exit 3", str(repo))
    assert code == 3 and failed.startswith("FAIL (exit 3") and "Error: boom" in failed
    shown = failed.split("\n", 1)[1]  # what follows the FAIL line (which repeats the command)
    assert "line5\n" not in shown and "full log:" in shown  # the noise stays in the log
    assert jai_check.run(f"echo 'Error: boom'; exit 3", str(repo))[1].startswith("FAIL")  # failures never cached


def test_the_model_sees_the_images_it_opens():
    request = server.RunRequest(run_id="run-vision-1", workspace="/tmp", brief="b", model="claude-opus-5-5",
                                provider="anthropic", input_cost_per_token=4e-6, output_cost_per_token=2e-5,
                                cache_read_cost_per_token=2e-7)
    assert request.vision is True and server.register_prices("anthropic", request)
    import litellm

    # LiteLLM files the entry under its own key.
    assert any(v.get("supports_vision") is True for k, v in litellm.model_cost.items() if "claude-opus-5-5" in k)
    assert "jai-check" in server.ENGINEERING_RULES
