"""
Toolchain for building projects in a workspace (MYCO Phase 0: pnpm, uv, local git).

The classifier lets agents run pnpm and uv, initialise a repository, stage and commit inside the
workspace folder, and still blocks chaining, pushing, resetting and cleaning. Commands that change
the folder they run in are refused without a workspace folder. The worker image carries Node 22,
pnpm, uv and Python 3.12 at build time. The git test runs real git through the real ToolRuntime.
"""
import asyncio
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.command.tool_runtime import ToolRuntime
from app.core.workspaces.fs_inspector import SANDBOX_CONTAINER_ROOT, classify_command, needs_workspace

from tests.conftest import AsyncTestingSessionLocal
from tests.repo_paths import repo_path


@pytest.mark.parametrize("command, expected", [
    ("pnpm --version", "safe"),
    ("uv --version", "safe"),
    ("uv python list", "safe"),
    ("git rev-parse HEAD", "safe"),
    ("pnpm install", "install"),
    ("pnpm install --lockfile-only", "install"),
    ("uv lock", "install"),
    ("uv sync", "install"),
    ("uv venv", "install"),
    ("uv tool install semgrep", "install"),
    ("uv python install 3.14", "install"),
    ("uvx osv-scanner --help", "install"),
    ("pnpm dlx create-vite", "install"),
    ("sudo uv tool install semgrep", "dangerous"),
    ("uv tool list", "safe"),
    ("jq --version", "safe"),
    ("pnpm -r test", "build"),
    ("pnpm typecheck", "build"),
    ("uv run pytest", "build"),
    ("git init", "build"),
    ("git add .", "build"),
    ("git add -A", "build"),
    ("git add docs/architecture.md pnpm-workspace.yaml", "build"),
    ('git commit -m "Phase 0: platform skeleton and format rules"', "build"),
    ('git commit -a -m "Confirm the dependency manifest"', "build"),
    ("git add . && rm -rf docs", "dangerous"),
    ("git add a;b", "dangerous"),
    ("git add $(ls)", "dangerous"),
    ('git commit -m "x; rm -rf /"', "dangerous"),
    ('git commit -m "a" && rm x', "dangerous"),
    ('git commit -m "$(whoami)"', "dangerous"),
    ("git push origin main", "dangerous"),
    ("git reset --hard", "dangerous"),
    ("pnpm add -g left-pad", "dangerous"),
    ("pnpm type-check", "build"),
    ("pnpm format", "build"),
    ("pnpm run e2e", "build"),
    ("yarn lint", "build"),
    ("yarn", "install"),
    ("yarn publish", "risky"),
    ("pnpm publish", "risky"),
    ("pnpm run publish", "risky"),
    ("npm run deploy", "risky"),
    ("pnpm run deploy:prod", "risky"),
    ("pnpm release", "risky"),
    ("pnpm config set registry x", "risky"),
    ("pnpm type-check; rm x", "dangerous"),
    ("git clean -fd", "risky"),
    ("git commit -m 'single quotes'", "risky"),
])
def test_toolchain_commands_are_classified(command, expected):
    assert classify_command(command) == expected


def test_folder_changing_commands_need_a_workspace():
    for command in ("git init", "git add .", 'git commit -m "x"', "pnpm install", "uv sync"):
        assert needs_workspace(command) is True, command
    for command in ("git status", "pnpm --version", "uv run pytest", "pnpm -r test"):
        assert needs_workspace(command) is False, command


async def _runtime(session):
    from app.models.user import User
    from app.models.workspace import Workspace

    uid, wid = uuid4(), uuid4()
    session.add(User(id=uid, username=f"u{uid.hex[:8]}", email=f"{uid.hex[:8]}@t.io",
                     password_hash="$2b$12$x", is_active=True, is_admin=False))
    session.add(Workspace(id=wid, name="Toolchain", slug=f"toolchain-{wid.hex[:8]}", description="d",
                          owner_id=uid, is_active=True, workspace_type="test", authority_level=5))
    await session.commit()
    return ToolRuntime(session, wid, None, operator=str(uid), authority_level=5, user_id=uid)


