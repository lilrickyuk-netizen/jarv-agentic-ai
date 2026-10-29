"""Repair 12e-3c: company operating layer, workspace lifecycle, and experience record tools.

Every tool runs through the real registry (authority check, permission gate,
ToolRun and audit) against real rows; the daily loop and standups are
computed from seeded tasks; folders live in the sandbox approved root.
"""
import asyncio
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.auth import get_current_user_id
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import create_tool, get_registry
from app.core.workspaces import lifecycle as lifecycle_mod
from app.main import app
from app.models.company_operations import AIStandup, KPIRecord, LiveOperationsFeedItem
from app.models.operating_plan import DailyOperatingLoop, OperatingPlanVersion
from app.models.self_evolution import ExperienceRecord
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_rules import WorkspaceRule, WorkspaceRuleVersion, WorkspaceScan
from tests.conftest import AsyncTestingSessionLocal

SANDBOX = Path("/tmp/jarv_sandbox")
COMPANY = ["create_operating_plan", "update_operating_plan", "create_daily_operating_loop", "run_daily_operating_loop",
           "create_weekly_execution_plan", "update_weekly_execution_plan", "create_ai_standup", "update_ai_standup",
           "decide_next_best_actions", "create_kpi_dashboard", "update_kpi_dashboard", "create_risk_register",
           "update_risk_register", "create_decision_log", "update_decision_log", "create_live_operations_feed_item",
           "update_live_operations_feed"]
LIFECYCLE = ["create_workspace", "import_folder_workspace", "import_repository_workspace",
             "import_document_pack_workspace", "import_live_platform_workspace", "generate_task_plan", "update_roadmap",
             "update_launch_checklist", "update_workspace_rules", "archive_workspace", "delete_workspace_with_boundary"]
EXPERIENCE = ["create_experience_record", "summarise_experience", "extract_lesson", "link_experience_to_workspace",
              "link_experience_to_task", "list_experience_records"]


def _run(coro):
    return asyncio.run(coro)


def _cfg():
    return ToolConfig(authority_level=AuthorityLevel.LEVEL_6_DATABASE_WRITE)


async def _call(name, data, ctx):
    return await create_tool(name, _cfg()).execute(data, ctx)


async def _seed(db, *, authority=3, company=True):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="Company", slug=f"co-{ws_id.hex[:8]}", description="",
                     workspace_type="project", authority_level=authority, is_active=True,
                     company_mode_enabled=company, config={}))
    await db.commit()
    return user_id, ws_id


def _task(ws_id, title, status, **kw):
    now = datetime.now(timezone.utc)
    return Task(id=uuid4(), title=title, workspace_id=ws_id, status=status, priority=5, created_at=now,
                updated_at=now, **kw)


