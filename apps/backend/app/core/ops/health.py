"""
JARV Backend - Operational health

Facts the monitoring and self-healing agents act on, each measured directly:
database, Redis, Celery workers and queue, stuck missions, Prometheus targets,
recent errors in a workspace, and database internals.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)


def prometheus_url() -> Optional[str]:
    value = (os.getenv("PROMETHEUS_URL") or getattr(settings, "PROMETHEUS_URL", "") or "").strip()
    return value.rstrip("/") or None


async def _timed(coro) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        detail = await coro
        return {"ok": True, "latency_ms": round((time.perf_counter() - start) * 1000, 1), **(detail or {})}
    except Exception as exc:  # noqa: BLE001 - a failed check is a result, not an exception
        return {"ok": False, "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


async def _database(db: AsyncSession) -> Dict[str, Any]:
    await db.execute(text("SELECT 1"))
    return {}


async def _redis() -> Dict[str, Any]:
    from app.core.redis import get_redis

    client = await get_redis()
    await client.ping()
    return {"queue_length": int(await client.llen("celery"))}


async def _workers() -> Dict[str, Any]:
    if settings.TESTING:
        return {"workers": None, "note": "not pinged in test mode"}
    from app.core.celery import celery_app

    # limit=1: return as soon as one worker answers instead of waiting out the timeout.
    replies = await asyncio.wait_for(asyncio.to_thread(celery_app.control.ping, timeout=2.0, limit=1), timeout=5)
    names = sorted(name for reply in (replies or []) for name in reply)
    if not names:
        raise RuntimeError("no Celery worker answered a ping")
    return {"workers": names}


async def _missions(db: AsyncSession) -> Dict[str, Any]:
    from app.core.runtime import lifecycle
    from app.core.runtime.missions import MISSION_TASK_TYPE, STALE_AFTER_SECONDS
    from app.models.task import Task

    now = datetime.now(timezone.utc)
    stale = (await db.execute(select(func.count()).where(
        Task.task_type == MISSION_TASK_TYPE, Task.status == lifecycle.RUNNING,
        Task.heartbeat_at < now - timedelta(seconds=STALE_AFTER_SECONDS)))).scalar() or 0
    queued = (await db.execute(select(func.count()).where(
        Task.task_type == MISSION_TASK_TYPE, Task.status == lifecycle.QUEUED))).scalar() or 0
    if stale:
        raise RuntimeError(f"{stale} running mission(s) stopped heartbeating")
    return {"queued": int(queued), "stale": 0}


async def _prometheus_targets() -> Dict[str, Any]:
    base = prometheus_url()
    if not base:
        return {"configured": False}
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{base}/api/v1/targets")
        response.raise_for_status()
    targets = response.json()["data"]["activeTargets"]
    down = [t["labels"].get("job") for t in targets if t.get("health") != "up"]
    if down:
        raise RuntimeError(f"Prometheus targets down: {', '.join(sorted(set(down)))}")
    return {"configured": True, "targets_up": len(targets)}


async def service_health(db: AsyncSession) -> Dict[str, Any]:
    checks = {
        "database": await _timed(_database(db)),
        "redis": await _timed(_redis()),
        "workers": await _timed(_workers()),
        "missions": await _timed(_missions(db)),
        "prometheus": await _timed(_prometheus_targets()),
    }
    failing = [name for name, result in checks.items() if not result["ok"]]
    return {"healthy": not failing, "failing": failing, "checks": checks,
            "checked_at": datetime.now(timezone.utc).isoformat()}


async def prometheus_query(query: str) -> Dict[str, Any]:
    base = prometheus_url()
    if not base:
        raise RuntimeError("PROMETHEUS_URL is not configured; start docker-compose.monitoring.yml.")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{base}/api/v1/query", params={"query": query})
    body = response.json()
    if body.get("status") != "success":
        raise RuntimeError(body.get("error") or f"Prometheus returned HTTP {response.status_code}")
    rows = body["data"]["result"][:100]
    return {"result_type": body["data"]["resultType"],
            "series": [{"labels": r.get("metric", {}), "value": (r.get("value") or [None, None])[1]} for r in rows]}


def _tool_name(action: str) -> str:
    if action.startswith("tool:"):
        return action[5:]
    if action.startswith("agent.tool."):
        return action.split(".")[2]
    return action


async def recent_errors(db: AsyncSession, workspace_id: UUID, hours: int = 24) -> Dict[str, Any]:
    """Failures in this workspace: missions, tool calls, error feed items, open incidents."""
    from app.models.company_operations import LiveOperationsFeedItem
    from app.models.operations import AuditLog, Incident
    from app.models.task import Task

    since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 24 * 14)))
    failed = (await db.execute(
        select(Task.id, Task.title, Task.error_message, Task.updated_at)
        .where(Task.workspace_id == workspace_id, Task.status == "failed", Task.updated_at >= since)
        .order_by(Task.updated_at.desc()).limit(20))).all()
    # Workspace-runtime tools log "tool:<name>"; registry tools log "agent.tool.<name>.tool.<name>".
    tools = (await db.execute(
        select(AuditLog.action, func.count())
        .where(AuditLog.workspace_id == workspace_id,
               or_(AuditLog.action_category == "tool_execution", AuditLog.action.like("agent.tool.%")),
               AuditLog.success.is_(False), AuditLog.created_at >= since)
        .group_by(AuditLog.action).order_by(func.count().desc()).limit(15))).all()
    feed = (await db.execute(
        select(LiveOperationsFeedItem.title, LiveOperationsFeedItem.message, LiveOperationsFeedItem.created_at)
        .where(LiveOperationsFeedItem.workspace_id == workspace_id,
               LiveOperationsFeedItem.severity.in_(("error", "critical")),
               LiveOperationsFeedItem.created_at >= since)
        .order_by(LiveOperationsFeedItem.created_at.desc()).limit(20))).all()
    incidents = (await db.execute(
        select(Incident.incident_number, Incident.title, Incident.severity, Incident.status, Incident.detected_at)
        .where(Incident.workspace_id == workspace_id, Incident.status.in_(("open", "investigating", "acknowledged")))
        .order_by(Incident.detected_at.desc()).limit(20))).all()
    return {
        "window_hours": hours,
        "failed_missions": [{"id": str(r[0]), "title": r[1][:200], "error": (r[2] or "")[:300],
                             "at": r[3].isoformat() if r[3] else None} for r in failed],
        "failing_tools": [{"tool": _tool_name(a), "failures": c} for a, c in tools],
        "error_events": [{"title": t, "message": (m or "")[:300], "at": at.isoformat() if at else None}
                         for t, m, at in feed],
        "open_incidents": [{"number": n, "title": t, "severity": s, "status": st,
                            "detected_at": d.isoformat() if d else None} for n, t, s, st, d in incidents],
    }


async def database_health(db: AsyncSession) -> Dict[str, Any]:
    if db.get_bind().dialect.name != "postgresql":
        await db.execute(text("SELECT 1"))
        return {"dialect": db.get_bind().dialect.name, "reachable": True}
    size = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar()
    states = dict((await db.execute(text(
        "SELECT coalesce(state, 'unknown'), count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() GROUP BY 1"))).all())
    longest = (await db.execute(text(
        "SELECT coalesce(max(extract(epoch FROM now() - query_start)), 0) FROM pg_stat_activity "
        "WHERE datname = current_database() AND state = 'active' AND pid <> pg_backend_pid()"))).scalar()
    limit = (await db.execute(text("SHOW max_connections"))).scalar()
    dead = (await db.execute(text(
        "SELECT relname, n_dead_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 5"))).all()
    return {"size_bytes": int(size or 0), "connections": states, "max_connections": int(limit),
            "longest_active_query_seconds": round(float(longest or 0), 1),
            "most_dead_tuples": [{"table": t, "dead_tuples": int(n)} for t, n in dead]}
