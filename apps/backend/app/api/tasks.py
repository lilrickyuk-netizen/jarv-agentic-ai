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
