"""
JARV Backend - Repair actions used by the self-healing runbooks

Each action does one real thing and reports what happened:
- service_state: container state/health through the Docker proxy, falling back
  to the API's /health endpoint when container operations are not configured;
- restart_and_wait: restart one approved service and wait until it is running
  (and healthy, if it has a health check);
- workers_alive: whether any Celery worker answers a ping;
- recover_missions: re-queue missions whose worker stopped heartbeating.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


def api_url() -> str:
    return (os.getenv("JARV_API_URL") or "http://localhost:8000").rstrip("/")


async def service_state(service: str) -> Dict[str, Any]:
    from app.core.ops.docker_ops import OpsRefused, OpsUnavailable, get_docker_ops

    ops = get_docker_ops()
    if ops.available:
        try:
            info = await ops.inspect(service)
            healthy = info["state"] == "running" and info.get("health") in (None, "healthy")
            return {"source": "docker", "healthy": healthy, **info}
        except (OpsUnavailable, OpsRefused) as exc:
            logger.warning(f"container state for {service} unavailable: {exc}")
    if service != "backend":
        return {"source": "none", "healthy": None, "error": "container operations are not configured"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{api_url()}/health")
        return {"source": "http", "healthy": response.status_code < 500, "status_code": response.status_code}
    except httpx.HTTPError as exc:
        return {"source": "http", "healthy": False, "error": f"{type(exc).__name__}: {exc}"}


async def restart_and_wait(service: str, reason: str, timeout_seconds: int = 120) -> Dict[str, Any]:
    from app.core.ops.docker_ops import get_docker_ops

    result = await get_docker_ops().restart(service)
    deadline = time.monotonic() + timeout_seconds
    state: Dict[str, Any] = {}
    await asyncio.sleep(3)
    while time.monotonic() < deadline:
        state = await service_state(service)
        if state.get("healthy"):
            break
        await asyncio.sleep(5)
    return {"action": "restart_service", **result, "reason": reason,
            "recovered": bool(state.get("healthy")), "state_after": state}


async def workers_alive() -> bool:
    from app.core.ops.health import _workers

    try:
        return bool((await _workers()).get("workers"))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"worker ping failed: {exc}")
        return False


async def recover_missions() -> Dict[str, Any]:
    from app.core.runtime.missions import MissionRunner

    summary = await MissionRunner().recover_stale()
    return {"action": "recover_stuck_missions", **summary}


async def stale_mission_count() -> int:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from app.core.runtime import lifecycle
    from app.core.runtime.missions import MISSION_TASK_TYPE, STALE_AFTER_SECONDS, session_factory
    from app.models.task import Task

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_AFTER_SECONDS)
    async with session_factory()() as db:
        return int((await db.execute(select(func.count()).where(
            Task.task_type == MISSION_TASK_TYPE, Task.status == lifecycle.RUNNING,
            Task.heartbeat_at < cutoff))).scalar() or 0)
