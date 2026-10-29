"""
JARV Backend - Operations tools (Repair 12d)

Real monitoring, container, server, and backup tools for the operations agents.
Names follow the design's tool registry (section 12). Every tool runs through
ToolBase.execute: authority check, central permission policy, ToolRun record.

Gating follows the design's authority model: reading health, logs, metrics and
errors is Level 1-2; restarting an approved JARV service and retrying stuck
missions are production repair (no approval, design section 6); restoring a
backup and deleting backups pause for Richard's approval.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type
from uuid import UUID

import httpx
import psutil
from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.tools import ToolBase, ToolContext, ToolResult


@asynccontextmanager
async def _session(context: ToolContext):
    if context.db_session is not None:
        yield context.db_session
    else:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            yield session
            await session.commit()


class _Empty(BaseModel):
    pass


class _Output(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


class _OpsTool(ToolBase):
    """Shared metadata for operations tools."""
    _name = ""
    _description = ""
    _input: Type[BaseModel] = _Empty
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS
    _approval = False
    _category = "operations"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> Type[BaseModel]:
        return self._input

    @property
    def output_schema(self) -> Type[BaseModel]:
        return _Output

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return self._authority

    @property
    def requires_approval(self) -> bool:
        return self._approval

    @property
    def category(self) -> str:
        return self._category

    def ok(self, data: Dict[str, Any], text: str) -> ToolResult:
        return self.create_result(success=True, result_data=data, output_text=text)

    def fail(self, message: str, **data: Any) -> ToolResult:
        return self.create_result(success=False, result_data=data, error_message=message)


# ----- health and monitoring ---------------------------------------------------------

class CheckHealthTool(_OpsTool):
    _name = "check_health"
    _description = ("Check JARV's own services: database, Redis, Celery workers, stuck missions, "
                    "and Prometheus scrape targets. Reports each check with latency or the error.")

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.health import service_health

        async with _session(context) as db:
            report = await service_health(db)
        summary = "all services healthy" if report["healthy"] else f"failing: {', '.join(report['failing'])}"
        return self.ok(report, summary)


class CheckQueueTool(_OpsTool):
    _name = "check_queue"
    _description = "Show the worker queue: messages waiting, queued missions, and missions that stopped heartbeating."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.health import _missions, _redis, _timed

        async with _session(context) as db:
            data = {"broker": await _timed(_redis()), "missions": await _timed(_missions(db))}
        return self.ok(data, f"queue: {data['broker'].get('queue_length')} waiting")


class _ErrorsInput(BaseModel):
    hours: int = Field(24, ge=1, le=336, description="Look-back window in hours")


class CheckErrorsTool(_OpsTool):
    _name = "check_errors"
    _description = "Recent failures in this workspace: failed missions, failing tools, error events, open incidents."
    _input = _ErrorsInput

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.health import recent_errors

        if context.workspace_id is None:
            return self.fail("A workspace is required.")
        async with _session(context) as db:
            data = await recent_errors(db, context.workspace_id, int(input_data.get("hours", 24)))
        return self.ok(data, f"{len(data['failed_missions'])} failed missions, "
                             f"{len(data['open_incidents'])} open incidents")


class CheckDatabaseHealthTool(_OpsTool):
    _name = "check_database_health"
    _description = "PostgreSQL internals: size, connections by state, longest running query, tables with most dead rows."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.health import database_health

        async with _session(context) as db:
            data = await database_health(db)
        return self.ok(data, "database reachable")


class _MetricsInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000,
                       description="PromQL, e.g. jarv_missions or rate(http_requests_total[5m])")


class QueryMetricsTool(_OpsTool):
    _name = "query_metrics"
    _description = "Run a read-only PromQL query against JARV's Prometheus (missions, agents, tools, API, host)."
    _input = _MetricsInput

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.health import prometheus_query

        try:
            data = await prometheus_query(input_data["query"])
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))
        return self.ok(data, f"{len(data['series'])} series")


class _UptimeInput(BaseModel):
    url: str = Field(..., description="Public http(s) URL to check")


class CheckUptimeTool(_OpsTool):
    _name = "check_uptime"
    _description = "Check that a public URL responds: status code, response time, and TLS (private networks are blocked)."
    _input = _UptimeInput
    _authority = AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.internet import _ssrf_ok

        url = input_data["url"].strip()
        allowed, reason = _ssrf_ok(url)
        if not allowed:
            return self.fail(f"URL refused: {reason}", url=url)
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            return self.ok({"url": url, "up": False, "error": f"{type(exc).__name__}: {exc}"}, f"{url} is DOWN")
        elapsed = round((time.perf_counter() - start) * 1000)
        up = response.status_code < 500
        return self.ok({"url": url, "up": up, "status_code": response.status_code, "response_ms": elapsed,
                        "final_url": str(response.url)}, f"{url} -> {response.status_code} in {elapsed}ms")


class InspectServerTool(_OpsTool):
    _name = "inspect_server"
    _description = "CPU, memory, disk, load, and uptime of the machine JARV runs on."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        disks = _disks()
        memory = psutil.virtual_memory()
        data = {"cpu_percent": await asyncio.to_thread(psutil.cpu_percent, 0.5), "cpu_count": psutil.cpu_count(),
                "load_average": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
                "memory_percent": memory.percent, "memory_available_gb": round(memory.available / 1e9, 2),
                "disks": disks, "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1)}
        return self.ok(data, f"cpu {data['cpu_percent']}%, memory {memory.percent}%")


def _disks() -> List[Dict[str, Any]]:
    """One entry per filesystem. Inside a container the root is an overlay that
    psutil does not list, and single files (/etc/hosts, ...) are bind-mounted
    from the same disk; both are folded so each disk appears once."""
    candidates = ["/"] + [p.mountpoint for p in psutil.disk_partitions(all=False)] + ["/data/backups"]
    disks: List[Dict[str, Any]] = []
    seen = set()
    for mount in candidates:
        if not os.path.isdir(mount):
            continue
        try:
            device = os.stat(mount).st_dev
            usage = psutil.disk_usage(mount)
        except OSError:
            continue
        if device in seen:
            continue
        seen.add(device)
        disks.append({"mount": mount, "percent": usage.percent,
                      "free_gb": round(usage.free / 1e9, 2), "total_gb": round(usage.total / 1e9, 2)})
    return disks


class CheckDiskSpaceTool(_OpsTool):
    _name = "check_disk_space"
    _description = "Disk usage of every mounted filesystem; flags any above 85% full."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        disks = _disks()
        full = [d["mount"] for d in disks if d["percent"] >= 85]
        return self.ok({"disks": disks, "over_85_percent": full},
                       f"{len(disks)} filesystems; nearly full: {', '.join(full) or 'none'}")


class CheckMemoryUsageTool(_OpsTool):
    _name = "check_memory_usage"
    _description = "RAM and swap usage, plus the processes using the most memory."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        memory, swap = psutil.virtual_memory(), psutil.swap_memory()
        top = sorted((p.info for p in psutil.process_iter(["pid", "name", "memory_percent"])
                      if p.info.get("memory_percent") is not None),
                     key=lambda i: i["memory_percent"], reverse=True)[:5]
        data = {"memory_percent": memory.percent, "available_gb": round(memory.available / 1e9, 2),
                "total_gb": round(memory.total / 1e9, 2), "swap_percent": swap.percent,
                "top_processes": [{**t, "memory_percent": round(t["memory_percent"], 2)} for t in top]}
        return self.ok(data, f"memory {memory.percent}%, swap {swap.percent}%")


class CheckCpuUsageTool(_OpsTool):
    _name = "check_cpu_usage"
    _description = "CPU usage overall and per core, with load average."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        per_core = await asyncio.to_thread(psutil.cpu_percent, 0.5, True)
        overall = round(sum(per_core) / max(1, len(per_core)), 1)
        data = {"cpu_percent": overall, "per_core": per_core, "cpu_count": psutil.cpu_count(),
                "load_average": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None}
        return self.ok(data, f"cpu {overall}% across {len(per_core)} cores")


_REQUIRED_SETTINGS = ("DATABASE_URL", "REDIS_URL", "SECRET_KEY")
_OPTIONAL_SETTINGS = ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DOCKER_OPS_URL",
                      "PROMETHEUS_URL", "BACKUP_DIR", "METRICS_TOKEN", "ALERT_WEBHOOK_TOKEN")


class CheckEnvVarsTool(_OpsTool):
    _name = "check_env_vars"
    _description = "Which required and optional settings are set (names only; values are never returned)."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        import os

        from app.core.config import settings

        def present(name: str) -> bool:
            return bool(str(os.getenv(name) or getattr(settings, name, "") or "").strip())

        missing = [n for n in _REQUIRED_SETTINGS if not present(n)]
        data = {"required_missing": missing,
                "required": {n: present(n) for n in _REQUIRED_SETTINGS},
                "optional": {n: present(n) for n in _OPTIONAL_SETTINGS}}
        return self.ok(data, "all required settings present" if not missing else f"missing: {', '.join(missing)}")


# ----- containers -----------------------------------------------------------------------

class CheckContainerStatusTool(_OpsTool):
    _name = "check_container_status"
    _description = "List JARV's containers with state and health (backend, worker, scheduler, dashboard, ...)."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.docker_ops import OpsUnavailable, get_docker_ops

        try:
            containers = [c.as_dict() for c in await get_docker_ops().containers()]
        except OpsUnavailable as exc:
            return self.fail(str(exc))
        unhealthy = [c["service"] for c in containers if c["state"] != "running" or c["health"] == "unhealthy"]
        return self.ok({"containers": containers, "unhealthy": unhealthy},
                       f"{len(containers)} containers; unhealthy: {', '.join(unhealthy) or 'none'}")


class CheckDockerStatusTool(CheckContainerStatusTool):
    _name = "check_docker_status"
    _description = "Whether JARV can reach Docker (through its restricted proxy) and the state of its containers."


class CheckCrashesTool(_OpsTool):
    _name = "check_crashes"
    _description = "Find JARV services that crashed: restarts, non-zero exit codes, out-of-memory kills, failing health checks."

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.docker_ops import OpsUnavailable, get_docker_ops

        ops = get_docker_ops()
        try:
            containers = await ops.containers()
            details = [await ops.inspect(c.service or c.name) for c in containers]
        except OpsUnavailable as exc:
            return self.fail(str(exc))
        crashed = [d for d in details if d.get("oom_killed") or (d.get("restart_count") or 0) > 0
                   or d.get("health") == "unhealthy" or (d.get("state") != "running" and d.get("exit_code"))]
        return self.ok({"crashed": crashed, "checked": len(details)},
                       f"{len(crashed)} of {len(details)} services show crashes")


class _LogsInput(BaseModel):
    service: str = Field(..., description="Service name, e.g. backend, worker, scheduler")
    lines: int = Field(100, ge=1, le=400)


class CheckContainerLogsTool(_OpsTool):
    _name = "check_container_logs"
    _description = "Recent log lines of one JARV service (secrets redacted)."
    _input = _LogsInput
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.docker_ops import OpsRefused, OpsUnavailable, get_docker_ops

        try:
            text = await get_docker_ops().logs(input_data["service"], input_data.get("lines", 100))
        except (OpsUnavailable, OpsRefused) as exc:
            return self.fail(str(exc))
        return self.ok({"service": input_data["service"], "logs": text[-12000:]},
                       f"{len(text.splitlines())} log lines")


class CheckServiceLogsTool(CheckContainerLogsTool):
    _name = "check_service_logs"
    _description = "Recent log lines of one JARV service (secrets redacted)."


class _AppLogsInput(BaseModel):
    lines: int = Field(150, ge=1, le=400)


class CheckLogsTool(_OpsTool):
    _name = "check_logs"
    _description = "Recent JARV application logs (API and worker), secrets redacted, with error lines pulled out."
    _input = _AppLogsInput
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.docker_ops import OpsRefused, OpsUnavailable, get_docker_ops

        ops, lines = get_docker_ops(), int(input_data.get("lines", 150))
        logs: Dict[str, str] = {}
        for service in ("backend", "worker"):
            try:
                logs[service] = (await ops.logs(service, lines))[-8000:]
            except OpsRefused:
                continue
            except OpsUnavailable as exc:
                return self.fail(str(exc))
        errors = [f"{svc}: {line}" for svc, text in logs.items() for line in text.splitlines()
                  if any(word in line for word in ("ERROR", "CRITICAL", "Traceback", "Exception"))][-60:]
        return self.ok({"logs": logs, "error_lines": errors}, f"{len(errors)} error lines")


class _RestartInput(BaseModel):
    service: str = Field(..., description="backend, worker, scheduler, dashboard, local-runner, voicebox, ...")
    reason: str = Field(..., min_length=5, description="Why the restart is needed (recorded)")


class RestartServiceTool(_OpsTool):
    _name = "restart_service"
    _description = ("Restart one JARV service container (production repair). Databases and Redis are never "
                    "restarted automatically. Verify recovery with check_health afterwards.")
    _input = _RestartInput
    _authority = AuthorityLevel.LEVEL_7_DEPLOYMENT

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.docker_ops import OpsRefused, OpsUnavailable, get_docker_ops

        try:
            data = await get_docker_ops().restart(input_data["service"])
        except OpsRefused as exc:
            return self.create_result(success=False, result_data={"blocked": True, "reason": str(exc)},
                                      error_message=str(exc))
        except OpsUnavailable as exc:
            return self.fail(str(exc))
        data["reason"] = input_data["reason"]
        return self.ok(data, f"restarted {data['service']}")


class RestartContainerTool(RestartServiceTool):
    _name = "restart_container"


class RecoverStuckMissionsTool(_OpsTool):
    _name = "recover_stuck_missions"
    _description = "Re-queue missions whose worker stopped heartbeating and re-dispatch missions nobody picked up."
    _authority = AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.runtime.missions import MissionRunner

        summary = await MissionRunner().recover_stale()
        moved = sum(len(v) for v in summary.values())
        return self.ok(summary, f"{moved} mission(s) recovered or closed")


# ----- backups ----------------------------------------------------------------------------

class _BackupCreateInput(BaseModel):
    reason: str = Field(..., min_length=3, description="Why this backup is taken (recorded)")
    retention_days: int = Field(30, ge=1, le=365)


class CreateBackupTool(_OpsTool):
    _name = "create_backup"
    _description = "Back up JARV's PostgreSQL database (pg_dump, checksummed, recorded)."
    _input = _BackupCreateInput
    _authority = AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.backups import BackupError, create_backup

        async with _session(context) as db:
            try:
                record = await create_backup(db, workspace_id=context.workspace_id,
                                             reason=input_data["reason"],
                                             retention_days=input_data.get("retention_days", 30))
            except BackupError as exc:
                return self.fail(str(exc))
            data = {"backup_id": str(record.id), "file": record.backup_name,
                    "size_bytes": record.backup_size_bytes, "sha256": (record.meta_data or {}).get("sha256")}
        return self.ok(data, f"backup {record.backup_name} ({record.backup_size_bytes} bytes)")


class _BackupIdInput(BaseModel):
    backup_id: str = Field(..., description="Backup id from list_backups")


async def _backup(db, backup_id: str):
    from sqlalchemy import select

    from app.models.operations import BackupRecord

    try:
        return (await db.execute(select(BackupRecord).where(BackupRecord.id == UUID(backup_id)))).scalar_one_or_none()
    except ValueError:
        return None


class VerifyBackupTool(_OpsTool):
    _name = "verify_backup"
    _description = "Verify a backup: file present, checksum matches, archive readable by pg_restore."
    _input = _BackupIdInput
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.backups import BackupError, verify_backup

        async with _session(context) as db:
            record = await _backup(db, input_data["backup_id"])
            if record is None:
                return self.fail("Backup not found.")
            try:
                data = await verify_backup(db, record)
            except BackupError as exc:
                return self.fail(str(exc))
        return self.ok(data, "verified" if data["verified"] else "verification FAILED")


class ListBackupsTool(_OpsTool):
    _name = "list_backups"
    _description = "List recorded backups with size, verification, and expiry."
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.backups import list_backups

        async with _session(context) as db:
            rows = await list_backups(db, context.workspace_id)
            data = {"backups": [{"backup_id": str(r.id), "file": r.backup_name, "status": r.status,
                                 "size_bytes": r.backup_size_bytes, "verified": r.is_verified,
                                 "started_at": r.started_at.isoformat() if r.started_at else None,
                                 "expires_at": r.expires_at.isoformat() if r.expires_at else None}
                                for r in rows]}
        return self.ok(data, f"{len(rows)} backups")


class RestoreBackupTool(_OpsTool):
    _name = "restore_backup_with_boundary"
    _description = ("Restore a verified backup into a NEW database (the live database is untouched). "
                    "Pauses for Richard's approval.")
    _input = _BackupIdInput
    _authority = AuthorityLevel.LEVEL_7_DEPLOYMENT
    _approval = True

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.backups import BackupError, restore_to_new_database

        async with _session(context) as db:
            record = await _backup(db, input_data["backup_id"])
            if record is None:
                return self.fail("Backup not found.")
            try:
                data = await restore_to_new_database(db, record)
            except BackupError as exc:
                return self.fail(str(exc))
        return self.ok(data, f"restored into {data['database']}")


class CleanupBackupsTool(_OpsTool):
    _name = "cleanup_backups"
    _description = "Delete backups past their retention, always keeping the newest verified ones. Pauses for approval."
    _authority = AuthorityLevel.LEVEL_7_DEPLOYMENT
    _approval = True

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        from app.core.ops.backups import cleanup_expired

        async with _session(context) as db:
            data = await cleanup_expired(db)
        return self.ok(data, f"removed {len(data['removed'])} expired backups")


OPS_TOOLS = [CheckHealthTool, CheckQueueTool, CheckErrorsTool, CheckDatabaseHealthTool, QueryMetricsTool,
             CheckUptimeTool, InspectServerTool, CheckDiskSpaceTool, CheckMemoryUsageTool, CheckCpuUsageTool,
             CheckEnvVarsTool, CheckContainerStatusTool, CheckDockerStatusTool, CheckCrashesTool,
             CheckContainerLogsTool, CheckServiceLogsTool, CheckLogsTool, RestartServiceTool,
             RestartContainerTool, RecoverStuckMissionsTool, CreateBackupTool, VerifyBackupTool,
             ListBackupsTool, RestoreBackupTool, CleanupBackupsTool]

__all__ = ["OPS_TOOLS"] + [tool.__name__ for tool in OPS_TOOLS]
