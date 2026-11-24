"""
24 November, Richard's three additions to the audit batches: the hung-call limit for OpenHands runs (software builds),
the card naming the team that actually worked, and ECC's learning system shown on every engine mission's record.
Real: the settings, the sandbox specialist's request, the card's team, ECC's own store layout (written here as ECC
writes it). The sandbox is an httpx MockTransport: no model is called.
"""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.core.command import claude_engine, sandbox_engine
from app.core.command.mission_org import Package
from app.core.command.service import worked_team
from app.core.config import settings
from tests.repo_paths import repo_path


def test_an_openhands_run_waits_at_most_five_minutes_a_call_and_retries_twice(monkeypatch):
    build = Package("B1", "Build", "builder", "g", [], [], [], "")
    team = SimpleNamespace(packages=[build], runtime=SimpleNamespace(task_id=None, workspace_id=None, user_id=None,
                                                                     authority_level=3),
                           workspace_root="/test_workspaces/x", lead_agent_id=None, _brief=lambda p, m: "b")
    sent = []

    async def no_register(self, root):
        return None

    async def follow(self, client, root):
        return {"status": "finished", "final_message": "", "steps": 1, "tokens": {}, "cost_usd": 0}

    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "_register", no_register)
    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "_follow", follow)
    monkeypatch.setattr(settings, "OPENHANDS_URL", "http://openhands:8010")

    def sandbox(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"run_id": "x", "status": "starting"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(sandbox)) as client:
            await sandbox_engine.SandboxSpecialist(team, build, "Build it", None, client=client)._attempt(
                [], "/host/workspaces/x", "claude-sonnet-5-5")

    asyncio.run(run())
    assert sent[0]["engine"] == "openhands"
    assert sent[0]["api_timeout_ms"] == 300000 and sent[0]["max_retries"] == 2
    server = repo_path("services", "openhands", "app", "server.py").read_text()
    assert "reasoning_effort=request.reasoning_effort, timeout=600" not in server and "num_retries=4" not in server
    assert "timeout=max(30, int(request.api_timeout_ms) // 1000), num_retries=int(request.max_retries)" in server


def test_the_card_names_the_team_that_worked_not_the_plans_generic_team():
    video = {"team": {"packages": [{"id": "P1", "specialist": "creation", "role": "Product Designer",
                                    "title": "The openmontage skill, end to end", "status": "finished"}]}}
    agents, steps = worked_team(video)
    assert agents == ["orchestrator", "creation"]
    assert "devops" not in agents and "qa" not in agents and "swarm_manager" not in agents
    assert steps == ["Product Designer: The openmontage skill, end to end (finished)"]
    build = {"team": {"packages": [{"id": "B1", "specialist": "builder", "title": "Build"},
                                   {"id": "P1", "specialist": "documentation", "title": "Docs"},
                                   {"id": "VER", "specialist": "verifier", "title": "Check"}]}}
    assert worked_team(build)[0] == ["orchestrator", "swarm_manager", "coding_agent", "documentation", "verifier"]
    acting = {"team": {"packages": [{"id": "B1", "specialist": "builder", "acting_as": "sales", "title": "List"},
                                    {"id": "VER", "specialist": "verifier", "title": "Check"}]}}
    assert worked_team(acting)[0] == ["orchestrator", "sales", "verifier"]
    role = worked_team({"role": {"specialist": "marketing", "title": "Marketing Lead"}})
    assert role[0] == ["orchestrator", "marketing", "verifier"] and "Marketing Lead: did the work." in role[1]
    assert worked_team({}) is None


def test_the_service_uses_the_team_that_worked():
    source = repo_path("apps", "backend", "app", "core", "command", "service.py").read_text()
    assert "worked = worked_team(result)" in source and "agents, steps = self._validate_agents(worked[0])" in source


def test_eccs_learning_for_the_product_is_read_from_its_own_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECC_LEARNING_DIR", str(tmp_path))
    folder = tmp_path / "Plexecute"
    folder.mkdir()
    store = tmp_path / "homunculus"
    (store / "instincts" / "personal").mkdir(parents=True)
    (store / "instincts" / "personal" / "grep-before-edit.yaml").write_text("id: grep-before-edit\n")
    project = store / "projects" / "a1b2c3d4e5f6"
    (project / "instincts" / "personal").mkdir(parents=True)
    for name in ("frames-in-workspace.yaml", "check-render-length.md"):
        (project / "instincts" / "personal" / name).write_text("id: x\n")
    (project / "observations.jsonl").write_text('{"a": 1}\n{"a": 2}\n{"a": 3}\n')
    (store / "projects.json").write_text(json.dumps({"a1b2c3d4e5f6": {"id": "a1b2c3d4e5f6", "name": "Plexecute",
                                                                       "root": str(folder.resolve())}}))
    learned = claude_engine.ecc_learned(folder)
    assert learned["project"] == "a1b2c3d4e5f6" and learned["project_instincts"] == 2
    assert learned["global_instincts"] == 1 and learned["observations_waiting"] == 3
    empty = claude_engine.ecc_learned(tmp_path / "Other")
    assert empty["project"] is None and empty["project_instincts"] == 0 and empty["global_instincts"] == 1


def test_an_engine_missions_record_and_report_carry_eccs_learning():
    source = repo_path("apps", "backend", "app", "core", "command", "claude_engine.py").read_text()
    assert '"ecc_learning": ecc_learned(self._folder())' in source
    assert "ECC's learning for this product:" in source
    # Its store is on Richard's disk (the backend folder is a bind mount), so it lasts across missions.
    assert settings.ECC_LEARNING_DIR.startswith("/app/")
    compose = repo_path("docker-compose.yml").read_text()
    assert "./apps/backend:/app" in compose
