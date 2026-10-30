"""Repair 12e-2: deployments with health checks, automatic restore, and rollback.

Real: git packaging of a real repository, the release layout on disk (tar
extraction, shared .env link, atomic `current` switch, pruning), the tools,
the permission policy, and DeploymentRecord persistence. Replaced at the
boundary: the SSH hop (commands run in a local shell against a temporary
"server" directory), Docker Compose (a script that records each `up` and fails
when the release contains FAIL_COMPOSE), and the app's HTTP health endpoint
(httpx.MockTransport).
"""
import asyncio
import os
import shutil
import stat
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

import app.tools.deploy as deploy_tools
from app.core import deploy
from app.core.agents.base import AuthorityLevel
from app.core.config import settings
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import get_registry
from app.models.operations import DeploymentRecord
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.deploy import (
    CheckDeployTargetTool, DeployProductionTool, DeployStagingTool, DeploymentLogsTool, DeploymentStatusTool,
    RollbackTool,
)
from tests.conftest import AsyncTestingSessionLocal

SANDBOX = Path("/tmp/jarv_sandbox")


def _run(coro):
    return asyncio.run(coro)


class LocalShell:
    """The deployment server, played by a local bash in a temporary directory."""

    def __init__(self, env):
        self.env = env
        self.commands = []

    async def run(self, command, *, stdin=None, timeout=600):
        self.commands.append(command)
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", command, env={**os.environ, **self.env},
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate(stdin)
        return proc.returncode, out.decode(), err.decode()


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=jarv@test", "-c", "user.name=JARV", "-c",
                    f"safe.directory={root}", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def server(tmp_path, monkeypatch):
    name = f"r12e-{uuid4().hex[:8]}"
    repo = SANDBOX / name
    repo.mkdir(parents=True)
    (repo / "docker-compose.yml").write_text("services:\n  web:\n    image: nginx:alpine\n")
    (repo / "app.txt").write_text("v1\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "v1")

    base = tmp_path / "srv"
    compose_log = tmp_path / "compose.log"
    compose = tmp_path / "fake-compose"
    compose.write_text('#!/bin/bash\necho "$PWD $*" >> "$COMPOSE_LOG"\n'
                       'if [ -f FAIL_COMPOSE ]; then echo "build failed: missing package" >&2; exit 1; fi\n')
    compose.chmod(0o755)
    health = {"status": 200}
    shell = LocalShell({"COMPOSE_LOG": str(compose_log)})
    transport = httpx.MockTransport(lambda request: httpx.Response(health["status"]))
    deployer = deploy.Deployer(shell, str(base), compose=str(compose), http=transport,
                               health_attempts=2, health_delay=0)
    monkeypatch.setattr(deploy_tools, "_deployer", lambda: deployer)
    yield {"repo": repo, "host": f"/test_workspaces/{name}", "base": base, "health": health,
           "compose_log": compose_log, "shell": shell}
    shutil.rmtree(repo, ignore_errors=True)


async def _workspace(db, host, health_url="https://staging.myco.example/health"):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="MYCO", slug=f"myco-{ws_id.hex[:4]}", description="",
                     workspace_type="software", authority_level=7, is_active=True,
                     config={"root_path": host, "deploy": {"app": "myco", "health_url": {
                         "staging": health_url, "production": "https://myco.example/health"}}}))
    await db.commit()
    return ws_id


def _tool(cls):
    return cls(ToolConfig(authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT))


def _current(server, env="staging"):
    link = server["base"] / f"myco-{env}" / "current"
    return os.readlink(link).split("/")[-1] if link.is_symlink() else None


# ----- registry -----------------------------------------------------------------------------

