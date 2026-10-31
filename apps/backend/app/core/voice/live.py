"""
JARV Backend - Live voice conversation (OpenAI Realtime)

A natural spoken conversation with JARV: the browser streams the microphone to
OpenAI's Realtime model over WebRTC and plays its voice back, with turn-taking
and interruption handled by the model. The browser never sees the OpenAI key:
JARV mints a short-lived client secret for one session, carrying JARV's
instructions and tools.

Everything JARV does during the conversation goes through ``run_tool`` on the
backend under the operator's own sign-in: reading status, starting a Command
Center mission (under the same approval gate as typed missions), checking or
cancelling a mission. Approvals are refused by voice here exactly as in
push-to-talk. Every session and tool call is written to the audit log.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.voice import engine

REALTIME_SECRETS = "https://api.openai.com/v1/realtime/client_secrets"
SESSION_ACTION = "voice.live_session"
TOOL_ACTION = "voice.live_tool"

_NO_WORKSPACE = {"type": "string", "description": "Workspace name, when Richard names one. Omit to use all of his."}

TOOLS: List[Dict[str, Any]] = [
    {"type": "function", "name": "get_status",
     "description": "What JARV is working on right now: missions in progress, what waits for Richard's approval, "
                    "recent failures and the latest activity.",
     "parameters": {"type": "object", "properties": {"workspace": _NO_WORKSPACE}, "additionalProperties": False}},
    {"type": "function", "name": "start_mission",
     "description": "Start real work: hands Richard's request to JARV's agents as a Command Center mission. Use it "
                    "when Richard asks for something to be done (built, fixed, researched, written, checked, "
                    "deployed), not for a question you can answer in conversation.",
     "parameters": {"type": "object", "properties": {
         "instruction": {"type": "string", "description": "The full request in Richard's words, with every detail "
                                                          "he gave, as a written instruction."},
         "workspace": _NO_WORKSPACE},
         "required": ["instruction"], "additionalProperties": False}},
    {"type": "function", "name": "resume_mission",
     "description": "Carry on with a mission that paused or stopped part-way (needs continuation or partial): the "
                    "same mission continues from where it stopped, with its progress. Use it whenever Richard asks "
                    "to continue, resume or carry on with a mission; never start a new mission for that. Without a "
                    "task_id it resumes his latest paused mission.",
     "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "additionalProperties": False}},
    {"type": "function", "name": "get_mission",
     "description": "The state and result of one mission (the latest one when no id is given).",
     "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "additionalProperties": False}},
    {"type": "function", "name": "cancel_mission",
     "description": "Cancel the mission in progress. Only when Richard clearly asks to stop or cancel it.",
     "parameters": {"type": "object", "properties": {"workspace": _NO_WORKSPACE}, "additionalProperties": False}},
    {"type": "function", "name": "list_workspace_files",
     "description": "What is in a workspace's folder on Richard's computer (one level; give path for a subfolder).",
     "parameters": {"type": "object", "properties": {
         "workspace": {"type": "string", "description": "Workspace name."},
         "path": {"type": "string", "description": "Subfolder inside the workspace, e.g. docs. Omit for the top."}},
         "required": ["workspace"], "additionalProperties": False}},
    {"type": "function", "name": "read_workspace_file",
     "description": "Read a text file in a workspace's folder (the first part of a long file), e.g. a design or spec.",
     "parameters": {"type": "object", "properties": {
         "workspace": {"type": "string", "description": "Workspace name."},
         "path": {"type": "string", "description": "File path inside the workspace, e.g. docs/MYCO-V3-spec.md."}},
         "required": ["workspace", "path"], "additionalProperties": False}},
    {"type": "function", "name": "list_workspaces",
     "description": "Richard's workspaces (projects) by name.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
]


class LiveUnavailable(RuntimeError):
    """Live conversation cannot start (no OpenAI key)."""


def available() -> bool:
    return bool(settings.OPENAI_API_KEY)


def setup_hint() -> Optional[str]:
    return None if available() else ("Live conversation uses OpenAI Realtime: set OPENAI_API_KEY "
                                     "(apps/backend/.env locally, .env.production on the server).")


async def _workspaces(db: AsyncSession, user_id: UUID):
    from app.models.workspace import Workspace

    return (await db.execute(select(Workspace).where(Workspace.owner_id == user_id,
                                                     Workspace.is_archived == False)  # noqa: E712
                             .order_by(Workspace.name))).scalars().all()


def _root(workspace) -> Optional[str]:
    config = workspace.config if isinstance(workspace.config, dict) else {}
    return config.get("root_path") or None


def instructions(spaces: List[Any]) -> str:
    projects = "; ".join(f"{w.name} (folder {_root(w)})" if _root(w) else f"{w.name} (no folder registered)"
                         for w in spaces) or "none yet"
    return (
        "You are JARV, Richard Curley's autonomous AI operating system, talking with him by voice. "
        "Speak naturally and warmly, like a capable chief of staff: short spoken sentences, no lists or markdown, "
        "British English. Let him interrupt; keep answers brief unless he asks for detail.\n"
        f"His workspaces: {projects}.\n"
        "Answer questions and talk things through yourself. For anything about his projects or what JARV is "
        "doing, use get_status, get_mission or list_workspaces rather than guessing. When he asks for work to "
        "be done, say in one sentence what you'll do and call start_mission with his full request; JARV's agents "
        "then do the work and you'll receive a message beginning [mission update] when it finishes or pauses; "
        "tell him the outcome in a sentence or two. When he asks to continue, resume or carry on with a mission, "
        "call resume_mission; never start a new mission to continue an old one.\n"
        "Each workspace is a folder on his computer that JARV and its agents work in. Never tell him you cannot "
        "access his files: use list_workspace_files and read_workspace_file to look at what is there, and "
        "start_mission for work on it, naming where to look, e.g. 'Read the design in the MYCO workspace's docs "
        "folder and write a build plan to docs/BUILD_PLAN.md'. If a workspace has no folder registered, say so "
        "and offer to register one when he gives the path.\n"
        "If a mission fails, tell him plainly what the error says. Do not claim you will fix it behind the "
        "scenes: you cannot change JARV's own code from a conversation. Restart a failed mission at most once, "
        "and only if he asks.\n"
        "You never approve anything, publish, spend money or send messages for him by voice: those wait on the "
        "Approvals page, because anyone near the microphone could speak. If he asks you to approve, say so and "
        "point him to the Approvals page. Never read out keys, passwords or secrets."
    )


async def create_session(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    """A short-lived Realtime client secret for this operator, carrying JARV's instructions and tools."""
    if not available():
        raise LiveUnavailable(setup_hint())
    from app.core.audit import AuditLogger

    spaces = await _workspaces(db, user_id)
    model, voice = settings.OPENAI_REALTIME_MODEL, settings.OPENAI_REALTIME_VOICE
    body = {"session": {
        "type": "realtime", "model": model, "instructions": instructions(spaces),
        "tools": TOOLS, "tool_choice": "auto",
        "audio": {"input": {"transcription": {"model": settings.OPENAI_REALTIME_TRANSCRIBE_MODEL},
                            "turn_detection": {"type": "semantic_vad"}},
                  "output": {"voice": voice}},
    }}
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json",
               # A stable, hashed operator id for OpenAI's abuse monitoring; never the user's name.
               "OpenAI-Safety-Identifier": hashlib.sha256(f"jarv:{user_id}".encode()).hexdigest()}
    try:
        async with engine.http_client(timeout=httpx.Timeout(20.0)) as client:
            response = await client.post(REALTIME_SECRETS, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise RuntimeError(engine._unreachable("openai", exc)) from exc
    if response.status_code >= 400:
        raise engine._error(response, "Starting the live conversation (openai)")
    payload = response.json()
    secret = payload.get("value") or (payload.get("client_secret") or {}).get("value")
    if not secret:
        raise RuntimeError("OpenAI returned no client secret for the live conversation")
    await AuditLogger.log_system_event(db, action=SESSION_ACTION, result="ok", resource_type="voice",
                                       user_id=user_id, details={"model": model, "voice": voice})
    await db.commit()
    return {"client_secret": secret, "expires_at": payload.get("expires_at"), "model": model, "voice": voice,
            "calls_url": "https://api.openai.com/v1/realtime/calls"}


async def _resolve_workspace(db: AsyncSession, user_id: UUID, name: Optional[str]):
    if not name:
        return None, None
    wanted = name.strip().lower()
    spaces = await _workspaces(db, user_id)
    match = next((w for w in spaces if w.name.lower() == wanted or w.slug.lower() == wanted), None) or \
        next((w for w in spaces if wanted in w.name.lower()), None)
    if match is None:
        return None, f"No workspace called {name}. His workspaces: {', '.join(w.name for w in spaces) or 'none'}."
    return match.id, None


def _inside(root: str, relative: Optional[str]) -> Optional[str]:
    """root joined with a relative path that stays inside it (None if it would leave)."""
    rel = (relative or "").strip().replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p and p != "."]
    if any(p == ".." for p in parts) or (rel and (":" in parts[0] if parts else False)):
        return None
    if not parts:
        return root
    sep = "\\" if ("\\" in root or ":" in root[:3]) else "/"
    return root.rstrip("\\/") + sep + sep.join(parts)