@pytest.mark.integration
def test_agent_initialises_stages_and_commits_inside_the_workspace(monkeypatch):
    for key, value in (("GIT_AUTHOR_NAME", "JARV"), ("GIT_AUTHOR_EMAIL", "jarv@localhost"),
                       ("GIT_COMMITTER_NAME", "JARV"), ("GIT_COMMITTER_EMAIL", "jarv@localhost")):
        monkeypatch.setenv(key, value)
    name = f"toolchain-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    host = f"/test_workspaces/{name}"

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            outside = await rt.run_command("git init")
            init = await rt.run_command("git init", cwd_host=host)
            write = await rt.write_file(f"{host}/README.md", "# MYCO\n")
            add = await rt.run_command("git add .", cwd_host=host)
            commit = await rt.run_command('git commit -m "Phase 0: platform skeleton"', cwd_host=host)
            push = await rt.run_command("git push origin main", cwd_host=host)
            return outside, init, write, add, commit, push

    outside, init, write, add, commit, push = asyncio.run(run())
    assert outside["blocked"] is True and "not inside an approved workspace" in outside["reason"]
    assert init["success"] is True, init
    assert write["success"] is True
    assert add["success"] is True, add
    assert commit["success"] is True, commit
    assert push["success"] is False and push["blocked"] is True
    log = subprocess.run(["git", "log", "--format=%an %s"], cwd=folder, capture_output=True, text=True)
    assert log.stdout.strip() == "JARV Phase 0: platform skeleton"
    shutil.rmtree(folder, ignore_errors=True)


def test_worker_image_carries_node_pnpm_uv_and_python_312():
    dockerfile = repo_path("apps", "backend", "Dockerfile").read_text()
    runtime = dockerfile.split("# Production stage", 1)[1]
    assert "FROM node:22-bookworm-slim AS node" in dockerfile
    assert "FROM ghcr.io/astral-sh/uv:" in dockerfile
    assert "COPY --from=node /usr/local/bin/node /usr/local/bin/node" in runtime
    assert "npm install -g pnpm@10" in runtime
    assert "COPY --from=uv /uv /uvx /usr/local/bin/" in runtime
    assert "uv python install 3.12 3.13" in runtime
    assert "build-essential" in runtime and "ripgrep" in runtime and "pnpm@10 yarn@1" in runtime
    assert "PATH=/home/jarv/.local/bin:$PATH" in runtime
    assert "HOME=/home/jarv" in runtime and "GIT_AUTHOR_NAME=JARV" in runtime
    assert "    nodejs \\" not in runtime  # the distribution's old Node is no longer installed


def test_jarv_user_matches_the_workspace_owner():
    dockerfile = repo_path("apps", "backend", "Dockerfile").read_text()
    assert "ARG JARV_UID=1000" in dockerfile and "ARG JARV_GID=1000" in dockerfile
    assert 'useradd -r -m -d /home/jarv -u "${JARV_UID}" -g jarv jarv' in dockerfile
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = repo_path(name).read_text()
        assert compose.count("JARV_UID: ${JARV_UID:-1000}") == 4, name


def test_tool_home_persists_for_backend_and_worker():
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = repo_path(name).read_text()
        assert compose.count("- tool_home:/home/jarv") == 2, name
        assert "\n  tool_home:\n    driver: local\n" in compose, name


@pytest.mark.integration
def test_an_approved_command_runs_exactly_in_its_workspace_folder():
    """Approving a paused command runs that command in the workspace folder, not a new agent mission."""
    from sqlalchemy import select
    from app.core.richard.workflow import COMPLETED, RichardBoundaryWorkflow
    from app.models.boundary import ResumeAction
    from app.models.workspace import Workspace

    name = f"approved-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    host = f"/test_workspaces/{name}"
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    (folder / "stray.txt").write_text("left over")

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            workspace = (await session.execute(
                select(Workspace).where(Workspace.id == rt.workspace_id))).scalar_one()
            workspace.config = {"root_path": host}
            await session.commit()
            paused = await rt.run_command("git clean -n", cwd_host=host)
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(
                approval_id=UUID(paused["approval_id"]), authenticated_user_id=rt.user_id,
                approve=True, authority_granted=5, expiry_seconds=3600)
            resumed = await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                    authenticated_user_id=rt.user_id)
            action = (await session.execute(select(ResumeAction).where(
                ResumeAction.checkpoint_id == UUID(paused["checkpoint_id"])))).scalar_one()
            return paused, resumed, action.action_details

    paused, resumed, details = asyncio.run(run())
    assert paused["requires_approval"] is True and paused["boundary_chain_opened"] is True
    assert resumed["resumed"] is True and resumed["status"] == COMPLETED, resumed
    ran = details["ran"][0]
    assert ran["success"] is True
    assert ran["output_preview"].startswith("Ran the approved command `git clean -n` (exit 0)")
    assert "Would remove stray.txt" in ran["output_preview"]
    assert (folder / "stray.txt").exists()  # git clean -n only lists; nothing was removed
    shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.integration