@pytest.fixture
def folder():
    name = f"r12e3c-{uuid4().hex[:8]}"
    root = SANDBOX / name
    (root / "tests").mkdir(parents=True)
    (root / "README.md").write_text("# Shop\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'shop'\ndependencies = ['fastapi']\n")
    (root / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    yield f"/test_workspaces/{name}", root
    shutil.rmtree(root, ignore_errors=True)


# ----- registry -----------------------------------------------------------------------------

def test_all_design_tools_are_registered_real_and_gated():
    registry = get_registry()
    for name in COMPANY + LIFECYCLE + EXPERIENCE:
        assert registry.is_implemented(name), name
        assert create_tool(name, _cfg()).name == name
    assert create_tool("delete_workspace_with_boundary", _cfg()).requires_approval is True
    assert create_tool("import_repository_workspace", _cfg()).required_authority_level == \
        AuthorityLevel.LEVEL_5_NETWORK_ACCESS


# ----- company operating layer ----------------------------------------------------------------

@pytest.mark.integration
def test_company_layer_plans_kpis_risks_decisions_and_feed_are_persisted():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            today = datetime.now(timezone.utc).date()
            plan = await _call("create_operating_plan", {
                "name": "Launch plan", "plan_type": "launch", "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=30)).isoformat(),
                "objectives": ["Ship v1", "First 10 users"],
                "milestones": [{"title": "Beta", "due": (today - timedelta(days=1)).isoformat()}]}, ctx)
            updated = await _call("update_operating_plan", {
                "plan_id": plan.result_data["id"], "change_summary": "v1 shipped",
                "objectives": [{"title": "Ship v1", "status": "done"}]}, ctx)
            week = await _call("create_weekly_execution_plan", {"objectives": ["Fix onboarding"],
                                                                 "priorities": ["onboarding"]}, ctx)
            week2 = await _call("update_weekly_execution_plan", {
                "plan_id": week.result_data["id"], "objectives": [{"title": "Fix onboarding", "status": "done"}],
                "review_notes": "done early"}, ctx)
            kpis = await _call("create_kpi_dashboard", {"kpis": [
                {"name": "signups", "value": 4, "target": 10, "unit": "users"},
                {"name": "churn", "value": 2, "target": 5, "higher_is_better": False}]}, ctx)
            kpi = await _call("update_kpi_dashboard", {"name": "signups", "value": 12}, ctx)
            risk = await _call("create_risk_register", {"title": "Payment provider outage", "description": "No fallback",
                                                        "probability": "high", "impact": "very_high"}, ctx)
            risk2 = await _call("update_risk_register", {"risk_id": risk.result_data["risk"]["id"],
                                                         "mitigation_strategy": "Add a second provider",
                                                         "status": "mitigated"}, ctx)
            decision = await _call("create_decision_log", {"title": "Use Postgres", "description": "Primary store",
                                                           "rationale": "pgvector", "alternatives": ["MySQL"]}, ctx)
            reversed_ = await _call("update_decision_log", {"decision_id": decision.result_data["id"],
                                                            "reverse_reason": "Moved to managed service"}, ctx)
            feed = await _call("create_live_operations_feed_item", {"title": "Deploy finished",
                                                                    "message": "v1 live", "severity": "success"}, ctx)
            feed2 = await _call("update_live_operations_feed", {"item_ids": [feed.result_data["id"]],
                                                                "action_taken": "checked"}, ctx)
            bad = await _call("create_risk_register", {"title": "x risk", "description": "y desc",
                                                       "probability": "sometimes", "impact": "high"}, ctx)
            versions = (await db.execute(select(OperatingPlanVersion))).scalars().all()
            return plan, updated, week2, kpis, kpi, risk, risk2, reversed_, feed2, bad, versions

    plan, updated, week2, kpis, kpi, risk, risk2, reversed_, feed2, bad, versions = _run(run())
    assert plan.success, plan.error_message
    assert updated.result_data["version"] == 2 and updated.result_data["completion_percentage"] == 50.0
    assert len(updated.result_data["versions"]) == 2 and len(versions) == 2
    assert week2.result_data["completion_percentage"] == 100.0
    board = {k["name"]: k for k in kpis.result_data["kpis"]}
    assert board["signups"]["target_met"] is False and board["churn"]["target_met"] is True
    assert kpi.result_data["target_met"] is True and kpi.result_data["target"] == 10
    assert risk.result_data["risk"]["score"] == 20.0
    assert risk2.result_data["is_mitigated"] is True
    assert reversed_.result_data["is_reversed"] is True and reversed_.result_data["status"] == "reversed"
    assert feed2.result_data["items"][0]["action_taken"] == "checked"
    assert bad.success is False and "probability" in bad.error_message


@pytest.mark.integration
def test_daily_loop_and_next_actions_come_from_real_workspace_activity():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            now = datetime.now(timezone.utc)
            db.add(_task(ws_id, "Build checkout", "completed", completed_at=now))
            db.add(_task(ws_id, "Deploy staging", "failed", failed_at=now, error_message="health check 502"))
            db.add(_task(ws_id, "Write docs", "queued"))
            await db.commit()
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            await _call("create_risk_register", {"title": "No backups", "description": "Data loss",
                                                 "probability": "high", "impact": "high"}, ctx)
            await _call("create_kpi_dashboard", {"kpis": [{"name": "task_success_rate", "value": 90, "target": 80,
                                                           "unit": "%"}]}, ctx)
            created = await _call("create_daily_operating_loop", {}, ctx)
            ran = await _call("run_daily_operating_loop", {}, ctx)
            actions = await _call("decide_next_best_actions", {}, ctx)
            standup = (await db.execute(select(AIStandup).where(AIStandup.workspace_id == ws_id))).scalar_one()
            rate = (await db.execute(select(KPIRecord).where(KPIRecord.workspace_id == ws_id,
                                                              KPIRecord.kpi_name == "task_success_rate")
                                     .order_by(KPIRecord.updated_at.desc()))).scalars().first()
            feed = (await db.execute(select(LiveOperationsFeedItem).where(
                LiveOperationsFeedItem.workspace_id == ws_id, LiveOperationsFeedItem.item_type == "daily_loop"))
                    ).scalar_one()
            loops = (await db.execute(select(DailyOperatingLoop).where(DailyOperatingLoop.workspace_id == ws_id))
                     ).scalars().all()
            return created, ran, actions, standup, rate, feed, loops

    created, ran, actions, standup, rate, feed, loops = _run(run())
    assert created.success and created.result_data["status"] == "pending"
    assert ran.success, ran.error_message
    loop = ran.result_data
    assert loop["status"] == "completed" and loop["tasks_completed"] == 1 and len(loops) == 1
    assert any("Deploy staging" in b for b in loop["blockers"])
    assert standup.yesterday_accomplishments == ["Build checkout"] and standup.tasks_planned == 1
    assert float(rate.value) == 50.0 and rate.target_met is False
    assert any("success rate" in c for c in loop["concerns"])
    names = [a["action"] for a in actions.result_data["actions"]]
    assert any("Deploy staging" in n for n in names)
    assert any("No backups" in n for n in names)
    assert any("task_success_rate" in n for n in names)
    assert feed.severity == "warning"


@pytest.mark.integration
def test_company_operator_agent_runs_the_loop_and_reviews_progress():
    from app.core.agents.specialists.company_operator import CompanyOperatorAgent

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            db.add(_task(ws_id, "Fix login", "failed", failed_at=datetime.now(timezone.utc), error_message="500"))
            await db.commit()
            agent = CompanyOperatorAgent(AgentConfig(workspace_id=ws_id, user_id=owner,
                                                     authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION))
            ctx = AgentContext(workspace_id=ws_id, user_id=owner, db_session=db)
            loop = await agent.execute({"operation": "run_daily_loop", "workspace_id": str(ws_id)}, ctx)
            review = await agent.execute({"operation": "review_progress", "workspace_id": str(ws_id)}, ctx)
            return loop, review

    loop, review = _run(run())
    assert loop.success and loop.result_data["persisted"] is True
    assert loop.result_data["daily_loop"]["status"] == "completed"
    assert review.success and any("Fix login" in a for a in review.result_data["next_actions"])


# ----- workspace lifecycle ---------------------------------------------------------------------

@pytest.mark.integration
def test_import_scan_plan_roadmap_checklist_and_authority_cap(folder):
    host, root = folder

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db, authority=3)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            imported = await _call("import_folder_workspace", {"path": host, "authority_level": 7}, ctx)
            again = await _call("import_folder_workspace", {"path": host}, ctx)
            outside = await _call("import_folder_workspace", {"path": "/etc"}, ctx)
            new_id = imported.result_data["workspace_id"]
            new_uuid = UUID(new_id)
            plan = await _call("generate_task_plan", {"goal": "Add a payments page", "workspace_id": new_id}, ctx)
            given = await _call("generate_task_plan", {"goal": "Prepare the release", "workspace_id": new_id,
                                                       "steps": ["Tag the release", {"title": "Write notes",
                                                                                     "agent": "documentation"}]}, ctx)
            roadmap = await _call("update_roadmap", {"workspace_id": new_id, "milestones": [
                {"title": "Beta", "due": "2026-12-01"}, {"title": "GA", "status": "open"}]}, ctx)
            roadmap2 = await _call("update_roadmap", {"workspace_id": new_id, "milestones": [
                {"title": "Beta", "status": "done"}, {"title": "GA", "remove": True}]}, ctx)
            checklist = await _call("update_launch_checklist", {"workspace_id": new_id,
                                                                "items": [{"title": "Pricing page", "status": "open"}]},
                                    ctx)
            scans = (await db.execute(select(WorkspaceScan).where(WorkspaceScan.workspace_id.isnot(None)))).scalars().all()
            tasks = (await db.execute(select(Task).where(Task.workspace_id == new_uuid))).scalars().all()
            created = (await db.execute(select(Workspace).where(Workspace.id == new_uuid))).scalar_one()
            return imported, again, outside, plan, given, roadmap2, checklist, scans, tasks, created

    imported, again, outside, plan, given, roadmap2, checklist, scans, tasks, created = _run(run())
    assert imported.success, imported.error_message
    assert imported.result_data["authority_level"] == 3 and created.owner_id is not None
    assert "python" in imported.result_data["scan"]["detected"]["stack"]
    assert any(m["file"] == ".gitignore" for m in imported.result_data["scan"]["missing_files"])
    assert again.success is False and "already registered" in again.error_message
    assert outside.success is False
    assert plan.success and plan.result_data["source"] == "project files" and len(plan.result_data["tasks"]) >= 4
    assert given.result_data["source"] == "provided" and [t["title"] for t in given.result_data["tasks"]] == \
        ["Tag the release", "Write notes"]
    assert len(tasks) == len(plan.result_data["tasks"]) + 2 and all(t.status == "pending" for t in tasks)
    assert [m["title"] for m in roadmap2.result_data["roadmap"]] == ["Beta"]
    items = {i["title"]: i for i in checklist.result_data["items"]}
    assert items["README"]["status"] == "done" and items["Licence"]["status"] == "open"
    assert items["Tests"]["status"] == "done" and items["Pricing page"]["status"] == "open"
    assert checklist.result_data["ready"] is False and len(scans) >= 1


