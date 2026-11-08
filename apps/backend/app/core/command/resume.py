"""
JAI Backend - A new mission carries on from the last one instead of starting again

A mission's rounds already share one requirement list, but a new mission used to derive a fresh list from its
brief, so "carry on building MYCO Phase 0" re-planned work that was already done and threw the evidence away.

When a new mission says to carry on (carry on, continue, resume, finish, where it left off) or names the same phase
as a recent mission in the same workspace that was not verified complete, it takes that mission's state over:

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


def wants_to_carry_on(brief: str, earlier_brief: str) -> bool:
    """The new brief says to carry on, or it is about the same phase as the earlier mission, and both are about
    the same project."""
    if not same_work(brief, earlier_brief):
        return False
    if CARRY_ON.search(brief or ""):
        return True
    shared = _phases(brief) & _phases(earlier_brief)
    return bool(shared)


async def last_state(db: AsyncSession, workspace_id: Optional[UUID], current_task_id: Optional[UUID],
                     brief: str) -> Optional[Dict[str, Any]]:
    """The state to carry on from: {"task_id", "requirements", "known"}, or None when this mission starts fresh."""
    if workspace_id is None:
        return None
    since = datetime.now(timezone.utc) - timedelta(days=LOOK_BACK_DAYS)
    query = (select(Task).where(Task.workspace_id == workspace_id, Task.task_type == "command",
                                Task.created_at >= since)
             .order_by(Task.created_at.desc()).limit(40))
    for task in (await db.execute(query)).scalars().all():
        if current_task_id is not None and task.id == current_task_id:
            continue
        if not wants_to_carry_on(brief, task.description or task.title or ""):
            continue  # another piece of work in the same workspace
        result = await _state(task)
        requirements = [r for r in (result.get("requirements") or []) if isinstance(r, dict) and r.get("id")]
        if not requirements:
            continue  # a short command, or a mission that stopped before it had a requirement list
        if (result.get("verification") or {}).get("verified") is True:
            return None  # the last mission on this work finished verified: this one is new work
        return {"task_id": str(task.id), "requirements": carried(requirements, task),
                "known": left_off(task, result, requirements)}
    return None


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
    return "\n".join(lines)
