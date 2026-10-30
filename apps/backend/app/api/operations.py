"""
JARV Backend - Operations API (Repair 12d)

What the dashboard's Infrastructure page and an operator need: live health,
JARV's containers, the server's resources, and database backups. Every
endpoint requires authentication. Restarting a service and taking a backup
are recorded in the audit log; restoring a backup stays with the approval-gated
restore tool and is not offered here.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from uuid import UUID

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLogger
from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.core.ops import backups as backup_ops
from app.core.ops import docker_ops
from app.core.ops.health import database_health, service_health

router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.get("/health")
async def health(user: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    return await service_health(db)


@router.get("/server")
async def server(user: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    from app.tools.ops import _disks

    memory = psutil.virtual_memory()
    return {
        "cpu_percent": await asyncio.to_thread(psutil.cpu_percent, 0.5),
        "cpu_count": psutil.cpu_count(),
        "load_average": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
        "memory_percent": memory.percent,
        "memory_total_gb": round(memory.total / 1e9, 2),
        "memory_available_gb": round(memory.available / 1e9, 2),
        "disks": _disks(),
        "database": await database_health(db),
    }


@router.get("/cost")
async def cost(user: CurrentUserId, workspace_id: Optional[UUID] = None,
               db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Monthly infrastructure cost (configured fixed costs, recorded resources, model use) against the budget."""
    from sqlalchemy import select

    from app.core.infra.configs import estimate_monthly
    from app.models.workspace import Workspace

    if workspace_id is not None:
        owned = (await db.execute(select(Workspace.id).where(Workspace.id == workspace_id,
                                                             Workspace.owner_id == UUID(str(user))))).scalar_one_or_none()
        if owned is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        return await estimate_monthly(db, workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/containers")
async def containers(user: CurrentUserId) -> Dict[str, Any]:
    ops = docker_ops.get_docker_ops()
    try:
        items = [c.as_dict() for c in await ops.containers()]
    except docker_ops.OpsUnavailable as exc:
        return {"available": False, "reason": str(exc), "containers": []}
    for item in items:
        item["restartable"] = item["service"] in docker_ops.RESTARTABLE
    return {"available": True, "containers": items}


class RestartRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=500)


@router.post("/services/{service}/restart")
async def restart(service: str, body: RestartRequest, user: CurrentUserId,
                  db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        result = await docker_ops.get_docker_ops().restart(service)
    except docker_ops.OpsRefused as exc:
        await AuditLogger.log_system_event(db, action="service_restart", result="refused", resource_type="service",
                                           details={"service": service, "operator": user, "reason": body.reason},
                                           severity="warning")
        raise HTTPException(status_code=403, detail=str(exc))
    except docker_ops.OpsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    await AuditLogger.log_system_event(db, action="service_restart", result="success", resource_type="service",
                                       details={**result, "operator": user, "reason": body.reason},
                                       severity="warning")
    return result


def _backup_info(record) -> Dict[str, Any]:
    return {"id": str(record.id), "file": record.backup_name, "status": record.status,
            "size_bytes": record.backup_size_bytes, "verified": record.is_verified,
            "error": record.error_message, "reason": record.description,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "expires_at": record.expires_at.isoformat() if record.expires_at else None}


@router.get("/backups")
async def list_backups(user: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    rows = await backup_ops.list_backups(db)
    return {"backups": [_backup_info(r) for r in rows], "directory": str(backup_ops.backup_dir())}


class BackupRequest(BaseModel):
    reason: str = Field("manual backup from the dashboard", min_length=3, max_length=500)


@router.post("/backups")
async def create_backup(body: BackupRequest, user: CurrentUserId,
                        db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    try:
        record = await backup_ops.create_backup(db, workspace_id=None, reason=body.reason)
        verification = await backup_ops.verify_backup(db, record)
    except backup_ops.BackupError as exc:
        await db.commit()
        await AuditLogger.log_system_event(db, action="database_backup", result="failure", resource_type="backup",
                                           details={"operator": user, "error": str(exc)}, severity="error")
        raise HTTPException(status_code=500, detail=str(exc))
    await db.commit()
    await AuditLogger.log_system_event(db, action="database_backup", result="success", resource_type="backup",
                                       resource_id=record.id, details={"operator": user, "file": record.backup_name})
    return {**_backup_info(record), "verification": verification}
