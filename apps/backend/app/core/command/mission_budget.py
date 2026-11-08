"""
JAI Backend - What one mission may spend on AI

The daily limit stops all spending for the day; on 8 November one MYCO mission and a duplicated video run used the
whole of it. Each mission now has its own allowance (MISSION_MAX_COST_USD, US dollars) across all its rounds and
re-queues: the team books what it spends as it goes, no package is given more than what is left, and when the
allowance is used the mission stops, keeps its progress and reports. A new mission ("carry on ...") starts a new
allowance; a resume Richard asks for gives the same mission a new one.

Kept in Redis for a week. If Redis cannot be reached the allowance is not enforced (the daily limit still is): the
budget is a guard, never the reason a mission cannot run.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

KEY = "mission:spend:{}"
TTL_SECONDS = 7 * 24 * 3600


def cap() -> float:
    """The allowance per mission in US dollars; 0 means no allowance (only the daily limit)."""
    return float(getattr(settings, "MISSION_MAX_COST_USD", 0) or 0)


async def _redis():
    from app.core.redis import get_redis

    return await asyncio.wait_for(get_redis(), timeout=2)


async def spent(task_id: Any) -> float:
    if task_id is None:
        return 0.0
    try:
        value = await asyncio.wait_for((await _redis()).get(KEY.format(task_id)), timeout=2)
        return float(value or 0)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"mission spend not read: {exc}")
        return 0.0


async def add(task_id: Any, usd: float) -> None:
    if task_id is None or not usd or usd <= 0:
        return
    try:
        redis = await _redis()
        await asyncio.wait_for(redis.incrbyfloat(KEY.format(task_id), float(usd)), timeout=2)
        await asyncio.wait_for(redis.expire(KEY.format(task_id), TTL_SECONDS), timeout=2)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"mission spend not recorded (${usd:.4f}): {exc}")


async def reset(task_id: Any) -> None:
    if task_id is None:
        return
    try:
        await asyncio.wait_for((await _redis()).delete(KEY.format(task_id)), timeout=2)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"mission spend not reset: {exc}")


async def left(task_id: Any) -> Optional[float]:
    """What the mission may still spend, or None when there is no allowance."""
    allowance = cap()
    if allowance <= 0:
        return None
    return max(0.0, allowance - await spent(task_id))