async def _workspace_files(db: AsyncSession, user_id: UUID, name: str, args: Dict[str, Any],
                           read: bool) -> Dict[str, Any]:
    from app.core.workspaces import fs_inspector

    workspace_id, problem = await _resolve_workspace(db, user_id, name)
    if problem or workspace_id is None:
        return {"error": problem or "Name the workspace."}
    workspace = next(w for w in await _workspaces(db, user_id) if w.id == workspace_id)
    root = _root(workspace)
    if not root:
        return {"error": f"{workspace.name} has no folder registered."}
    target = _inside(root, args.get("path"))
    if target is None:
        return {"error": "That path is outside the workspace."}
    if read:
        found = fs_inspector.read_file(target, max_bytes=12000)
        if not found.accessible or not found.exists:
            return {"error": found.reason or f"No file at {args.get('path')}."}
        return {"path": args.get("path"), "content": found.data.get("content", ""),
                "truncated": bool(found.data.get("truncated")), "size_bytes": found.data.get("size_bytes")}
    listed = fs_inspector.list_dir(target)
    if not listed.accessible or not listed.exists:
        return {"error": listed.reason or f"No folder at {args.get('path') or 'the top of the workspace'}."}
    entries = listed.data.get("entries", [])
    return {"workspace": workspace.name, "folder": target, "count": len(entries),
            "entries": [{"name": e["name"], "folder": e["is_dir"]} for e in entries[:200]]}


