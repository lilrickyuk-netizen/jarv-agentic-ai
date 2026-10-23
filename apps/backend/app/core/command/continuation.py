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
    executor = AgentExecutor(runtime, getattr(settings, "DEFAULT_MODEL", "claude-sonnet-4-6"), root)
    result = await executor.run(mission, steps_per_round=8, max_continuations=max_cont,
                                start_continuation=prior)

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