def test_deploy_tools_registered_and_production_is_approval_gated():
    registry = get_registry()
    for name in ("check_deploy_target", "deploy_staging", "deploy_production_with_boundary", "rollback",
                 "deployment_status", "deployment_logs"):
        meta = registry.get_metadata(name)
        assert meta is not None and meta.is_implemented and meta.category == "deployment", name
    assert DeployProductionTool(ToolConfig()).requires_approval is True
    assert DeployStagingTool(ToolConfig()).requires_approval is False
    from app.core.agents.registry import get_registry as agents

    assert "deploy_production_with_boundary" in agents().get_metadata("devops").default_tools
    assert "rollback" in agents().get_metadata("rollback").default_tools


# ----- the release lifecycle ----------------------------------------------------------------------

@pytest.mark.integration
def test_deploy_restore_and_rollback_lifecycle(server):
    repo = server["repo"]

    async def run():
        async with AsyncTestingSessionLocal() as db:
            ws_id = await _workspace(db, server["host"])
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            first = await _tool(DeployStagingTool).execute({}, ctx)

            (repo / "app.txt").write_text("v2\n")
            _git(repo, "commit", "-qam", "v2")
            second = await _tool(DeployStagingTool).execute({}, ctx)

            (repo / "FAIL_COMPOSE").write_text("x")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "broken build")
            broken = await _tool(DeployStagingTool).execute({}, ctx)

            (repo / "FAIL_COMPOSE").unlink()
            _git(repo, "commit", "-qam", "fixed build, unhealthy app")
            server["health"]["status"] = 503
            unhealthy = await _tool(DeployStagingTool).execute({}, ctx)
            server["health"]["status"] = 200

            rolled = await _tool(RollbackTool).execute({"environment": "staging", "reason": "v2 regressed"}, ctx)
            status = await _tool(DeploymentStatusTool).execute({"environment": "staging"}, ctx)
            await db.commit()
            records = (await db.execute(select(DeploymentRecord).where(DeploymentRecord.workspace_id == ws_id)
                                        .order_by(DeploymentRecord.started_at))).scalars().all()
            return first, second, broken, unhealthy, rolled, status, records

    first, second, broken, unhealthy, rolled, status, records = _run(run())
    r1, r2 = first.result_data["release"], second.result_data["release"]

    assert first.success and second.success and r1 < r2
    assert second.result_data["previous"] == r1
    assert (server["base"] / "myco-staging" / "releases" / r2 / "app.txt").read_text() == "v2\n"

    assert broken.success is False and broken.result_data["rolled_back"] is True
    assert "build failed" in broken.error_message
    assert unhealthy.success is False and unhealthy.result_data["rolled_back"] is True
    assert unhealthy.result_data["health"]["status_code"] == 503

    assert rolled.success and rolled.result_data["release"] == r1 and rolled.result_data["previous"] == r2
    assert _current(server) == r1 and status.result_data["current"] == r1

    ups = [line for line in server["compose_log"].read_text().splitlines() if " up " in line]
    assert all(" -p myco-staging -f docker-compose.yml up -d --build --remove-orphans" in line for line in ups)
    assert sum(r2 in line.split()[0] for line in ups) == 3  # deployed, restored after both failures

    assert [r.status for r in records] == ["succeeded", "succeeded", "rolled_back", "rolled_back", "succeeded"]
    assert records[-1].deployment_type == "rollback" and records[1].can_rollback is True
    assert records[2].commit_sha and "build failed" in records[2].error_message


@pytest.mark.integration
def test_uncommitted_changes_and_bad_names_are_refused(server):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            ws_id = await _workspace(db, server["host"])
            ctx = ToolContext(workspace_id=ws_id, db_session=db)
            (server["repo"] / "app.txt").write_text("edited, not committed\n")
            dirty = await _tool(DeployStagingTool).execute({}, ctx)
            bad = await _tool(DeployStagingTool).execute({"app": "myco;rm -rf /"}, ctx)
            return dirty, bad

    dirty, bad = _run(run())
    assert dirty.success is False and "uncommitted" in dirty.error_message
    assert bad.success is False
    assert not (server["base"]).exists() or not any((server["base"]).iterdir())


