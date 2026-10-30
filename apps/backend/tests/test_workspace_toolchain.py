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
from uuid import uuid4

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


def test_tool_home_persists_for_backend_and_worker():
    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = repo_path(name).read_text()
        assert compose.count("- tool_home:/home/jarv") == 2, name
        assert "\n  tool_home:\n    driver: local\n" in compose, name
