"""
JAI Backend - Worker Tasks

Background tasks for async operations.
"""
import logging
import asyncio
import os
from typing import Any
from celery import Task

from app.core.celery import celery_app
from app.core.config import settings

logger = logging.getLogger(__name__)

_loop: "asyncio.AbstractEventLoop | None" = None
_loop_pid: "int | None" = None


def run_async(coro):
    """Run a coroutine on this worker process's own long-lived event loop.

    Clients created once per process (the database pool, Redis, the model
    providers' HTTP clients) stay bound to the loop they first ran on.
    asyncio.run closes its loop after every task, so the next task reusing
    those clients failed with "Event loop is closed". One loop per process
    (recreated after a fork) keeps them valid across tasks.
    """
    global _loop, _loop_pid
    if _loop is None or _loop.is_closed() or _loop_pid != os.getpid():
        _loop = asyncio.new_event_loop()
        _loop_pid = os.getpid()
        asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


class AsyncTask(Task):
    """Base task class with async support"""

    def __call__(self, *args, **kwargs):
        """Execute task with async support"""
        return run_async(self.run_async(*args, **kwargs))

    async def run_async(self, *args, **kwargs):
        """Override this method in subclasses"""
        raise NotImplementedError


@celery_app.task(name="test_task", bind=True)
def test_task(self: Task, message: str = "Hello from JAI worker") -> dict[str, Any]:
    """Test task to verify worker queue is functioning"""
    logger.info(f"Test task started: {message}")

    task_info = {
        "task_id": self.request.id,
        "task_name": self.name,
        "message": message,
        "status": "completed",
        "environment": settings.ENVIRONMENT,
    }

    logger.info(f"Test task completed: {task_info}")
    return task_info


@celery_app.task(name="async_test_task", bind=True, base=AsyncTask)
async def async_test_task(self: AsyncTask, message: str = "Hello from async JAI worker") -> dict[str, Any]:
    """Async test task to verify async worker support"""
    logger.info(f"Async test task started: {message}")

    # Simulate async work
    await asyncio.sleep(1)

    task_info = {
        "task_id": self.request.id,
        "task_name": self.name,
        "message": message,
        "status": "completed",
        "async": True,
        "environment": settings.ENVIRONMENT,
    }

    logger.info(f"Async test task completed: {task_info}")
    return task_info


@celery_app.task(name="health_check_task", bind=True)
def health_check_task(self: Task) -> dict[str, Any]:
    """Health check task for worker monitoring"""
    return {
        "task_id": self.request.id,
        "status": "healthy",
        "worker": self.request.hostname,
    }


