"""Repair 12d: operations agents on real tools.

The Docker Engine is replaced by an in-process HTTP double at the transport
layer (httpx.MockTransport), so the real DockerOps adapter, tools, toolbox,
permission policy, and audit logging all run. The backup test runs the real
pg_dump / pg_restore / createdb against the PostgreSQL the suite migrates.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.registry import get_registry as agent_registry
from app.core.agents.specialists.monitoring import MonitoringAgent
from app.core.agents.specialists.self_healing import SelfHealingAgent
from app.core.agents.specialists.infrastructure import InfrastructureAgent
from app.core.config import settings
from app.core.ops import docker_ops
from app.core.ops.docker_ops import DockerOps, OpsRefused, OpsUnavailable, _demux
from app.core.tools.base import ToolConfig, ToolContext
from app.core.tools.registry import get_registry as tool_registry
from app.models.operations import AuditLog
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace
from app.tools.ops import (
    OPS_TOOLS, CheckEnvVarsTool, CheckErrorsTool, CheckUptimeTool, CreateBackupTool, InspectServerTool,
    RestartServiceTool, RestoreBackupTool, VerifyBackupTool, ListBackupsTool,
)
from tests.conftest import AsyncTestingSessionLocal

ROOT = Path(__file__).resolve().parents[3]


def _run(coro):
    return asyncio.run(coro)


# ----- a Docker Engine double ---------------------------------------------------------

class FakeDocker:
    """Answers the Docker Engine endpoints the proxy allows; records requests."""

    def __init__(self, project="jarv-agentic-ai"):
        self.project = project
        self.requests = []
        self.containers = {}

    def add(self, cid, service, state="running", health="healthy", project=None):
        self.containers[cid] = {"service": service, "state": state, "health": health,
                                "project": project or self.project, "restarts": 0}

    def _summary(self, cid, c):
        status = "Up 5 minutes" if c["state"] == "running" else "Exited (1) 2 minutes ago"
        if c["state"] == "running" and c["health"]:
            status += f" ({c['health']})"
        return {"Id": cid + "f" * 52, "Names": [f"/jarv-{c['service']}-{cid[:4]}"], "Image": f"jarv-{c['service']}",
                "State": c["state"], "Status": status,
                "Labels": {"com.docker.compose.project": c["project"], "com.docker.compose.service": c["service"]}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path, dict(request.url.params)))
        path = request.url.path
        if path == "/containers/json":
            wanted = json.loads(request.url.params["filters"])["label"][0].split("=", 1)[1]
            return httpx.Response(200, json=[self._summary(cid, c) for cid, c in self.containers.items()
                                             if c["project"] == wanted])
        cid = path.split("/")[2][:12]
        c = self.containers.get(cid)
        if c is None:
            return httpx.Response(404, json={"message": "no such container"})
        if path.endswith("/json"):
            return httpx.Response(200, json={
                "RestartCount": c["restarts"],
                "State": {"Status": c["state"], "StartedAt": "2026-10-29T10:00:00Z",
                          "ExitCode": 0 if c["state"] == "running" else 1, "OOMKilled": False,
                          "Health": {"Log": [{"Output": "ok"}]}},
                "Config": {"Labels": {"com.docker.compose.project": c["project"]}}})
        if path.endswith("/logs"):
            line = b"2026-10-29 ERROR worker lost connection; token sk-ant-api03-SECRETSECRETSECRETSECRET\n"
            return httpx.Response(200, content=b"\x01\x00\x00\x00" + len(line).to_bytes(4, "big") + line)
        if path.endswith("/restart") and request.method == "POST":
            c["state"], c["health"], c["restarts"] = "running", "healthy", c["restarts"] + 1
            return httpx.Response(204)
        return httpx.Response(403, text="forbidden by proxy")

    def ops(self):
        return DockerOps("http://docker-proxy:2375", transport=httpx.MockTransport(self.handler))

    def restarts(self):
        return [p for m, p, _ in self.requests if m == "POST"]


@pytest.fixture
def docker(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", fake.project)
    monkeypatch.setattr(docker_ops, "get_docker_ops", fake.ops)
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)
    return fake


async def _seed(db, authority=6):
    user_id, ws_id = uuid4(), uuid4()
    db.add(User(id=user_id, username=f"u{user_id.hex[:8]}", email=f"{user_id.hex[:8]}@t.io",
                password_hash="x", is_active=True, is_admin=False))
    db.add(Workspace(id=ws_id, owner_id=user_id, name="R12d", slug=f"r12d-{ws_id.hex[:8]}",
                     description="", workspace_type="test", authority_level=authority, is_active=True))
    await db.commit()
    return user_id, ws_id


def _tool(cls, level=AuthorityLevel.LEVEL_7_DEPLOYMENT):
    return cls(ToolConfig(authority_level=level))


# ----- registry and wiring -------------------------------------------------------------

def test_every_operations_tool_is_registered_and_implemented():
    registry = tool_registry()
    names = [cls(ToolConfig()).name for cls in OPS_TOOLS]
    assert len(names) == len(set(names)) == 25
    for name in names:
        meta = registry.get_metadata(name)
        assert meta is not None and meta.is_implemented and meta.category == "operations", name
    from app.tools.infrastructure import BackupCreateTool, BackupRestoreTool

    assert BackupCreateTool is CreateBackupTool and BackupRestoreTool is RestoreBackupTool


def test_ops_agents_declare_only_registered_tools_within_their_authority():
    agents, tools = agent_registry(), tool_registry()
    for name in ("monitoring", "self_healing", "rollback", "infrastructure"):
        meta = agents.get_metadata(name)
        assert "check_container_status" in meta.default_tools or "check_health" in meta.default_tools
        for tool in meta.default_tools:
            tmeta = tools.get_metadata(tool)
            assert tmeta is not None and tmeta.is_implemented, (name, tool)
            assert tmeta.required_authority_level <= meta.required_authority_level, (name, tool)
    assert "restart_service" not in agents.get_metadata("monitoring").default_tools
    assert "restart_service" in agents.get_metadata("self_healing").default_tools


def test_restart_needs_production_authority_and_restore_always_needs_approval():
    from app.core.tools.base import ToolAuthorizationError

    ctx = ToolContext(workspace_id=uuid4(), user_id=uuid4())
    with pytest.raises(ToolAuthorizationError):
        _run(_tool(RestartServiceTool, AuthorityLevel.LEVEL_6_DATABASE_WRITE).execute(
            {"service": "worker", "reason": "worker crashed"}, ctx))
    restore = _run(_tool(RestoreBackupTool).execute({"backup_id": str(uuid4())}, ctx))
    assert restore.success is False
    assert restore.result_data["blocked"] is True and restore.result_data["requires_approval"] is True


# ----- Docker adapter --------------------------------------------------------------------

def test_docker_ops_lists_only_its_project_and_redacts_logs(docker):
    docker.add("aaaaaaaaaaaa", "backend")
    docker.add("bbbbbbbbbbbb", "worker", state="exited", health=None)
    docker.add("cccccccccccc", "web", project="someone-else")
    ops = docker.ops()

    services = [c.service for c in _run(ops.containers())]
    logs = _run(ops.logs("worker", 50))

    assert services == ["backend", "worker"]
    assert "ERROR worker lost connection" in logs and "SECRETSECRET" not in logs
    assert _demux(b"plain text") == "plain text"
    with pytest.raises(OpsRefused):
        _run(ops.logs("web"))


def test_docker_ops_never_restarts_data_stores_or_itself(docker, monkeypatch):
    docker.add("aaaaaaaaaaaa", "backend")
    docker.add("dddddddddddd", "postgres", state="exited", health=None)
    docker.add("eeeeeeeeeeee", "redis", state="exited", health=None)
    ops = docker.ops()
    for service in ("postgres", "redis", "docker-proxy-missing"):
        with pytest.raises(OpsRefused):
            _run(ops.restart(service))
    monkeypatch.setattr(docker_ops.socket, "gethostname", lambda: "aaaaaaaaaaaa")
    with pytest.raises(OpsRefused, match="another JARV service"):
        _run(ops.restart("backend"))
    assert docker.restarts() == []
    with pytest.raises(OpsUnavailable):
        _run(DockerOps(base_url="").containers())


def test_restart_targets_only_the_unhealthy_replica(docker):
    docker.add("111111111111", "worker")
    docker.add("222222222222", "worker", state="running", health="unhealthy")
    result = _run(docker.ops().restart("worker"))
    assert result["restarted"] and len(result["containers"]) == 1
    assert docker.restarts() == ["/containers/222222222222/restart"]


# ----- direct tools ------------------------------------------------------------------------

def test_server_and_config_tools_measure_without_leaking_values():
    ctx = ToolContext(workspace_id=uuid4())
    server = _run(_tool(InspectServerTool).execute({}, ctx))
    env = _run(_tool(CheckEnvVarsTool).execute({}, ctx))
    assert server.success and 0 <= server.result_data["memory_percent"] <= 100 and server.result_data["disks"]
    assert env.success and env.result_data["required"]["SECRET_KEY"] is True
    assert settings.SECRET_KEY not in json.dumps(env.result_data)


def test_uptime_refuses_private_and_metadata_addresses():
    ctx = ToolContext(workspace_id=uuid4())
    for url in ("http://127.0.0.1:8000/health", "http://169.254.169.254/latest", "file:///etc/passwd"):
        result = _run(_tool(CheckUptimeTool).execute({"url": url}, ctx))
        assert result.success is False and "refused" in result.error_message.lower(), url


@pytest.mark.integration
def test_check_errors_reports_this_workspace_only():
    async def run():
        async with AsyncTestingSessionLocal() as db:
            _, ws_id = await _seed(db)
            _, other_ws = await _seed(db)
            for ws, title in ((ws_id, "mine"), (other_ws, "theirs")):
                now = datetime.now(timezone.utc)
                db.add(Task(id=uuid4(), workspace_id=ws, title=title, description=title, task_type="command",
                            status="failed", priority=5, error_message=f"{title} broke", meta_data={},
                            created_at=now, updated_at=now))
            await db.commit()
            result = await _tool(CheckErrorsTool).execute({"hours": 2}, ToolContext(workspace_id=ws_id, db_session=db))
            return result

    result = _run(run())
    assert result.success
    assert [m["title"] for m in result.result_data["failed_missions"]] == ["mine"]


# ----- agents ---------------------------------------------------------------------------------

def _ctx(db, ws_id, user_id):
    return AgentContext(workspace_id=ws_id, user_id=user_id, db_session=db, metadata={"ops_enabled": True})


@pytest.mark.integration
def test_monitoring_agent_measures_real_state_and_logs_every_check(docker):
    docker.add("aaaaaaaaaaaa", "backend")
    docker.add("bbbbbbbbbbbb", "worker", state="exited", health=None)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db)
            agent = MonitoringAgent(AgentConfig(workspace_id=ws_id, user_id=user_id,
                                                authority_level=AuthorityLevel.LEVEL_6_DATABASE_WRITE))
            result = await agent.execute({"targets": ["backend", "http://10.0.0.5/"]}, _ctx(db, ws_id, user_id))
            await db.commit()
            actions = (await db.execute(select(AuditLog.action).where(AuditLog.workspace_id == ws_id))).scalars().all()
            return result, actions

    result, actions = _run(run())
    data = result.result_data
    statuses = {s["target"]: s["status"] for s in data["target_statuses"]}
    assert result.success and data["monitoring_active"] is True
    assert statuses["service:worker"] == "critical" and statuses["service:backend"] == "healthy"
    assert statuses["jarv:database"] == "healthy" and statuses["http://10.0.0.5/"] == "unknown"
    assert any(a["target"] == "service:worker" for a in data["alerts_triggered"])
    assert docker.restarts() == []
    logged = {a.split(".")[2] for a in actions if a.startswith("agent.tool.")}
    assert {"check_health", "check_container_status", "check_errors", "check_uptime"} <= logged


@pytest.mark.integration
def test_self_healing_agent_restarts_the_crashed_service_and_verifies(docker):
    docker.add("aaaaaaaaaaaa", "backend")
    docker.add("bbbbbbbbbbbb", "worker", state="exited", health=None)
    docker.add("dddddddddddd", "postgres")

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db)
            agent = SelfHealingAgent(AgentConfig(workspace_id=ws_id, user_id=user_id,
                                                 authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT))
            result = await agent.execute({"issue_detected": "missions are not running",
                                          "affected_system": "worker"}, _ctx(db, ws_id, user_id))
            await db.commit()
            return result

    result = _run(run())
    data = result.result_data
    assert result.success, result.output_text
    assert [a["service"] for a in data["actions_taken"] if a["action"] == "restart_service"] == ["worker"]
    assert data["verified_healthy"] is True and data["blocked"] is False
    assert docker.restarts() == ["/containers/bbbbbbbbbbbb/restart"]


@pytest.mark.integration
def test_self_healing_reports_without_acting_when_repairs_are_not_allowed(docker):
    docker.add("bbbbbbbbbbbb", "worker", state="exited", health=None)

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db)
            agent = SelfHealingAgent(AgentConfig(workspace_id=ws_id, user_id=user_id,
                                                 authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT))
            return await agent.execute({"issue_detected": "worker down", "affected_system": "worker",
                                        "auto_fix_enabled": False}, _ctx(db, ws_id, user_id))

    result = _run(run())
    assert result.result_data["actions_taken"] == [] and result.result_data["findings"]
    assert docker.restarts() == []


@pytest.mark.integration
def test_infrastructure_agent_reports_measurements_and_missing_docker_honestly(monkeypatch):
    monkeypatch.setattr(docker_ops, "get_docker_ops", lambda: DockerOps(base_url=""))

    async def run():
        async with AsyncTestingSessionLocal() as db:
            user_id, ws_id = await _seed(db)
            agent = InfrastructureAgent(AgentConfig(workspace_id=ws_id, user_id=user_id,
                                                    authority_level=AuthorityLevel.LEVEL_7_DEPLOYMENT))
            return await agent.execute({"operation": "status"}, _ctx(db, ws_id, user_id))

    result = _run(run())
    data = result.result_data
    assert result.success and data["operation_completed"] is True
    assert "inspect_server" in data["measurements"] and "check_env_vars" in data["measurements"]
    assert data["live_integration_connected"] is False
    assert any("DOCKER_OPS_URL" in item for item in data["limitations"])


def test_runbook_restart_explains_what_is_missing_without_container_operations(monkeypatch):
    from app.core.self_healing.runbooks import IntegrationRequiredError, QueueStuckRunbook, WebsiteDownRunbook

    monkeypatch.setattr(docker_ops, "get_docker_ops", lambda: DockerOps(base_url=""))
    for call in (WebsiteDownRunbook()._restart_application_services, QueueStuckRunbook()._restart_workers):
        with pytest.raises(IntegrationRequiredError, match="DOCKER_OPS_URL"):
            _run(call())


# ----- backups (real PostgreSQL client tools) ------------------------------------------------

@pytest.mark.integration
def test_backup_create_verify_restore_round_trip(tmp_path, monkeypatch):
    if not settings.DATABASE_URL or not make_url(str(settings.DATABASE_URL)).drivername.startswith("postgresql"):
        pytest.skip("backups need DATABASE_URL to point at PostgreSQL")
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    from app.core.ops.backups import _connection, _run as run_client

    async def run():
        async with AsyncTestingSessionLocal() as db:
            ctx = ToolContext(workspace_id=None, db_session=db)
            created = await _tool(CreateBackupTool).execute({"reason": "repair 12d test"}, ctx)
            assert created.success, created.error_message
            backup_id = created.result_data["backup_id"]
            verified = await _tool(VerifyBackupTool).execute({"backup_id": backup_id}, ctx)
            listed = await _tool(ListBackupsTool).execute({}, ctx)
            gated = await _tool(RestoreBackupTool).execute({"backup_id": backup_id}, ctx)
            approved = await _tool(RestoreBackupTool).execute(
                {"backup_id": backup_id}, ToolContext(db_session=db, approved_tools=["restore_backup_with_boundary"]))
            next(tmp_path.glob("*.dump")).write_bytes(b"tampered")
            tampered = await _tool(VerifyBackupTool).execute({"backup_id": backup_id}, ctx)
            await db.commit()
            return created, verified, listed, gated, approved, tampered

    created, verified, listed, gated, approved, tampered = _run(run())
    try:
        assert created.result_data["size_bytes"] > 0 and len(created.result_data["sha256"]) == 64
        assert verified.success and verified.result_data["verified"] is True
        assert verified.result_data["archive_entries"] > 0
        assert created.result_data["backup_id"] in json.dumps(listed.result_data)
        assert gated.success is False
        assert approved.success, approved.error_message
        assert approved.result_data["database"].startswith("jarv_restore_")
        assert tampered.result_data["verified"] is False
        assert tampered.result_data["checksum_matches"] is False
    finally:
        if approved.success:
            args, env, _ = _connection()
            _run(run_client(["dropdb", *args, approved.result_data["database"]], env, timeout=60))


# ----- deployment configuration --------------------------------------------------------------

@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_docker_proxy_is_restricted_and_internal(compose):
    data = yaml.safe_load((ROOT / compose).read_text())
    proxy = data["services"]["docker-proxy"]
    env = {k: str(v) for k, v in proxy["environment"].items()}
    assert proxy["image"].startswith("tecnativa/docker-socket-proxy:") and not proxy["image"].endswith(":latest")
    assert env["POST"] == "0" and env["CONTAINERS"] == "1" and env["ALLOW_RESTARTS"] == "1"
    assert "EXEC" not in env and "IMAGES" not in env and "VOLUMES" not in env
    assert proxy["volumes"] == ["/var/run/docker.sock:/var/run/docker.sock:ro"]
    assert proxy["networks"] == ["jarv-ops"] and "ports" not in proxy
    assert data["networks"]["jarv-ops"]["internal"] is True
    for service in ("backend", "worker"):
        spec = data["services"][service]
        assert "jarv-ops" in spec["networks"]
        assert spec["environment"]["DOCKER_OPS_URL"] == "http://docker-proxy:2375"
        assert "backups:/data/backups" in spec["volumes"]
    for service, spec in data["services"].items():
        if service not in ("backend", "worker", "docker-proxy"):
            assert "jarv-ops" not in (spec.get("networks") or []), service
            assert "docker.sock" not in json.dumps(spec.get("volumes") or []), service


# ----- operations API -------------------------------------------------------------------------

@pytest.mark.api
def test_operations_api_requires_authentication(client):
    for method, path in (("get", "/api/operations/health"), ("get", "/api/operations/containers"),
                         ("get", "/api/operations/backups"), ("post", "/api/operations/backups")):
        assert getattr(client, method)(path).status_code == 401, path


@pytest.mark.api
def test_operations_api_reports_live_state_and_restarts_through_the_adapter(client, docker, monkeypatch, tmp_path):
    from app.core.auth import get_current_user_id
    from app.main import app

    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    docker.add("aaaaaaaaaaaa", "backend")
    docker.add("bbbbbbbbbbbb", "worker", state="exited", health=None)
    docker.add("dddddddddddd", "postgres", state="exited", health=None)
    app.dependency_overrides[get_current_user_id] = lambda: "admin_richard"

    health = client.get("/api/operations/health")
    server = client.get("/api/operations/server")
    listed = client.get("/api/operations/containers")
    restarted = client.post("/api/operations/services/worker/restart", json={"reason": "worker exited"})
    refused = client.post("/api/operations/services/postgres/restart", json={"reason": "postgres exited"})
    backups = client.get("/api/operations/backups")

    assert health.status_code == 200 and "database" in health.json()["checks"]
    assert server.status_code == 200 and server.json()["disks"]
    body = listed.json()
    assert body["available"] is True
    assert {c["service"]: c["restartable"] for c in body["containers"]} == {
        "backend": True, "postgres": False, "worker": True}
    assert restarted.status_code == 200 and restarted.json()["containers"]
    assert refused.status_code == 403
    assert docker.restarts() == ["/containers/bbbbbbbbbbbb/restart"]
    assert backups.status_code == 200 and isinstance(backups.json()["backups"], list)


def test_restore_ignores_only_unknown_session_settings_from_a_newer_pg_dump():
    from app.core.ops.backups import _ignorable_restore_errors

    benign = ('pg_restore: error: could not execute query: ERROR:  unrecognized configuration parameter '
              '"transaction_timeout"\nCommand was: SET transaction_timeout = 0;\n'
              'pg_restore: warning: errors ignored on restore: 1\n')
    real = benign.replace('unrecognized configuration parameter "transaction_timeout"',
                          'relation "public.tasks" does not exist')
    assert _ignorable_restore_errors(benign) == ["transaction_timeout"]
    assert _ignorable_restore_errors(real) == []
    assert _ignorable_restore_errors(benign + benign.splitlines()[0] + "\n") == []
