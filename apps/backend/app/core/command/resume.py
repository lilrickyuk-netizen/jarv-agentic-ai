"""
JAI Backend - A new mission carries on from the last one instead of starting again

A mission's rounds already share one requirement list, but a new mission used to derive a fresh list from its
brief, so "carry on building MYCO Phase 0" re-planned work that was already done and threw the evidence away.

When a new mission says to carry on (carry on, continue, resume, finish, where it left off) or names the same phase
as a recent mission on the same project that was not verified complete (in the same workspace, or in another one
when both name the project's folder or this workspace), it takes that mission's state over:

- its requirement list, every status and evidence kept, so the team plans only what is still open;
- a short account of where it left off: each package's outcome, what the Verifier found unmet, the last report.

The Verifier still checks every requirement against the files at the end, carried-over ones included: nothing is
accepted on the strength of an earlier mission's word.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task

CARRY_ON = re.compile(r"\b(carry on|carry-on|continue|continuing|resume|pick up|left off|finish|complete the rest)\b",
                      re.I)
PHASE = re.compile(r"\bphase\s*(\d+)\b", re.I)
LOOK_BACK_DAYS = 21


FOLDER = re.compile(r"projects[\\/]+([A-Za-z0-9_.-]+)", re.I)


def _phases(text: str) -> set:
    return {m.group(1) for m in PHASE.finditer(text or "")}


def _folders(text: str) -> set:
    return {m.group(1).lower() for m in FOLDER.finditer(text or "")}


def same_work(brief: str, earlier_brief: str) -> bool:
    """Both missions are about the same project: when both name a project folder, it is the same one."""
    mine, theirs = _folders(brief), _folders(earlier_brief)
    return not (mine and theirs) or bool(mine & theirs)


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def same_project(brief: str, earlier_brief: str, workspace_name: str = "") -> bool:
    """Plainly the same project, for a mission in another workspace: both name the same project folder, or both
    name this workspace (four letters or more)."""
    if _folders(brief) & _folders(earlier_brief):
        return True
    name = _letters(workspace_name)
    return len(name) >= 4 and name in _letters(brief) and name in _letters(earlier_brief)


async def _workspace_name(db: AsyncSession, workspace_id: UUID) -> str:
    from app.models.workspace import Workspace

    return (await db.execute(select(Workspace.name).where(Workspace.id == workspace_id))).scalar_one_or_none() or ""


def wants_to_carry_on(brief: str, earlier_brief: str) -> bool:
    """The new brief says to carry on, or it is about the same phase as the earlier mission, and both are about
    the same project."""
    if not same_work(brief, earlier_brief):
        return False
    if CARRY_ON.search(brief or ""):
        return True
    shared = _phases(brief) & _phases(earlier_brief)
    return bool(shared)


# Words that say what to do, not what the work is about: they do not tie a "carry on" to an earlier mission.
_NOT_TOPIC = set("""carry continue continuing resume pick left finish complete rest mission missions work please with
from that this then them they their there here into each every stop adding add rows row rename remove fill mark
check checks still requirement requirements status done open last where what which when should would could also
have about make sure keep just only more less after before again""".split())
SAME_TOPIC = 2       # shared topic words for a "carry on" to take over a mission in the same workspace
OTHER_WORKSPACE = 3  # and in another of Richard's workspaces, when the brief names no folder


def topic(text: str) -> set:
    """The words that say what a brief is about (four letters or more, plural folded)."""
    words = set()
    for word in re.findall(r"[a-z][a-z-]{3,}", (text or "").lower()):
        for part in word.split("-"):
            part = part[:-1] if len(part) > 4 and part.endswith("s") else part
            if len(part) >= 4 and part not in _NOT_TOPIC:
                words.add(part)
    return words


async def last_state(db: AsyncSession, workspace_id: Optional[UUID], current_task_id: Optional[UUID],
                     brief: str) -> Optional[Dict[str, Any]]:
    """The state to carry on from: {"task_id", "requirements", "known", "brief", "workspace_id"}, or None when this
    mission starts fresh.

    The mission carried on is the one the brief is about, not just the most recent (14 November: "carry on with
    the booking-partners database" took over an investors mission that happened to be newer, in the wrong
    folder). A "carry on" that names its subject takes over the unfinished mission sharing the most topic words
    with it; one that names nothing ("carry on") takes over the most recent. A brief that names no folder may
    carry on a mission in another of the same owner's workspaces when it is plainly about that work."""
    if workspace_id is None:
        return None
    from app.models.workspace import Workspace

    since = datetime.now(timezone.utc) - timedelta(days=LOOK_BACK_DAYS)
    # Earlier work on the same project may have run in another workspace (MYCO's first missions ran in the
    # Command Center before missions went to the workspace their brief is about): those count only when they are
    # plainly the same project, by its folder or by this workspace's name, or by what the brief is about.
    name = await _workspace_name(db, workspace_id)
    owner = (await db.execute(select(Workspace.owner_id).where(Workspace.id == workspace_id))).scalar_one_or_none()
    mine = topic(brief)
    asked = bool(CARRY_ON.search(brief or ""))
    no_folder = not _folders(brief)
    query = (select(Task, Workspace.owner_id).outerjoin(Workspace, Workspace.id == Task.workspace_id)
             .where(Task.task_type == "command", Task.created_at >= since)
             .order_by(Task.created_at.desc()).limit(120))
    best: Optional[tuple] = None
    for order, (task, task_owner) in enumerate((await db.execute(query)).all()):
        if current_task_id is not None and task.id == current_task_id:
            continue
        earlier = task.description or task.title or ""
        shared = len(mine & topic(earlier))
        here = task.workspace_id == workspace_id
        if not here and not same_project(brief, earlier, name):
            if not (asked and no_folder and owner is not None and task_owner == owner and shared >= OTHER_WORKSPACE):
                continue  # another workspace's work
        if not wants_to_carry_on(brief, earlier):
            continue  # another piece of work in the same workspace
        if asked and mine and shared < SAME_TOPIC and not _phases(brief) & _phases(earlier) \
                and not _folders(brief) & _folders(earlier):
            continue  # it says carry on, but with something else
        rank = (shared, -order)
        if best is not None and rank <= best[0]:
            continue
        result = await _state(task)
        requirements = [r for r in (result.get("requirements") or []) if isinstance(r, dict) and r.get("id")]
        if not requirements:
            continue  # a short command, or a mission that stopped before it had a requirement list
        best = (rank, task, result, requirements)
        if not mine:
            break  # "carry on" alone: the most recent unfinished mission
    if best is None:
        return None
    _, task, result, requirements = best
    if (result.get("verification") or {}).get("verified") is True:
        return None  # the mission on this work finished verified: this one is new work
    return {"task_id": str(task.id), "requirements": carried(requirements, task),
            "known": left_off(task, result, requirements), "brief": task.description or task.title or "",
            "workspace_id": task.workspace_id}