async def _run_scheduled_loop(job_name: str, description: str) -> dict[str, Any]:
    """Autonomous health check and repair, run by Celery beat (no operator command).

    Each run measures JAI (database, Redis, workers, missions, Prometheus, and
    container state through the Docker proxy) and records one audit entry.
    The operations feed gets an entry only when the overall state changes, so a
    healthy system does not flood it. With SELF_HEALING_ENABLED, a restartable
    JAI service that is down or unhealthy on two consecutive runs is restarted
    (never the data stores, never this worker itself) and the restart is
    recorded in the feed and the audit log.
    """
    from datetime import datetime, timezone
    from uuid import uuid4
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.ops import docker_ops
    from app.core.ops.health import service_health
    from app.core.redis import get_redis
    from app.models.company_operations import LiveOperationsFeedItem
    from app.models.operations import AuditLog
    from app.models.workspace import Workspace

    now = datetime.now(timezone.utc)
    redis = await get_redis()
    async with AsyncSessionLocal() as db:
        health = await service_health(db)
        containers: list = []
        broken: list = []
        ops = docker_ops.get_docker_ops()
        if ops.available:
            try:
                containers = await ops.containers()
                problems = {c.service: docker_ops.container_problem(c) for c in containers}
                broken = [svc for svc, why in problems.items() if why and svc not in docker_ops.OPTIONAL_SERVICES]
                optional_off = [svc for svc, why in problems.items() if why and svc in docker_ops.OPTIONAL_SERVICES]
                health["optional_unavailable"] = sorted(set(health.get("optional_unavailable") or [])
                                                        | set(optional_off))
            except docker_ops.OpsUnavailable as exc:
                health["failing"].append("containers")
                health["checks"]["containers"] = {"ok": False, "error": str(exc)}
        repairs: list = []
        if settings.SELF_HEALING_ENABLED and ops.available:
            for service in sorted({c.service for c in containers}):
                key = f"selfheal:strikes:{service}"
                if service not in broken:
                    await redis.delete(key)
                    continue
                strikes = int(await redis.incr(key))
                await redis.expire(key, 3600)
                if strikes < 2 or service in docker_ops.NEVER_RESTART or service not in docker_ops.RESTARTABLE:
                    continue
                try:
                    result = await ops.restart(service)
                    repairs.append({"service": service, "restarted": result["containers"]})
                    await redis.delete(key)
                except (docker_ops.OpsRefused, docker_ops.OpsUnavailable) as exc:
                    repairs.append({"service": service, "error": str(exc)})

        failing = sorted(set(health["failing"]) | {f"service:{s}" for s in broken})
        state = "healthy" if not failing else "degraded: " + ", ".join(failing)
        summary = f"Scheduled '{job_name}': {state}."
        if health.get("optional_unavailable"):
            summary += " Optional, not running: " + ", ".join(sorted(health["optional_unavailable"])) + "."
        if repairs:
            summary += " Repairs: " + "; ".join(
                f"{r['service']} {'restarted' if 'restarted' in r else 'not restarted (' + r['error'] + ')'}"
                for r in repairs)

        ws_id = (await db.execute(select(Workspace.id).order_by(Workspace.created_at.asc()).limit(1))
                 ).scalar_one_or_none()
        previous = await redis.get(f"scheduler:last_state:{job_name}")
        if ws_id is not None and (previous != state or repairs):
            db.add(LiveOperationsFeedItem(
                id=uuid4(), workspace_id=ws_id, item_type="self_healing" if repairs else "health",
                severity="warning" if failing else "info",
                title=("Self-healing restarted a service" if repairs else
                       ("JAI health degraded" if failing else "JAI health restored" if previous else
                        "JAI health check")),
                message=summary, requires_action=bool(failing and not repairs),
                created_at=now, updated_at=now))
        await redis.set(f"scheduler:last_state:{job_name}", state)
        db.add(AuditLog(
            id=uuid4(), workspace_id=ws_id, actor_type="scheduler",
            action="scheduled_run", action_category="scheduler", description=summary,
            target_type="scheduled_job", target_id=job_name,
            after_state={"job": job_name, "state": state, "failing": failing, "repairs": repairs,
                         "description": description},
            success=not failing or bool(repairs), created_at=now, updated_at=now))
        await db.commit()
        return {"job": job_name, "state": state, "failing": failing, "repairs": repairs, "summary": summary}


@celery_app.task(name="scheduled_status_loop", bind=True)
def scheduled_status_loop(self: Task) -> dict[str, Any]:
    """Daily operating / heartbeat loop — runs autonomously via Celery Beat."""
    return run_async(_run_scheduled_loop(
        "daily_status_check",
        "Autonomous health check and self-healing of JAI's own services (no operator command)."))


# ===== Mission runtime (Repair 12) =====

@celery_app.task(name="run_mission", bind=True, acks_late=True, reject_on_worker_lost=True)
def run_mission(self: Task, task_id: str, reason: str = "") -> dict[str, Any]:
    """Claim and run one queued mission. A duplicate delivery is a no-op: the
    claim only succeeds for a mission that is still queued or recovering."""
    from app.core.runtime.missions import MissionRunner

    logger.info(f"run_mission {task_id} ({reason or 'dispatch'}) on {self.request.hostname}")
    return run_async(MissionRunner().run(task_id))


@celery_app.task(name="resume_checkpoint", bind=True, acks_late=True)
def resume_checkpoint_task(self: Task, checkpoint_id: str, user_id: str) -> dict[str, Any]:
    """Resume a boundary-paused mission after Richard approved it. The workflow
    is idempotent, so a redelivered message cannot run the action twice."""
    from app.core.runtime.dispatcher import resume_checkpoint

    return run_async(resume_checkpoint(checkpoint_id, user_id))


@celery_app.task(name="backup_database", bind=True)
def backup_database(self: Task) -> dict[str, Any]:
    """Scheduled backup of JAI's database, verified straight after (Celery beat)."""
    from app.core.database import AsyncSessionLocal
    from app.core.ops.backups import BackupError, create_backup, verify_backup

    async def run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            try:
                record = await create_backup(db, workspace_id=None, reason="scheduled backup",
                                             retention_days=int(settings.BACKUP_RETENTION_DAYS))
                verification = await verify_backup(db, record)
            except BackupError as exc:
                await db.commit()
                logger.error(f"Scheduled backup failed: {exc}")
                return {"success": False, "error": str(exc)}
            await db.commit()
            return {"success": verification["verified"], "backup_id": str(record.id),
                    "file": record.backup_name, "size_bytes": record.backup_size_bytes}

    return run_async(run())


