"""
JAI Backend - Telling a working mission something

When Richard says something about a mission that is working right now ("stop adding rows to the booking database
and tidy the sheets"), it goes to the agent doing that mission, at its next step, in his own words. Before this a
second mission started beside the first, with its own agent writing the same files (14 November).

The notes wait in Redis under the mission's id; the role's agent reads them at the top of each step
(role_mission.RoleExecutor._notes). A mission run by the software builder in its sandbox cannot be told this way,
so a follow-up to one starts as a mission that carries it on, as before.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 3600
FRESH_MINUTES = 12  # a working mission has taken a step this recently
NOTE_CHARS = 4000


def key(task_id: Any) -> str:
    return f"mission:notes:{task_id}"


async def _redis():
    from app.core.redis import get_redis

    return await asyncio.wait_for(get_redis(), timeout=2)


async def can_tell(task: Any) -> bool:
    """The mission is working now, on a role's own agent (which reads its notes), and took a step recently."""
    if task is None or task.status not in ("running", "resuming"):
        return False
    try:
        from app.core.command import progress
        from app.core.command.mission_org import SPECIALISTS

        live = await progress.load(task.id) or {}
        packages = (live.get("team") or {}).get("packages") or []
        if len(packages) != 1 or packages[0].get("specialist") not in SPECIALISTS:
            return False
        if live.get("phase") != "working":
            return False  # the independent check or the report is under way: the work is over
        since = progress.age(live).get("minutes_since_last_step")
        return since is not None and since <= FRESH_MINUTES
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"could not tell whether the mission can be told: {exc}")
        return False


async def tell(task_id: Any, text: str) -> bool:
    """Leave Richard's words for the mission's agent. True when they were kept."""
    try:
        redis = await _redis()
        note = json.dumps({"text": (text or "").strip()[:NOTE_CHARS],
                           "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        await asyncio.wait_for(redis.rpush(key(task_id), note), timeout=2)
        await asyncio.wait_for(redis.expire(key(task_id), TTL_SECONDS), timeout=2)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"note for mission {task_id} not kept: {exc}")
        return False


async def take(task_id: Any) -> List[str]:
    """Richard's words left for this mission since its agent last looked (each is given once). Never raises."""
    if task_id is None:
        return []
    out: List[str] = []
    try:
        redis = await _redis()
        for _ in range(10):
            raw: Optional[Any] = await asyncio.wait_for(redis.lpop(key(task_id)), timeout=2)
            if raw is None:
                break
            try:
                out.append(str(json.loads(raw).get("text") or ""))
            except (TypeError, ValueError):
                out.append(str(raw))
        for note in [n for n in out if n]:  # kept for the mission's later rounds
            await asyncio.wait_for(redis.rpush(_said_key(task_id), note), timeout=2)
        if out:
            await asyncio.wait_for(redis.expire(_said_key(task_id), 21 * 24 * 3600), timeout=2)
    except Exception as exc:  # noqa: BLE001 - the mission works on without it
        logger.debug(f"mission notes not read: {exc}")
    return [note for note in out if note]


def _said_key(task_id: Any) -> str:
    return f"mission:told:{task_id}"


async def said(task_id: Any) -> List[str]:
    """Everything Richard has told this mission while it worked, oldest first (kept for its later rounds)."""
    if task_id is None:
        return []
    try:
        redis = await _redis()
        rows = await asyncio.wait_for(redis.lrange(_said_key(task_id), 0, 19), timeout=2)
        return [row.decode() if isinstance(row, bytes) else str(row) for row in rows or []]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"what the mission was told not read: {exc}")
        return []


def standing(notes: List[str]) -> str:
    lines = "\n".join(f"- \u201c{note}\u201d" for note in notes)
    return ("WHAT RICHARD SAID ABOUT THIS MISSION WHILE IT WORKED (it still applies; where it changes what the "
            f"mission asks for, his latest words win):\n{lines}")


def as_message(notes: List[str]) -> str:
    said = "\n\n".join(f"“{note}”" for note in notes)
    return ("[RICHARD HAS JUST SAID THIS ABOUT THE MISSION YOU ARE DOING] Follow it from this step on; where it "
            f"changes what the mission asks for, his latest words win:\n{said}\n\nSay in one line how this changes "
            "what you do next, then do it.")
