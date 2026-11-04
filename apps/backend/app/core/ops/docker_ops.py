"""
JAI Backend - Container operations

Lets JAI inspect and restart its own services, which is what turns
self-healing from "alert" into "fix". It talks to the Docker Engine API
through a restricted socket proxy (``docker-proxy`` in the compose files),
never to the raw Docker socket.

What this adapter will do, and nothing else:
- list, inspect, and read logs of containers in JAI's own Compose project;
- restart a container in that project whose service is in RESTARTABLE,
  never the container making the request (it would die mid-operation).
  With replicas, only the unhealthy containers of the service are restarted.

Data stores (postgres, redis) are never restarted from here. Log output is
secret-redacted before it is returned. When ``DOCKER_OPS_URL`` is not set the
adapter reports itself unavailable instead of failing obscurely.
"""
from __future__ import annotations

import json
import logging
import os
import socket
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from app.core.security import redact_text

logger = logging.getLogger(__name__)

RESTARTABLE = frozenset({"backend", "worker", "scheduler", "dashboard", "local-runner", "cloud-runner",
                         "voicebox", "prometheus", "grafana", "alertmanager"})
NEVER_RESTART = frozenset({"postgres", "redis", "docker-proxy"})
# Services JAI runs without: switched on by a compose profile or the monitoring file, or only for local
# development. One not running is reported as such, never as JAI being degraded.
OPTIONAL_SERVICES = frozenset({"voicebox", "prometheus", "grafana", "alertmanager", "postgres-exporter",
                               "redis-exporter", "node-exporter", "local-runner", "cloud-runner",
                               # Waves 2-6: each switched on by its own profile, and the heavy ones switched off by
                               # Richard from the Command Center to share the memory; JAI is not degraded by one off.
                               "voice", "chatterbox", "comfyui", "moneyprinter", "postiz", "temporal", "searxng",
                               "crawl4ai", "serena", "docling", "browser", "knowledge", "promptfoo"})
# Services Richard switches on and off from the Command Center to share the computer's memory (Wave 6): heavy, and
# JAI works without each of them (it says which one to switch on when a task needs it). Name -> what it is.
SWITCHABLE = {
    "comfyui": ("Image generator", "FLUX.1-schnell on the GPU; about 7 GB of memory while it works"),
    "chatterbox": ("Natural voice", "Chatterbox in George's voice; Kokoro speaks when it is off"),
    "moneyprinter": ("Video maker", "MoneyPrinterTurbo; up to 3 GB while rendering"),
    "docling": ("Document reader", "Docling for PDFs, Word, PowerPoint and scans; up to 3 GB"),
    "browser": ("Browser", "browser-use with Chromium, for clicking through sites"),
    "serena": ("Code understanding", "Serena's language servers; up to 2 GB"),
}
# How long a switched-off service gets to close down before Docker stops it outright.
STOP_GRACE_SECONDS = 15
# Jobs that run once and exit (database migrations): exited with code 0 is their finished state.
ONE_SHOT_SERVICES = frozenset({"migrate"})


def container_problem(container: "Container") -> Optional[str]:
    """Why a container counts against JAI's health, or None when it is where it should be."""
    if container.service in ONE_SHOT_SERVICES:
        return None if container.state == "running" or "Exited (0)" in container.status else (
            f"{container.service} did not finish cleanly ({container.status})")
    if container.state != "running":
        return f"{container.service} is {container.state or 'not running'}"
    if container.health == "unhealthy":
        return f"{container.service} is unhealthy"
    return None
_PROJECT_LABEL = "com.docker.compose.project"
_SERVICE_LABEL = "com.docker.compose.service"
_MAX_LOG_LINES = 400


class OpsUnavailable(RuntimeError):
    """Container operations are not configured or the proxy cannot be reached."""


class OpsRefused(PermissionError):
    """The requested container operation is outside what JAI may do."""


@dataclass
class Container:
    id: str
    name: str
    service: str
    state: str
    status: str
    health: Optional[str]
    restart_count: Optional[int]
    image: str

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def ops_url() -> Optional[str]:
    from app.core.config import settings

    value = (os.getenv("DOCKER_OPS_URL") or getattr(settings, "DOCKER_OPS_URL", "") or "").strip()
    return value.rstrip("/") or None


