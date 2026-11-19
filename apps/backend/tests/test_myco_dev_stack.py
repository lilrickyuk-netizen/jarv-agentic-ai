"""
19 November: MYCO's local development stack (MYCO spec v3.2 Phase 2, local-development mapping). Official images pinned
to the spec's dependency baseline, on a private network with no route out and no port published, reached by JAI's
engineering sandbox by name only; switched on and off together from the Command Center; restarted and rehearsed
(point-in-time recovery) by JAI's specialists through the dev_services tool, which touches nothing but the stack.
Real: the compose file and scripts as committed, the Docker ops adapter against the Docker Engine double, the
permission policy. Nothing runs and nothing is spent.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
import yaml

from app.core.ops import docker_ops
from tests.repo_paths import repo_path
from tests.test_repair12d_ops_tools import FakeDocker

STACK = docker_ops.MYCO_DEV_STACK


def _compose():
    return yaml.safe_load(repo_path("docker-compose.yml").read_text())


def test_the_stack_is_pinned_to_the_specs_baseline_and_locked_down():
    compose = _compose()
    services = compose["services"]
    images = {name: services[name].get("image", "") for name in STACK + (docker_ops.MYCO_PITR,)}
    assert images["myco-postgres"].endswith(":-postgres:18.6}") and images["myco-pitr"] == images["myco-postgres"]
    assert images["myco-redis"].endswith(":-redis:8.10.1}")
    assert images["myco-neo4j"].endswith(":-neo4j:2026.08.1}")
    assert images["myco-otel"].endswith(":-otel/opentelemetry-collector-contrib:0.161.0}")
    assert ":latest" not in images["myco-redpanda"] and ":latest" not in images["myco-temporal"]
    for name in STACK + (docker_ops.MYCO_PITR,):
        service = services[name]
        assert service["profiles"] == ["myco"], name
        assert service["networks"] == ["myco-dev"], name     # nothing else, so no route to JAI or the internet
        assert "ports" not in service, name                  # reached by name on the private network only
        assert service.get("mem_limit"), name
        assert not service.get("privileged"), name
    assert compose["networks"]["myco-dev"] == {"driver": "bridge", "internal": True}
    # The sandbox reaches the stack over the network, with the connection settings in its login shell.
    openhands = services["openhands"]
    assert "myco-dev" in openhands["networks"]
    mounts = [m for m in openhands["volumes"] if isinstance(m, str)]
    assert "./infra/myco-dev/sandbox-profile.sh:/etc/profile.d/myco-dev.sh:ro" in mounts
    assert "./infra/myco-dev/connection.env:/etc/myco-dev.env:ro" in mounts
    assert "infra/myco-dev/connection.env" in repo_path(".gitignore").read_text()


def test_postgres_archives_its_wal_and_keeps_the_three_authorities_apart():
    postgres = _compose()["services"]["myco-postgres"]
    command = " ".join(postgres["command"])
    assert "archive_mode=on" in command and "/wal-archive/%f" in command and "wal_level=replica" in command
    init = repo_path("infra", "myco-dev", "postgres", "10-myco-databases.sh").read_text()
    for database, owner in (("keycloak", "keycloak"), ("myco_global", "myco_global"),
                            ("myco_cell_local_c0001", "myco_cell_c0001")):
        assert f"CREATE DATABASE {database} OWNER {owner};" in init
        assert f"REVOKE ALL ON DATABASE {database} FROM PUBLIC;" in init
    # Function rights are per database: the WAL switch is granted where the rehearsal calls it.
    assert init.index("\\connect myco_pitr_rehearsal") < init.index("GRANT EXECUTE ON FUNCTION pg_switch_wal()")
    assert "PASSWORD '" not in init  # passwords come from the environment, never the file
    rehearsal = repo_path("infra", "myco-dev", "postgres", "pitr-rehearsal.sh").read_text()
    assert "recovery_target_time" in rehearsal and '"before-backup,kept"' in rehearsal
    assert "PITR REHEARSAL PASS" in rehearsal


def test_pgbouncer_is_built_from_the_postgres_projects_repository_at_an_exact_release():
    dockerfile = repo_path("services", "myco-pgbouncer", "Dockerfile").read_text()
    assert "ARG PGBOUNCER_VERSION=1.26.1" in dockerfile and "apt-cache madison pgbouncer" in dockerfile
    assert "USER postgres" in dockerfile
    entry = repo_path("services", "myco-pgbouncer", "entrypoint.sh").read_text()
    assert "umask 077" in entry and "/tmp/userlist.txt" in entry


class StackDocker(FakeDocker):
    """The Docker double with start and stop, and a PITR rehearsal container that exits with a verdict."""

    def __init__(self, verdict=0, log=b"PITR REHEARSAL PASS: restored\n"):
        super().__init__()
        self.verdict, self.log = verdict, log

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        cid = path.split("/")[2][:12] if path.startswith("/containers/") and path != "/containers/json" else ""
        c = self.containers.get(cid)
        if request.method == "POST" and (path.endswith("/start") or path.endswith("/stop")) and c is not None:
            self.requests.append((request.method, path, dict(request.url.params)))
            starting = path.endswith("/start")
            if c["service"] == docker_ops.MYCO_PITR and starting:
                c["state"], c["exit_code"] = "exited", self.verdict  # the rehearsal runs and exits
            else:
                c["state"] = "running" if starting else "exited"
            return httpx.Response(204)
        if c is not None and c["service"] == docker_ops.MYCO_PITR:
            if path.endswith("/json"):
                self.requests.append((request.method, path, {}))
                return httpx.Response(200, json={"State": {"Running": c["state"] == "running",
                                                           "ExitCode": c["exit_code"]}})
            if path.endswith("/logs"):
                return httpx.Response(200, content=b"\x01\x00\x00\x00" + len(self.log).to_bytes(4, "big") + self.log)
        return super().handler(request)


def _stack(monkeypatch, state="running", **kwargs):
    fake = StackDocker(**kwargs)
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", fake.project)
    monkeypatch.setattr(docker_ops, "get_docker_ops", fake.ops)
    for i, service in enumerate(STACK):
        fake.add(f"{i:012d}", service, state=state, health=None)
    fake.add("999999999999", docker_ops.MYCO_PITR, state="exited", health=None, exit_code=0)
    fake.add("aaaaaaaaaaaa", "postgres")
    fake.add("bbbbbbbbbbbb", "backend")
    return fake


def _posts(fake):
    names = {cid: c["service"] for cid, c in fake.containers.items()}
    return [(p.rsplit("/", 1)[1], names[p.split("/")[2][:12]]) for m, p, _ in fake.requests if m == "POST"]


def test_the_command_center_switches_the_whole_stack_in_order(monkeypatch):
    fake = _stack(monkeypatch, state="exited")
    ops = fake.ops()
    listed = {s["service"]: s for s in asyncio.run(ops.switches())}
    assert listed["myco"]["label"] == "MYCO dev stack" and listed["myco"]["installed"] is True
    assert listed["myco"]["on"] is False and listed["myco"]["status"] == "0 of 8 running"
    asyncio.run(ops.switch("myco", True))
    started = _posts(fake)
    assert started[0] == ("start", "myco-postgres")  # the database first, then the rest together
    assert sorted(started) == sorted(("start", name) for name in STACK)
    assert {s["service"]: s for s in asyncio.run(ops.switches())}["myco"]["on"] is True
    fake.requests.clear()
    asyncio.run(ops.switch("myco", False))
    assert sorted(_posts(fake)) == sorted(("stop", name) for name in STACK)
    # The rehearsal and JAI's own services are never part of the switch.
    assert all(service not in ("myco-pitr", "postgres", "backend") for _, service in _posts(fake))


def test_the_switch_reports_the_stack_not_installed(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", fake.project)
    fake.add("aaaaaaaaaaaa", "postgres")
    listed = {s["service"]: s for s in asyncio.run(fake.ops().switches())}
    assert listed["myco"]["installed"] is False and listed["myco"]["status"] == "not installed"
    with pytest.raises(docker_ops.OpsRefused, match="not installed"):
        asyncio.run(fake.ops().switch("myco", True))


def test_specialists_restart_only_the_stacks_services(monkeypatch):
    fake = _stack(monkeypatch)
    ops = fake.ops()
    assert asyncio.run(ops.dev_restart("myco-postgres"))["restarted"] == ["myco-postgres"]
    for other in ("postgres", "backend", "redis", "docker-proxy", "myco-pitr", "comfyui"):
        with pytest.raises(docker_ops.OpsRefused):
            asyncio.run(ops.dev_restart(other))
    restarted = [p for m, p, _ in fake.requests if m == "POST"]
    assert restarted == ["/containers/000000000000/restart"]
    fake.requests.clear()
    result = asyncio.run(ops.dev_restart("all"))
    assert result["restarted"] == list(STACK)
    assert _posts(fake) == [("stop", n) for n in reversed(STACK)] + [("start", n) for n in STACK]


def test_the_pitr_rehearsal_gives_its_verdict(monkeypatch):
    fake = _stack(monkeypatch)
    passed = asyncio.run(fake.ops().dev_pitr_rehearsal(poll_seconds=0))
    assert passed["passed"] is True and passed["exit_code"] == 0 and "PITR REHEARSAL PASS" in passed["log"]
    failing = _stack(monkeypatch, verdict=1, log=b"PITR REHEARSAL FAIL: restored rows were 'x'\n")
    failed = asyncio.run(failing.ops().dev_pitr_rehearsal(poll_seconds=0))
    assert failed["passed"] is False and failed["exit_code"] == 1 and "FAIL" in failed["log"]


def test_the_stack_never_counts_against_jais_health(monkeypatch):
    for name in STACK + (docker_ops.MYCO_PITR,):
        assert name in docker_ops.OPTIONAL_SERVICES
        assert name not in docker_ops.RESTARTABLE  # JAI's self-healing never restarts them on its own
    rehearsal = docker_ops.Container(id="9", name="myco-pitr", service="myco-pitr", state="exited",
                                     status="Exited (0) 1 minute ago", health=None, restart_count=None, image="x")
    assert docker_ops.container_problem(rehearsal) is None


def test_dev_services_is_build_and_test_authority_and_an_mcp_tool():
    from app.api.v1.agent_tools import ADDS, JAI_TOOLS
    from app.core.agents.toolbox import WORKSPACE_TOOLS
    from app.core.command.tool_runtime import _TOOL_AUTHORITY
    from app.core.safety.permission_policy import check_tool_permission

    assert "dev_services" in WORKSPACE_TOOLS and "dev_services" in JAI_TOOLS and "dev_services" not in ADDS
    assert _TOOL_AUTHORITY["dev_services"] == 3
    content = "MYCO dev stack restart myco-postgres"
    assert check_tool_permission(tool_id="dev_services", content=content, authority_level=3).allowed is True
    assert check_tool_permission(tool_id="dev_services", content=content, authority_level=2).allowed is False


def test_dev_services_reports_and_records_every_call(monkeypatch):
    from app.core.command.tool_runtime import ToolRuntime

    fake = _stack(monkeypatch)
    recorded = []

    async def allow(*_args, **_kwargs):
        return None

    async def record(tool, inputs, ok, summary, output=None):
        recorded.append((tool, inputs, ok, summary))

    runtime = SimpleNamespace(_enforce=allow, _record=record)
    status = asyncio.run(ToolRuntime.dev_services(runtime, "status"))
    assert status["success"] is True and status["all_running"] is True
    restarted = asyncio.run(ToolRuntime.dev_services(runtime, "restart", "myco-redis"))
    assert restarted["success"] is True and restarted["restarted"] == ["myco-redis"]
    refused = asyncio.run(ToolRuntime.dev_services(runtime, "restart", "backend"))
    assert refused["success"] is False and "not one of MYCO's dev-stack services" in refused["error"]
    assert asyncio.run(ToolRuntime.dev_services(runtime, "restart"))["success"] is False
    assert asyncio.run(ToolRuntime.dev_services(runtime, "delete"))["success"] is False
    assert [r[2] for r in recorded] == [True, True, False]
    assert fake.containers["bbbbbbbbbbbb"]["restarts"] == 0  # JAI's backend was never touched