def test_an_approved_command_needs_a_workspace_folder():
    from app.core.richard.workflow import RichardBoundaryWorkflow

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            paused = await rt.run_command("git clean -n")
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(
                approval_id=UUID(paused["approval_id"]), authenticated_user_id=rt.user_id,
                approve=True, authority_granted=5, expiry_seconds=3600)
            return await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                 authenticated_user_id=rt.user_id)

    resumed = asyncio.run(run())
    assert resumed["resumed"] is False
    assert "no folder" in str(resumed)


def test_the_planner_keeps_normal_work_away_from_richard():
    from app.agents import orchestrator

    source = Path(orchestrator.__file__).read_text()
    assert "true for any task that modifies files" not in source
    assert "Writing and editing files, installing" in source


@pytest.mark.integration
def test_an_approved_command_runs_in_the_folder_it_was_paused_in():
    """A mission works in its own folder (MYCO) while its task belongs to another workspace. Approving a paused
    command ran nothing ("the workspace has no folder"); the folder is now kept with the checkpoint."""
    from app.core.richard.workflow import COMPLETED, RichardBoundaryWorkflow

    name = f"mission-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    host = f"/test_workspaces/{name}"
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    (folder / "notes.txt").write_text("x")

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)  # its workspace has no folder
            paused = await rt.run_command("git clean -n", cwd_host=host)
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(
                approval_id=UUID(paused["approval_id"]), authenticated_user_id=rt.user_id,
                approve=True, authority_granted=5, expiry_seconds=3600)
            return await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                 authenticated_user_id=rt.user_id)

    resumed = asyncio.run(run())
    assert resumed["status"] == COMPLETED, resumed
    assert "Would remove notes.txt" in resumed["ran"][0]["output_preview"]
    shutil.rmtree(folder, ignore_errors=True)


@pytest.mark.integration
def test_a_failed_approved_command_does_not_overwrite_a_running_mission():
    from sqlalchemy import select
    from app.core.richard.workflow import RichardBoundaryWorkflow
    from app.models.task import Task

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            mission = Task(id=uuid4(), title="Finish MYCO Phase 0", description="d", workspace_id=rt.workspace_id,
                           status="pending", priority=5, task_type="agent_task")
            session.add(mission)
            await session.commit()
            rt.task_id = mission.id
            paused = await rt.run_command("git clean -n")  # no folder anywhere: the approved run fails
            row = (await session.execute(select(Task).where(Task.id == mission.id))).scalar_one()
            row.status = "running"  # the mission's agent loop carried on and is still working
            await session.commit()
            workflow = RichardBoundaryWorkflow(session)
            await workflow.record_richard_decision(
                approval_id=UUID(paused["approval_id"]), authenticated_user_id=rt.user_id,
                approve=True, authority_granted=5, expiry_seconds=3600)
            resumed = await workflow.resume_mission(checkpoint_id=UUID(paused["checkpoint_id"]),
                                                    authenticated_user_id=rt.user_id)
            status = (await session.execute(select(Task.status).where(Task.id == mission.id))).scalar_one()
            return resumed, status

    resumed, status = asyncio.run(run())
    assert resumed["resumed"] is False
    assert status == "running"


def test_read_only_git_commands_never_need_approval():
    for command in ("git ls-files", "git ls-tree HEAD", "git describe --tags", "git check-ignore dist",
                    "git show HEAD", "git grep SERVICE_NAME", "git blame README.md", "git tag -l"):
        assert classify_command(command) == "safe", command


@pytest.mark.integration
def test_env_templates_are_project_files_and_real_env_files_stay_protected():
    """Phase 0 asks for .env.example (setting names only); JARV refused to write it as a secret file."""
    name = f"envtpl-{uuid4().hex[:8]}"
    folder = Path(SANDBOX_CONTAINER_ROOT) / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    host = f"/test_workspaces/{name}"

    async def run():
        async with AsyncTestingSessionLocal() as session:
            rt = await _runtime(session)
            template = await rt.write_file(f"{host}/.env.example", "DATABASE_URL=\nANTHROPIC_API_KEY=\n")
            read = await rt.read_file(f"{host}/.env.example")
            real = await rt.write_file(f"{host}/.env", "DATABASE_URL=\n")
            leaked = await rt.write_file(f"{host}/.env.sample", "OPENAI_API_KEY=sk-REPAIR10SECRETKEY1234567890\n")
            return template, read, real, leaked

    template, read, real, leaked = asyncio.run(run())
    assert template["success"] is True, template
    assert "ANTHROPIC_API_KEY=" in read["data"]["content"]
    assert real["success"] is False
    assert leaked["success"] is False and not (folder / ".env.sample").exists()
    shutil.rmtree(folder, ignore_errors=True)