@celery_app.task(name="recover_stale_missions", bind=True)
def recover_stale_missions(self: Task) -> dict[str, Any]:
    """Re-queue missions whose worker stopped heartbeating, and time out
    sub-agents whose run stopped without a result (Celery beat)."""
    from app.core.database import AsyncSessionLocal
    from app.core.runtime.missions import MissionRunner
    from app.core.swarm.sub_agent import SubAgentManager

    async def run() -> dict[str, Any]:
        summary = await MissionRunner().recover_stale()
        async with AsyncSessionLocal() as db:
            timed_out = await SubAgentManager().time_out_stale(db)
            await db.commit()
        return {**summary, "sub_agents_timed_out": [str(i) for i in timed_out]}

    return run_async(run())


@celery_app.task(name="company_daily_loop", bind=True)
def company_daily_loop(self: Task) -> dict[str, Any]:
    """Run the daily operating loop for every active workspace with company mode on (Celery beat)."""
    from app.core.company_ops.service import company_ops
    from app.core.database import AsyncSessionLocal

    async def run() -> dict[str, Any]:
        from sqlalchemy import select

        from app.models.workspace import Workspace

        results: dict[str, Any] = {}
        async with AsyncSessionLocal() as db:
            ids = (await db.execute(select(Workspace.id).where(
                Workspace.company_mode_enabled.is_(True), Workspace.is_active.is_(True),
                Workspace.is_archived.is_(False)))).scalars().all()
            for ws_id in ids:
                try:
                    loop = await company_ops.run_daily_loop(db, ws_id)
                    await db.commit()
                    results[str(ws_id)] = loop.summary
                except Exception as exc:  # noqa: BLE001 - one workspace's failure does not stop the others
                    await db.rollback()
                    logger.error(f"Daily loop failed for workspace {ws_id}: {exc}")
                    results[str(ws_id)] = f"failed: {exc}"
        return {"workspaces": len(results), "results": results}

    return run_async(run())


@celery_app.task(name="workflows_advance", bind=True)
def workflows_advance(self: Task) -> dict[str, Any]:
    """Move each workflow on when its mission has finished or Richard has decided its gate (Celery beat)."""
    from app.core.database import AsyncSessionLocal
    from app.core.councils import service as workflows

    async def run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            return await workflows.tick(db)

    return run_async(run())


@celery_app.task(name="sales_send_due", bind=True)
def sales_send_due(self: Task) -> dict[str, Any]:
    """Send the sales emails Richard approved that are due now, in every workspace (Upgrade 6, Celery beat)."""
    from sqlalchemy import select

    from app.core.business.prospecting import prospecting_service
    from app.core.database import AsyncSessionLocal
    from app.models.prospecting import OutreachMessage

    async def run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            spaces = (await db.execute(select(OutreachMessage.workspace_id).where(
                OutreachMessage.status == "approved").distinct())).scalars().all()
            results = {}
            for workspace_id in spaces:
                outcome = await prospecting_service.send_due(db, workspace_id)
                await db.commit()
                results[str(workspace_id)] = {"sent": len(outcome["sent"]), "waiting": outcome["waiting"],
                                              "reason": outcome["reason"]}
        return {"workspaces": len(results), "results": results}

    return run_async(run())


@celery_app.task(name="knowledge_refresh", bind=True)
def knowledge_refresh(self: Task) -> dict[str, Any]:
    """Re-fetch every catalogue source; changed pages get a new version of their passages (Celery beat)."""
    from collections import Counter

    from app.core.database import AsyncSessionLocal
    from app.core.knowledge.documentation import catalogue
    from app.core.knowledge.ingest import knowledge_ingestor

    async def run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            results = await knowledge_ingestor.install(db, catalogue())
        counts = Counter(r["status"] for r in results)
        return {"sources": len(results), "counts": dict(counts),
                "errors": [{"url": r["url"], "reason": r.get("reason")} for r in results if r["status"] == "error"]}

    return run_async(run())


async def _home_workspace(db):
    """The workspace JAI's own notices go to: the Command Center, or the oldest active workspace."""
    from sqlalchemy import select

    from app.models.workspace import Workspace

    rows = (await db.execute(select(Workspace).where(Workspace.is_active.is_(True), Workspace.is_archived.is_(False))
                             .order_by(Workspace.created_at))).scalars().all()
    home = next((w for w in rows if (w.name or "").lower() == "command center"), rows[0] if rows else None)
    return home


@celery_app.task(name="approvals_digest_daily", bind=True)
def approvals_digest_daily(self: Task) -> dict[str, Any]:
    """One morning digest of everything waiting for Richard, grouped by kind of action (Celery beat)."""
    from app.core import approvals_digest
    from app.core.database import AsyncSessionLocal

    async def run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            home = await _home_workspace(db)
            if home is None:
                return {"total": 0}
            result = await approvals_digest.post(db, home.id, home.owner_id)
            await db.commit()
        return {"total": result["total"], "by_class": result["by_class"]}

    return run_async(run())
