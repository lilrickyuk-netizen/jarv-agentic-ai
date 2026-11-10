"""
JAI Backend - Mission continuation

Continues a mission that stopped at its step limit (status
``needs_continuation``). The same task continues in the same workspace: prior
work stays on disk and in the task record; nothing restarts.

The mission runner calls this automatically (routine continuation is JAI's
job, not Richard's), up to ``MAX_AUTO_CONTINUATIONS`` per mission. The tasks
API exposes the same path for an explicit resume.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.command.agent_executor import AgentExecutor
from app.core.command.mission_org import mission_executor
from app.core.command.tool_runtime import ToolRuntime
from app.core.config import settings
from app.core.runtime import lifecycle
from app.core.command.metrics import merge as merge_metrics
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import AuditLog
from app.models.task import Task

logger = logging.getLogger(__name__)

MAX_AUTO_CONTINUATIONS = 6
PROGRESS_CHARS = 14000
PROGRESS_CALLS = 300


def progress_note(result: Dict[str, Any]) -> str:
    """What earlier rounds of this mission already did, for the next round's agent.

    Each round starts a new conversation, so without this the agent sees only the request and
    the files on disk, and cannot tell its own finished work from anything else in the folder.
    Built from the task's recorded tool calls (inputs are already redacted) and the last summary.
    """
    calls = [c for c in (result.get("tool_calls") or []) if isinstance(c, dict)][-PROGRESS_CALLS:]
    written: Dict[str, bool] = {}
    commands: list = []
    for call in calls:
        inputs = call.get("inputs") if isinstance(call.get("inputs"), dict) else {}
        tool = call.get("tool")
        if tool == "write_file" and inputs.get("path"):
            written[str(inputs["path"])] = bool(call.get("success"))
        elif tool == "run_command" and inputs.get("command"):
            output = call.get("output") if isinstance(call.get("output"), dict) else {}
            exit_code = output.get("exit_code")
            outcome = f"exit {exit_code}" if exit_code is not None else ("ok" if call.get("success") else "not run")
            commands.append(f"- `{str(inputs['command'])[:200]}`: {outcome}")
    lines = ["PROGRESS FROM EARLIER ROUNDS OF THIS SAME MISSION (your own work; it is on disk):"]
    if written:
        lines.append("Files written:")
        lines += [f"- {path}{'' if ok else ' (write failed)'}" for path, ok in written.items()]
    if commands:
        lines.append("Commands run (latest last):")
        lines += commands[-80:]
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    if verification.get("unmet"):
        lines.append("THE INDEPENDENT CHECK FOUND THESE REQUIREMENTS NOT MET (fix each one, then verify):")
        lines += [f"- {item}" for item in verification["unmet"][:30]]
    summary = str(result.get("response") or "").strip()
    if summary:
        lines.append("Last round's summary:")
        lines.append(summary[:3000])
    if len(lines) == 1:
        return ""
    lines.append("Continue from here: check what is still missing against the mission, do it, verify it, "
                 "and call finish. Do not redo finished work and do not stop just because this is a new round.")
    note = "\n".join(lines)
    return note if len(note) <= PROGRESS_CHARS else note[:PROGRESS_CHARS - 40] + "\n(earlier entries omitted)"


def continuation_count(task: Task) -> int:
    result = task.result if isinstance(task.result, dict) else {}
    return int(result.get("continuation_count", 0) or 0)


def automatic_rounds(task: Task) -> int:
    """How many times the mission runner has re-queued this mission on its own.

    Kept apart from continuation_count, which also counts the short pauses inside each run: one
    run already counts four or five of those, so capping on it stopped long missions after a
    single round.
    """
    result = task.result if isinstance(task.result, dict) else {}
    return int(result.get("auto_rounds", 0) or 0)


RESUMABLE = (lifecycle.NEEDS_CONTINUATION, lifecycle.PARTIAL)

# A round that changes nothing in the workspace and still does not pass the independent check would only repeat
# the same checks next round. After this many such rounds in a row the mission stops for Richard's review.
IDLE_ROUNDS_LIMIT = 2
_CHANGES = ("write_file", "edit_file", "move_file", "copy_file", "create_folder", "delete_file_with_boundary")


def round_changed_workspace(calls) -> bool:
    """Whether a round changed the workspace: a file written, edited, moved or deleted, or a commit made."""
    for call in calls or []:
        if not isinstance(call, dict) or not call.get("success"):
            continue
        if call.get("tool") in _CHANGES:
            return True
        command = str((call.get("inputs") or {}).get("command") or "").strip().lower()
        if call.get("tool") == "run_command" and command.startswith("git commit"):
            return True
    return False


def _done(requirements) -> int:
    return sum(1 for r in requirements or [] if isinstance(r, dict) and r.get("status") == "done")


def round_progressed(before, after, calls) -> bool:
    """Whether a round moved the mission on. With a requirement list, only a requirement newly done counts: on
    8 November MYCO rounds kept changing files, completed nothing and kept paying. Without one, a change to the
    workspace counts."""
    if after:
        return _done(after) > _done(before)
    return round_changed_workspace(calls)


def after_round(outcome: str, reason, changed: bool, idle_before: int):
    """The outcome of a round once idle rounds are counted: (outcome, reason, idle rounds so far)."""
    idle = 0 if changed else int(idle_before or 0) + 1
    if outcome == lifecycle.NEEDS_CONTINUATION and idle >= IDLE_ROUNDS_LIMIT:
        return (lifecycle.PARTIAL,
                f"Stopped for Richard's review: {idle} rounds in a row completed no new requirement and the "
                f"independent check still did not pass, so another round would only pay to repeat them. "
                f"The report shows what is evidenced and what the check still disputes.", idle)
    return outcome, reason, idle


async def queue_resume(db: AsyncSession, task: Task, *, operator: str, reason: str) -> Dict[str, Any]:
    """Send a paused mission back to the worker to carry on: the same task, workspace and progress.

    The next round runs in JAI's worker, never inside a web request, so closing or leaving the
    dashboard cannot stop it. A resume Richard asks for gives the mission a fresh allowance of
    automatic rounds and a new spending allowance.
    """
    from app.core.runtime.dispatcher import dispatch_mission

    status = lifecycle.normalise(task.status)
    if status not in RESUMABLE:
        raise ValueError(f"Task status '{status}' is not resumable.")
    if (task.meta_data or {}).get("archived_at"):
        raise ValueError("This mission is archived; unarchive it before resuming.")
    other = await other_active_mission(db, task)
    if other is not None:
        raise ValueError(f"Mission {str(other.id)[:8]} ('{(other.title or '')[:60]}') is already active in this "
                         f"workspace. Only one mission works in a folder at a time: let it finish, or close it, "
                         f"before carrying on with this one.")
    lifecycle.transition(task, lifecycle.QUEUED, reason=reason, actor=operator)
    result = dict(task.result if isinstance(task.result, dict) else {})
    if result.pop("provider_unavailable", None):
        # The provider pause is over once the mission carries on: its note no longer describes the mission.
        note = str(result.pop("final_status_reason", "") or "")
        if note:
            result["response"] = str(result.get("response") or "").replace(note, "").strip()
        task.error_message = None
    task.result = {**result, "auto_rounds": 0}
    task.meta_data = {**(task.meta_data or {}), "resume_mode": "continuation", "operator": operator}
    from app.core.command import mission_budget

    await mission_budget.reset(task.id)  # a resume he asks for comes with a new spending allowance
    await db.commit()
    dispatched = await dispatch_mission(task.id, reason=reason)
    return {"task_id": str(task.id), "status": lifecycle.QUEUED, "resumed": True,
            "continuation_count": continuation_count(task), "dispatch": dispatched.get("mode"),
            "reply": "Carrying on with that mission from where it stopped."}


# A mission is active while it runs, waits in the queue, recovers, or is about to be continued.
ACTIVE = (lifecycle.RUNNING, lifecycle.QUEUED, lifecycle.RECOVERING, lifecycle.NEEDS_CONTINUATION)


async def other_active_mission(db: AsyncSession, task: Task, statuses=ACTIVE):
    """Another mission working in the same workspace right now, if any (archived ones never count).
    Two missions in one folder undo each other's work: the old Phase 0 missions, resumed by voice, kept
    reverting the correction mission's changes."""
    from sqlalchemy import select

    if task.workspace_id is None:
        return None
    rows = (await db.execute(select(Task).where(
        Task.workspace_id == task.workspace_id, Task.id != task.id, Task.task_type == task.task_type,
        Task.status.in_(statuses)).order_by(Task.created_at.desc()))).scalars().all()
    return next((t for t in rows if not (t.meta_data or {}).get("archived_at")), None)