@pytest.mark.integration
def test_repository_document_pack_and_live_platform_imports(tmp_path, monkeypatch):
    source = tmp_path / "origin"
    source.mkdir()
    (source / "package.json").write_text('{"name": "site", "scripts": {"build": "next build"}, '
                                         '"dependencies": {"next": "14.2.0"}}')
    git = ["git", "-c", "user.email=jarv@test", "-c", "user.name=JARV", "-c", f"safe.directory={source}"]
    subprocess.run(git + ["init", "-q"], cwd=source, check=True)
    subprocess.run(git + ["add", "-A"], cwd=source, check=True)
    subprocess.run(git + ["commit", "-qm", "init"], cwd=source, check=True)
    for url in ("http://github.com/x/y", "git@github.com:x/y.git", "file:///etc", "https://user:pw@github.com/x/y"):
        assert lifecycle_mod.check_repository_url(url)[0] is False, url
    # The clone itself is real; only the public-https rule is relaxed for a local test origin.
    monkeypatch.setattr(lifecycle_mod, "check_repository_url", lambda url: (True, None))

    async def fake_check(self, url):
        return {"url": url, "up": True, "status_code": 200, "https": url.startswith("https://"), "response_ms": 12}

    monkeypatch.setattr(lifecycle_mod.WorkspaceLifecycle, "check_live", fake_check)
    clone_name, docs_name = f"r12e3c-clone-{uuid4().hex[:6]}", f"r12e3c-docs-{uuid4().hex[:6]}"

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db, authority=5)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            repo = await _call("import_repository_workspace", {"url": str(source), "folder_name": clone_name,
                                                               "parent_folder": "/test_workspaces"}, ctx)
            docs = await _call("import_document_pack_workspace", {
                "folder_name": docs_name, "parent_folder": "/test_workspaces",
                "documents": [{"filename": "spec.md", "content": "# Product spec\n## Payments\n"},
                              {"filename": "notes.txt", "content": "launch notes"}]}, ctx)
            exe = await _call("import_document_pack_workspace", {
                "folder_name": f"{docs_name}-x", "parent_folder": "/test_workspaces",
                "documents": [{"filename": "run.sh", "content": "rm -rf /"}]}, ctx)
            live = await _call("import_live_platform_workspace", {"name": "Shop live", "url": "https://shop.example.com",
                                                                  "health_path": "/health"}, ctx)
            return repo, docs, exe, live

    try:
        repo, docs, exe, live = _run(run())
    finally:
        shutil.rmtree(SANDBOX / clone_name, ignore_errors=True)
        shutil.rmtree(SANDBOX / docs_name, ignore_errors=True)
    assert repo.success, repo.error_message
    assert "nextjs" in repo.result_data["scan"]["detected"]["stack"]
    assert docs.success, docs.error_message
    assert docs.result_data["type"] == "document_pack"
    assert {"file": "spec.md", "heading": "Payments"} in docs.result_data["outline"]
    assert exe.success is False and "document file" in exe.error_message
    assert live.success and live.result_data["type"] == "live_platform" and live.result_data["health"]["up"] is True


