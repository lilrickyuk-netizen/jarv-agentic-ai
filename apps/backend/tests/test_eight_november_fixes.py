"""
The fixes from the 8 November 2026 research ("Making JAI agents work"), each tested against what went wrong that day:
model tiers and prices, a specialist taken over by Opus when it stops short, each mission's own spending allowance,
rounds that complete nothing, recovery that never starts a second copy of a running mission, the frozen acceptance
ledger, failure kinds, the approvals digest, self-healing in shadow, and UK PECR for sales email.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.command import failures, ledger, mission_budget, sandbox_engine
from app.core.command.continuation import round_progressed
from app.core.command.metrics import PRICES
from app.core.command.mission_org import Package
from app.core.config import settings
from tests.conftest import AsyncTestingSessionLocal


# ----- models and prices ------------------------------------------------------------------------------------------

def test_sonnet_does_the_hands_on_work_and_opus_checks_builds_and_takes_over(monkeypatch):
    from app.core import gateway
    from tests.test_model_tiers import _forget_no_credit

    # Anthropic's prices on 8 November 2026 (cache hits are 0.05x input).
    assert PRICES["claude-sonnet-5-5"] == (2.00, 10.00, 0.10, 2.50)
    assert PRICES["claude-opus-5-5"] == (4.00, 20.00, 0.20, 5.00)
    monkeypatch.setattr(settings, "GATEWAY_MODELS", "claude-opus-5-5,gpt-6-sol")  # an older .env
    assert "claude-sonnet-5-5" in gateway.allowed_models()

    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "anthropic-key-for-tests")
    asyncio.run(_forget_no_credit())
    team = SimpleNamespace(runtime=SimpleNamespace(task_id=uuid4()), workspace_root="/test_workspaces/x")

    def chosen(package):
        return asyncio.run(sandbox_engine.SandboxSpecialist(team, package, "m", "").model())

    writer = Package("P1", "api", "coding_agent", "g", [], [], [], "d")
    assert chosen(writer) == "claude-sonnet-5-5"
    # Since 10 November software builds and checks on Sonnet; Opus takes over when a round completed nothing.
    assert chosen(Package("VER", "check", "verifier", "g", [], [], [], "d")) == "claude-sonnet-5-5"
    assert chosen(Package("B1", "build", "builder", "g", [], [], [], "d")) == "claude-sonnet-5-5"
    assert chosen(Package("P1", "video", "creation", "g", [], [], [], "d", model="lead")) == "claude-sonnet-5-5"
    team.stuck = True
    assert chosen(Package("B1", "build", "builder", "g", [], [], [], "d")) == "claude-opus-5-5"
    assert "claude-haiku-5-5" in gateway.allowed_models() and "claude-opus-5-5" in gateway.allowed_models()


def test_a_writer_that_stops_short_is_taken_over_once_by_opus(monkeypatch):
    from tests.test_model_tiers import _forget_no_credit

    monkeypatch.setattr(settings, "CLAUDE_API_KEY", "anthropic-key-for-tests")
    asyncio.run(_forget_no_credit())
    team = SimpleNamespace(runtime=SimpleNamespace(task_id=uuid4(), workspace_id=uuid4(), user_id=None,
                                                    authority_level=4), workspace_root="/test_workspaces/x")
    package = Package("P1", "api", "coding_agent", "g", [], [], ["R1"], "d")
    specialist = sandbox_engine.SandboxSpecialist(team, package, "m", "", poll_seconds=0.01)
    runs = []
    answers = [{"success": False, "answer": "Tests still fail in apps/api.", "steps": 30, "cost_usd": 0.8},
               {"success": True, "answer": "R1: done — pytest passed", "steps": 12, "cost_usd": 1.1}]

    async def attempt(self, requirements, root, used):
        runs.append(used)
        return dict(answers[len(runs) - 1])

    monkeypatch.setattr(sandbox_engine.SandboxSpecialist, "_attempt", attempt)
    result = asyncio.run(specialist.run([{"id": "R1", "text": "api", "status": "open"}]))
    assert runs == ["claude-sonnet-5-5", "claude-opus-5-5"] and result["success"] is True
    assert "took the package over" in result["answer"] and abs(result["cost_usd"] - 1.9) < 1e-9


# ----- each mission's own allowance -------------------------------------------------------------------------------

def test_a_mission_has_its_own_allowance_and_a_package_only_its_share(monkeypatch):
    monkeypatch.setattr(settings, "MISSION_MAX_COST_USD", 12.0)
    task = uuid4()

    async def run():
        await mission_budget.add(task, 4.5)
        await mission_budget.add(task, 1.5)
        spent, left = await mission_budget.spent(task), await mission_budget.left(task)
        await mission_budget.reset(task)
        return spent, left, await mission_budget.left(task)

    spent, left, after_reset = asyncio.run(run())
    assert spent == pytest.approx(6.0) and left == pytest.approx(6.0) and after_reset == pytest.approx(12.0)
    monkeypatch.setattr(settings, "MISSION_MAX_COST_USD", 0.0)
    assert asyncio.run(mission_budget.left(task)) is None  # no allowance: only the daily limit

    async def left_now():
        return 3.0

    team = SimpleNamespace(runtime=SimpleNamespace(task_id=task), budget_left=left_now, running_now=2)
    share = sandbox_engine.SandboxSpecialist(team, Package("P1", "a", "coding_agent", "g", [], [], [], "d"), "m", "")
    assert asyncio.run(share._allowance("claude-sonnet-5-5")) == pytest.approx(1.5)
    video = Package("P1", "v", "creation", "g", [], [], [], "d", max_cost=10.0)
    team.running_now = 1
    assert asyncio.run(sandbox_engine.SandboxSpecialist(team, video, "m", "")._allowance("x")) == pytest.approx(3.0)


def test_rounds_that_complete_no_requirement_count_as_idle():
    """8 November: MYCO rounds kept changing files, completed nothing and kept paying."""
    before = [{"id": "R1", "status": "done"}, {"id": "R2", "status": "open"}]
    changed_files = [{"tool": "write_file", "inputs": {"path": "x"}, "success": True}]
    assert round_progressed(before, [{"id": "R1", "status": "done"}, {"id": "R2", "status": "open"}],
                            changed_files) is False
    assert round_progressed(before, [{"id": "R1", "status": "done"}, {"id": "R2", "status": "done"}], []) is True
    assert round_progressed(None, None, changed_files) is True  # no requirement list: a change still counts


# ----- recovery never starts a second copy ------------------------------------------------------------------------

@pytest.mark.integration
def test_a_late_heartbeat_with_live_progress_is_not_requeued(monkeypatch):
    """8 November: the sweeper re-queued the video mission while it was still running ($4.92 duplicate)."""
    from app.core.command import progress
    from app.core.runtime.missions import MissionRunner
    from tests.test_repair12_mission_runtime import _get, _mission, _seed_owner

    monkeypatch.setenv("MISSION_EXECUTION_MODE", "deferred")
    old = datetime.now(timezone.utc) - timedelta(minutes=10)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws = await _seed_owner(db)
            alive = await _mission(db, ws, "running", heartbeat_at=old, lease_owner="busy-worker", updated_at=old)
            dead = await _mission(db, ws, "running", heartbeat_at=old, lease_owner="dead-worker", updated_at=old)
        await progress.save(alive, {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        summary = await MissionRunner().recover_stale()
        return summary, alive, dead

    summary, alive, dead = asyncio.run(run())
    assert str(alive) not in summary["recovered"] and asyncio.run(_get(alive)).status == "running"
    assert str(dead) in summary["recovered"]


# ----- the frozen acceptance ledger and failure kinds -------------------------------------------------------------

def test_the_phase_ledger_is_the_plan_and_names_what_is_blocked():
    from app.core.workspaces.fs_inspector import SANDBOX_CONTAINER_ROOT

    name = f"ledger-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    (folder / ".jai").mkdir(parents=True)
    (folder / ".jai" / "ledger.json").write_text(json.dumps({"phase": "Phase 0", "items": [
        {"id": "R1", "text": "Monorepo builds", "check": "pnpm -r build", "passes": True, "blocked": None},
        {"id": "R2", "text": "SBOM with Syft", "check": "task sbom", "passes": False,
         "blocked": {"class": "environment", "error": "syft: command not found", "needs": "Syft 1.55.0"}},
        {"id": "note", "text": "not a requirement"}]}))
    root = f"/test_workspaces/{name}"
    try:
        reqs = ledger.requirements(root, "Carry on building MYCO Phase 0")
        assert [(r["id"], r["status"]) for r in reqs] == [("R1", "done"), ("R2", "open")]
        assert "check: `pnpm -r build`" in reqs[0]["text"] and reqs[0]["source"] == "acceptance ledger"
        assert ledger.requirements(root, "Start MYCO Phase 1") is None  # another phase: planned afresh
        assert ledger.blocked(root) == ["R2 [environment] syft: command not found — needs: Syft 1.55.0"]
        assert ledger.requirements("/test_workspaces/none-here", "Phase 0") is None
        # 9 November: a ledger without a phase belongs to the work it was written for. A new brief in the same
        # folder (the Plexecute pitch deck after the ad) is planned afresh; "carry on" takes the ledger over.
        (folder / ".jai" / "ledger.json").write_text(json.dumps({"phase": "this mission", "items": [
            {"id": "R1", "text": "Ad renders", "check": "pytest ad", "passes": True, "blocked": None}]}))
        assert ledger.requirements(root, "Make me an investor pitch deck for Plexecute") is None
        assert [r["id"] for r in ledger.requirements(root, "Carry on with the Plexecute video ad")] == ["R1"]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_each_unmet_requirement_says_what_kind_of_failure_it_is():
    assert failures.classify("bash: syft: command not found") == "environment"
    assert failures.classify("The spec does not say which Node version to pin") == "spec"
    assert failures.classify("test_upload is flaky: passed on retry") == "flaky"
    assert failures.classify("R4: test_sub fails: expected 1, got 2") == "code"
    assert failures.label(["trivy: command not found", "[ledger] R2 blocked"]) == [
        "[environment] trivy: command not found", "[ledger] R2 blocked"]


def test_the_builder_is_told_how_a_long_build_is_done():
    method = sandbox_engine.builder_method("Carry on building MYCO Phase 0")
    for must in (".jai/progress.md", "git log --oneline -20", ".jai/init.sh", ".jai/ledger.json",
                 '"phase": "Phase 0"', "one at a time", "jai-check", "git commit", "three times", "fresh clone"):
        assert must in method, must


# ----- the approvals digest and self-healing in shadow ------------------------------------------------------------

def test_what_waits_for_richard_is_grouped_by_kind_of_action():
    from app.core import approvals_digest

    assert approvals_digest.classify("spend $40 on ads") == "money"
    assert approvals_digest.classify("deploy to production") == "public"
    assert approvals_digest.classify("delete the staging database") == "irreversible"
    assert approvals_digest.classify("enter the AWS password") == "credentials"
    result = approvals_digest.digest([
        {"class": "public", "what": "Push MYCO Phase 0", "why": "pushing to a remote"},
        {"class": "money", "what": "Buy a domain", "why": ""}])
    assert result["total"] == 2 and result["by_class"]["public"] == 1 and "2 decisions waiting" in result["summary"]
    assert result["lines"][0] == "[money] Buy a domain"
    assert approvals_digest.digest([])["summary"] == "Nothing is waiting for you."


def test_a_repair_action_runs_in_shadow_until_richard_promotes_it(monkeypatch):
    from app.core.ops import repair
    from app.core.self_healing import shadow

    restarted = []

    class Ops:
        async def restart(self, service):
            restarted.append(service)
            return {"service": service, "restarted": True}

    async def healthy(service):
        return {"healthy": True}

    monkeypatch.setattr("app.core.ops.docker_ops.get_docker_ops", lambda: Ops())
    monkeypatch.setattr(repair, "service_state", healthy)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(repair.asyncio, "sleep", lambda *_: real_sleep(0))

    async def run():
        await shadow.demote("restart:voice")
        first = await repair.restart_and_wait("voice", "unhealthy for 3 checks", timeout_seconds=1)
        never = await repair.restart_and_wait("postgres", "slow", timeout_seconds=1)
        await shadow.promote("restart:voice")
        second = await repair.restart_and_wait("voice", "unhealthy again", timeout_seconds=1)
        worker = await repair.restart_and_wait("worker", "no ping", timeout_seconds=1)
        logged = await shadow.log()
        await shadow.demote("restart:voice")
        return first, never, second, worker, logged

    first, never, second, worker, logged = asyncio.run(run())
    assert first["shadow"] is True and "would have" in first["note"] and never["shadow"] is True
    assert restarted == ["voice", "worker"] and second["recovered"] is True and worker["recovered"] is True
    assert {e["action"] for e in logged} >= {"restart:voice", "restart:postgres"}
    with pytest.raises(ValueError):
        asyncio.run(shadow.promote("restart:redis"))


# ----- UK PECR -----------------------------------------------------------------------------------------------------

def test_only_a_business_shown_to_be_a_company_is_emailed_without_consent(monkeypatch):
    from app.core.business import prospecting
    from app.core.business.prospecting import pecr_status, prospecting_service
    from app.models.prospecting import OutreachMessage, Prospect, ProspectCompany
    from tests.test_repair12_mission_runtime import _seed_owner

    assert pecr_status("Bright Smile Dental Ltd, registered in England", "u")["subscriber"] == "corporate"
    assert pecr_status("Tom Reed, dentist. Call us.", "u")["subscriber"] == "individual or unknown"
    monkeypatch.setattr(prospecting, "compliance_footer", lambda: ("footer", []))

    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws = await _seed_owner(db)
            company = ProspectCompany(workspace_id=ws, name="Tom Reed Dental", source="openstreetmap",
                                      source_ref=uuid4().hex, signals={"_pecr": pecr_status("Tom Reed", "u")},
                                      published_emails=[], status="qualified")
            db.add(company)
            await db.flush()
            person = Prospect(workspace_id=ws, company_id=company.id, name="Tom Reed", email="tom@reed.test",
                              email_status="verified", stage="new")
            db.add(person)
            await db.flush()
            row = OutreachMessage(workspace_id=ws, prospect_id=person.id, step=1, subject="Hi", body="Hello",
                                  status="approved", meta={})
            db.add(row)
            await db.flush()
            blocked = await prospecting_service._unsendable(db, ws, person, row)
            await prospecting_service.record_consent(db, ws, str(company.id), "Signed up at the Leeds expo, 3 Nov")
            allowed = await prospecting_service._unsendable(db, ws, person, row)
            await db.rollback()
            return blocked, allowed

    blocked, allowed = asyncio.run(run())
    assert blocked and "PECR" in blocked and allowed is None


# ----- a brief that carries on still has its own instructions -------------------------------------------------------

def test_new_instructions_in_a_carry_on_brief_become_requirements_of_their_own():
    """8 November: "carry on with Phase 0 ... add .mise/ to .gitignore, merge the reports" reused the earlier
    mission's list, and the builder changed nothing."""
    from app.core.command.requirements import additions

    tracked = [{"id": "R1", "text": "Monorepo builds", "status": "done"},
               {"id": "R9", "text": "Phase 0 acceptance tag exists", "status": "open"}]
    seen = {}

    class Router:
        async def complete(self, request):
            seen["system"], seen["prompt"] = request.system, request.messages[0].content
            return SimpleNamespace(usage={"total_tokens": 42}, tool_calls=[{"function": {
                "name": "record_requirements", "arguments": json.dumps({"requirements": [
                    {"text": ".mise/ is listed in .gitignore and nothing under .mise/ is tracked",
                     "source": "new brief"},
                    {"text": "The overlapping Phase 0 reports in docs/ are merged into the ones the spec names",
                     "source": "new brief"}]})}}])

    out = asyncio.run(additions(Router(), "m", "Carry on with Phase 0; add .mise/ to .gitignore; merge the "
                                               "reports.", tracked))
    assert [r["id"] for r in out["requirements"]] == ["R10", "R11"] and out["tokens"] == 42
    assert all(r["status"] == "open" for r in out["requirements"])
    assert "R9 [open] Phase 0 acceptance tag exists" in seen["prompt"] and "only what the new brief" in seen["system"]

    class Down:
        async def complete(self, request):
            raise RuntimeError("provider down")

    assert asyncio.run(additions(Down(), "m", "Carry on.", tracked))["requirements"] == []  # the list stands


