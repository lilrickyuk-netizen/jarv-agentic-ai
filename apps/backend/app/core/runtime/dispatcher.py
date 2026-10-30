"""
JARV Backend - Mission dispatch

Hands a queued mission to something that will run it. Modes
(``MISSION_EXECUTION_MODE``):

- ``celery``     (default) Send to the Celery worker queue. Missions survive API
                 restarts, run 24/7 on the cloud runner, and a worker that dies
                 mid-mission has the message redelivered (acks_late) and the
                 mission recovered by the sweeper. If the broker cannot be
                 reached, the mission runs in the API process instead and the
                 fallback is logged and shown in the operations feed.
- ``background`` Run in the API process without blocking the request. For a
                 single-machine setup with no worker container. The sweeper
                 still recovers missions interrupted by a restart.
- ``sync``       Run to completion before returning. Used by tests and scripts.
- ``deferred``   Record only; something else runs the mission. The default
                 inside the unit-test suite so API tests do not execute
                 missions unless a test opts in.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional, Set
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

MODES = ("celery", "background", "sync", "deferred")
_background: Set[asyncio.Task] = set()


def execution_mode() -> str:
    configured = (os.getenv("MISSION_EXECUTION_MODE")
                  or getattr(settings, "MISSION_EXECUTION_MODE", None) or "").strip().lower()
    if configured in MODES:
        return configured
    return "deferred" if settings.TESTING else "celery"


async def _record_dispatch(task_id: UUID, mode: str, celery_id: Optional[str], note: str) -> None:
    from sqlalchemy import select

    from app.core.runtime.missions import _feed, session_factory
    from app.models.task import Task

    try:
        async with session_factory()() as db:
            task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
            if task is None:
                return
            meta = dict(task.meta_data or {})
            meta["dispatch_mode"] = mode
            if celery_id:
                meta["celery_task_id"] = celery_id
            task.meta_data = meta
            if note:
                _feed(db, task, "Mission dispatch", note, severity="warning")
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - dispatch itself already happened
        logger.warning(f"could not record dispatch for {task_id}: {exc}")


def _spawn(coro) -> None:
    job = asyncio.get_running_loop().create_task(coro)
    _background.add(job)
    job.add_done_callback(_background.discard)


async def _run_in_process(task_id: UUID) -> Dict[str, Any]:
    from app.core.runtime.missions import MissionRunner

    return await MissionRunner().run(task_id)


async def dispatch_mission(task_id: UUID | str, *, reason: str = "") -> Dict[str, Any]:
    """Send a queued mission to be run. Never raises for a broker outage."""
    task_id = UUID(str(task_id))
    mode = execution_mode()
    if mode == "deferred":
        return {"task_id": str(task_id), "mode": mode, "dispatched": False}
    if mode == "sync":
        result = await _run_in_process(task_id)
        return {"task_id": str(task_id), "mode": mode, "dispatched": True, "result": result}
    if mode == "celery":
        try:
            from app.core.celery import celery_app

            sent = await asyncio.to_thread(
                celery_app.send_task, "run_mission", args=[str(task_id)], kwargs={"reason": reason})
            await _record_dispatch(task_id, mode, sent.id, "")
            return {"task_id": str(task_id), "mode": mode, "dispatched": True, "celery_task_id": sent.id}
        except Exception as exc:  # noqa: BLE001 - fall back so the mission still runs
            logger.error(f"worker queue unavailable, running mission {task_id} in-process: {exc}")
            await _record_dispatch(task_id, "background", None,
                                   "Worker queue unreachable; running this mission in the API process.")
            mode = "background"
    _spawn(_run_in_process(task_id))
    return {"task_id": str(task_id), "mode": mode, "dispatched": True}


async def dispatch_resume(checkpoint_id: UUID | str, user_id: str, *, reason: str = "") -> Dict[str, Any]:
    """Resume a boundary-paused mission from its checkpoint after approval."""
    checkpoint_id = UUID(str(checkpoint_id))
    mode = execution_mode()
    if mode == "deferred":
        return {"checkpoint_id": str(checkpoint_id), "mode": mode, "dispatched": False}
    if mode == "sync":
        return {"checkpoint_id": str(checkpoint_id), "mode": mode, "dispatched": True,
                "result": await resume_checkpoint(checkpoint_id, user_id)}
    if mode == "celery":
        try:
            from app.core.celery import celery_app

            sent = await asyncio.to_thread(
                celery_app.send_task, "resume_checkpoint", args=[str(checkpoint_id), str(user_id)])
            return {"checkpoint_id": str(checkpoint_id), "mode": mode, "dispatched": True,
                    "celery_task_id": sent.id}
        except Exception as exc:  # noqa: BLE001
            logger.error(f"worker queue unavailable, resuming {checkpoint_id} in-process: {exc}")
            mode = "background"
    _spawn(resume_checkpoint(checkpoint_id, user_id))
    return {"checkpoint_id": str(checkpoint_id), "mode": mode, "dispatched": True}


async def resume_checkpoint(checkpoint_id: UUID, user_id: str) -> Dict[str, Any]:
    """Run the Richard Boundary resume for one checkpoint in its own session."""
    from app.core.richard.workflow import RichardBoundaryWorkflow
    from app.core.runtime.missions import session_factory

    async with session_factory()() as db:
        result = await RichardBoundaryWorkflow(db).resume_mission(
            checkpoint_id=UUID(str(checkpoint_id)), authenticated_user_id=user_id)
        await db.commit()
        return result
