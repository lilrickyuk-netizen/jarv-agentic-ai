"""
JARV Backend - Mission continuation

Continues a mission that stopped at its step limit (status
``needs_continuation``). The same task continues in the same workspace: prior
work stays on disk and in the task record; nothing restarts.

The mission runner calls this automatically (routine continuation is JARV's
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
from app.core.command.tool_runtime import ToolRuntime
from app.core.config import settings
from app.core.runtime import lifecycle
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
    executor = AgentExecutor(runtime, model, root)
    note = progress_note(res)
    result = await executor.run(f"{mission}\n\n{note}" if note else mission, steps_per_round=8,
                                max_continuations=max_cont, start_continuation=prior)

    if result["needs_continuation"]:
        outcome, reason = lifecycle.NEEDS_CONTINUATION, "Reached the step limit again; checkpoint saved."
    elif result["success"]:
        outcome, reason = lifecycle.COMPLETED, None
    elif result.get("answer"):
        outcome, reason = lifecycle.PARTIAL, "Continued and produced output but could not verify full success."
    else:
        outcome, reason = lifecycle.FAILED, "Continuation produced no verifiable output."

    checkpoint_id = str(uuid4()) if outcome == lifecycle.NEEDS_CONTINUATION else res.get("checkpoint_id")
    updated = dict(res)
    updated.update({
        "response": result["answer"], "task_status": outcome,
        "agent_needs_continuation": result["needs_continuation"],
        "step_limit_reached": result["step_limit_reached"],
        "continuation_required": result["needs_continuation"],
        "continuation_count": number + result["continuation_count"],
        "resume_from_step": result["resume_from_step"],
        "remaining_steps": result["remaining_steps"],
        "checkpoint_id": checkpoint_id,
        "final_status_reason": reason,
        "tool_calls": (res.get("tool_calls") or []) + runtime.calls,
    })
    task.result = updated
    task.tokens_used = (task.tokens_used or 0) + int(result.get("tokens", 0))
    await db.refresh(task, attribute_names=["status"])
    if lifecycle.normalise(task.status) not in (lifecycle.CANCELLED, lifecycle.WAITING_ON_APPROVAL):
        lifecycle.transition(task, outcome, reason=reason or "", actor="orchestrator")
        if outcome == lifecycle.FAILED:
            task.error_message = reason

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