async def newer_mission(db: AsyncSession, task: Task):
    """A later mission in the same workspace that is still live (active, stopped part-way or waiting on
    Richard): it supersedes this one, so this one must not continue on its own."""
    from sqlalchemy import select

    if task.workspace_id is None or task.created_at is None:
        return None
    live = ACTIVE + (lifecycle.PARTIAL, lifecycle.WAITING_ON_APPROVAL)
    rows = (await db.execute(select(Task).where(
        Task.workspace_id == task.workspace_id, Task.id != task.id, Task.task_type == task.task_type,
        Task.status.in_(live), Task.created_at > task.created_at))).scalars().all()
    return next((t for t in rows if not (t.meta_data or {}).get("archived_at")), None)


async def recall_for_mission(db: AsyncSession, workspace_id, text: str) -> str:
    """What JAI remembers and has verified for this workspace, for the mission's agent."""
    from app.core.command.service import _known_for_mission
    from app.core.jarv_memory import memory_service
    from app.core.learning import learning_service

    context: Dict[str, Any] = {"relevant_memory": [], "verified_lessons": []}
    if workspace_id is None:
        return ""
    try:
        hits = await memory_service.search_scored(db, text[:2000], limit=5, workspace_id=workspace_id)
        context["relevant_memory"] = [{"type": h.memory.memory_type, "content": h.memory.content} for h in hits]
    except Exception as exc:  # noqa: BLE001 - recall is advisory; the round runs without it
        logger.warning(f"memory recall for continuation failed: {exc}")
    try:
        lessons = await learning_service.retrieve_lessons(db, workspace_id=workspace_id, agent_name="orchestrator",
                                                          query=text[:2000], limit=3)
        context["verified_lessons"] = [{"lesson": i["lesson"], "outcome": i["polarity"]} for i in lessons]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"lesson recall for continuation failed: {exc}")
    return _known_for_mission(context)


