"""
Richard switches JAI's heavy services (the image generator, natural voice, video maker, document reader, browser and
code understanding) on and off from the Command Center, to share the computer's memory. Real: the Docker ops
adapter's start and stop requests (against the Docker Engine double), the refusal of every other container, the API
and its audit record, and the proxy allowing start and stop.
"""
import asyncio

import httpx
import pytest
import yaml

from app.core.ops import docker_ops
from tests.repo_paths import repo_path
from tests.test_repair12d_ops_tools import FakeDocker


class SwitchingDocker(FakeDocker):
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and (path.endswith("/start") or path.endswith("/stop")):
            self.requests.append((request.method, path, dict(request.url.params)))
            c = self.containers[path.split("/")[2][:12]]
            c["state"] = "running" if path.endswith("/start") else "exited"
            return httpx.Response(204)
        return super().handler(request)


@pytest.fixture
def docker(monkeypatch):
    fake = SwitchingDocker()
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", fake.project)
    monkeypatch.setattr(docker_ops, "get_docker_ops", fake.ops)
    fake.add("aaaaaaaaaaaa", "comfyui", state="exited", health=None, exit_code=0)
    fake.add("bbbbbbbbbbbb", "chatterbox")
    fake.add("cccccccccccc", "postgres")
    fake.add("dddddddddddd", "backend")
    return fake


def test_the_image_generator_is_switched_on_and_off(docker):
    ops = docker.ops()
    listed = {s["service"]: s for s in asyncio.run(ops.switches())}
    assert listed["comfyui"]["on"] is False and listed["comfyui"]["label"] == "Image generator"
    assert listed["chatterbox"]["on"] is True and listed["docling"]["installed"] is False
    assert asyncio.run(ops.switch("comfyui", True))["changed"]
    assert {s["service"]: s for s in asyncio.run(ops.switches())}["comfyui"]["on"] is True
    assert asyncio.run(ops.switch("comfyui", True))["changed"] == []  # already on: nothing sent
    asyncio.run(ops.switch("comfyui", False))
    posts = [p for m, p, _ in docker.requests if m == "POST"]
    assert posts == ["/containers/aaaaaaaaaaaa" + "f" * 52 + "/start", "/containers/aaaaaaaaaaaa" + "f" * 52 + "/stop"]


@pytest.mark.parametrize("service", ["postgres", "backend", "redis", "docker-proxy", "anything"])
def test_nothing_else_can_be_switched(docker, service):
    with pytest.raises(docker_ops.OpsRefused):
        asyncio.run(docker.ops().switch(service, False))
    assert not [r for r in docker.requests if r[0] == "POST"]


def test_a_service_that_is_not_installed_is_reported(docker):
    with pytest.raises(docker_ops.OpsRefused, match="not installed"):
        asyncio.run(docker.ops().switch("docling", True))


def test_the_command_center_switch_is_audited(docker, client):
    listed = client.get("/api/operations/switches").json()
    assert listed["available"] is True and listed["memory_total_gb"] > 0
    assert [s["service"] for s in listed["switches"]] == list(docker_ops.SWITCHABLE)
    switched = client.post("/api/operations/switches/comfyui", json={"on": True})
    assert switched.status_code == 200 and switched.json()["on"] is True
    assert client.post("/api/operations/switches/postgres", json={"on": False}).status_code == 403


def test_the_proxy_allows_start_and_stop_and_still_no_general_post():
    env = {k: str(v) for k, v in yaml.safe_load(repo_path("docker-compose.yml").read_text())["services"]
           ["docker-proxy"]["environment"].items()}
    assert env["ALLOW_START"] == "1" and env["ALLOW_STOP"] == "1" and env["POST"] == "0"


def test_switched_off_services_never_make_jai_degraded():
    for service in docker_ops.SWITCHABLE:
        assert service in docker_ops.OPTIONAL_SERVICES, service
    for core in ("backend", "worker", "postgres", "redis", "dashboard", "scheduler"):
        assert core not in docker_ops.OPTIONAL_SERVICES


def test_jai_knows_its_recent_upgrades_from_the_repository_history(tmp_path, monkeypatch):
    import subprocess

    from app.core import upgrades
    from app.core.config import settings

    repo = tmp_path / "jai"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("-c", "user.email=r@jai", "-c", "user.name=Richard", "commit", "-q", "--allow-empty", "-m",
        "Wave 6: documents, a real browser, knowledge graph and memory")
    run("-c", "user.email=r@jai", "-c", "user.name=Richard", "commit", "-q", "--allow-empty", "-m",
        "JAI's services panel: switch the image generator on and off")
    monkeypatch.setattr(settings, "JAI_REPO_GIT", str(repo / ".git"))
    found = asyncio.run(upgrades.recent(3, 15))
    assert [f["what"] for f in found] == ["JAI's services panel: switch the image generator on and off",
                                          "Wave 6: documents, a real browser, knowledge graph and memory"]
    assert found[0]["when"][:4].isdigit()
    monkeypatch.setattr(settings, "JAI_REPO_GIT", str(tmp_path / "missing"))
    assert asyncio.run(upgrades.recent()) == []
