"""
JARV Backend - Settings API (Repair 14b)

The Settings page's data, all read live: version and feature switches, the
real database and Redis status, the model failover order with which
providers are configured, every external service (configured or not, what it
enables, how to set it up; never a value), voice backends, notification
targets, the safety switches, and each service's last live check. POST
.../check runs one service's free, read-only check and records it in the
audit log.
"""
from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.auth import CurrentUserId
from app.core.config import settings
from app.core.database import get_db
from app.core.ops import connections

router = APIRouter(prefix="/api/settings", tags=["settings"])

CHECK_ACTION = "settings.service_check"


async def _readiness(db: AsyncSession) -> Dict[str, Any]:
    from app.core.redis import check_redis_health

    try:
        await db.execute(text("SELECT 1"))
        database: Dict[str, Any] = {"status": "healthy"}
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        database = {"status": "unhealthy", "error": type(exc).__name__}
    redis = await check_redis_health()
    redis = {k: v for k, v in redis.items() if k in ("status", "redis_version", "uptime_seconds")}
    return {"database": database, "redis": redis,
            "ready": database["status"] == "healthy" and redis.get("status") == "healthy"}


async def _last_checks(db: AsyncSession) -> Dict[str, Dict[str, Any]]:
    from app.models.operations import AuditLog

    rows = (await db.execute(select(AuditLog).where(AuditLog.action == CHECK_ACTION)
                             .order_by(AuditLog.created_at.desc()).limit(300))).scalars().all()
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        meta = row.meta_data or {}
        key = meta.get("service")
        if key and key not in latest:
            latest[key] = {"ok": bool(row.success), "detail": meta.get("detail"),
                           "at": row.created_at.isoformat() if row.created_at else None}
    return latest


def _routing(services: List[Dict[str, Any]]) -> Dict[str, Any]:
    from app.core.providers.router import _provider_order

    configured = {s["key"]: s["configured"] for s in services}
    order = [{"provider": p.value, "configured": configured.get(p.value, False)} for p in _provider_order()]
    active = next((o["provider"] for o in order if o["configured"]), None)
    return {"order": order, "primary": active, "default_model": settings.DEFAULT_MODEL,
            "openai_model": getattr(settings, "OPENAI_MODEL", None),
            "note": None if active else "No model provider is configured: missions cannot run. Set CLAUDE_API_KEY."}


@router.get("/overview")
async def overview(user_id: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    from app.core.integrations import integrations
    from app.core.voice import engine as voice

    services = connections.overview()
    last = await _last_checks(db)
    for row in services:
        row["last_check"] = last.get(row["key"])
    return {
        "system": {"service": "jarv-backend", "version": __version__, "environment": settings.ENVIRONMENT,
                   "python_version": sys.version.split()[0], "platform": platform.platform(),
                   "checked_at": datetime.now(timezone.utc).isoformat()},
        "readiness": await _readiness(db),
        "features": {"swarm": settings.SWARM_ENABLED, "self_evolution": settings.SELF_EVOLUTION_ENABLED,
                     "company_operator": settings.COMPANY_OPERATOR_ENABLED,
                     "self_healing": settings.SELF_HEALING_ENABLED, "voice": settings.VOICE_ENABLED},
        "limits": {"default_authority_level": settings.DEFAULT_AUTHORITY_LEVEL,
                   "max_subagents_per_workspace": settings.MAX_SUBAGENTS_PER_WORKSPACE,
                   "max_subagents_global": settings.MAX_SUBAGENTS_GLOBAL,
                   "monthly_budget": float(getattr(settings, "INFRA_MONTHLY_BUDGET", 0) or 0) or None,
                   "log_retention_days": settings.LOG_RETENTION_DAYS},
        "safety": {"audit_logging": settings.AUDIT_LOGGING_ENABLED,
                   "boundary_reporting": settings.BOUNDARY_REPORTING_ENABLED,
                   "note": "Audit logging, boundary reports and verifier checks cannot be switched off from the "
                           "dashboard; disabling any of them is a hard boundary."},
        "routing": _routing(services),
        "services": services,
        "voice": voice.status(),
        "notifications": integrations.list(),
    }


@router.post("/services/{key}/check")
async def check_service(key: str, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    from app.core.audit import AuditLogger

    try:
        result = await connections.check(key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    entry = await AuditLogger.log_system_event(
        db, action=CHECK_ACTION, result="ok" if result["ok"] else "failed", resource_type="service",
        user_id=UUID(str(user_id)), details={"service": key, "detail": result["detail"]},
        severity="info" if result["ok"] else "warning")
    result["at"] = entry.created_at.isoformat() if entry.created_at else datetime.now(timezone.utc).isoformat()
    return result