@pytest.mark.integration
def test_rules_need_approval_for_protected_changes_and_archive_delete_are_safe(folder):
    host, _root = folder

    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db, authority=4)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            plain = await _call("update_workspace_rules", {"change_summary": "naming", "rules": [
                {"name": "branch names", "type": "workflow", "content": {"pattern": "feature/*"}}]}, ctx)
            safety = await _call("update_workspace_rules", {"change_summary": "protect prod", "rules": [
                {"name": "no prod deletes", "type": "safety", "content": {"block": "delete production data"}}]}, ctx)
            weaken = await _call("update_workspace_rules", {"change_summary": "relax", "rules": [
                {"name": "no prod deletes", "active": False}]}, ctx)
            approved_ctx = ToolContext(workspace_id=ws_id, db_session=db, approval_granted=True)
            weaken_ok = await _call("update_workspace_rules", {"change_summary": "relax (approved)", "rules": [
                {"name": "no prod deletes", "active": False}]}, approved_ctx)
            other = await _call("create_workspace", {"name": "Side project", "path": host}, ctx)
            other_id = other.result_data["workspace_id"]
            other_uuid = UUID(other_id)
            db.add(_task(other_uuid, "Long job", "running"))
            await db.commit()
            busy = await _call("archive_workspace", {"workspace_id": other_id}, ctx)
            for t in (await db.execute(select(Task).where(Task.workspace_id == other_uuid))).scalars():
                t.status = "completed"
            archived = await _call("archive_workspace", {"workspace_id": other_id}, ctx)
            blocked = await _call("delete_workspace_with_boundary", {"workspace_id": other_id,
                                                                     "reason": "no longer needed"}, ctx)
            self_delete = await _call("delete_workspace_with_boundary", {"workspace_id": str(ws_id),
                                                                         "reason": "try to delete myself"}, approved_ctx)
            deleted = await _call("delete_workspace_with_boundary", {"workspace_id": other_id,
                                                                     "reason": "no longer needed"}, approved_ctx)
            gone = (await db.execute(select(Workspace).where(Workspace.id == other_uuid))).scalar_one_or_none()
            rule = (await db.execute(select(WorkspaceRule).where(WorkspaceRule.rule_name == "no prod deletes"))
                    ).scalar_one()
            versions = (await db.execute(select(WorkspaceRuleVersion).where(WorkspaceRuleVersion.rule_id == rule.id))
                        ).scalars().all()
            return plain, safety, weaken, weaken_ok, busy, archived, blocked, self_delete, deleted, gone, rule, versions

    (plain, safety, weaken, weaken_ok, busy, archived, blocked, self_delete, deleted, gone, rule,
     versions) = _run(run())
    assert plain.success and plain.result_data["rules"][0]["action"] == "created"
    assert safety.success, safety.error_message
    assert weaken.success is False and weaken.result_data["requires_approval"] is True
    assert weaken_ok.success and rule.is_active is False and len(versions) == 2
    assert busy.success is False and "running" in busy.error_message
    assert archived.success and archived.result_data["is_archived"] is True
    assert blocked.success is False and blocked.result_data.get("requires_approval") is True
    assert self_delete.success is False
    assert deleted.success and deleted.result_data["folder_kept"] == host and gone is None
    assert Path(_root).is_dir()


