"""
Audit batch 1 (24 November): stop the waste. From the read-only audit "JAI audit: what stops it running 24/7" of
23 November. Real: the studio's instructions, the mission card's model, the metered usage, the image generator's
start and stop around the natural voice, the voiceover's wait. Docker and the GPU services are recorded answers;
nothing is spent and no model is called.
"""
import asyncio
import shutil

import httpx
import pytest

from app.core.command import sandbox_engine
from app.core.config import settings
from app.core.creative import images, voiceover
from app.core.ops import docker_ops
from tests.conftest import _SQLITE, AsyncTestingSessionLocal
from tests.repo_paths import repo_path


# ----- atelier mode and working files ---------------------------------------------------------------------------

def test_the_studio_composes_marketing_in_atelier_mode_inside_openmontages_own_project():
    """23 November: effects scenes were written outside OpenMontage's Remotion project, rendered at its defaults
    (landscape, 30 seconds) and failed to bundle; the video Richard liked (d8f3f5a6) used atelier mode."""
    from app.core.command.mission_org import studio_goal

    goal = studio_goal()
    assert "atelier" in goal and "Composition Authoring Mode" in goal
    assert "bespoke-composition.md" in goal and "taste-direction.md" in goal
    assert "scaffold_atelier_project.py" in goal and '--root "$OPENMONTAGE_PROJECTS_DIR"' in goal
    assert 'composition_mode: \\"atelier\\"' not in goal and 'composition_mode: "atelier"' in goal
    assert "_stage_atelier_project" in goal and "never run npx remotion render on an entry outside" in goal
    assert "1080x1920" in goal and "width, height, fps and length" in goal
    # the templated route stays for plain footage-and-captions edits
    assert "remotion_render" in goal and "word-level captions" in goal


def test_openmontages_atelier_contract_is_the_one_its_pinned_code_reads():
    """The edit decisions the studio is told to write are the keys OpenMontage 2e003e65's VideoCompose reads."""
    from app.core.command.mission_org import studio_goal

    goal = studio_goal()
    for key in ("render_runtime", "composition_mode", "bespoke", "entry", "composition_id", "public_dir",
                "art_direction"):
        assert key in goal, key


def test_working_files_stay_in_the_mission_folder_not_tmp():
    """23 November: check frames saved in /tmp were refused by the file tool, so checks were skipped."""
    from app.core.command.mission_org import studio_goal

    goal = studio_goal()
    assert ".jai/work/" in goal and "never in /tmp" in goal
    sandbox_rules = repo_path("services", "openhands", "app", "server.py").read_text()
    assert ".jai/work/" in sandbox_rules and "never in /tmp" in sandbox_rules


# ----- the true model and provider on the card ------------------------------------------------------------------

def test_usage_records_which_model_answered_each_call():
    from app.core.command.metrics import Usage

    usage = Usage()
    usage.add({"input_tokens": 10, "output_tokens": 2}, "claude-sonnet-5-5", "work")
    usage.add({"input_tokens": 10, "output_tokens": 2}, "claude-sonnet-5-5", "work")
    usage.add({"input_tokens": 10, "output_tokens": 2}, "gpt-6-sol", "work")
    assert usage.summary()["models"] == {"claude-sonnet-5-5": 2, "gpt-6-sol": 1}


def test_the_card_names_the_model_that_did_the_work():
    """23 November: the card said claude-opus-5-5 (the Orchestrator's) for sandbox and fallback work."""
    from app.core.command.service import worked_on

    engine = worked_on({"role": {"engine": {"model": "claude-haiku-5-5"}}})
    assert engine == {"provider": "claude-agent-sdk", "model": "claude-haiku-5-5", "models": ["claude-haiku-5-5"]}
    team = worked_on({"team": {"packages": [{"id": "P1", "ran_on": "claude-sonnet-5-5", "cost_usd": 3.1},
                                            {"id": "VER", "ran_on": "claude-opus-5-5", "cost_usd": 0.4}]}})
    assert team["model"] == "claude-sonnet-5-5" and team["provider"] == "claude"
    assert team["models"] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    fallback = worked_on({"team": {"packages": [{"id": "P1", "ran_on": "gpt-6-sol", "cost_usd": 0.9}]}})
    assert fallback["model"] == "gpt-6-sol" and fallback["provider"] == "openai"
    native = worked_on({"metrics": {"usage": {"models": {"gpt-6-luna": 12, "claude-opus-5-5": 1}}}})
    assert native["model"] == "gpt-6-luna" and native["provider"] == "openai"
    assert worked_on({}) is None and worked_on({"team": {"packages": [{"id": "P1"}]}}) is None


