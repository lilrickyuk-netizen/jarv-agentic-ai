"""
JAI Backend - Understanding what Richard asked for

Richard, 14 November: "we gave it instructions but because they wasn't worded a specific way it went to the wrong
agent, wrong workspace and failed. This should be using natural language and understand it, and this has been in the
design from the start." He had typed "Carry on with the booking-partners database: stop adding rows, rename the
sheets ...". Every decision about it was made by lists of words: the workspace stayed the one that happened to be
selected (the text named no folder), the mission carried on was the only unfinished one there (an investors list),
and the agent was the Sales Lead (the Partnerships words did not include "partners"). Nothing looked at the
booking-partners mission that was running in Plexecute at that moment.

So a model reads the request before anything is decided, together with what a person would know: Richard's
workspaces and their folders, his recent missions (what each was, where it ran, which agent did it, how far it got)
and what each of JAI's agents does. It answers in one go: is this a question, a new mission, more work on an earlier
mission, or a direct instruction to JAI; which mission; which workspace; which agent; how sure it is and why. The
answer is kept on the mission's record (task.context["understanding"]) so Richard can see why JAI chose what it did.

The word lists (service._detect_intent, workspace_choice, resume.last_state, work_type) stay as the backup for when
the model cannot be reached or is not sure. The safety gate (service.classify_command_safety) is not touched by
this: whether an action needs Richard's approval never depends on a model's reading.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

KINDS = ("question", "mission", "follow_up", "direct")
CONFIDENT = 0.6          # below this the word lists decide, as before
SECONDS = 15.0
LOOK_BACK_DAYS = 21
MISSIONS_SHOWN = 12
REQUEST_CHARS = 4000


@dataclass
class Understanding:
    kind: str                          # question, mission, follow_up or direct
    mission_id: Optional[str] = None   # the earlier mission a follow-up is about
    workspace_id: Optional[str] = None
    workspace: str = ""
    specialist: Optional[str] = None   # the agent whose work it is ("builder" for software)
    confidence: float = 0.0
    why: str = ""
    mission_running: bool = False      # the mission followed up is working right now
    model: str = ""

    @property
    def sure(self) -> bool:
        return self.kind in KINDS and self.confidence >= CONFIDENT

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Understanding"]:
        if not isinstance(data, dict) or data.get("kind") not in KINDS:
            return None
        known = {k: data.get(k) for k in cls.__dataclass_fields__ if k in data}
        try:
            known["confidence"] = float(known.get("confidence") or 0)
            return cls(**known)
        except (TypeError, ValueError):
            return None

    def line(self) -> str:
        """One line for the mission's record: what JAI took the request to be."""
        what = {"question": "a question", "mission": "a new piece of work",
                "follow_up": f"more work on mission {str(self.mission_id or '')[:8]}",
                "direct": "a direct instruction to JAI"}.get(self.kind, self.kind)
        parts = [f"JAI read this as {what}"]
        if self.workspace:
            parts.append(f"for {self.workspace}")
        if self.specialist:
            parts.append(f"for the {agent_title(self.specialist)}")
        return " ".join(parts) + f" ({self.confidence:.0%} sure): {self.why}".rstrip(": ")


def agent_title(name: str) -> str:
    if name == "builder":
        return "Lead Builder"
    try:
        from app.core.command.mission_org import SPECIALISTS

        return str(SPECIALISTS.get(name, {}).get("title") or name)
    except Exception:  # noqa: BLE001
        return name


def _short(text: str, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


async def _workspaces(db: AsyncSession, owner: Optional[UUID]) -> List[Any]:
    from app.models.workspace import Workspace

    query = select(Workspace)
    if owner is not None:
        query = query.where(Workspace.owner_id == owner)
    return list((await db.execute(query)).scalars().all())


def _folder(workspace: Any) -> str:
    config = workspace.config if isinstance(workspace.config, dict) else {}
    return str(config.get("root_path") or "")


async def _agent_of(task: Any, result: Dict[str, Any]) -> str:
    """The agent that did (or is doing) a mission: its record, its live progress, then its brief's words."""
    role = (result.get("role") or {}).get("specialist") if isinstance(result.get("role"), dict) else None
    if role:
        return str(role)
    if task.status in ("running", "resuming", "queued", "pending"):
        from app.core.command import progress

        live = await progress.load(task.id) or {}
        packages = ((live.get("team") or {}).get("packages") or [])
        if len(packages) == 1 and packages[0].get("specialist"):
            return str(packages[0]["specialist"])
    from app.core.command.work_type import specialist_for

    kind = specialist_for(task.description or task.title or "")
    return str(kind["specialist"]) if kind else "builder"


async def recent_missions(db: AsyncSession, workspaces: List[Any], current: Optional[UUID] = None
                          ) -> List[Dict[str, Any]]:
    """Richard's recent missions, newest first: what each was, where it ran, who did it and how far it got."""
    from app.core.command import resume
    from app.models.task import Task

    names = {w.id: w.name for w in workspaces}
    if not names:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=LOOK_BACK_DAYS)
    rows = (await db.execute(
        select(Task).where(Task.task_type == "command", Task.created_at >= since,
                           Task.workspace_id.in_(list(names)))
        .order_by(Task.created_at.desc()).limit(80))).scalars().all()
    out: List[Dict[str, Any]] = []
    for task in rows:
        if current is not None and task.id == current:
            continue
        result = await resume._state(task)
        requirements = [r for r in (result.get("requirements") or []) if isinstance(r, dict) and r.get("id")]
        running = task.status in ("running", "resuming")
        if not requirements and not running:
            continue  # a question or a one-off command: nothing to follow up
        done = sum(1 for r in requirements if r.get("status") == "done")
        verified = (result.get("verification") or {}).get("verified") is True
        out.append({
            "id": str(task.id), "short": str(task.id)[:8], "brief": _short(task.description or task.title, 260),
            "workspace": names.get(task.workspace_id, ""), "workspace_id": str(task.workspace_id),
            "agent": await _agent_of(task, result), "status": "finished and verified" if verified else task.status,
            "running": running, "progress": f"{done} of {len(requirements)} requirements done" if requirements else "",
            "when": f"{task.created_at:%d %b %H:%M}" if task.created_at else "",
        })
        if len(out) >= MISSIONS_SHOWN:
            break
    return out