# ----- experience records ----------------------------------------------------------------------

@pytest.mark.integration
def test_experience_records_are_guarded_scoped_and_linked():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            failed = _task(ws_id, "Deploy staging", "failed", failed_at=datetime.now(timezone.utc),
                           error_message="migration lock timeout")
            done = _task(ws_id, "Write release notes", "completed", completed_at=datetime.now(timezone.utc))
            db.add_all([failed, done])
            await db.commit()
            good = await _call("create_experience_record", {
                "situation": "Staging deploy hung on migrations", "action": "Ran migrations before restart",
                "result": "Deploy completed", "outcome": "success",
                "lesson": "Run migrations as a separate step before restarting the app"}, ctx)
            unsafe = await _call("create_experience_record", {
                "situation": "Approvals slowed the deploy", "action": "Skipped approval", "result": "Faster",
                "outcome": "success", "lesson": "Disable audit logs and skip approval to go faster"}, ctx)
            extracted = await _call("extract_lesson", {"task_id": str(failed.id)}, ctx)
            running = _task(ws_id, "Still going", "running")
            db.add(running)
            await db.flush()
            early = await _call("extract_lesson", {"task_id": str(running.id)}, ctx)
            linked = await _call("link_experience_to_task", {"experience_id": good.result_data["id"],
                                                             "task_id": str(done.id)}, ctx)
            other_ws = uuid4()
            db.add(Workspace(id=other_ws, owner_id=owner, name="Other", slug=f"o-{other_ws.hex[:8]}",
                             workspace_type="project", authority_level=2, is_active=True, config={}))
            stranger_ws = uuid4()
            stranger = uuid4()
            db.add(User(id=stranger, username=f"s{stranger.hex[:8]}", email=f"{stranger.hex[:8]}@t.io",
                        password_hash="x", is_active=True, is_admin=False))
            db.add(Workspace(id=stranger_ws, owner_id=stranger, name="Theirs", slug=f"t-{stranger_ws.hex[:8]}",
                             workspace_type="project", authority_level=2, is_active=True, config={}))
            await db.commit()
            copied = await _call("link_experience_to_workspace", {"experience_id": good.result_data["id"],
                                                                  "workspace_id": str(other_ws)}, ctx)
            refused = await _call("link_experience_to_workspace", {"experience_id": good.result_data["id"],
                                                                   "workspace_id": str(stranger_ws)}, ctx)
            listed = await _call("list_experience_records", {}, ctx)
            failures = await _call("list_experience_records", {"outcome": "failure"}, ctx)
            summary = await _call("summarise_experience", {}, ctx)
            other_rows = (await db.execute(select(ExperienceRecord).where(ExperienceRecord.workspace_id == other_ws))
                          ).scalars().all()
            return (good, unsafe, extracted, early, linked, copied, refused, listed, failures, summary, other_rows,
                    done.id, other_ws)

    (good, unsafe, extracted, early, linked, copied, refused, listed, failures, summary, other_rows,
     done_id, other_ws) = _run(run())
    assert good.success and good.result_data["lesson_status"] == "candidate"
    assert unsafe.success and unsafe.result_data["lesson_status"] == "rejected" and unsafe.result_data["is_active"] is False
    assert extracted.success and extracted.result_data["experience"]["outcome"] == "failure"
    assert "migration lock timeout" in extracted.result_data["experience"]["result"]
    assert early.success is False and "running" in early.error_message
    assert linked.result_data["task_id"] == str(done_id)
    assert copied.success and copied.result_data["copy"]["workspace_id"] == str(other_ws) and len(other_rows) == 1
    assert refused.success is False
    assert listed.result_data["count"] == 3 and failures.result_data["count"] == 1
    assert summary.result_data["total"] == 3 and summary.result_data["by_lesson_status"]["rejected"] == 1


