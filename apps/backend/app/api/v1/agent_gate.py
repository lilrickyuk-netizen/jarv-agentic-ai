"""
JAI Backend - The authority check for JAI's engineering sandbox

POST /api/agent-gate/check   may this sandbox run do this command or file action? {"allow", "reason"}
POST /api/agent-gate/record  what it did: written to the mission's audit trail, live feed and sub-agent log

Called only by the sandbox service, with the token JAI shares with it (OPENHANDS_TOKEN). A run JAI did not register
(app/core/command/sandbox_engine.py) is refused everything. The decisions are app/core/command/sandbox_policy.py.
"""
from __future__ import annotations

import hmac
import logging
import re
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.command import sandbox_engine, sandbox_policy
from app.core.config import settings
from app.core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent-gate", tags=["agent-gate"])


class Action(BaseModel):
    run_id: str = Field(max_length=120)
    tool: str = Field(max_length=40)
    command: Optional[str] = Field(default=None, max_length=20000)
    path: Optional[str] = Field(default=None, max_length=4000)
    cwd: Optional[str] = Field(default=None, max_length=4000)
    is_input: bool = False


class Done(Action):
    ok: bool = False
    summary: str = Field(default="", max_length=4000)
    exit_code: Optional[int] = None
    refused: bool = False


def _authorised(authorization: Optional[str] = Header(default=None)) -> None:
    """A dependency, so a caller without the token is refused before its request is even read."""
    header = authorization
    expected = str(settings.OPENHANDS_TOKEN or "")
    given = (header or "")[7:].strip() if (header or "").lower().startswith("bearer ") else (header or "").strip()
    if not expected or not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Not JAI's sandbox token.")


def _scope(run: Dict[str, Any]) -> sandbox_policy.Scope:
    return sandbox_policy.Scope(root=str(run["root"]), owns=tuple(run.get("owns") or ()),
                                authority=int(run.get("authority") or 0))


def decide(action: Action, run: Optional[Dict[str, Any]]) -> Optional[str]:
    if run is None:
        return "Not run: JAI has no record of this sandbox run, so it may do nothing."
    scope = _scope(run)
    if action.tool == "terminal":
        return sandbox_policy.check_command(action.command or "", action.cwd or scope.root, scope)
    if action.tool == "file_editor":
        if run.get("read_only") and str(action.command or "view") != "view":
            return "Not done: the independent Verifier looks and tests; it never changes the project's files."
        return sandbox_policy.check_file(str(action.command or "view"), action.path or "", scope)
    return f"Not run: {action.tool} is not a tool JAI's sandbox offers."


# Installing dependencies rewrites the same folders (node_modules, .venv, the lockfile): two specialists doing it at
# once in one workspace break each other's install, so one installs at a time and the other is asked to wait.
_INSTALL = re.compile(r"\b((npm|pnpm|yarn|bun)\s+(install|i|ci|add|remove|update|up)\b|(npm|pnpm|yarn)\s*$|"
                      r"uv\s+(sync|add|remove|lock|pip)\b|pip3?\s+install\b|poetry\s+(install|add|lock)\b|"
                      r"corepack\s+(enable|prepare|install)\b)", re.IGNORECASE)
INSTALL_LOCK = "sandbox:install:{}"
INSTALL_LOCK_SECONDS = 900


async def _take_install_turn(action: Action, run: Dict[str, Any]) -> Optional[str]:
    """None when this run may install now (it holds the workspace's install turn); otherwise who is installing."""
    if action.tool != "terminal" or not _INSTALL.search(" ".join((action.command or "").split())):
        return None
    from app.core.redis import get_redis

    redis = await get_redis()
    key = INSTALL_LOCK.format(run["root"])
    if await redis.set(key, action.run_id, nx=True, ex=INSTALL_LOCK_SECONDS):
        return None
    holder = await redis.get(key)
    holder = holder.decode() if isinstance(holder, bytes) else holder
    if holder == action.run_id:
        return None
    other = await sandbox_engine.load_run(str(holder)) if holder else None
    who = f"{(other or {}).get('package', '')} {(other or {}).get('specialist', 'another specialist')}".strip()
    return (f"Not run yet: {who} is installing dependencies in this workspace right now, and two installs at once "
            "break each other. Do other work and run it again in a minute.")


async def _end_install_turn(done: "Done", run: Dict[str, Any]) -> None:
    if done.tool != "terminal" or not _INSTALL.search(" ".join((done.command or "").split())):
        return
    from app.core.redis import get_redis

    redis = await get_redis()
    key = INSTALL_LOCK.format(run["root"])
    holder = await redis.get(key)
    holder = holder.decode() if isinstance(holder, bytes) else holder
    if holder == done.run_id:
        await redis.delete(key)


@router.post("/check")
async def check(action: Action, _: None = Depends(_authorised)) -> Dict[str, Any]:
    try:
        run = await sandbox_engine.load_run(action.run_id)
    except Exception as exc:  # noqa: BLE001 - no answer is a refusal
        logger.warning(f"sandbox run {action.run_id} not readable: {exc}")
        run = None
    reason = decide(action, run)
    if reason is None and run is not None:
        reason = await _take_install_turn(action, run)
    return {"allow": reason is None, "reason": reason or ""}


@router.post("/record")
async def record(done: Done, _: None = Depends(_authorised), db=Depends(get_db)) -> Dict[str, Any]:
    run = await sandbox_engine.load_run(done.run_id)
    if run is None:
        return {"recorded": False}
    await _end_install_turn(done, run)
    if not run.get("workspace_id"):
        return {"recorded": False}
    from app.core.command.tool_runtime import ToolRuntime
    from app.core.security import redact_text
    from app.models.swarm import SubAgentLog

    call = sandbox_engine.as_call(done.model_dump(), str(run["root"]), str(run.get("root_host") or ""),
                                  str(run.get("specialist") or ""), str(run.get("package") or ""))
    runtime = ToolRuntime(db, UUID(run["workspace_id"]), UUID(run["task_id"]) if run.get("task_id") else None,
                          operator=f"agent:{run.get('specialist')}", authority_level=int(run.get("authority") or 0),
                          user_id=UUID(run["user_id"]) if run.get("user_id") else None)
    summary = ("refused: " if done.refused else "") + call["summary"]
    await runtime._record(call["tool"], {**call["inputs"], "engine": "openhands", "package": run.get("package")},
                          call["success"], summary, output=call["output"] or None)
    if run.get("sub_agent_id"):
        db.add(SubAgentLog(subagent_id=UUID(run["sub_agent_id"]),
                           log_level="info" if call["success"] else "warning", log_category="tool",
                           log_message=redact_text(f"{call['tool']} {list(call['inputs'].values())[0]} -> "
                                                   f"{summary}")[:4000],
                           context={"parent_agent_id": run.get("parent_agent_id"), "package": run.get("package"),
                                    "task_id": run.get("task_id"), "engine": "openhands",
                                    "tool": call["tool"], "ok": call["success"]}))
    await db.commit()
    return {"recorded": True}