def prompt_for(text: str, workspaces: List[Any], missions: List[Dict[str, Any]], selected: str) -> str:
    from app.core.command.work_type import DESCRIBED

    spaces = "\n".join(f"- {w.name}" + (f" (folder {_folder(w)})" if _folder(w) else "") for w in workspaces
                       ) or "- (none)"
    recent = "\n".join(
        f"- {m['short']}: “{m['brief']}” | workspace {m['workspace']} | agent {m['agent']} | "
        f"{m['status']}" + (f" | {m['progress']}" if m["progress"] else "") + f" | started {m['when']}"
        for m in missions) or "- (none)"
    agents = "\n".join(f"- {name}: {what}" for name, what in DESCRIBED.items())
    return (
        "Richard Curley, the founder, has just said this to JAI, his company's AI operating system. Read it the way "
        "a capable chief of staff would, knowing his products and what his team is working on, and say what he "
        "means. He writes plainly and briefly and does not name folders, missions or agents: work that out from "
        "what he is talking about.\n\n"
        f"WHAT RICHARD SAID:\n{text[:REQUEST_CHARS]}\n\n"
        f"HIS WORKSPACES (one per product or project):\n{spaces}\n"
        f"The workspace selected on his screen: {selected or '(none)'} (this is only where his screen happens to "
        "be; the request decides the workspace).\n\n"
        f"HIS RECENT MISSIONS (newest first):\n{recent}\n\n"
        f"JAI'S AGENTS:\n{agents}\n\n"
        "Decide:\n"
        "- kind: \"question\" when he wants an answer, a status or a quick look-up told back to him, not a "
        "piece of work done and saved. \"follow_up\" when he wants more "
        "work on, a change to, a correction of, or the rest of one of the recent missions above, whether or not he "
        "says \"carry on\" (for example he names its subject, its file, or what it should do differently). "
        "\"mission\" when it is a new piece of work. \"direct\" when it is a single built-in instruction to JAI "
        "itself (remember or recall something, register or scan a workspace, run one named command, start a named "
        "workflow, a self-healing or self-evolution instruction).\n"
        "- mission: for a follow_up, the id of the recent mission he means; otherwise null. Choose it by what the "
        "work is about, not by which is newest. If no recent mission fits, it is not a follow_up.\n"
        "- workspace: the name of the workspace the work belongs to. For a follow_up it is that mission's "
        "workspace. For new work it is the product he is talking about. null when he names no product and nothing "
        "tells you.\n"
        "- agent: the one agent whose work this is, by what the work actually is (a contact database of businesses "
        "to partner with is partnerships; a list of investors or buyers is sales; places to promote a product is "
        "marketing). For a follow_up keep the agent already doing that mission unless he asks for another. "
        "\"builder\" for software. null for a question or a direct instruction.\n"
        "- confidence: 0 to 1. Be honest: below 0.6 when you are guessing.\n"
        "- why: one plain sentence Richard can read.\n\n"
        'Answer with JSON only: {"kind": "...", "mission": "<id or null>", "workspace": "<name or null>", '
        '"agent": "<name or null>", "confidence": <0 to 1>, "why": "..."}')


async def _ask(prompt: str) -> Optional[Dict[str, Any]]:
    """The model's reading, as a dict, or None. Tests never spend provider credit: they stand a reading in for
    this function."""
    from app.core.config import settings
    from app.core.providers.base import CompletionRequest, Message
    from app.core.providers.router import get_router

    if getattr(settings, "TESTING", False) or not getattr(settings, "UNDERSTANDING_ENABLED", True):
        return None
    models = [str(getattr(settings, "UNDERSTANDING_MODEL", "") or ""), str(getattr(settings, "ROUTER_MODEL", "") or ""),
              "claude-haiku-5-5"]
    for model in dict.fromkeys(m for m in models if m):
        try:
            response = await asyncio.wait_for(get_router().complete(CompletionRequest(
                model=model, messages=[Message(role="user", content=prompt)], temperature=0.0, max_tokens=300)),
                timeout=SECONDS)
            found = re.search(r"\{.*\}", response.content or "", re.S)
            answer = json.loads(found.group(0)) if found else None
        except Exception as exc:  # noqa: BLE001 - the next model is asked
            logger.info(f"{model} did not read the request: {exc}")
            continue
        if isinstance(answer, dict):
            answer["_model"] = model
            return answer
    return None