def test_the_service_writes_the_worker_model_onto_the_card():
    source = repo_path("apps", "backend", "app", "core", "command", "service.py").read_text()
    assert "did = worked_on(result_extra)" in source
    assert 'task.result["provider"], task.result["model"] = did["provider"], did["model"]' in source


@pytest.mark.integration
@pytest.mark.skipif(_SQLITE, reason="the team's records are written from several sessions at once")
def test_a_sandbox_package_card_carries_the_model_it_ran_on_after_a_fallback(monkeypatch):
    from app.core.command import agent_executor, mission_org
    from app.core.command.mission_org import MissionTeam
    from tests.test_mission_team import TWO_PACKAGES, TeamRouter
    from tests.test_workspace_toolchain import _mission_folder, _mission_workspace

    host, folder = _mission_folder()
    router = TeamRouter(TWO_PACKAGES, {"lead": [[("finish", {"summary": "Confirmed.", "success": True})]]})
    monkeypatch.setattr(settings, "MISSION_TEAM_ENABLED", True)
    monkeypatch.setattr(agent_executor, "get_router", lambda: router)
    monkeypatch.setattr(mission_org, "get_router", lambda: router)

    async def up():
        return True

    async def in_sandbox(self, requirements):
        model = "gpt-6-sol" if self.package.id == "B1" else "claude-sonnet-5-5"  # B1 fell back to OpenAI
        return {"success": True, "answer": "\n".join(f"{r['id']}: done — checked" for r in requirements),
                "requirements": [{**r, "status": "done", "evidence": "checked"} for r in requirements],
                "steps": 5, "tokens": 100, "token_detail": {"input": 80, "output": 20}, "cost_usd": 0.01,
                "model": model}

    monkeypatch.setattr(sandbox_engine, "available", up)
    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "run", in_sandbox)

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _mission_workspace(session, host)
            result = await MissionTeam(rt, "claude-opus-5-5", host, session_factory=AsyncTestingSessionLocal).run(
                "Add sub(a, b) to the project and document it.", max_continuations=2)
            await session.commit()
            return result

    try:
        result = asyncio.run(run())
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    from app.core.command.service import worked_on

    cards = {p["id"]: p for p in result["team"]["packages"]}
    assert cards["B1"]["ran_on"] == "gpt-6-sol" and cards["VER"]["ran_on"] == "claude-sonnet-5-5"
    assert worked_on({"team": result["team"]})["model"] in ("gpt-6-sol", "claude-sonnet-5-5")
    assert "claude-opus-5-5" not in worked_on({"team": result["team"]})["models"]


# ----- the image generator's permanent settings and the voice on the same card ----------------------------------

def test_the_image_generators_fast_settings_are_permanent_and_are_comfyuis_own_flags():
    """23 November: fast, stable images only with these flags, lost on every restart. Each is a ComfyUI v0.44.0
    command-line option (comfy/cli_args.py: --reserve-vram, --disable-pinned-memory, --cache-none)."""
    dockerfile = repo_path("services", "comfyui", "Dockerfile").read_text()
    assert "ARG COMFYUI_REF=v0.44.0" in dockerfile
    cmd = dockerfile[dockerfile.index("CMD ["):]
    assert '"--reserve-vram", "1.0"' in cmd and '"--disable-pinned-memory"' in cmd and '"--cache-none"' in cmd
    assert '"3.5"' not in cmd


class Ops:
    """The restricted Docker proxy's answers for ComfyUI and Chatterbox."""

    def __init__(self, voice_on: bool):
        self.on = {"comfyui": False, "chatterbox": voice_on}
        self.switched = []
        self.available = True

    async def containers(self):
        return [docker_ops.Container(id=name, name=f"jarv-{name}", service=name,
                                     state="running" if on else "exited", status="", health=None,
                                     restart_count=0, image=name) for name, on in self.on.items()]

    async def switch(self, service, on):
        self.switched.append((service, on))
        self.on[service] = on
        return {"service": service, "on": on, "changed": [f"jarv-{service}"]}