async def state_of(db: AsyncSession, task_id: Any, current_task_id: Optional[UUID] = None
                   ) -> Optional[Dict[str, Any]]:
    """The state of one named mission to carry on from, in last_state's shape, or None when it kept no requirement
    list. Used when JAI has read the request as more work on that mission (command/understanding): a change asked
    for after the mission finished verified still carries its list, so the finished work is kept and checked."""
    try:
        wanted = UUID(str(task_id))
    except (TypeError, ValueError):
        return None
    if current_task_id is not None and wanted == current_task_id:
        return None
    task = (await db.execute(select(Task).where(Task.id == wanted))).scalar_one_or_none()
    if task is None:
        return None
    result = await _state(task)
    requirements = [r for r in (result.get("requirements") or []) if isinstance(r, dict) and r.get("id")]
    if not requirements:
        return None
    return {"task_id": str(task.id), "requirements": carried(requirements, task),
            "known": left_off(task, result, requirements), "brief": task.description or task.title or "",
            "workspace_id": task.workspace_id}


async def _state(task: Task) -> Dict[str, Any]:
    """A mission's final record; for one stopped or cancelled before it finished, its live progress (kept for a
    week): the requirement list with statuses and evidence, and every package's state."""
    result = dict(task.result or {})
    if result.get("requirements"):
        return result
    from app.core.command import progress

    saved = await progress.load(task.id) or {}
    items = (saved.get("requirements") or {}).get("items") or []
    if items:
        result["requirements"] = [{**item, "source": item.get("source") or "mission"} for item in items]
        result.setdefault("team", saved.get("team") or {})
    return result


def carried(requirements: List[Dict[str, Any]], task: Task) -> List[Dict[str, Any]]:
    """The earlier requirements as this mission's own: done ones stay done with their evidence (the Verifier checks
    them again), everything else is open for the team."""
    when = f"{task.created_at:%d %b}" if task.created_at else "earlier"
    out = []
    for r in requirements:
        item = dict(r)
        if item.get("status") == "done":
            evidence = str(item.get("evidence") or "").strip()
            item["evidence"] = f"(from the {when} mission) {evidence}".strip()
        else:
            item["status"] = "open"
        out.append(item)
    return out


def left_off(task: Task, result: Dict[str, Any], requirements: List[Dict[str, Any]]) -> str:
    """Where the earlier mission left off, for the lead and the planner (short: it goes into every brief)."""
    when = f"{task.created_at:%d %b %H:%M}" if task.created_at else "earlier"
    done = [r["id"] for r in requirements if r.get("status") == "done"]
    open_ = [r["id"] for r in requirements if r.get("status") != "done"]
    lines = [f"WHERE THE LAST MISSION LEFT OFF ({when}, {task.status}). Carry on from here: do not redo finished "
             f"work, build on the files already in the workspace, and plan only what is still open.",
             f"- Requirements done ({len(done)}): {', '.join(done) or 'none'}",
             f"- Still open ({len(open_)}): {', '.join(open_) or 'none'}"]
    for package in ((result.get("team") or {}).get("packages") or [])[:12]:
        summary = " ".join(str(package.get("summary") or "").split())[:220]
        lines.append(f"- {package.get('id')} {package.get('role') or package.get('specialist')} — "
                     f"{package.get('title')}: {'finished' if package.get('success') else 'stopped'}"
                     + (f". {summary}" if summary else ""))
    unmet = (result.get("verification") or {}).get("unmet") or []
    if unmet:
        lines.append("- The Verifier found unmet: " + "; ".join(" ".join(str(u).split())[:200] for u in unmet[:8]))
    if task.error_message:
        lines.append(f"- It stopped because: {' '.join(task.error_message.split())[:300]}")
    try:  # what it had already looked up, so the work carries on and does not start its research again
        from app.core.command.continuation import research_record

        lines += research_record(result.get("tool_calls"))
    except Exception:  # noqa: BLE001 - the requirement list alone still carries the mission on
        pass
    return "\n".join(lines)
