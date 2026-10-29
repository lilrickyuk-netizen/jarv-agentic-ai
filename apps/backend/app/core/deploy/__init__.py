"""
JARV Backend - Deployments to Richard's VPS (Repair 12e-2)

How a workspace project reaches a server:

1. Package: ``git archive HEAD`` of the workspace repository. Only committed
   code ships; a dirty working tree is refused so a release always matches a
   commit.
2. Upload over SSH into ``<base>/<app>-<env>/releases/<release id>`` and link
   the server-side ``shared/.env`` into it (secrets live on the server, never
   in the repository or in JARV).
3. ``docker compose -p <app>-<env> up -d --build --remove-orphans`` in the
   release directory.
4. Health check. Success moves the ``current`` link to the new release and
   prunes old releases (the newest ``KEEP_RELEASES`` are kept). Failure brings
   the previous release back up automatically and the deployment is recorded
   as failed and rolled back.

Staging and production are separate Compose projects on the same server.
Rollback returns to the release before ``current`` (or a named one) and is
health-checked the same way.

The SSH private key and the server's host key come from settings
(``DEPLOY_SSH_PRIVATE_KEY`` base64, ``DEPLOY_SSH_KNOWN_HOSTS``). The key is
written to a private temporary file only for the duration of a command, and
the host key is pinned (StrictHostKeyChecking=yes), so JARV never connects to
a server it has not been told to trust. Every remote argument is shell-quoted.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shlex
import stat
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.security import redact_text

logger = logging.getLogger(__name__)

ENVIRONMENTS = ("staging", "production")
KEEP_RELEASES = 5
_APP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_RELEASE_RE = re.compile(r"^\d{8}T\d{9}Z-[0-9a-f]{7,12}$")
_MAX_ARCHIVE_BYTES = 300 * 1024 * 1024


class DeployError(RuntimeError):
    """A deployment step failed; the message says which and why."""


class DeployNotConfigured(DeployError):
    """No deployment server is configured."""


# ----- target -----------------------------------------------------------------------------

@dataclass
class DeployTarget:
    host: str
    user: str
    port: int
    base_dir: str
    private_key: str
    known_hosts: str
    compose: str = "docker compose"

    @property
    def address(self) -> str:
        return f"{self.user}@{self.host}"


def target_status() -> Dict[str, Any]:
    """Which deployment settings are present (names only, never values)."""
    fields = {
        "DEPLOY_SSH_HOST": bool(settings.DEPLOY_SSH_HOST),
        "DEPLOY_SSH_USER": bool(settings.DEPLOY_SSH_USER),
        "DEPLOY_SSH_PRIVATE_KEY": bool(settings.DEPLOY_SSH_PRIVATE_KEY),
        "DEPLOY_SSH_KNOWN_HOSTS": bool(settings.DEPLOY_SSH_KNOWN_HOSTS),
    }
    missing = [name for name, present in fields.items() if not present]
    return {"configured": not missing, "missing": missing, "host": settings.DEPLOY_SSH_HOST or None,
            "base_dir": settings.DEPLOY_BASE_DIR}


def load_target() -> DeployTarget:
    status = target_status()
    if not status["configured"]:
        raise DeployNotConfigured(
            "No deployment server is configured. Missing: " + ", ".join(status["missing"])
            + ". See docs/DEPLOYMENT.md for the one-time server setup.")
    try:
        key = base64.b64decode(settings.DEPLOY_SSH_PRIVATE_KEY, validate=True).decode()
    except Exception as exc:  # noqa: BLE001
        raise DeployNotConfigured("DEPLOY_SSH_PRIVATE_KEY must be the base64 of the private key file.") from exc
    if "PRIVATE KEY" not in key:
        raise DeployNotConfigured("DEPLOY_SSH_PRIVATE_KEY does not contain a private key.")
    return DeployTarget(host=settings.DEPLOY_SSH_HOST, user=settings.DEPLOY_SSH_USER,
                        port=int(settings.DEPLOY_SSH_PORT), base_dir=settings.DEPLOY_BASE_DIR.rstrip("/"),
                        private_key=key if key.endswith("\n") else key + "\n",
                        known_hosts=settings.DEPLOY_SSH_KNOWN_HOSTS.strip() + "\n",
                        compose=settings.DEPLOY_COMPOSE_COMMAND or "docker compose")


# ----- shells -------------------------------------------------------------------------------

class Shell(Protocol):
    async def run(self, command: str, *, stdin: Optional[bytes] = None,
                  timeout: int = 600) -> Tuple[int, str, str]:
        ...


class SshShell:
    """Runs one command on the deployment server over SSH with a pinned host key."""

    def __init__(self, target: DeployTarget):
        self.target = target

    async def run(self, command: str, *, stdin: Optional[bytes] = None,
                  timeout: int = 600) -> Tuple[int, str, str]:
        with tempfile.TemporaryDirectory(prefix="jarv-ssh-") as folder:
            key = Path(folder) / "id"
            hosts = Path(folder) / "known_hosts"
            key.write_text(self.target.private_key)
            hosts.write_text(self.target.known_hosts)
            os.chmod(key, stat.S_IRUSR | stat.S_IWUSR)
            argv = ["ssh", "-i", str(key), "-p", str(self.target.port),
                    "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                    "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={hosts}",
                    "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
                    self.target.address, "--", command]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            except FileNotFoundError as exc:
                raise DeployError("The ssh client is not installed in this container.") from exc
            try:
                out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                raise DeployError(f"Remote command timed out after {timeout}s")
        return proc.returncode, out.decode(errors="replace"), redact_text(err.decode(errors="replace"))


def remote_shell() -> Shell:
    return SshShell(load_target())


# ----- packaging ----------------------------------------------------------------------------

async def _local(argv: List[str], cwd: Path, timeout: int = 300) -> Tuple[int, bytes, str]:
    proc = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise DeployError(f"{argv[0]} timed out")
    return proc.returncode, out, err.decode(errors="replace")


@dataclass
class Package:
    archive: bytes
    commit: str
    branch: Optional[str]
    release_id: str


async def package_workspace(root: Path) -> Package:
    """A gzipped tar of the committed tree at HEAD."""
    if not (root / ".git").exists():
        raise DeployError(f"{root} is not a git repository; commit the project before deploying.")
    git = ["git", "-c", f"safe.directory={root}"]
    code, out, err = await _local(git + ["rev-parse", "HEAD"], root)
    if code != 0:
        raise DeployError(f"Cannot read the current commit: {err.strip()[:300]}")
    commit = out.decode().strip()
    code, out, err = await _local(git + ["status", "--porcelain", "--untracked-files=no"], root)
    if code != 0:
        raise DeployError(f"git status failed: {err.strip()[:300]}")
    if out.strip():
        raise DeployError("The workspace has uncommitted changes. Commit them first: a release must "
                          "match a commit so it can be reproduced and rolled back.")
    _, branch_out, _ = await _local(git + ["rev-parse", "--abbrev-ref", "HEAD"], root)
    code, archive, err = await _local(git + ["archive", "--format=tar.gz", "HEAD"], root)
    if code != 0:
        raise DeployError(f"git archive failed: {err.strip()[:300]}")
    if len(archive) > _MAX_ARCHIVE_BYTES:
        raise DeployError(f"The release archive is {len(archive) // 1_000_000} MB; the limit is "
                          f"{_MAX_ARCHIVE_BYTES // 1_000_000} MB. Keep build outputs out of git.")
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond // 1000:03d}Z"  # sortable, millisecond resolution
    return Package(archive=archive, commit=commit, branch=branch_out.decode().strip() or None,
                   release_id=f"{stamp}-{commit[:10]}")


# ----- deployer ---------------------------------------------------------------------------

@dataclass
class DeployResult:
    success: bool
    app: str
    environment: str
    release: Optional[str]
    previous: Optional[str]
    rolled_back: bool = False
    health: Dict[str, Any] = field(default_factory=dict)
    log: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def validate_names(app: str, environment: str) -> None:
    if not _APP_RE.match(app or ""):
        raise DeployError("App names are lowercase letters, digits and hyphens (max 40), e.g. 'myco'.")
    if environment not in ENVIRONMENTS:
        raise DeployError(f"Environment must be one of {', '.join(ENVIRONMENTS)}.")


class Deployer:
    def __init__(self, shell: Shell, base_dir: str, compose: str = "docker compose",
                 http: Optional[httpx.AsyncBaseTransport] = None, health_attempts: int = 12,
                 health_delay: float = 5.0):
        self.shell = shell
        self.base_dir = base_dir.rstrip("/")
        self.compose = compose
        self.http = http
        self.health_attempts = health_attempts
        self.health_delay = health_delay

    # paths
    def app_dir(self, app: str, environment: str) -> str:
        return f"{self.base_dir}/{app}-{environment}"

    async def _sh(self, command: str, log: List[str], *, stdin: Optional[bytes] = None,
                  timeout: int = 900, check: bool = True) -> str:
        code, out, err = await self.shell.run(command, stdin=stdin, timeout=timeout)
        log.append(f"$ {command[:300]}\n{(out + err)[-3000:]}".rstrip())
        if check and code != 0:
            raise DeployError(f"Remote step failed (exit {code}): {(err or out).strip()[-800:]}")
        return out

    async def releases(self, app: str, environment: str) -> Dict[str, Any]:
        validate_names(app, environment)
        d = shlex.quote(self.app_dir(app, environment))
        out = await self._sh(
            f"if [ -d {d}/releases ]; then ls -1 {d}/releases; fi; echo '--current--'; "
            f"readlink {d}/current 2>/dev/null || true", [])
        listing, _, current = out.partition("--current--")
        names = sorted(n for n in listing.split() if _RELEASE_RE.match(n))
        current = Path(current.strip()).name if current.strip() else None
        return {"releases": names, "current": current if current in names else None}

    async def _up(self, app: str, environment: str, release: str, compose_file: str, log: List[str]) -> None:
        d = self.app_dir(app, environment)
        rel = shlex.quote(f"{d}/releases/{release}")
        await self._sh(
            f"cd {rel} && {self.compose} -p {shlex.quote(f'{app}-{environment}')} "
            f"-f {shlex.quote(compose_file)} up -d --build --remove-orphans", log, timeout=1800)

    async def _switch(self, app: str, environment: str, release: str, log: List[str]) -> None:
        d = self.app_dir(app, environment)
        await self._sh(f"ln -sfn {shlex.quote(f'releases/{release}')} {shlex.quote(d + '/current.tmp')} && "
                       f"mv -Tf {shlex.quote(d + '/current.tmp')} {shlex.quote(d + '/current')}", log)

    async def health(self, url: Optional[str], *, attempts: Optional[int] = None,
                     delay: Optional[float] = None) -> Dict[str, Any]:
        """Poll ``url`` until it answers below 500. Loopback URLs are checked on the server itself."""
        attempts = attempts or self.health_attempts
        delay = self.health_delay if delay is None else delay
        if not url:
            return {"checked": False, "healthy": True, "note": "no health URL configured; containers started"}
        host = (urlparse(url).hostname or "").lower()
        last: Dict[str, Any] = {}
        for attempt in range(1, attempts + 1):
            if host in ("localhost", "127.0.0.1", "::1"):
                code, out, err = await self.shell.run(
                    f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 {shlex.quote(url)}", timeout=30)
                status = int(out.strip() or 0) if out.strip().isdigit() else 0
                last = {"status_code": status, "via": "server", "error": None if status else err.strip()[:200]}
            else:
                try:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True, transport=self.http) as client:
                        response = await client.get(url)
                    last = {"status_code": response.status_code, "via": "jarv"}
                except httpx.HTTPError as exc:
                    last = {"status_code": 0, "via": "jarv", "error": f"{type(exc).__name__}: {exc}"}
            if 0 < last["status_code"] < 500:
                return {"checked": True, "healthy": True, "attempts": attempt, "url": url, **last}
            if attempt < attempts:
                await asyncio.sleep(delay)
        return {"checked": True, "healthy": False, "attempts": attempts, "url": url, **last}

    async def deploy(self, app: str, environment: str, package: Package, *, compose_file: str = "docker-compose.yml",
                     health_url: Optional[str] = None, health_attempts: Optional[int] = None,
                     health_delay: Optional[float] = None) -> DeployResult:
        validate_names(app, environment)
        if not _RELEASE_RE.match(package.release_id):
            raise DeployError("Invalid release id.")
        log: List[str] = []
        d = self.app_dir(app, environment)
        state = await self.releases(app, environment)
        previous = state["current"]
        result = DeployResult(success=False, app=app, environment=environment, release=package.release_id,
                              previous=previous, log=log)
        rel_dir = f"{d}/releases/{package.release_id}"
        try:
            await self._sh(f"mkdir -p {shlex.quote(rel_dir)} {shlex.quote(d + '/shared')} && "
                           f"tar -xzf - -C {shlex.quote(rel_dir)}", log, stdin=package.archive)
            await self._sh(f"if [ -f {shlex.quote(d + '/shared/.env')} ]; then "
                           f"ln -sfn ../../shared/.env {shlex.quote(rel_dir + '/.env')}; fi", log)
            await self._sh(f"test -f {shlex.quote(rel_dir + '/' + compose_file)}", log)
            await self._up(app, environment, package.release_id, compose_file, log)
        except DeployError as exc:
            result.error = str(exc)
            result.rolled_back = await self._restore(app, environment, previous, compose_file, log)
            await self._discard(app, environment, rel_dir, compose_file, stop=not result.rolled_back, log=log)
            return result
        result.health = await self.health(health_url, attempts=health_attempts, delay=health_delay)
        if not result.health["healthy"]:
            result.error = (f"Health check failed at {health_url}: "
                            f"{result.health.get('status_code') or result.health.get('error')}")
            result.rolled_back = await self._restore(app, environment, previous, compose_file, log)
            await self._discard(app, environment, rel_dir, compose_file, stop=not result.rolled_back, log=log)
            return result
        await self._switch(app, environment, package.release_id, log)
        await self._prune(app, environment, keep={package.release_id, previous}, log=log)
        result.success = True
        return result

    async def _restore(self, app: str, environment: str, previous: Optional[str], compose_file: str,
                       log: List[str]) -> bool:
        if not previous:
            log.append("No previous release to restore.")
            return False
        try:
            await self._up(app, environment, previous, compose_file, log)
            log.append(f"Restored previous release {previous}.")
            return True
        except DeployError as exc:
            log.append(f"Restoring {previous} failed: {exc}")
            return False

    async def _discard(self, app: str, environment: str, rel_dir: str, compose_file: str, *, stop: bool,
                       log: List[str]) -> None:
        """Remove a failed release so it can never be chosen as a rollback target. With
        no previous release to restore, its containers are stopped first."""
        if stop:
            await self._sh(f"cd {shlex.quote(rel_dir)} && {self.compose} -p {shlex.quote(f'{app}-{environment}')} "
                           f"-f {shlex.quote(compose_file)} down --remove-orphans", log, check=False)
        await self._sh(f"rm -rf {shlex.quote(rel_dir)}", log, check=False)

    async def _prune(self, app: str, environment: str, keep: set, log: List[str]) -> None:
        names = (await self.releases(app, environment))["releases"]
        stale = [n for n in names[:-KEEP_RELEASES] if n not in keep]
        if stale:
            d = self.app_dir(app, environment)
            await self._sh("rm -rf " + " ".join(shlex.quote(f"{d}/releases/{n}") for n in stale), log)

    async def rollback(self, app: str, environment: str, *, to_release: Optional[str] = None,
                       compose_file: str = "docker-compose.yml", health_url: Optional[str] = None,
                       health_attempts: Optional[int] = None, health_delay: Optional[float] = None) -> DeployResult:
        state = await self.releases(app, environment)
        current, names = state["current"], state["releases"]
        if to_release is None:
            if current is None or names.index(current) == 0:
                raise DeployError("There is no earlier release to roll back to.")
            to_release = names[names.index(current) - 1]
        if to_release not in names:
            raise DeployError(f"Release {to_release} does not exist on the server.")
        log: List[str] = []
        result = DeployResult(success=False, app=app, environment=environment, release=to_release,
                              previous=current, log=log)
        try:
            await self._up(app, environment, to_release, compose_file, log)
        except DeployError as exc:
            result.error = str(exc)
            if current:
                await self._restore(app, environment, current, compose_file, log)
            return result
        result.health = await self.health(health_url, attempts=health_attempts, delay=health_delay)
        if not result.health["healthy"]:
            result.error = f"Health check failed after rollback at {health_url}"
            if current:
                await self._restore(app, environment, current, compose_file, log)
            return result
        await self._switch(app, environment, to_release, log)
        result.success = True
        return result

    async def status(self, app: str, environment: str, compose_file: str = "docker-compose.yml") -> Dict[str, Any]:
        state = await self.releases(app, environment)
        services: Any = []
        if state["current"]:
            d = self.app_dir(app, environment)
            code, out, err = await self.shell.run(
                f"cd {shlex.quote(d + '/current')} && {self.compose} -p {shlex.quote(f'{app}-{environment}')} "
                f"-f {shlex.quote(compose_file)} ps --format json", timeout=60)
            services = out.strip() if code == 0 else f"unavailable: {err.strip()[:300]}"
        return {**state, "services": services}

    async def replicas(self, app: str, environment: str, service: str,
                       compose_file: str = "docker-compose.yml") -> int:
        """Running containers of one service in the current release (0 when none are reported)."""
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$", service or ""):
            raise DeployError("Invalid service name.")
        state = await self.releases(app, environment)
        if not state["current"]:
            raise DeployError(f"{app} has no current {environment} release.")
        d = self.app_dir(app, environment)
        code, out, _err = await self.shell.run(
            f"cd {shlex.quote(d + '/current')} && {self.compose} -p {shlex.quote(f'{app}-{environment}')} "
            f"-f {shlex.quote(compose_file)} ps --format json {shlex.quote(service)}", timeout=60)
        if code != 0:
            return 0
        text = out.strip()
        if text.startswith("["):
            try:
                return len(json.loads(text))
            except ValueError:
                return 0
        return sum(1 for line in text.splitlines() if line.strip().startswith("{"))

    async def scale(self, app: str, environment: str, service: str, replicas: int,
                    compose_file: str = "docker-compose.yml") -> Dict[str, Any]:
        """Run ``replicas`` containers of one service in the current release."""
        if not 0 <= int(replicas) <= 50:
            raise DeployError("Replicas must be between 0 and 50.")
        before = await self.replicas(app, environment, service, compose_file)
        d = self.app_dir(app, environment)
        log: List[str] = []
        await self._sh(
            f"cd {shlex.quote(d + '/current')} && {self.compose} -p {shlex.quote(f'{app}-{environment}')} "
            f"-f {shlex.quote(compose_file)} up -d --no-recreate --scale {shlex.quote(f'{service}={int(replicas)}')} "
            f"{shlex.quote(service)}", log, timeout=900)
        return {"app": app, "environment": environment, "service": service, "previous_replicas": before,
                "replicas": int(replicas), "log": log}

    async def logs(self, app: str, environment: str, lines: int = 200,
                   compose_file: str = "docker-compose.yml") -> str:
        state = await self.releases(app, environment)
        if not state["current"]:
            raise DeployError(f"{app} has no current {environment} release.")
        d = self.app_dir(app, environment)
        code, out, err = await self.shell.run(
            f"cd {shlex.quote(d + '/current')} && {self.compose} -p {shlex.quote(f'{app}-{environment}')} "
            f"-f {shlex.quote(compose_file)} logs --no-color --tail {max(1, min(int(lines), 1000))}", timeout=60)
        if code != 0:
            raise DeployError(f"Could not read logs: {err.strip()[:300]}")
        return redact_text(out)


def deployer() -> Deployer:
    target = load_target()
    return Deployer(SshShell(target), target.base_dir, target.compose)
