"""
JAI Backend - Workflows API

The workflows Richard can start (each with its council and steps), his runs and where each one is, starting one in a
workspace, and cancelling one. Gates are decided on the Approvals page (api/approvals).
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.core.auth import CurrentUserId, get_current_user_id
from app.core.database import get_db
from app.core.scoping import owned_workspaces
from app.core.workflows import service as workflows
from app.models import WorkflowRun
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/workflows", tags=["workflows"], dependencies=[Depends(get_current_user_id)])


class StartRequest(BaseModel):
    template: str
    workspace_id: UUID


@router.get("")
async def list_workflows() -> List[Dict[str, Any]]:
    """The workflows that can be started, with their councils and steps."""
    return workflows.catalogue()


@router.get("/runs")
async def list_runs(operator: CurrentUserId, limit: int = 20, db=Depends(get_db)) -> List[Dict[str, Any]]:
    rows = (await db.execute(select(WorkflowRun).where(WorkflowRun.workspace_id.in_(owned_workspaces(operator)))
                             .order_by(WorkflowRun.created_at.desc()).limit(max(1, min(limit, 100))))).scalars().all()
    return [workflows.describe(r) for r in rows]


@router.post("/start")
async def start_workflow(body: StartRequest, operator: CurrentUserId, db=Depends(get_db)) -> Dict[str, Any]:
    workspace = (await db.execute(select(Workspace).where(Workspace.id == body.workspace_id,
                                                          Workspace.owner_id == UUID(str(operator))))
                 ).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        run = await workflows.start(db, user_id=UUID(str(operator)), workspace=workspace, template=body.template)
    except workflows.WorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return workflows.describe(run)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: UUID, operator: CurrentUserId, db=Depends(get_db)) -> Dict[str, Any]:
    run: Optional[WorkflowRun] = (await db.execute(select(WorkflowRun).where(
        WorkflowRun.id == run_id, WorkflowRun.workspace_id.in_(owned_workspaces(operator))))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflows.describe(await workflows.cancel(db, run, actor=str(operator)))
