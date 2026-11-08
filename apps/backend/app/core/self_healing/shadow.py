"""
JAI Backend - Self-healing actions earn their autonomy in shadow first

On independent benchmarks AI repair agents find the exact root cause about a fifth of the time, and a fixed runbook
repairs nearly as well as the best agent. So JAI repairs only through runbook actions, and an action that has not
been promoted runs in shadow: JAI records what it would have done ("would have restarted voice: unhealthy for 3
checks") instead of doing it. Richard promotes an action once its shadow record looks right
(POST /api/operations/healing/actions/{action}/promote) and can demote it again at any time.

Restarting the backend and the worker were proven before shadow mode existed and are live from the start. Restarting
postgres, redis and the Docker proxy is never done automatically, promoted or not.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

LIVE_FROM_THE_START = frozenset({"restart:backend", "restart:worker"})
NEVER = frozenset({"restart:postgres", "restart:redis", "restart:docker-proxy"})
LIVE_KEY = "healing:live"
LOG_KEY = "healing:shadow-log"
LOG_LENGTH = 200


async def _redis():
    from app.core.redis import get_redis

    return await asyncio.wait_for(get_redis(), timeout=2)


async def promoted() -> List[str]:
    try:
        return sorted(str(v) for v in await (await _redis()).smembers(LIVE_KEY))
    except Exception as exc:  # noqa: BLE001
        logger.info(f"promoted healing actions not read: {exc}")
        return []


async def is_live(action: str) -> bool:
    if action in NEVER:
        return False
    if action in LIVE_FROM_THE_START:
        return True
    return action in await promoted()


async def promote(action: str) -> Dict[str, Any]:
    if action in NEVER:
        raise ValueError(f"{action} is never done automatically")
    await (await _redis()).sadd(LIVE_KEY, action)
    return {"action": action, "live": True}


async def demote(action: str) -> Dict[str, Any]:
    await (await _redis()).srem(LIVE_KEY, action)
    return {"action": action, "live": action in LIVE_FROM_THE_START}


async def would_have(action: str, reason: str, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Record what the action would have done (shadow mode), and return that as the action's result."""
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "action": action, "reason": reason,
             **({"details": details} if details else {})}
    try:
        redis = await _redis()
        await redis.lpush(LOG_KEY, json.dumps(entry, default=str))
        await redis.ltrim(LOG_KEY, 0, LOG_LENGTH - 1)
    except Exception as exc:  # noqa: BLE001
        logger.info(f"shadow record not kept: {exc}")
    logger.warning(f"self-healing in shadow: would have done {action} ({reason})")
    return {"action": action, "shadow": True, "recovered": False,
            "note": f"Shadow mode: JAI would have done {action} ({reason}); promote it to let JAI do it."}


async def log(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        rows = await (await _redis()).lrange(LOG_KEY, 0, max(0, limit - 1))
    except Exception as exc:  # noqa: BLE001
        logger.info(f"shadow log not read: {exc}")
        return []
    out = []
    for row in rows:
        try:
            out.append(json.loads(row))
        except (TypeError, ValueError):
            continue
    return out
