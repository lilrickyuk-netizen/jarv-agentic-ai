"""
JAI Backend - Live voice conversation (OpenAI Realtime)

A natural spoken conversation with JAI: the browser streams the microphone to
OpenAI's Realtime model over WebRTC and plays its voice back, with turn-taking
and interruption handled by the model. The browser never sees the OpenAI key:
JAI mints a short-lived client secret for one session, carrying JAI's
instructions and tools.

Everything JAI does during the conversation goes through ``run_tool`` on the
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
     "description": "What JAI is working on right now: missions in progress, what waits for Richard's approval, "
                    "recent failures and the latest activity.",
     "parameters": {"type": "object", "properties": {"workspace": _NO_WORKSPACE}, "additionalProperties": False}},
    {"type": "function", "name": "start_mission",
     "description": "Start real work: hands Richard's request to JAI's agents as a Command Center mission. Use it "
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
    {"type": "function", "name": "ask_jarv",
     "description": "Ask JAI's own reasoning core a question about Richard's projects, missions, decisions, "
                    "progress or plans. It answers from JAI's memory, verified lessons, recent missions and "
                    "what waits for approval, so use it for anything you would otherwise guess.",
     "parameters": {"type": "object", "properties": {
         "question": {"type": "string", "description": "The question in Richard's words, with every detail."},
         "workspace": _NO_WORKSPACE},
         "required": ["question"], "additionalProperties": False}},
    {"type": "function", "name": "search_memory",
     "description": "What JAI remembers about a subject (decisions, facts, preferences, past work), best first.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "What to look for."}, "workspace": _NO_WORKSPACE},
         "required": ["query"], "additionalProperties": False}},
    {"type": "function", "name": "trace_artifact",
     "description": "Why something is the way it is in a workspace: what a file, requirement (R4) or decision is "
                    "connected to, which mission changed it, what verified it and which checks contradict it. Use it "
                    "for questions like 'why is Python 3.12.8?' or 'what proves R4?'.",
     "parameters": {"type": "object", "properties": {
         "key": {"type": "string", "description": "A file path, a requirement id such as R4, or a command."},
         "workspace": _NO_WORKSPACE},
         "required": ["key"], "additionalProperties": False}},
    {"type": "function", "name": "list_approvals",
     "description": "What is waiting for Richard's decision on the Approvals page. Read-only: you never approve.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
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
        "You are JAI, Richard Curley's autonomous AI operating system, talking with him by voice. "
        "Your name is written JAI and said \"Jay\", as one word, never spelled out letter by letter. "
        "Speak naturally and warmly, like a capable chief of staff: short spoken sentences, no lists or markdown, "
        "British English. Let him interrupt; keep answers brief unless he asks for detail.\n"
        f"His workspaces: {projects}.\n"
        "You are the voice of JAI's whole system, not a separate assistant: JAI's memory, missions, workspaces "
        "and approvals are yours through your tools. Talk things through yourself, but for anything about his "
        "projects, decisions, progress or what JAI is doing, use ask_jarv, search_memory, get_status, "
        "get_mission, list_approvals or list_workspaces rather than guessing. When he asks for work to "
        "be done, say in one sentence what you'll do and call start_mission with his full request; JAI's agents "
        "then do the work and you'll receive a message beginning [mission update] when it finishes or pauses; "
        "tell him the outcome in a sentence or two. When he asks to continue, resume or carry on with a mission, "
        "call resume_mission; never start a new mission to continue an old one.\n"
        "Each workspace is a folder on his computer that JAI and its agents work in. Never tell him you cannot "
        "access his files: use list_workspace_files and read_workspace_file to look at what is there, and "
        "start_mission for work on it, naming where to look, e.g. 'Read the design in the MYCO workspace's docs "
        "folder and write a build plan to docs/BUILD_PLAN.md'. If a workspace has no folder registered, say so "
        "and offer to register one when he gives the path.\n"
        "If a mission fails, tell him plainly what the error says. Do not claim you will fix it behind the "
        "scenes: you cannot change JAI's own code from a conversation. Restart a failed mission at most once, "
        "and only if he asks.\n"
        "You never approve anything, publish, spend money or send messages for him by voice: those wait on the "
        "Approvals page, because anyone near the microphone could speak. If he asks you to approve, say so and "
        "point him to the Approvals page. Never read out keys, passwords or secrets."
    )


# Talk with JAI remembers the conversation: every spoken turn is kept per operator (newest 60, for 30 days)
# and the recent ones open each new session, so a new conversation carries on from the last one.
HISTORY_TURNS = 60
HISTORY_IN_SESSION = 30
HISTORY_TTL_SECONDS = 30 * 24 * 3600
_SPEAKERS = {"you": "Richard", "jarv": "JAI"}


def _history_key(user_id: UUID) -> str:
    return f"voice:history:{user_id}"


async def remember_turn(user_id: UUID, who: str, text: str) -> Dict[str, Any]:
    """Keep one spoken turn ("you" is Richard, "jarv" is JAI). Secrets never enter the history."""
    import json
    from datetime import datetime, timezone

    from app.core.redis import get_redis
    from app.core.security import redact_text

    if who not in _SPEAKERS:
        raise ValueError("who must be 'you' or 'jarv'")
    clean = redact_text(" ".join(str(text or "").split()))[:1500]
    if not clean:
        return {"kept": False}
    redis = await get_redis()
    key = _history_key(user_id)
    await redis.lpush(key, json.dumps({"who": who, "text": clean,
                                       "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    await redis.ltrim(key, 0, HISTORY_TURNS - 1)
    await redis.expire(key, HISTORY_TTL_SECONDS)
    return {"kept": True}


async def recent_turns(user_id: UUID, limit: int = HISTORY_IN_SESSION) -> List[Dict[str, Any]]:
    """The latest spoken turns, oldest first."""
    import json

    from app.core.redis import get_redis

    try:
        raw = await (await get_redis()).lrange(_history_key(user_id), 0, max(0, limit - 1))
    except Exception:  # noqa: BLE001 - a conversation starts without history rather than not at all
        return []
    turns = []
    for item in reversed(raw or []):
        try:
            turns.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return turns


def now_block() -> str:
    """Today's date and time where Richard is (Europe/London), so JAI knows how long ago things happened."""
    from datetime import datetime, timezone

    try:
        from zoneinfo import ZoneInfo

        now, zone = datetime.now(ZoneInfo("Europe/London")), "UK time"
    except Exception:  # noqa: BLE001 - no time-zone database in the image: say UTC rather than guess
        now, zone = datetime.now(timezone.utc), "UTC"
    return (f"\nIt is now {now:%A %-d %B %Y, %H:%M} {zone}. Times in the conversation below are UTC; "
            "when he spoke to you earlier today, say so, and never greet him as if it were a new day "
            "when it is not.")