def _comfyui(ops, seen):
    async def answer(request):
        if request.url.path == "/system_stats":
            return httpx.Response(200 if ops.on["comfyui"] else 503, json={})
        if request.url.path == "/prompt":
            seen.append(dict(ops.on))
            return httpx.Response(200, json={"prompt_id": "p1"})
        if request.url.path == "/history/p1":
            return httpx.Response(200, json={"p1": {"status": {"status_str": "success"}, "outputs": {
                "9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}}}})
        if request.url.path == "/view":
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nimage")
        return httpx.Response(200, json={})
    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


def test_the_natural_voice_is_off_while_an_image_is_made_and_back_on_after(monkeypatch):
    ops = Ops(voice_on=True)
    monkeypatch.setattr(docker_ops, "get_docker_ops", lambda: ops)
    monkeypatch.setattr(images, "comfyui_url", lambda: "http://comfyui:8188")
    seen = []
    asyncio.run(images.generate("A desk at dawn", client=_comfyui(ops, seen)))
    assert seen == [{"comfyui": True, "chatterbox": False}]  # the card was ComfyUI's while it worked
    assert ops.switched == [("chatterbox", False), ("comfyui", True), ("chatterbox", True)]
    assert asyncio.run(images.voice_back_since()) is not None


def test_a_voice_richard_switched_off_stays_off(monkeypatch):
    ops = Ops(voice_on=False)
    monkeypatch.setattr(docker_ops, "get_docker_ops", lambda: ops)
    monkeypatch.setattr(images, "comfyui_url", lambda: "http://comfyui:8188")

    async def clear():
        from app.core.redis import get_redis

        await (await get_redis()).delete(images.VOICE_BACK_KEY)

    asyncio.run(clear())
    asyncio.run(images.generate("A desk at dawn", client=_comfyui(ops, [])))
    assert ("chatterbox", True) not in ops.switched and ops.on["chatterbox"] is False


def test_the_voice_is_switched_back_on_even_when_the_image_fails(monkeypatch):
    ops = Ops(voice_on=True)
    monkeypatch.setattr(docker_ops, "get_docker_ops", lambda: ops)
    monkeypatch.setattr(images, "comfyui_url", lambda: "http://comfyui:8188")

    def refuse(request):
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={})
        return httpx.Response(400, text="bad graph")

    with pytest.raises(images.ImageUnavailable):
        asyncio.run(images.generate("A desk", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse))))
    assert ops.switched[-1] == ("chatterbox", True) and ops.on["chatterbox"] is True


def test_a_voiceover_right_after_an_image_waits_for_the_voice_to_load(monkeypatch):
    import time

    states = iter(["loading", "loading", "ok"])

    async def back():
        return time.time()

    async def no_sleep(_):
        return None

    monkeypatch.setattr(images, "voice_back_since", back)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    calls = []

    def answer(request):
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": next(states)})
        return httpx.Response(200, content=b"\x00\x00" * 10)

    monkeypatch.setattr(voiceover, "chatterbox_url", lambda: "http://chatterbox:8770")
    out = asyncio.run(voiceover.speak("Hello there.", client=httpx.AsyncClient(transport=httpx.MockTransport(answer))))
    assert calls == ["/health", "/health", "/health", "/speak"] and out["sentences"] == 1


def test_a_voiceover_with_no_recent_image_does_not_wait(monkeypatch):
    async def never():
        return None

    monkeypatch.setattr(images, "voice_back_since", never)
    calls = []

    def answer(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=b"\x00\x00" * 10)

    monkeypatch.setattr(voiceover, "chatterbox_url", lambda: "http://chatterbox:8770")
    asyncio.run(voiceover.speak("Hello.", client=httpx.AsyncClient(transport=httpx.MockTransport(answer))))
    assert calls == ["/speak"]


# ----- playwright-cli and speech to text --------------------------------------------------------------------------

def test_playwright_cli_is_installed_at_the_version_its_pinned_skill_was_written_for():
    """23 November: the playwright-cli skill was offered and the command was installed nowhere. @playwright/cli
    0.1.24 is the version in package.json at the skill pack's pinned commit b217248."""
    from app.core.knowledge.skill_packs import PACKS

    assert PACKS["playwright-cli"]["commit"].startswith("b21724888b")
    dockerfile = repo_path("services", "openhands", "Dockerfile").read_text()
    assert "ARG PLAYWRIGHT_CLI_VERSION=0.1.24" in dockerfile
    assert 'npm install -g "@playwright/cli@${PLAYWRIGHT_CLI_VERSION}"' in dockerfile
    assert "PLAYWRIGHT_MCP_EXECUTABLE_PATH=/usr/bin/chromium" in dockerfile
    assert "/etc/profile.d/jai-playwright-cli.sh" in dockerfile


def test_skills_that_name_whisper_are_pointed_at_faster_whisper():
    rules = repo_path("services", "openhands", "app", "server.py").read_text()
    assert "faster-whisper" in rules and "no whisper or whisper-cli command" in rules
