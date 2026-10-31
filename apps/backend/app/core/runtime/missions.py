"""
JARV Backend - Mission runner and recovery

How a queued mission runs:

1. Claim. A worker atomically moves the mission from ``queued`` (or
   ``recovering``) to ``running`` and records itself as the lease owner. Two
   workers can never run the same mission: the losing claim updates no row.
2. Heartbeat. While the mission runs, the worker refreshes ``heartbeat_at``
   every ``HEARTBEAT_SECONDS`` from its own database session (a separate column,
   so it never overwrites the mission's own updates).
3. Run. The command pipeline (or a continuation round) executes and records
   its outcome through the enforced lifecycle.
4. Continue. A mission that stopped at its step limit is re-queued and
   continued automatically, up to ``MAX_AUTO_CONTINUATIONS``.

How a mission whose worker died is recovered:

The sweeper (Celery beat every minute, and once at API startup) finds running
missions whose heartbeat is older than ``STALE_AFTER_SECONDS``, moves them
``running -> recovering -> queued`` and dispatches them again. A mission whose
worker is lost more than ``MAX_RECOVERIES`` times is failed with the reason.
Missions queued for longer than ``QUEUE_STALE_SECONDS`` without a worker
picking them up are dispatched again.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.runtime import lifecycle
from app.models.company_operations import LiveOperationsFeedItem
from app.models.task import Task

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = float(getattr(settings, "MISSION_HEARTBEAT_SECONDS", 15))
STALE_AFTER_SECONDS = float(getattr(settings, "MISSION_STALE_SECONDS", 120))
QUEUE_STALE_SECONDS = float(getattr(settings, "MISSION_QUEUE_STALE_SECONDS", 600))
MAX_RECOVERIES = int(getattr(settings, "MISSION_MAX_RECOVERIES", 2))
# Missions left "running" by the old in-request pipeline (no heartbeat ever
# written) are failed honestly rather than replayed long after they were sent.
LEGACY_ABANDON_SECONDS = 3600

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
MISSION_TASK_TYPE = "command"

SessionFactory = Callable[[], Any]


def _now() -> datetime:
    return datetime.now(timezone.utc)


_factory_override: Optional[SessionFactory] = None


def set_session_factory(factory: Optional[SessionFactory]) -> None:
    """Point the runtime at another database (tests use the test database)."""
    global _factory_override
    _factory_override = factory


def session_factory() -> SessionFactory:
    if _factory_override is not None:
        return _factory_override
    from app.core.database import AsyncSessionLocal

    return AsyncSessionLocal


_default_factory = session_factory


def _feed(db: AsyncSession, task: Task, title: str, message: str, severity: str = "info") -> None:
    now = _now()
    db.add(LiveOperationsFeedItem(
        id=uuid4(), workspace_id=task.workspace_id, item_type="mission_runtime",
        severity=severity, title=title, message=message[:1000], related_task_id=task.id,
        requires_action=False, created_at=now, updated_at=now,
    ))


class MissionRunner:
    """Claims, runs, heartbeats, continues, and recovers missions."""

    def __init__(self, session_factory: Optional[SessionFactory] = None, worker_id: str = WORKER_ID):
        self.session_factory = session_factory or _default_factory()
        self.worker_id = worker_id

    # ----- claim / lease ------------------------------------------------------

    async def claim(self, db: AsyncSession, task_id: UUID) -> Optional[Task]:
        """Atomically take ownership of a queued or recovering mission."""
        current = (await db.execute(select(Task.status).where(Task.id == task_id))).scalar_one_or_none()
        if current is None or lifecycle.normalise(current) not in (lifecycle.QUEUED, lifecycle.RECOVERING):
            return None
        now = _now()
        claimed = await db.execute(
            update(Task)
            .where(Task.id == task_id, Task.status == current)
            .values(status=lifecycle.RUNNING, lease_owner=self.worker_id, heartbeat_at=now,
                    updated_at=now, started_at=func.coalesce(Task.started_at, now))
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            await db.rollback()
            return None
        task = (await db.execute(
            select(Task).where(Task.id == task_id).execution_options(populate_existing=True)
        )).scalar_one()
        lifecycle.record_history(task, lifecycle.normalise(current), lifecycle.RUNNING,
                                 reason="claimed by worker", actor=self.worker_id)
        task.updated_at = now
        await db.commit()
        return task

    async def _heartbeat(self, task_id: UUID) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                async with self.session_factory() as db:
                    await db.execute(
                        update(Task)
                        .where(Task.id == task_id, Task.lease_owner == self.worker_id)
                        .values(heartbeat_at=_now())
                        .execution_options(synchronize_session=False)
                    )
                    await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a missed beat is retried next interval
                logger.warning(f"heartbeat failed for mission {task_id}: {exc}")

    async def _release(self, task_id: UUID) -> None:
        try:
            async with self.session_factory() as db:
                await db.execute(
                    update(Task)
                    .where(Task.id == task_id, Task.lease_owner == self.worker_id)
                    .values(lease_owner=None)
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"lease release failed for mission {task_id}: {exc}")

    # ----- run -----------------------------------------------------------------

    async def run(self, task_id: UUID | str) -> Dict[str, Any]:
        """Claim and execute one mission. Returns a summary of what happened."""
        task_id = UUID(str(task_id))
        from app.core.observability.context import mission_context

        with mission_context(task_id):
            return await self._run(task_id)

    async def _run(self, task_id: UUID) -> Dict[str, Any]:
        async with self.session_factory() as db:
            task = await self.claim(db, task_id)
            if task is None:
                status = (await db.execute(select(Task.status).where(Task.id == task_id))).scalar_one_or_none()
                logger.info(f"mission {task_id} not claimed (status={status})")
                return {"task_id": str(task_id), "claimed": False, "status": status}

            heartbeat = asyncio.create_task(self._heartbeat(task_id))
            try:
                meta = task.meta_data or {}
                if meta.get("resume_mode") == "continuation":
                    from app.core.command.continuation import continue_mission

                    outcome = await continue_mission(db, task, operator=meta.get("operator") or "operator")
                else:
                    from app.core.command import CommandService

                    service = CommandService(model=meta.get("model"))
                    outcome = (await service.run_task(db, task)).to_dict()
            except Exception as exc:  # noqa: BLE001 - recorded on the mission, never swallowed silently
                logger.error(f"mission {task_id} crashed: {exc}", exc_info=True)
                await db.rollback()
                await self._fail(task_id, f"Mission runner error: {exc}")
                outcome = {"task_id": str(task_id), "status": lifecycle.FAILED, "error": str(exc)}
            finally:
                heartbeat.cancel()
                try:
                    await heartbeat
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                await self._release(task_id)

        outcome["claimed"] = True
        outcome["continued"] = await self._auto_continue(task_id)
        return outcome

    async def _fail(self, task_id: UUID, reason: str) -> None:
        async with self.session_factory() as db:
            task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
            if task is None or lifecycle.normalise(task.status) in lifecycle.TERMINAL:
                return
            if lifecycle.can_transition(task.status, lifecycle.FAILED):
                lifecycle.transition(task, lifecycle.FAILED, reason=reason, actor=self.worker_id)
                task.error_message = reason[:4000]
                _feed(db, task, "Mission failed", reason, severity="error")
                await db.commit()

    async def _auto_continue(self, task_id: UUID) -> bool:
        """Re-queue a mission that paused at its step limit, within the cap."""
        from app.core.command.continuation import MAX_AUTO_CONTINUATIONS, automatic_rounds

        async with self.session_factory() as db:
            task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
            if task is None or lifecycle.normalise(task.status) != lifecycle.NEEDS_CONTINUATION:
                return False
            done = automatic_rounds(task)
            if done >= MAX_AUTO_CONTINUATIONS:
                _feed(db, task, "Continuation limit reached",
                      f"Mission paused after {done} automatic continuations; resume it to keep going.",
                      severity="warning")
                await db.commit()
                return False
            lifecycle.transition(task, lifecycle.QUEUED, actor=self.worker_id,
                                 reason=f"automatic continuation {done + 1}")
            task.result = {**(task.result if isinstance(task.result, dict) else {}), "auto_rounds": done + 1}
            task.meta_data = {**(task.meta_data or {}), "resume_mode": "continuation"}
            await db.commit()
        from app.core.runtime.dispatcher import dispatch_mission

        await dispatch_mission(task_id, reason="automatic continuation")
        return True

    # ----- recovery ------------------------------------------------------------

    async def recover_stale(self) -> Dict[str, Any]:
        """Re-queue missions whose worker died; re-dispatch missions nobody picked up."""
        now = _now()
        stale_cutoff = now - timedelta(seconds=STALE_AFTER_SECONDS)
        queue_cutoff = now - timedelta(seconds=QUEUE_STALE_SECONDS)
        legacy_cutoff = now - timedelta(seconds=LEGACY_ABANDON_SECONDS)
        requeue: List[UUID] = []
        summary: Dict[str, Any] = {"recovered": [], "failed": [], "abandoned": [], "redispatched": []}

        async with self.session_factory() as db:
            query = select(Task).where(
                Task.task_type == MISSION_TASK_TYPE,
                Task.status == lifecycle.RUNNING,
                or_(Task.heartbeat_at < stale_cutoff,
                    and_(Task.heartbeat_at.is_(None), Task.updated_at < stale_cutoff)),
            )
            if _dialect(db) == "postgresql":
                query = query.with_for_update(skip_locked=True)
            for task in (await db.execute(query)).scalars().all():
                if task.heartbeat_at is None:
                    if _aware(task.updated_at) < legacy_cutoff:
                        lifecycle.transition(task, lifecycle.FAILED, actor="recovery",
                                             reason="abandoned by the in-request pipeline before recovery existed")
                        task.error_message = "Mission was interrupted and is too old to replay safely."
                        _feed(db, task, "Interrupted mission closed", task.error_message, severity="warning")
                        summary["abandoned"].append(str(task.id))
                        continue
                lost = task.lease_owner or "unknown worker"
                lifecycle.transition(task, lifecycle.RECOVERING, actor="recovery",
                                     reason=f"{lost} stopped heartbeating")
                task.lease_owner = None
                task.retry_count = (task.retry_count or 0) + 1
                if task.retry_count > MAX_RECOVERIES:
                    reason = f"Worker lost {task.retry_count} times; mission stopped to avoid a loop."
                    lifecycle.transition(task, lifecycle.FAILED, actor="recovery", reason=reason)
                    task.error_message = reason
                    _feed(db, task, "Mission failed after repeated worker loss", reason, severity="error")
                    summary["failed"].append(str(task.id))
                    continue
                lifecycle.transition(task, lifecycle.QUEUED, actor="recovery",
                                     reason=f"re-queued after worker loss (attempt {task.retry_count + 1})")
                _feed(db, task, "Mission recovered",
                      f"The worker running this mission stopped ({lost}); it was re-queued automatically.",
                      severity="warning")
                requeue.append(task.id)
                summary["recovered"].append(str(task.id))

            stuck = (await db.execute(select(Task).where(
                Task.task_type == MISSION_TASK_TYPE,
                Task.status == lifecycle.QUEUED,
                Task.updated_at < queue_cutoff,
            ))).scalars().all()
            for task in stuck:
                task.updated_at = now
                lifecycle.record_history(task, lifecycle.QUEUED, lifecycle.QUEUED, actor="recovery",
                                         reason="no worker picked the mission up; dispatched again")
                requeue.append(task.id)
                summary["redispatched"].append(str(task.id))
            await db.commit()

        from app.core.runtime.dispatcher import dispatch_mission

        for task_id in requeue:
            await dispatch_mission(task_id, reason="recovery")
        if any(summary.values()):
            logger.warning(f"mission recovery: {summary}")
        return summary


def _dialect(db: AsyncSession) -> str:
    try:
        return db.get_bind().dialect.name
    except Exception:  # noqa: BLE001
        return ""


def _aware(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def cancel_mission(db: AsyncSession, task: Task, *, actor: str, reason: str = "") -> bool:
    """Cancel a mission that has not finished. A running worker's outcome will not
    overwrite the cancellation; the worker is also signalled to stop."""
    if not lifecycle.can_transition(task.status, lifecycle.CANCELLED):
        return False
    lifecycle.transition(task, lifecycle.CANCELLED, actor=actor, reason=reason or "cancelled by operator")
    _feed(db, task, "Mission cancelled", reason or "Cancelled by the operator.", severity="warning")
    celery_id = (task.meta_data or {}).get("celery_task_id")
    if celery_id:
        try:
            from app.core.celery import celery_app

            celery_app.control.revoke(celery_id, terminate=True)
        except Exception as exc:  # noqa: BLE001 - the status change alone stops the outcome being recorded
            logger.warning(f"could not signal worker for {task.id}: {exc}")
    await db.flush()
    return True


async def retry_mission(db: AsyncSession, task: Task, *, actor: str) -> bool:
    """Run a failed or partial mission again from the start."""
    if lifecycle.normalise(task.status) not in (lifecycle.FAILED, lifecycle.PARTIAL):
        return False
    lifecycle.transition(task, lifecycle.QUEUED, actor=actor, reason="retry requested")
    task.meta_data = {k: v for k, v in (task.meta_data or {}).items() if k != "resume_mode"}
    task.error_message = None
    task.retry_count = 0
    await db.flush()
    return True
