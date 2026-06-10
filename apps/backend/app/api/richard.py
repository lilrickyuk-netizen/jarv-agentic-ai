"""
JARV Backend - Richard Boundary Operator API (Repair 8)

Authenticated entry points for the real hard-boundary -> decision -> resume loop.

The decision endpoints derive the deciding identity from the AUTHENTICATED current
user (the JWT auth dependency), never from request-body fields. A client cannot
impersonate Richard by sending a decided_by/authorized field — those are not
accepted; ``decided_by`` is bound to the authenticated user inside the workflow.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.core.richard.workflow import RichardBoundaryWorkflow
from app.models.boundary import ApprovalWindow, BoundaryApproval, BoundaryReport

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/richard", tags=["richard-boundary-operator"])


# ----------------------------------------------------------------------------- #
# Schemas
# ----------------------------------------------------------------------------- #

class DecisionRequest(BaseModel):
    """Body for a Richard decision.

    NOTE: there is intentionally NO decided_by / authorized field. The deciding
    identity is the authenticated user; authorisation is the owner check in the
    workflow. Accepting those from the body would allow impersonation.
    """
    approve: bool = Field(..., description="True to grant, False to reject")
    reason: Optional[str] = Field(None, description="Decision note")
    richard_input_value: Optional[str] = Field(None, description="Value Richard entered, if any")
    scope_action: Optional[str] = Field(None, description="Override the exact approved action scope")
    authority_granted: Optional[int] = Field(None, description="Authority granted by this approval")
    spend_limit: Optional[float] = Field(None, description="Spend limit, if relevant")
    release_scope: Optional[str] = Field(None, description="Release/deployment scope, if relevant")
    expiry_seconds: Optional[int] = Field(3600, description="Window lifetime in seconds")
    single_use: bool = Field(True, description="Window is single-use")


class ResumeRequest(BaseModel):
    checkpoint_id: str = Field(..., description="SafeCheckpoint id to resume from")


# ----------------------------------------------------------------------------- #
# Endpoints
# ----------------------------------------------------------------------------- #

@router.get("/pending")
async def list_pending_decisions(
    operator: CurrentUserId,
    workspace_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List pending Richard decisions (paused hard boundaries awaiting a decision)."""
    wf = RichardBoundaryWorkflow(db)
    return await wf.list_pending_decisions(workspace_id=workspace_id)


@router.get("/boundary-reports/{report_id}")
async def get_boundary_report(
    report_id: UUID,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Read a persisted BoundaryReport."""
    row = (await db.execute(
        select(BoundaryReport).where(BoundaryReport.id == report_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Boundary report not found")
    return {
        "id": str(row.id), "boundary_type": row.boundary_type, "severity": row.severity,
        "title": row.title, "description": row.description,
        "attempted_action": row.attempted_action, "was_blocked": row.was_blocked,
        "action_taken": row.action_taken, "resolution": row.resolution,
        "approval_id": str(row.approval_id) if row.approval_id else None,
        "context": row.context, "session_id": str(row.session_id),
        "authority_level_required": row.authority_level_required,
        "authority_level_available": row.authority_level_available,
    }


@router.post("/decisions/{approval_id}")
async def submit_decision(
    approval_id: UUID,
    body: DecisionRequest,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Record Richard's authenticated decision for a paused boundary.

    ``operator`` is the authenticated current user; it — not any body field — is
    bound to ``decided_by``. Authorisation (owner check) happens in the workflow.
    """
    wf = RichardBoundaryWorkflow(db)
    result = await wf.record_richard_decision(
        approval_id=approval_id,
        authenticated_user_id=operator,
        approve=body.approve,
        reason=body.reason,
        richard_input_value=body.richard_input_value,
        scope_action=body.scope_action,
        authority_granted=body.authority_granted,
        spend_limit=body.spend_limit,
        release_scope=body.release_scope,
        expiry_seconds=body.expiry_seconds,
        single_use=body.single_use,
    )
    if result.get("blocked") and result.get("reason", "").startswith("authenticated user is not"):
        raise HTTPException(status_code=403, detail=result["reason"])
    if result.get("blocked") and "not found" in result.get("reason", ""):
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@router.get("/approval-windows/{approval_id}")
async def get_approval_window(
    approval_id: UUID,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Read the ApprovalWindow opened for an approval (its exact scope)."""
    approval = (await db.execute(
        select(BoundaryApproval).where(BoundaryApproval.id == approval_id)
    )).scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.approval_window_id is None:
        return {"approval_id": str(approval_id), "window": None,
                "note": "no active window (approval pending or rejected)"}
    window = (await db.execute(
        select(ApprovalWindow).where(ApprovalWindow.id == approval.approval_window_id)
    )).scalar_one_or_none()
    if window is None:
        return {"approval_id": str(approval_id), "window": None}
    return {"approval_id": str(approval_id), "window": {
        "id": str(window.id), "status": window.status, "window_type": window.window_type,
        "title": window.title, "scope": window.meta_data,
        "opened_at": window.opened_at.isoformat() if window.opened_at else None,
        "closed_at": window.closed_at.isoformat() if window.closed_at else None,
    }}


@router.post("/resume")
async def resume_mission(
    body: ResumeRequest,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Resume a mission from a checkpoint after Richard cleared the gate."""
    try:
        cid = UUID(body.checkpoint_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="invalid checkpoint_id")
    wf = RichardBoundaryWorkflow(db)
    result = await wf.resume_mission(checkpoint_id=cid, authenticated_user_id=operator)
    return result
