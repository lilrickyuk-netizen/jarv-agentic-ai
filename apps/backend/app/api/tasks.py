"""
JARV Backend - Task Management API

Endpoints for managing tasks and task state transitions.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from datetime import datetime
from uuid import UUID
import logging

from app.core.state_machine import (
    TaskState,
    TaskStateMachine,
    get_all_states,
    get_terminal_states,
    get_waiting_states,
    get_active_states,
    validate_state_transition,
)
from app.core.database import get_db
from app.models.task import Task
from app.models.operations import AuditLog
from app.models.company_operations import LiveOperationsFeedItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


class StateTransitionRequest(BaseModel):
    """Request to transition task state"""
    to_state: str = Field(..., description="Target state")
    reason: str = Field(..., description="Reason for transition")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class StateInfo(BaseModel):
    """Information about a task state"""
    name: str
    value: str
    is_terminal: bool
    is_waiting: bool
    is_active: bool


class StateMachineInfo(BaseModel):
    """Information about task state machine"""
    current_state: str
    is_terminal: bool
    is_waiting: bool
    is_active: bool
    duration_in_state: float
    allowed_transitions: List[str]
    history_count: int


@router.get(
    "/states",
    response_model=List[StateInfo],
    summary="List all task states",
    description="Get list of all possible task states with their properties"
)
async def list_task_states() -> List[StateInfo]:
    """
    List all task states.

    Returns:
        List of all task states with properties
    """
    try:
        states = get_all_states()
        return [
            StateInfo(
                name=state.name,
                value=state.value,
                is_terminal=state.is_terminal,
                is_waiting=state.is_waiting,
                is_active=state.is_active,
            )
            for state in states
        ]

    except Exception as e:
        logger.error(f"Error listing task states: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list task states: {str(e)}"
        )


@router.get(
    "/states/terminal",
    response_model=List[str],
    summary="List terminal states",
    description="Get list of terminal states (states that cannot transition further)"
)
async def list_terminal_states() -> List[str]:
    """
    List terminal task states.

    Returns:
        List of terminal state names
    """
    try:
        states = get_terminal_states()
        return [state.value for state in states]

    except Exception as e:
        logger.error(f"Error listing terminal states: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list terminal states: {str(e)}"
        )


@router.get(
    "/states/waiting",
    response_model=List[str],
    summary="List waiting states",
    description="Get list of waiting states (states where execution is paused)"
)
async def list_waiting_states() -> List[str]:
    """
    List waiting task states.

    Returns:
        List of waiting state names
    """
    try:
        states = get_waiting_states()
        return [state.value for state in states]

    except Exception as e:
        logger.error(f"Error listing waiting states: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list waiting states: {str(e)}"
        )


@router.get(
    "/states/active",
    response_model=List[str],
    summary="List active states",
    description="Get list of active execution states"
)
async def list_active_states() -> List[str]:
    """
    List active task states.

    Returns:
        List of active state names
    """
    try:
        states = get_active_states()
        return [state.value for state in states]

    except Exception as e:
        logger.error(f"Error listing active states: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list active states: {str(e)}"
        )


@router.post(
    "/states/validate",
    response_model=Dict[str, Any],
    summary="Validate state transition",
    description="Check if a state transition is allowed"
)
async def validate_transition(
    from_state: str,
    to_state: str,
) -> Dict[str, Any]:
    """
    Validate if a state transition is allowed.

    Args:
        from_state: Current state
        to_state: Target state

    Returns:
        Validation result with allowed status
    """
    try:
        # Parse states
        try:
            from_state_enum = TaskState(from_state)
            to_state_enum = TaskState(to_state)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state name: {str(e)}"
            )

        # Validate transition
        is_allowed = validate_state_transition(from_state_enum, to_state_enum)

        # Get allowed transitions
        machine = TaskStateMachine(initial_state=from_state_enum)
        allowed = [s.value for s in machine.get_allowed_transitions()]

        return {
            "from_state": from_state,
            "to_state": to_state,
            "is_allowed": is_allowed,
            "allowed_transitions": allowed,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating transition: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate transition: {str(e)}"
        )


@router.get(
    "/states/diagram",
    response_model=Dict[str, List[str]],
    summary="Get state transition diagram",
    description="Get complete state machine diagram showing all allowed transitions"
)
async def get_state_diagram() -> Dict[str, List[str]]:
    """
    Get state transition diagram.

    Returns:
        Dictionary mapping each state to its allowed transitions
    """
    try:
        diagram = {}
        for state in get_all_states():
            machine = TaskStateMachine(initial_state=state)
            allowed = [s.value for s in machine.get_allowed_transitions()]
            diagram[state.value] = allowed

        return diagram

    except Exception as e:
        logger.error(f"Error getting state diagram: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get state diagram: {str(e)}"
        )


@router.post(
    "/state-machine/create",
    response_model=StateMachineInfo,
    summary="Create state machine",
    description="Create a new task state machine for testing"
)
async def create_state_machine_endpoint(
    initial_state: str = "created"
) -> StateMachineInfo:
    """
    Create a new task state machine.

    Args:
        initial_state: Initial state (default: created)

    Returns:
        State machine information
    """
    try:
        # Parse state
        try:
            state_enum = TaskState(initial_state)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state name: {str(e)}"
            )

        # Create machine
        machine = TaskStateMachine(initial_state=state_enum)

        return StateMachineInfo(
            current_state=machine.current_state.value,
            is_terminal=machine.is_terminal(),
            is_waiting=machine.is_waiting(),
            is_active=machine.is_active(),
            duration_in_state=machine.get_duration_in_state(),
            allowed_transitions=[s.value for s in machine.get_allowed_transitions()],
            history_count=len(machine.history),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating state machine: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create state machine: {str(e)}"
        )

# ===== Task Database Endpoints =====

class TaskInfo(BaseModel):
    """Task information response"""
    id: str
    title: str
    description: Optional[str]
    task_type: str
    workspace_id: str
    assigned_agent_id: Optional[str]
    status: str
    priority: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    failed_at: Optional[datetime]
    execution_duration_seconds: Optional[int]
    tokens_used: int
    retry_count: int
    created_at: datetime
    updated_at: datetime


class TaskStats(BaseModel):
    """Task statistics"""
    total_tasks: int
    pending_tasks: int
    in_progress_tasks: int
    completed_tasks: int
    failed_tasks: int
    total_tokens_used: int


@router.get(
    "/list",
    response_model=List[TaskInfo],
    summary="List all tasks",
    description="Get list of all tasks from database"
)
async def list_tasks(
    workspace_id: Optional[UUID] = None,
    task_status: Optional[str] = None,
    assigned_only: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> List[TaskInfo]:
    """
    List all tasks.

    Args:
        workspace_id: Filter by workspace
        task_status: Filter by status
        assigned_only: Only show assigned tasks
        limit: Maximum number of tasks to return
        db: Database session

    Returns:
        List of task information
    """
    try:
        query = select(Task)

        if workspace_id:
            query = query.where(Task.workspace_id == workspace_id)

        if task_status:
            query = query.where(Task.status == task_status)

        if assigned_only:
            query = query.where(Task.assigned_agent_id.isnot(None))

        query = query.order_by(Task.created_at.desc()).limit(limit)

        result = await db.execute(query)
        tasks = result.scalars().all()

        return [
            TaskInfo(
                id=str(task.id),
                title=task.title,
                description=task.description,
                task_type=task.task_type,
                workspace_id=str(task.workspace_id),
                assigned_agent_id=str(task.assigned_agent_id) if task.assigned_agent_id else None,
                status=task.status,
                priority=task.priority,
                started_at=task.started_at,
                completed_at=task.completed_at,
                failed_at=task.failed_at,
                execution_duration_seconds=task.execution_duration_seconds,
                tokens_used=task.tokens_used,
                retry_count=task.retry_count,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
            for task in tasks
        ]

    except Exception as e:
        logger.error(f"Error listing tasks: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tasks: {str(e)}"
        )


@router.get(
    "/stats",
    response_model=TaskStats,
    summary="Get task statistics",
    description="Get aggregated task statistics"
)
async def get_task_stats(
    workspace_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
) -> TaskStats:
    """
    Get task statistics.

    Args:
        workspace_id: Filter by workspace
        db: Database session

    Returns:
        Task statistics
    """
    try:
        query = select(Task)
        if workspace_id:
            query = query.where(Task.workspace_id == workspace_id)

        result = await db.execute(query)
        all_tasks = result.scalars().all()

        pending = sum(1 for t in all_tasks if t.status == "pending")
        in_progress = sum(1 for t in all_tasks if t.status == "in_progress")
        completed = sum(1 for t in all_tasks if t.status == "completed")
        failed = sum(1 for t in all_tasks if t.status == "failed")
        total_tokens = sum(t.tokens_used for t in all_tasks)

        return TaskStats(
            total_tasks=len(all_tasks),
            pending_tasks=pending,
            in_progress_tasks=in_progress,
            completed_tasks=completed,
            failed_tasks=failed,
            total_tokens_used=total_tokens,
        )

    except Exception as e:
        logger.error(f"Error getting task stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get task stats: {str(e)}"
        )


class TaskEvent(BaseModel):
    """A linked audit or operations-feed event for a task."""
    kind: str  # "audit" | "operation"
    title: str
    detail: Optional[str] = None
    severity: Optional[str] = None
    success: Optional[bool] = None
    required_approval: Optional[bool] = None
    created_at: Optional[datetime] = None


class TaskDetail(BaseModel):
    """Full task detail for the dashboard task page (the whole operating loop)."""
    id: str
    title: str
    command: str
    description: Optional[str]
    task_type: str
    workspace_id: str
    assigned_agent_id: Optional[str]
    status: str
    priority: int
    requires_approval: bool
    approval_status: str  # "not_required" | "pending" | "approved" | "rejected"
    response_text: Optional[str]
    selected_agents: List[str]
    plan_steps: List[str]
    provider: Optional[str]
    model: Optional[str]
    tool_calls: List[Dict[str, Any]]
    verification: Optional[Dict[str, Any]]
    failure: Optional[Dict[str, Any]]
    result: Optional[Dict[str, Any]]
    error_message: Optional[str]
    execution_logs: Optional[List[Dict[str, Any]]]
    context: Optional[Dict[str, Any]]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    failed_at: Optional[datetime]
    execution_duration_seconds: Optional[int]
    tokens_used: int
    retry_count: int
    created_at: datetime
    updated_at: datetime
    audit_events: List[TaskEvent]
    operation_events: List[TaskEvent]


@router.get(
    "/{task_id}",
    response_model=TaskDetail,
    summary="Get task details",
    description="Get full detail of a task: result, agents, provider/model, approval status, audit + operation events"
)
async def get_task(
    task_id: UUID,
    db: Session = Depends(get_db),
) -> TaskDetail:
    """
    Get full task detail, including the linked audit trail and operations-feed
    events, so the dashboard task page can show the complete operating loop.

    Raises:
        404: If task not found
    """
    try:
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()

        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task '{task_id}' not found"
            )

        res = task.result if isinstance(task.result, dict) else {}
        ctx = task.context if isinstance(task.context, dict) else {}
        requires_approval = bool(ctx.get("requires_approval")) or task.status == "blocked"

        # Approval status derived from task state.
        if not requires_approval:
            approval_status = "not_required"
        elif task.status == "blocked":
            approval_status = "pending"
        elif task.status in ("approved", "completed"):
            approval_status = "approved"
        elif task.status in ("cancelled", "rejected"):
            approval_status = "rejected"
        else:
            approval_status = "pending"

        # Linked audit events (command service writes target_id = str(task.id)).
        audit_rows = (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.target_id == str(task_id))
                .order_by(AuditLog.created_at.asc())
            )
        ).scalars().all()
        audit_events = [
            TaskEvent(
                kind="audit",
                title=a.action,
                detail=a.description,
                success=a.success,
                required_approval=a.required_approval,
                created_at=a.created_at,
            )
            for a in audit_rows
        ]

        # Linked operations-feed events (related_task_id = task.id).
        feed_rows = (
            await db.execute(
                select(LiveOperationsFeedItem)
                .where(LiveOperationsFeedItem.related_task_id == task_id)
                .order_by(LiveOperationsFeedItem.created_at.asc())
            )
        ).scalars().all()
        operation_events = [
            TaskEvent(
                kind="operation",
                title=f.title,
                detail=f.message,
                severity=f.severity,
                created_at=f.created_at,
            )
            for f in feed_rows
        ]

        return TaskDetail(
            id=str(task.id),
            title=task.title,
            command=task.description or task.title,
            description=task.description,
            task_type=task.task_type,
            workspace_id=str(task.workspace_id),
            assigned_agent_id=str(task.assigned_agent_id) if task.assigned_agent_id else None,
            status=task.status,
            priority=task.priority,
            requires_approval=requires_approval,
            approval_status=approval_status,
            response_text=res.get("response"),
            selected_agents=res.get("selected_agents", []) or [],
            plan_steps=res.get("plan_steps", []) or [],
            provider=res.get("provider"),
            model=res.get("model"),
            tool_calls=res.get("tool_calls", []) or [],
            verification=res.get("verification") if isinstance(res.get("verification"), dict) else None,
            failure=res.get("failure") if isinstance(res.get("failure"), dict) else None,
            result=task.result if isinstance(task.result, dict) else None,
            error_message=task.error_message,
            execution_logs=task.execution_logs if isinstance(task.execution_logs, list) else None,
            context=ctx or None,
            started_at=task.started_at,
            completed_at=task.completed_at,
            failed_at=task.failed_at,
            execution_duration_seconds=task.execution_duration_seconds,
            tokens_used=task.tokens_used,
            retry_count=task.retry_count,
            created_at=task.created_at,
            updated_at=task.updated_at,
            audit_events=audit_events,
            operation_events=operation_events,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get task: {str(e)}"
        )


# ===== Resume (continue a step-limited / needs_continuation task) =====
from uuid import uuid4 as _uuid4
from datetime import timezone as _tz
from app.core.auth import CurrentUserId
from app.core.config import settings as _settings
from app.core.command.tool_runtime import ToolRuntime
from app.core.command.agent_executor import AgentExecutor

_RESUMABLE = ("needs_continuation", "partial", "running")


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: UUID,
    operator: CurrentUserId,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Resume a step-limited / needs_continuation task. Continues the SAME task in
    the SAME workspace (prior work persists on disk) — never restarts the mission,
    never duplicates the workspace. Refuses blocked/approval-gated tasks.
    """
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in ("blocked", "waiting_on_approval"):
        raise HTTPException(status_code=400, detail=f"Task is {task.status}; clear the boundary first.")
    if task.status not in _RESUMABLE:
        raise HTTPException(status_code=400, detail=f"Task status '{task.status}' is not resumable.")

    res = task.result if isinstance(task.result, dict) else {}
    mission = res.get("mission") or task.description or task.title
    root = res.get("workspace_path")
    prior_cont = int(res.get("continuation_count", 0) or 0)
    new_count = prior_cont + 1
    max_cont = int(res.get("max_continuations", 4) or 4)

    task.status = "resuming"
    task.updated_at = datetime.now(_tz.utc)
    await db.flush()
    await db.execute(select(Task).where(Task.id == task_id))  # keep session warm

    db.add(LiveOperationsFeedItem(
        id=_uuid4(), workspace_id=task.workspace_id, item_type="resume", severity="info",
        title="Task resume started",
        message=f"Continuation #{new_count} for task {str(task.id)[:8]} (same workspace, no restart).",
        related_task_id=task.id, requires_action=False,
        created_at=datetime.now(_tz.utc), updated_at=datetime.now(_tz.utc)))
    await db.flush()

    runtime = ToolRuntime(db, task.workspace_id, task.id, operator=operator)
    executor = AgentExecutor(runtime, getattr(_settings, "DEFAULT_MODEL", "claude-sonnet-4-6"), root)
    result = await executor.run(mission, steps_per_round=8, max_continuations=max_cont,
                                start_continuation=prior_cont)

    if result["needs_continuation"]:
        new_status = "needs_continuation"
        reason = "Reached the continuation cap again; checkpoint saved. Resume again to continue."
    elif result["success"]:
        new_status = "completed"
        reason = None
    elif result.get("answer"):
        new_status = "partial"
        reason = "Resumed and produced output but could not verify full success."
    else:
        new_status = "failed"
        reason = "Resume produced no verifiable output."

    checkpoint_id = str(_uuid4()) if new_status == "needs_continuation" else res.get("checkpoint_id")
    new_result = dict(res)
    new_result.update({
        "response": result["answer"], "task_status": new_status,
        "agent_needs_continuation": result["needs_continuation"],
        "step_limit_reached": result["step_limit_reached"],
        "continuation_required": result["needs_continuation"],
        "continuation_count": new_count + result["continuation_count"],
        "resume_from_step": result["resume_from_step"],
        "remaining_steps": result["remaining_steps"],
        "checkpoint_id": checkpoint_id,
        "final_status_reason": reason,
        "tool_calls": (res.get("tool_calls") or []) + runtime.calls,
    })
    task.status = new_status
    task.result = new_result
    task.tokens_used = (task.tokens_used or 0) + int(result.get("tokens", 0))
    if new_status == "completed":
        task.completed_at = datetime.now(_tz.utc)
    elif new_status == "failed":
        task.failed_at = datetime.now(_tz.utc)
        task.error_message = reason
    task.updated_at = datetime.now(_tz.utc)

    db.add(LiveOperationsFeedItem(
        id=_uuid4(), workspace_id=task.workspace_id, item_type="resume",
        severity="success" if new_status == "completed" else "warning",
        title=f"Task resume -> {new_status}",
        message=(result["answer"] or "")[:300], related_task_id=task.id, requires_action=False,
        created_at=datetime.now(_tz.utc), updated_at=datetime.now(_tz.utc)))
    db.add(AuditLog(
        id=_uuid4(), workspace_id=task.workspace_id, actor_type="operator",
        action="task_resumed", action_category="resume",
        description=f"Task {task.id} resumed (continuation #{new_count}) -> {new_status}",
        target_type="task", target_id=str(task.id), after_state={"status": new_status},
        success=new_status == "completed",
        created_at=datetime.now(_tz.utc), updated_at=datetime.now(_tz.utc)))
    await db.commit()

    return {"task_id": str(task.id), "status": new_status,
            "continuation_count": new_result["continuation_count"],
            "checkpoint_id": checkpoint_id, "reason": reason,
            "output_preview": (result["answer"] or "")[:400]}