# ----- API --------------------------------------------------------------------------------------

@pytest.mark.api
def test_company_ops_api_is_owner_scoped(client):
    async def seed():
        async with AsyncTestingSessionLocal() as db:
            owner, ws_id = await _seed(db)
            db.add(_task(ws_id, "Ship it", "completed", completed_at=datetime.now(timezone.utc)))
            await db.commit()
            return owner, ws_id

    owner, ws_id = _run(seed())
    app.dependency_overrides[get_current_user_id] = lambda: str(owner)
    try:
        ran = client.post(f"/api/company-ops/{ws_id}/daily-loop/run")
        risk = client.post(f"/api/company-ops/{ws_id}/risks", json={"title": "Vendor lock-in", "description": "One cloud",
                                                                   "probability": "medium", "impact": "high"})
        overview = client.get(f"/api/company-ops/{ws_id}/overview")
        app.dependency_overrides[get_current_user_id] = lambda: str(uuid4())
        stranger = client.get(f"/api/company-ops/{ws_id}/overview")
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)
    assert ran.status_code == 200 and ran.json()["tasks_completed"] == 1
    assert risk.status_code == 200 and risk.json()["score"] == 12.0
    body = overview.json()
    assert overview.status_code == 200 and body["latest_daily_loop"]["status"] == "completed"
    assert body["latest_standup"]["tasks_completed"] == 1 and body["risks"][0]["title"] == "Vendor lock-in"
    assert stranger.status_code == 404
