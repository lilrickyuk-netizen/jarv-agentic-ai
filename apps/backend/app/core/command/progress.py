"""
JAI Backend - A mission's live progress

After every step a mission keeps a short record of where it is: the round and step, what it is doing (working,
the independent check, writing the report), each requirement's status, the files it changed, the commands it
ran with their exit codes, what failed and why, and what the step cost. It is kept in Redis for seven days, keyed
by the mission, so anyone asking "how is it going?" (the voice, the dashboard) reads the facts of this moment
without touching the mission's own database transaction.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

TTL_SECONDS = 7 * 24 * 3600
EDITS = ("write_file", "edit_file", "move_file", "copy_file", "create_folder", "delete_file_with_boundary")


def key(task_id: Any) -> str:
    return f"mission:progress:{task_id}"


def _relative(path: str, root: Optional[str]) -> str:
    """A path as the workspace sees it: relative to its folder, forward slashes (as the evidence graph keys it)."""
    norm = str(path).replace("\\", "/").strip()
    base = str(root or "").replace("\\", "/").rstrip("/")
    if base and norm.lower().startswith(base.lower() + "/"):
        norm = norm[len(base) + 1:]
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _target(call: Dict[str, Any], root: Optional[str] = None) -> str:
    inputs = call.get("inputs") or {}
    for name in ("command", "path", "destination", "file_path", "url", "query", "id"):
        if inputs.get(name):
            value = str(inputs[name])
            return (value if name in ("command", "url", "query", "id") else _relative(value, root))[:160]
    return ""


def _exit_code(call: Dict[str, Any]) -> Optional[int]:
    value = (call.get("output") or {}).get("exit_code")
    return value if isinstance(value, int) else None


def snapshot(calls: List[Dict[str, Any]], requirements: List[Dict[str, Any]], *, round_no: int, step: int,
             step_budget: int, phase: str, usage: Optional[Dict[str, Any]] = None,
             started_at: Optional[str] = None, root: Optional[str] = None) -> Dict[str, Any]:
    """Where a mission is now, from its own tool calls and requirement list."""
    files: List[str] = []
    for call in calls:
        if call.get("tool") in EDITS and call.get("success"):
            target = _target(call, root)
            if target and target not in files:
                files.append(target)
    commands = [{"command": _target(c), "exit_code": _exit_code(c), "ok": bool(c.get("success"))}
                for c in calls if c.get("tool") == "run_command"]
    failures = [{"tool": c.get("tool"), "target": _target(c, root), "why": str(c.get("summary") or "")[:200]}
                for c in calls if not c.get("success")]
    counts: Dict[str, int] = {}
    for req in requirements:
        status = str(req.get("status") or "open")
        counts[status] = counts.get(status, 0) + 1
    last = calls[-1] if calls else None
    cost = (usage or {}).get("cost_usd")
    return {
        "phase": phase, "round": round_no, "step": step, "step_budget": step_budget,
        "started_at": started_at, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "doing_now": ({"tool": last.get("tool"), "target": _target(last, root), "ok": bool(last.get("success")),
                       "result": str(last.get("summary") or "")[:200]} if last else None),
        "requirements": {"total": len(requirements), "by_status": counts,
                         "items": [{"id": r.get("id"), "text": str(r.get("text") or "")[:140],
                                    "status": r.get("status") or "open",
                                    "evidence": str(r.get("evidence") or "")[:120]} for r in requirements[:40]]},
        "files_changed": files[-25:], "files_changed_count": len(files),
        "commands_run": len(commands), "commands_failed": sum(1 for c in commands if not c["ok"]),
        "recent_commands": commands[-6:],
        "recent_failures": failures[-5:],
        "tokens": ({k: (usage or {}).get(k) for k in ("calls", "input", "cached", "output")}
                   | ({"cost_usd": cost} if cost is not None else {})) if usage else None,
    }


async def save(task_id: Any, data: Dict[str, Any]) -> bool:
    """Store a mission's progress. Never raises: progress is a view of the mission, never a reason to stop it."""
    if task_id is None:
        return False
    try:
        from app.core.redis import get_redis

        redis = await asyncio.wait_for(get_redis(), timeout=2)
        await asyncio.wait_for(redis.set(key(task_id), json.dumps(data, default=str), ex=TTL_SECONDS), timeout=2)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"mission progress not saved: {exc}")
        return False


async def load(task_id: Any) -> Optional[Dict[str, Any]]:
    try:
        from app.core.redis import get_redis

        redis = await asyncio.wait_for(get_redis(), timeout=2)
        raw = await asyncio.wait_for(redis.get(key(UUID(str(task_id)))), timeout=2)
        return json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"mission progress not read: {exc}")
        return None