@pytest.mark.integration
def test_production_release_pauses_for_approval_then_ships(server):
    async def run():
        async with AsyncTestingSessionLocal() as db:
            ws_id = await _workspace(db, server["host"])
            blocked = await _tool(DeployProductionTool).execute({}, ToolContext(workspace_id=ws_id, db_session=db))
            approved = await _tool(DeployProductionTool).execute({}, ToolContext(
                workspace_id=ws_id, db_session=db, approved_tools=["deploy_production_with_boundary"]))
            logs = await _tool(DeploymentLogsTool).execute({"environment": "production"},
                                                           ToolContext(workspace_id=ws_id, db_session=db))
            return blocked, approved, logs

    blocked, approved, logs = _run(run())
    assert blocked.success is False and blocked.result_data["requires_approval"] is True
    assert approved.success and _current(server, "production") == approved.result_data["release"]
    assert _current(server, "staging") is None
    assert logs.success


def test_old_releases_are_pruned_but_current_and_previous_kept(tmp_path):
    shell = LocalShell({})
    deployer = deploy.Deployer(shell, str(tmp_path), compose="true", health_attempts=1, health_delay=0)

    async def run():
        releases = []
        for i in range(deploy.KEEP_RELEASES + 3):
            package = deploy.Package(archive=_tar_of({"n.txt": str(i)}), commit=f"{i:07d}abc", branch="main",
                                     release_id=f"2026102{i % 10}T10000{i}000Z-{i:07d}abc")
            result = await deployer.deploy("myco", "staging", package, compose_file="n.txt")
            assert result.success, result.error
            releases.append(package.release_id)
        return releases, await deployer.releases("myco", "staging")

    releases, state = _run(run())
    assert state["current"] == releases[-1]
    assert len(state["releases"]) == deploy.KEEP_RELEASES and releases[-2] in state["releases"]


def _tar_of(files):
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


# ----- configuration and the SSH hop --------------------------------------------------------------

def test_unconfigured_server_is_reported_with_the_missing_settings(monkeypatch):
    monkeypatch.setattr(settings, "DEPLOY_SSH_HOST", "", raising=False)
    result = _run(_tool(CheckDeployTargetTool).execute({}, ToolContext(workspace_id=uuid4())))
    assert result.success and result.result_data["configured"] is False
    assert "DEPLOY_SSH_HOST" in result.result_data["missing"]
    with pytest.raises(deploy.DeployNotConfigured, match="docs/DEPLOYMENT.md"):
        deploy.load_target()


def test_ssh_pins_the_host_key_and_keeps_the_private_key_private(monkeypatch):
    import base64

    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n"
    for name, value in (("DEPLOY_SSH_HOST", "203.0.113.10"), ("DEPLOY_SSH_USER", "deploy"),
                        ("DEPLOY_SSH_PRIVATE_KEY", base64.b64encode(key.encode()).decode()),
                        ("DEPLOY_SSH_KNOWN_HOSTS", "203.0.113.10 ssh-ed25519 AAAAC3Nza")):
        monkeypatch.setattr(settings, name, value, raising=False)
    seen = {}

    async def fake_exec(*argv, **kwargs):
        key_path = Path(argv[argv.index("-i") + 1])
        seen.update(argv=argv, mode=stat.S_IMODE(key_path.stat().st_mode), key=key_path.read_text(),
                    key_path=key_path)

        class Proc:
            returncode = 0

            async def communicate(self, data=None):
                return b"ok", b""

        return Proc()

    monkeypatch.setattr(deploy.asyncio, "create_subprocess_exec", fake_exec)
    code, out, _ = _run(deploy.SshShell(deploy.load_target()).run("docker compose version"))

    assert code == 0 and out == "ok"
    assert "StrictHostKeyChecking=yes" in seen["argv"] and "BatchMode=yes" in seen["argv"]
    assert seen["argv"][-3:] == ("deploy@203.0.113.10", "--", "docker compose version")
    assert seen["mode"] == 0o600 and seen["key"] == key
    assert not seen["key_path"].exists()