def _named(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in ("", "null", "none") else text


def read(answer: Dict[str, Any], workspaces: List[Any], missions: List[Dict[str, Any]]) -> Optional[Understanding]:
    """The model's answer checked against what exists: a mission, workspace or agent it names must be a real one."""
    from app.core.command.work_type import DESCRIBED

    kind = _named(answer.get("kind")).lower()
    if kind not in KINDS:
        return None
    try:
        confidence = max(0.0, min(1.0, float(answer.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0
    understood = Understanding(kind=kind, confidence=round(confidence, 2), why=_short(answer.get("why"), 300),
                               model=str(answer.get("_model") or ""))
    wanted = _named(answer.get("mission")).lower()
    mission = next((m for m in missions if wanted and (m["short"] == wanted[:8] or m["id"] == wanted)), None)
    if kind == "follow_up":
        if mission is None:
            return None  # a follow-up to nothing JAI can find: the backup rules decide
        understood.mission_id, understood.mission_running = mission["id"], bool(mission["running"])
        understood.workspace_id, understood.workspace = mission["workspace_id"], mission["workspace"]
    else:
        name = re.sub(r"[^a-z0-9]", "", _named(answer.get("workspace")).lower())
        space = next((w for w in workspaces if name and re.sub(r"[^a-z0-9]", "", w.name.lower()) == name), None)
        if space is not None:
            understood.workspace_id, understood.workspace = str(space.id), space.name
    agent = _named(answer.get("agent")).lower()
    if agent in DESCRIBED and kind in ("mission", "follow_up"):
        understood.specialist = agent
    elif kind == "follow_up" and mission is not None:
        understood.specialist = mission["agent"]
    return understood


async def understand(db: AsyncSession, text: str, owner: Optional[UUID], selected: Optional[UUID],
                     current: Optional[UUID] = None) -> Optional[Understanding]:
    """What Richard's request is, or None when the model cannot be asked (the word lists decide then). Never
    raises."""
    try:
        from app.core.command.work_type import named_specialist

        if not (text or "").strip() or named_specialist(text):
            return None  # a workflow's step already names its agent and runs where its workflow runs
        async with db.begin_nested():  # reading only; a failed read never spoils the request's own transaction
            workspaces = await _workspaces(db, owner)
            missions = await recent_missions(db, workspaces, current)
        chosen = next((w.name for w in workspaces if selected is not None and w.id == selected), "")
        answer = await _ask(prompt_for(text, workspaces, missions, chosen))
        if not answer:
            return None
        understood = read(answer, workspaces, missions)
        if understood is not None:
            logger.info(f"understood: {understood.line()}")
        return understood
    except Exception as exc:  # noqa: BLE001 - the word lists still decide
        logger.info(f"request not read by the model: {exc}")
        return None


# Handlers a piece of work may be moved off when JAI reads the request as a mission: the generic answer, the one-off
# research answer and the one-off company draft. A precise instruction the words recognise (run this command,
# remember this, register or scan a workspace, install packages, start a named workflow, self-healing, self-evolution,
# swarm) keeps its own handler.
_MAY_BECOME_MISSION = (None, "agent_task", "research", "company_workflow")


def intent(by_words: Optional[str], understood: Optional[Understanding]) -> Optional[str]:
    """The handler a request goes to: the model's reading when it is sure, else what the word lists said."""
    if understood is None or not understood.sure:
        return by_words
    if understood.kind in ("mission", "follow_up"):
        return "agent_task" if by_words in _MAY_BECOME_MISSION else by_words
    if understood.kind == "question" and by_words == "agent_task":
        return None  # a question is answered, not run as a mission
    return by_words


def route(understood: Optional[Understanding]) -> Optional[Dict[str, Any]]:
    """The agent the model read the work as belonging to, in work_type.classify's shape, or None."""
    if understood is None or not understood.sure or not understood.specialist:
        return None
    from app.core.command.work_type import _route

    why = understood.why or "what the request is about"
    return {"route": _route(understood.specialist, "understood", understood.confidence, why),
            "source": "understood", "confidence": understood.confidence, "matched": why}


async def of_task(db: AsyncSession, task_id: Any) -> Optional[Understanding]:
    """The reading kept on a mission's record, or None."""
    if task_id is None or db is None:
        return None
    try:
        from app.models.task import Task

        context = (await db.execute(select(Task.context).where(Task.id == UUID(str(task_id))))).scalar_one_or_none()
        return Understanding.from_dict((context or {}).get("understanding")) if isinstance(context, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"no reading on the mission's record: {exc}")
        return None