async def _cost_line(task_id) -> str:
    from app.core.command import mission_budget

    return await mission_budget.line(task_id)


async def continue_mission(db: AsyncSession, task: Task, *, operator: str) -> Dict[str, Any]:
    """Run the next continuation round. The task must already be ``running``."""
    now = datetime.now(timezone.utc)
    res = task.result if isinstance(task.result, dict) else {}
    mission = res.get("mission") or task.description or task.title
    root = res.get("workspace_path")
    prior = int(res.get("continuation_count", 0) or 0)
    number = prior + 1
    max_cont = int(res.get("max_continuations", 4) or 4)

    db.add(LiveOperationsFeedItem(
        id=uuid4(), workspace_id=task.workspace_id, item_type="resume", severity="info",
        title="Mission continuing",
        message=f"Continuation #{number} for task {str(task.id)[:8]} (same workspace, no restart).",
        related_task_id=task.id, requires_action=False, created_at=now, updated_at=now))
    await db.flush()

    runtime = ToolRuntime(db, task.workspace_id, task.id, operator=operator)
    # The same model that started the mission continues it.
    model = res.get("model") or getattr(settings, "DEFAULT_MODEL", "claude-sonnet-4-6")
    # A round that completed nothing hands the software work to Opus for the next one.
    executor = mission_executor(runtime, model, root, stuck=int(res.get("idle_rounds") or 0) >= 1)
    note = progress_note(res)
    from app.core.command import sign_off

    requirements = res.get("requirements") or None
    meta = dict(task.meta_data or {})
    if sign_off.granted(meta):  # Richard approved the sign-off the mission stopped for
        approved, requirements = sign_off.resume(requirements, meta)
        note = f"{note}\n\n{approved}" if note else approved
        meta["sign_off_used_at"] = now.isoformat(timespec="seconds")
        task.meta_data = meta
    result = await executor.run(f"{mission}\n\n{note}" if note else mission, steps_per_round=8,
                                max_continuations=max_cont, start_continuation=prior,
                                known=await recall_for_mission(db, task.workspace_id, str(mission)),
                                requirements=requirements,
                                prior_calls=res.get("tool_calls") or None)

    if result["needs_continuation"] and result.get("finished"):
        outcome, reason = lifecycle.NEEDS_CONTINUATION, "The independent check found work still to do."
    elif result["needs_continuation"]:
        outcome, reason = lifecycle.NEEDS_CONTINUATION, "Reached the step limit again; checkpoint saved."
    elif result["success"] and sign_off.waiting(result):
        outcome, reason = lifecycle.BLOCKED, sign_off.reason(sign_off.waiting(result))
    elif result["success"]:
        outcome, reason = lifecycle.COMPLETED, None
    elif result.get("answer"):
        outcome, reason = lifecycle.PARTIAL, "Continued and produced output but could not verify full success."
    else:
        outcome, reason = lifecycle.FAILED, "Continuation produced no verifiable output."

    outcome, reason, idle = after_round(outcome, reason, round_progressed(res.get("requirements"),
                                                                          result.get("requirements"),
                                                                          runtime.calls),
                                        int(res.get("idle_rounds") or 0))
    checkpoint_id = str(uuid4()) if outcome == lifecycle.NEEDS_CONTINUATION else res.get("checkpoint_id")
    updated = dict(res)
    updated.update({
        "response": (result["answer"] or "") + await _cost_line(task.id), "task_status": outcome,
        "agent_needs_continuation": result["needs_continuation"],
        "step_limit_reached": result["step_limit_reached"],
        "continuation_required": result["needs_continuation"],
        # The run counts on from this round's number, so its own count already includes the earlier ones.
        "continuation_count": max(number, int(result.get("continuation_count") or 0)),
        "resume_from_step": result["resume_from_step"],
        "remaining_steps": result["remaining_steps"],
        "checkpoint_id": checkpoint_id,
        "final_status_reason": reason,
        "idle_rounds": idle,
        "verification": result.get("verification"),
        "requirements": result.get("requirements") or res.get("requirements"),
        "report": result.get("report"),
        "agent_summary": result.get("agent_summary"),
        # The mission's cost and effort across every round so far (Upgrade 5).
        "metrics": merge_metrics(res.get("metrics"), result.get("metrics") or {}),
        "tool_calls": (res.get("tool_calls") or []) + runtime.calls,
        "team": result.get("team") or res.get("team"),
    })
    task.result = updated
    task.tokens_used = (task.tokens_used or 0) + int(result.get("tokens", 0))
    await db.refresh(task, attribute_names=["status"])
    if lifecycle.normalise(task.status) not in (lifecycle.CANCELLED, lifecycle.WAITING_ON_APPROVAL):
        lifecycle.transition(task, outcome, reason=reason or "", actor="orchestrator")
        if outcome == lifecycle.FAILED:
            task.error_message = reason
        if outcome == lifecycle.BLOCKED:
            sign_off.mark(task, sign_off.waiting(result))

    finished = datetime.now(timezone.utc)
    db.add(LiveOperationsFeedItem(
        id=uuid4(), workspace_id=task.workspace_id, item_type="resume",
        severity="success" if outcome == lifecycle.COMPLETED else "warning",
        title=f"Continuation -> {task.status}",
        message=(result["answer"] or "")[:300], related_task_id=task.id, requires_action=False,
        created_at=finished, updated_at=finished))
    db.add(AuditLog(
        id=uuid4(), workspace_id=task.workspace_id, actor_type="system",
        action="task_resumed", action_category="resume",
        description=f"Task {task.id} continuation #{number} -> {task.status}",
        target_type="task", target_id=str(task.id), after_state={"status": task.status},
        success=task.status == lifecycle.COMPLETED, created_at=finished, updated_at=finished))
    await db.commit()

    return {"task_id": str(task.id), "status": task.status,
            "continuation_count": updated["continuation_count"],
            "checkpoint_id": checkpoint_id, "reason": reason,
            "output_preview": (result["answer"] or "")[:400]}