class DockerOps:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.base_url = base_url or ops_url()
        self.timeout = timeout
        self.transport = transport
        self._project: Optional[str] = None

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self.base_url:
            raise OpsUnavailable("Container operations are not configured (DOCKER_OPS_URL is not set).")
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout,
                                         transport=self.transport) as client:
                response = await client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise OpsUnavailable(f"Docker proxy unreachable: {exc}") from exc
        if response.status_code == 403:
            raise OpsRefused("The Docker proxy refused this operation.")
        return response

    async def project(self) -> str:
        """The Compose project this process runs in (read from its own container)."""
        if self._project:
            return self._project
        configured = os.getenv("COMPOSE_PROJECT_NAME")
        if configured:
            self._project = configured
            return configured
        response = await self._request("GET", f"/containers/{socket.gethostname()}/json")
        if response.status_code != 200:
            raise OpsUnavailable("Cannot determine this service's Compose project.")
        project = (response.json().get("Config", {}).get("Labels") or {}).get(_PROJECT_LABEL)
        if not project:
            raise OpsUnavailable("This process is not running under Docker Compose.")
        self._project = project
        return project

    async def containers(self) -> List[Container]:
        project = await self.project()
        response = await self._request("GET", "/containers/json", params={
            "all": "true", "filters": json.dumps({"label": [f"{_PROJECT_LABEL}={project}"]})})
        response.raise_for_status()
        found: List[Container] = []
        for item in response.json():
            labels = item.get("Labels") or {}
            status = item.get("Status") or ""
            health = None
            for word in ("healthy", "unhealthy", "starting"):
                if f"({word}" in status:
                    health = word
                    break
            found.append(Container(
                id=item.get("Id", "")[:12], name=(item.get("Names") or ["?"])[0].lstrip("/"),
                service=labels.get(_SERVICE_LABEL, ""), state=item.get("State", ""), status=status,
                health=health, restart_count=None, image=item.get("Image", ""),
            ))
        return sorted(found, key=lambda c: c.service)

    async def _resolve(self, service: str) -> Container:
        service = (service or "").strip().lower()
        for container in await self.containers():
            if container.service == service or container.name == service:
                return container
        raise OpsRefused(f"No container for service '{service}' in this JAI project.")

    async def inspect(self, service: str) -> Dict[str, Any]:
        container = await self._resolve(service)
        response = await self._request("GET", f"/containers/{container.id}/json")
        response.raise_for_status()
        data = response.json()
        state = data.get("State") or {}
        return {**container.as_dict(), "restart_count": data.get("RestartCount"),
                "started_at": state.get("StartedAt"), "exit_code": state.get("ExitCode"),
                "oom_killed": state.get("OOMKilled"),
                "health_log": [h.get("Output", "")[-300:] for h in (state.get("Health") or {}).get("Log", [])[-3:]]}

    async def logs(self, service: str, lines: int = 100) -> str:
        container = await self._resolve(service)
        lines = max(1, min(int(lines), _MAX_LOG_LINES))
        response = await self._request("GET", f"/containers/{container.id}/logs", params={
            "stdout": "true", "stderr": "true", "tail": str(lines), "timestamps": "true"})
        response.raise_for_status()
        return redact_text(_demux(response.content))

    async def restart(self, service: str, timeout_seconds: int = 20) -> Dict[str, Any]:
        """Restart a service's containers. With replicas, only the unhealthy ones
        (or all of them when none is marked unhealthy); never this process's own."""
        service = (service or "").strip().lower()
        matches = [c for c in await self.containers() if service in (c.service, c.name)]
        if not matches:
            raise OpsRefused(f"No container for service '{service}' in this JAI project.")
        name = matches[0].service
        if name in NEVER_RESTART or name not in RESTARTABLE:
            raise OpsRefused(f"JAI does not restart '{name}' automatically.")
        own = socket.gethostname()
        others = [c for c in matches if not (c.id and own.startswith(c.id))]
        if not others:
            raise OpsRefused(f"'{name}' is the container running this request; "
                             "another JAI service (API or worker) must restart it.")
        broken = [c for c in others if c.state != "running" or c.health == "unhealthy"]
        targets = broken or others
        restarted: List[str] = []
        for container in targets:
            response = await self._request("POST", f"/containers/{container.id}/restart",
                                           params={"t": str(max(1, min(timeout_seconds, 120)))})
            if response.status_code not in (204, 200):
                raise OpsUnavailable(f"Restart of {container.name} failed: HTTP {response.status_code}")
            logger.warning(f"Restarted service {name} ({container.name})")
            restarted.append(container.name)
        return {"service": name, "containers": restarted, "container": restarted[0], "restarted": True}


    async def switches(self) -> List[Dict[str, Any]]:
        """Each switchable service: whether it is on, as the Command Center shows it."""
        found = {c.service: c for c in await self.containers()}
        out = []
        for service, (label, about) in SWITCHABLE.items():
            container = found.get(service)
            out.append({"service": service, "label": label, "about": about, "installed": container is not None,
                        "on": bool(container and container.state == "running"),
                        "status": container.status if container else "not installed"})
        return out

    async def switch(self, service: str, on: bool) -> Dict[str, Any]:
        """Start or stop one of the SWITCHABLE services, and nothing else."""
        service = (service or "").strip().lower()
        if service not in SWITCHABLE:
            raise OpsRefused(f"'{service}' is not one of the services switched on and off from the Command Center.")
        matches = [c for c in await self.containers() if c.service == service]
        if not matches:
            raise OpsRefused(f"{SWITCHABLE[service][0]} is not installed on this computer.")
        changed: List[str] = []
        for container in matches:
            if (container.state == "running") == on:
                continue
            # Docker answers a stop only when the container has exited: up to STOP_GRACE_SECONDS for it to close
            # down, then it is killed. The request waits that long and more (a 10-second wait made every switch-off
            # of the video maker and image generator report a failure while they were still closing down).
            response = await self._request("POST", f"/containers/{container.id}/{'start' if on else 'stop'}",
                                           params={} if on else {"t": str(STOP_GRACE_SECONDS)},
                                           timeout=httpx.Timeout(STOP_GRACE_SECONDS + 50.0, connect=5.0))
            if response.status_code not in (204, 304, 200):
                raise OpsUnavailable(f"{'Starting' if on else 'Stopping'} {container.name} failed: "
                                     f"HTTP {response.status_code}")
            changed.append(container.name)
        logger.warning(f"Switched {service} {'on' if on else 'off'} ({', '.join(changed) or 'already so'})")
        return {"service": service, "label": SWITCHABLE[service][0], "on": on, "changed": changed}


def _demux(raw: bytes) -> str:
    """Decode Docker's multiplexed log stream (8-byte frame headers) or plain text."""
    out: List[str] = []
    i = 0
    framed = len(raw) >= 8 and raw[0] in (0, 1, 2) and raw[1:4] == b"\x00\x00\x00"
    if not framed:
        return raw.decode("utf-8", errors="replace")
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4:i + 8], "big")
        out.append(raw[i + 8:i + 8 + size].decode("utf-8", errors="replace"))
        i += 8 + size
    return "".join(out)


def get_docker_ops() -> DockerOps:
    return DockerOps()