async def _mission(db: AsyncSession, user_id: UUID, task_id: Optional[str]) -> Dict[str, Any]:
    from app.core.scoping import owned_workspaces
    from app.models.task import Task

    query = select(Task).where(Task.workspace_id.in_(owned_workspaces(user_id)), Task.task_type != "subtask")
    if task_id:
        try:
            query = query.where(Task.id == UUID(str(task_id)))
        except ValueError:
            return {"error": "That is not a mission id."}
        task = (await db.execute(query)).scalar_one_or_none()
    else:
        # "The mission" is the one still being worked on, if any; otherwise the latest one that is not archived.
        recent = (await db.execute(query.order_by(Task.created_at.desc()).limit(50))).scalars().all()
        visible = [t for t in recent if not (t.meta_data or {}).get("archived_at")]
        working = [t for t in visible if (t.status or "").lower() in ("queued", "running", "recovering", "needs_continuation")]
        task = (working or visible or [None])[0]
    if task is None:
        return {"error": "No mission found."}
    result = task.result if isinstance(task.result, dict) else {}
    # Missions store their report under "response".
    summary = (result.get("response") or result.get("response_text") or result.get("output")
               or result.get("summary") or "")
    return {"task_id": str(task.id), "title": task.title, "status": task.status,
            "folder": result.get("workspace_path"),
            "result": str(summary)[:1500], "error": (task.error_message or "")[:300] or None}