def history_block(turns: List[Dict[str, Any]]) -> str:
    if not turns:
        return ""
    lines = [f"[{str(t.get('at', ''))[:16].replace('T', ' ')}] {_SPEAKERS.get(t.get('who'), 'JAI')}: {t.get('text', '')}"
             for t in turns]
    return ("\nYOUR RECENT CONVERSATION WITH RICHARD (earlier sessions, oldest first). Carry on from it as one "
            "continuous relationship: remember what he told you and what you said, and do not re-introduce "
            "yourself. Check facts about missions with your tools, because they may have moved on since:\n"
            + "\n".join(lines))


async def create_session(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    """A short-lived Realtime client secret for this operator, carrying JAI's instructions and tools."""
    if not available():
        raise LiveUnavailable(setup_hint())
    from app.core.audit import AuditLogger

    spaces = await _workspaces(db, user_id)
    model, voice = settings.OPENAI_REALTIME_MODEL, settings.OPENAI_REALTIME_VOICE
    body = {"session": {
        "type": "realtime", "model": model,
        "instructions": instructions(spaces) + now_block() + history_block(await recent_turns(user_id)),
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
    if (task.status or "").lower() in ("queued", "running", "recovering"):
        # A mission being worked on is described by what it is doing now; its last report and error are
        # from an earlier round (a pause it has since come back from) and would mislead.
        return {"task_id": str(task.id), "title": task.title, "status": task.status, "in_progress": True,
                "folder": result.get("workspace_path"), "latest_activity": await _activity(db, task.id),
                "note": "Still being worked on. Describe it from latest_activity; earlier pauses are over."}
    # Missions store their report under "response".
    summary = (result.get("response") or result.get("response_text") or result.get("output")
               or result.get("summary") or "")
    return {"task_id": str(task.id), "title": task.title, "status": task.status,
            "folder": result.get("workspace_path"),
            "result": str(summary)[:1500], "error": (task.error_message or "")[:300] or None,
            # The evidence report (Upgrade 4): say what is shown done with evidence, nothing more.
            "report": _spoken_report(result.get("report"))}


async def _memories(db: AsyncSession, user_id: UUID, query: str, workspace_id: Optional[UUID],
                    limit: int = 8) -> List[Dict[str, Any]]:
    """JAI's memories that match, from the named workspace or all of his, best first (never another owner's)."""
    from app.core.jarv_memory import memory_service

    scopes = [workspace_id] if workspace_id else [w.id for w in await _workspaces(db, user_id)]
    hits: List[Any] = []
    for scope in scopes:
        hits += await memory_service.search_scored(db, query, limit=limit, workspace_id=scope)
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return [{"content": str(hit.memory.content)[:600], "type": hit.memory.memory_type,
             "category": hit.memory.memory_category, "score": round(hit.score, 3)} for hit in hits[:limit]]


async def _approvals(db: AsyncSession, user_id: UUID) -> Dict[str, Any]:
    from app.core.richard.workflow import RichardBoundaryWorkflow

    pending = await RichardBoundaryWorkflow(db).list_pending_decisions(owner=user_id)
    return {"count": len(pending), "waiting": [
        {"action": str(item.get("action_description") or "")[:200], "type": item.get("boundary_type"),
         "expires_at": item.get("expires_at")} for item in pending[:10]],
        "note": "Richard approves these on the Approvals page; never by voice."}


async def _activity(db: AsyncSession, task_id, limit: int = 12) -> List[str]:
    """What a running mission did most recently, from the operations feed (newest first)."""
    from app.models.company_operations import LiveOperationsFeedItem

    rows = (await db.execute(select(LiveOperationsFeedItem).where(
        LiveOperationsFeedItem.related_task_id == task_id)
        .order_by(LiveOperationsFeedItem.created_at.desc()).limit(limit))).scalars().all()
    return [f"{r.created_at:%H:%M} {r.title}: {(r.message or '')[:160]}" for r in rows if r.created_at]


async def _recent_missions(db: AsyncSession, user_id: UUID, limit: int = 6) -> List[Dict[str, Any]]:
    from app.core.scoping import owned_workspaces
    from app.models.task import Task

    rows = (await db.execute(select(Task).where(
        Task.workspace_id.in_(owned_workspaces(user_id)), Task.task_type == "command")
        .order_by(Task.created_at.desc()).limit(limit * 3))).scalars().all()
    missions = []
    for task in rows:
        if (task.meta_data or {}).get("archived_at"):
            continue
        result = task.result if isinstance(task.result, dict) else {}
        entry = {"id": str(task.id)[:8], "title": (task.title or "")[:120], "status": task.status,
                 "started": task.created_at.isoformat(timespec="minutes") if task.created_at else None,
                 "folder": result.get("workspace_path"),
                 "last_report": str(result.get("response") or task.error_message or "")[:700]}
        if (task.status or "").lower() in ("running", "queued", "recovering"):
            entry["in_progress"] = True
            entry["latest_activity"] = await _activity(db, task.id)
        missions.append(entry)
        if len(missions) == limit:
            break
    return missions


async def _ask_jarv(db: AsyncSession, user_id: UUID, question: str, workspace_id: Optional[UUID]) -> Dict[str, Any]:
    """Answer from JAI's own memory, lessons, missions and approvals with JAI's reasoning model."""
    import json

    from app.core.command import CommandService
    from app.core.learning import learning_service
    from app.core.providers import CompletionRequest, Message, get_router

    facts: Dict[str, Any] = {
        "workspaces": [{"name": w.name, "folder": _root(w), "authority_level": w.authority_level}
                       for w in await _workspaces(db, user_id)],
        "recent_missions": await _recent_missions(db, user_id),
        "waiting_for_approval": (await _approvals(db, user_id))["waiting"],
        "memories": await _memories(db, user_id, question, workspace_id),
        "now": now_block().strip(),
        "recent_conversation": [f"[{str(t.get('at', ''))[:16]}] {_SPEAKERS.get(t.get('who'), 'JAI')}: "
                                f"{t.get('text', '')[:300]}" for t in await recent_turns(user_id, 16)],
    }
    if workspace_id is not None:
        try:
            facts["verified_lessons"] = [
                {"lesson": item["lesson"], "outcome": item["polarity"]} for item in
                await learning_service.retrieve_lessons(db, workspace_id=workspace_id, agent_name="orchestrator",
                                                        query=question, limit=3)]
        except Exception:  # noqa: BLE001 - lessons are an addition, never a reason to fail the answer
            facts["verified_lessons"] = []
    service = CommandService()
    response = await get_router().complete(CompletionRequest(
        model=service.model, max_tokens=700, temperature=0.2,
        system=("You are JAI's reasoning core answering Richard Curley's spoken question. Answer only from the "
                "facts given (JAI's memory, missions, workspaces, approvals and your recent conversation with "
                "him); when they do not contain the answer, say so plainly and say what JAI would need to find "
                "out. A mission marked in_progress is still running: describe it only from its own "
                "latest_activity, never from another mission's last_report, and do not say it committed, passed "
                "or finished unless its own activity shows that. Each last_report belongs only to its own "
                "mission. Two to five spoken sentences, British English, no lists or markdown."),
        messages=[Message(role="user", content=f"Question: {question}\n\nFacts:\n{json.dumps(facts, default=str)}")]))
    return {"answer": (response.content or "").strip() or "I could not form an answer from what I know.",
            "missions_considered": len(facts["recent_missions"]), "memories_considered": len(facts["memories"])}


def _spoken_report(report: Any) -> Optional[Dict[str, Any]]:
    """The mission's evidence report in short form for speech: the overall line and each requirement's status."""
    if not isinstance(report, dict):
        return None
    return {"overall": report.get("overall"), "confidence": report.get("confidence"),
            "risks": (report.get("risks") or [])[:5],
            "requirements": [f"{i.get('id')} {i.get('status')}: {str(i.get('text'))[:120]}"
                             for i in (report.get("items") or [])[:30]],
            "hard_checks_failing": len(report.get("hard_failures") or []),
            "waiting_on_richard": report.get("waiting") or []}


def _best_to_resume(candidates: List[Any]) -> Optional[Any]:
    """The mission "carry on" means: the newest mission that works in a folder and is not archived, whether it
    paused at its step limit or stopped part-way. Status never outranks age: preferring step-limit pauses made
    "carry on" restart days-old Phase 0 missions instead of the one Richard had just been running. A mission
    without a folder (for example one created by asking to resume) is never chosen: it has nothing to work on.
    ``candidates`` are newest first."""
    usable = [t for t in candidates if not (t.meta_data or {}).get("archived_at")
              and isinstance(t.result, dict) and t.result.get("workspace_path")]
    return usable[0] if usable else None


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
    elif name == "list_approvals":
        output = await _approvals(db, user_id)
    elif name == "trace_artifact":
        workspace_id, problem = await _resolve_workspace(db, user_id, args.get("workspace"))
        key = str(args.get("key") or "").strip()
        if problem:
            output = {"error": problem}
        elif not key:
            output = {"error": "Say which file, requirement or command to trace."}
        else:
            from app.core.graph import graph_service

            # A named workspace, or each of Richard's own workspaces in turn (never anyone else's).
            ids = [workspace_id] if workspace_id else [w.id for w in await _workspaces(db, user_id)]
            links: List[str] = []
            records = 0
            for wid in ids:
                trace = await graph_service.trace(db, wid, key)
                if trace["nodes"]:
                    records += len(trace["nodes"])
                    links += graph_service.describe(trace).splitlines()
            output = {"key": key, "links": links[:30] or ["Nothing is recorded for that yet."], "records": records}
    elif name in ("ask_jarv", "search_memory"):
        workspace_id, problem = await _resolve_workspace(db, user_id, args.get("workspace"))
        if problem:
            output = {"error": problem}
        elif name == "search_memory":
            query = str(args.get("query") or "").strip()
            output = {"memories": await _memories(db, user_id, query, workspace_id)} if query else \
                {"error": "Say what to look for."}
        else:
            question = str(args.get("question") or "").strip()
            output = await _ask_jarv(db, user_id, question, workspace_id) if question else \
                {"error": "The question is empty."}
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