# ----- every report says what JAI actually used ------------------------------------------------------------------------

def test_the_report_says_which_skills_and_jai_tools_the_team_used():
    """Richard asked for days whether JAI uses its skills, knowledge and tools; no report could say."""
    from app.core.command.mission_org import used_summary

    builder = Package("B1", "build", "builder", "g", [], [], [], "d",
                      tools_used={"terminal": 40, "file_editor": 12, "invoke_skill": 2, "search_knowledge": 3,
                                  "think": 5, "finish": 1},
                      skills_used=["superpowers/verification-before-completion"])
    checker = Package("VER", "check", "verifier", "g", [], [], [], "d",
                      tools_used={"terminal": 9, "recall_memory": 1})
    line = used_summary([builder, checker])
    assert line.startswith("**What JAI used:** skills loaded: superpowers/verification-before-completion")
    assert "search_knowledge ×3" in line and "recall_memory ×1" in line and "shell ×49" in line
    assert "think" not in line and "invoke_skill" not in line
    bare = used_summary([Package("B1", "b", "builder", "g", [], [], [], "d", tools_used={"terminal": 7})])
    assert "no skills loaded" in bare and "none of JAI's own tools" in bare
    assert used_summary([Package("B1", "b", "builder", "g", [], [], [], "d")]) == ""  # nothing recorded


def test_what_a_package_used_adds_up_across_its_runs():
    merged = sandbox_engine.SandboxSpecialist._merge(
        {"steps": 3, "tools_used": {"terminal": 4}, "skills_used": ["a"]},
        {"steps": 2, "tools_used": {"terminal": 1, "search_knowledge": 2}, "skills_used": ["a", "b"]})
    assert merged["tools_used"] == {"terminal": 5, "search_knowledge": 2} and merged["skills_used"] == ["a", "b"]
    assert merged["steps"] == 5


def test_voicebox_is_no_longer_part_of_jai():
    """9 November: Richard's voice runs on Fish (Kokoro inside the voice service as the fallback); the separate
    Voicebox service only took memory. With no address set, the voice tools use Fish and OpenAI instead."""
    import yaml

    from tests.repo_paths import repo_path

    compose = yaml.safe_load(repo_path("docker-compose.yml").read_text())
    assert "voicebox" not in compose["services"]
    assert not any(name.startswith("voicebox") for name in compose.get("volumes") or {})
    assert compose["services"]["backend"]["environment"]["VOICEBOX_BASE_URL"] == "${VOICEBOX_BASE_URL:-}"