def _best_to_resume(candidates: List[Any]) -> Optional[Any]:
    """The mission "carry on" means: one that works in a folder and is not archived, a mission that
    paused at its step limit before one that ended partial, the newest first. A mission without a
    folder (for example one created by asking to resume) is never chosen: it has nothing to work on."""
    usable = [t for t in candidates if not (t.meta_data or {}).get("archived_at")
              and isinstance(t.result, dict) and t.result.get("workspace_path")]
    for wanted in ("needs_continuation", "partial"):
        for task in usable:
            if (task.status or "").lower() == wanted:
                return task
    return None


async def _resume(db: AsyncSession, user_id: UUID, task_id: Optional[str]) -> Dict[str, Any]:
    from app.core.command.continuation import RESUMABLE, queue_resume
    from app.core.scoping import owned_workspaces
    from app.models.task import Task

    query = select(Task).where(Task.workspace_id.in_(owned_workspaces(user_id)), Task.task_type != "subtask")
    if task_id:
        try:
            query = query.where(Task.id == UUID(str(task_id)))
        except ValueError:
            return {"error": "That is not a mission id."}
        task = (await db.execute(query)).scalar_one_or_none()
    else:
        task = _best_to_resume((await db.execute(
            query.where(Task.status.in_(RESUMABLE)).order_by(Task.created_at.desc()).limit(50))).scalars().all())
    if task is None:
        return {"error": "There is no paused mission to carry on with."}
    try:
        return {**await queue_resume(db, task, operator=str(user_id), reason="resumed by voice"),
                "title": task.title}
    except ValueError as exc:
        return {"error": f"{exc} It can only carry on when it has paused part-way.", "task_id": str(task.id)}


async def run_tool(db: AsyncSession, user_id: UUID, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Carry out one tool call from the live conversation as the signed-in operator; audit-logged."""
    from app.core.audit import AuditLogger

    args = arguments if isinstance(arguments, dict) else {}
    if name == "list_workspaces":
        output: Dict[str, Any] = {"workspaces": [w.name for w in await _workspaces(db, user_id)]}
    elif name in ("list_workspace_files", "read_workspace_file"):
        output = await _workspace_files(db, user_id, str(args.get("workspace") or ""), args,
                                        read=name == "read_workspace_file")
    elif name == "get_mission":
        output = await _mission(db, user_id, args.get("task_id"))
    elif name == "resume_mission":
        output = await _resume(db, user_id, args.get("task_id"))
    elif name in ("get_status", "start_mission", "cancel_mission"):
        workspace_id, problem = await _resolve_workspace(db, user_id, args.get("workspace"))
        if problem:
            output = {"error": problem}
        elif name == "get_status":
            output = await engine._status_reply(db, user_id, workspace_id)
        elif name == "cancel_mission":
            output = await engine.route(db, "cancel the current mission", user_id=user_id, workspace_id=workspace_id)
        else:
            instruction = str(args.get("instruction") or "").strip()
            if not instruction:
                output = {"error": "The mission needs an instruction."}
            else:
                output = await engine.route(db, instruction, user_id=user_id, workspace_id=workspace_id)
    else:
        raise LookupError(f"Unknown tool: {name}")
    await AuditLogger.log_system_event(
        db, action=TOOL_ACTION, result="error" if "error" in output else "ok", resource_type="voice",
        user_id=user_id, details={"tool": name, "arguments": {k: str(v)[:300] for k, v in args.items()},
                                  "intent": output.get("intent"), "task_id": output.get("task_id")})
    await db.commit()
    return output
