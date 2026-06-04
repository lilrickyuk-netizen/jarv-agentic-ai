"""
JARV Backend - Command API

Dashboard command control endpoint. Accepts a text command (typed or produced
by browser speech-to-text), runs it through the live command pipeline
(orchestrator + Claude planning + agent selection + task lifecycle + execution),
and returns a real result. Also exposes recent command history.
"""
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.command import CommandService
from app.core.config import settings
from app.core.database import get_db
from app.models.task import Task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/command", tags=["command"])


class CommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=4000)
    workspace_id: Optional[UUID] = None


class CommandResponse(BaseModel):
    task_id: str
    command: str
    status: str
    requires_approval: bool
    response_text: str
    plan_steps: List[str]
    selected_agents: List[str]
    provider: Optional[str]
    model: Optional[str]
    execution_time: float
    tokens_used: int
    approval_reason: Optional[str] = None
    error: Optional[str] = None


class CommandHistoryItem(BaseModel):
    task_id: str
    command: str
    status: str
    response_text: Optional[str]
    selected_agents: List[str]
    created_at: str
    completed_at: Optional[str]
    error: Optional[str]


@router.post("/execute", response_model=CommandResponse)
async def execute_command(
    request: CommandRequest,
    db: AsyncSession = Depends(get_db),
) -> CommandResponse:
    """
    Execute a dashboard command through the real JARV pipeline.

    Flow: safety gate -> task created -> orchestrator + Claude planning ->
    agent selection -> live execution -> task completed -> result returned.
    Commands that modify files / deploy / delete / spend are paused for approval.
    """
    try:
        service = CommandService()
        result = await service.execute(
            command_text=request.command,
            db=db,
            workspace_id=request.workspace_id,
        )
        return CommandResponse(**result.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.error(f"Command execution error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Command execution failed: {e}")


@router.get("/history", response_model=List[CommandHistoryItem])
async def command_history(
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
) -> List[CommandHistoryItem]:
    """Return recent dashboard commands (task_type='command')."""
    query = (
        select(Task)
        .where(Task.task_type == "command")
        .order_by(Task.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    tasks = result.scalars().all()

    items: List[CommandHistoryItem] = []
    for t in tasks:
        res = t.result or {}
        items.append(
            CommandHistoryItem(
                task_id=str(t.id),
                command=t.title,
                status=t.status,
                response_text=res.get("response"),
                selected_agents=res.get("selected_agents", []) if isinstance(res, dict) else [],
                created_at=t.created_at.isoformat() if t.created_at else "",
                completed_at=t.completed_at.isoformat() if t.completed_at else None,
                error=t.error_message,
            )
        )
    return items


@router.get("/info")
async def command_info() -> dict:
    """Expose the active provider/model for display in the command UI (no secrets)."""
    model = getattr(settings, "DEFAULT_MODEL", None) or "claude-sonnet-4-6"
    return {"provider": "claude", "model": model}
