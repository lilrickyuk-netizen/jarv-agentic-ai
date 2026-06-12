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
from app.core.richard.service import (
    RichardBoundaryService, OK, NOT_FOUND, FORBIDDEN,
)
from app.models.boundary import ApprovalWindow, BoundaryApproval, BoundaryReport

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/richard", tags=["richard-boundary-operator"])


def _access_to_http(access: str) -> None:
    """Raise the right HTTP error for a service access result (or return)."""
    if access == NOT_FOUND:
        raise HTTPException(status_code=404, detail="Boundary case not found")
    if access == FORBIDDEN:
        raise HTTPException(
            status_code=403,
            detail="Not authorised for this workspace's boundary case",
        )


def _decision_to_http(result: Dict[str, Any]) -> Dict[str, Any]:
    """Map a workflow decision result dict to HTTP semantics."""
    if result.get("decided"):
        return result
    reason = result.get("reason", "") or ""
    # Repair 10: an expired approval request can never be decided (410 Gone).
    if result.get("expired"):
        raise HTTPException(status_code=410, detail=reason or "approval request expired")
    if result.get("already_decided"):
        if result.get("idempotent"):
            return result  # identical repeat is a successful no-op (200)
        raise HTTPException(status_code=409, detail=reason or "conflicting decision")
    if result.get("blocked"):
        if "not found" in reason:
            raise HTTPException(status_code=404, detail=reason)
        if "not authorised" in reason or "mission owner" in reason:
            raise HTTPException(status_code=403, detail=reason)
        if "unauthenticated" in reason:
            raise HTTPException(status_code=401, detail=reason)
    return result


def _resume_to_http(result: Dict[str, Any]) -> Dict[str, Any]:
    """Map a workflow resume result dict to HTTP semantics."""
    status = result.get("status")
    reason = result.get("reason", "") or ""
    if status == "expired":
        raise HTTPException(status_code=410, detail=reason or "approval expired")
    if status in ("rejected", "waiting_on_richard"):
        raise HTTPException(status_code=409, detail=reason or "cannot resume")
    # Repair 10: a consumed (already-used) approval window cannot resume again.
    if status == "blocked" and (result.get("consumed") or "already used" in reason):
        raise HTTPException(status_code=409, detail=reason or "approval already consumed")
    return result


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


class BoundaryCaseResponse(BaseModel):
    """Structured, redacted view of one complete boundary case (Repair 9).

    Sensitive metadata is redacted and the checkpoint is summarised (no raw state
    snapshot) by the service before this model is constructed.
    """
    report: Dict[str, Any]
    description: str
    boundary_type: str
    severity: str
    authority_level_required: int
    authority_level_available: int
    safe_work_continuing: List[str]
    workflow_state: str
    pending_approval: Optional[Dict[str, Any]] = None
    richard_decision: Optional[Dict[str, Any]] = None
    approval_window: Optional[Dict[str, Any]] = None
    checkpoint: Optional[Dict[str, Any]] = None
    resume_history: List[Dict[str, Any]] = Field(default_factory=list)
    timestamps: Dict[str, Any]
    limitations: List[str] = Field(default_factory=list)


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


# =========================================================================== #
# Repair 9: report-centric, workspace-isolated operator API.
# These use the RichardBoundaryService (ownership isolation + real relational
# queries) and DELEGATE all state changes to the same Repair-8 workflow above.
# =========================================================================== #

@router.get("/reports")
async def list_reports(
    operator: CurrentUserId,
    workspace_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List boundary reports in workspaces the authenticated operator owns."""
    svc = RichardBoundaryService(db)
    return await svc.list_reports(
        operator, workspace_id=workspace_id, task_id=task_id,
        status=status, limit=limit, offset=offset)


@router.get("/reports/{report_id}", response_model=BoundaryCaseResponse)
async def get_boundary_case(
    report_id: UUID,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> BoundaryCaseResponse:
    """Return the complete, redacted boundary case for one report."""
    svc = RichardBoundaryService(db)
    case, access = await svc.get_case(operator, report_id)
    _access_to_http(access)
    return BoundaryCaseResponse(**case)


@router.get("/reports/{report_id}/history")
async def get_boundary_history(
    report_id: UUID,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return the full approval/checkpoint/window/resume history for a report."""
    svc = RichardBoundaryService(db)
    history, access = await svc.get_history(operator, report_id)
    _access_to_http(access)
    return history


@router.post("/reports/{report_id}/decision")
async def decide_report(
    report_id: UUID,
    body: DecisionRequest,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Record Richard's authenticated decision for a report's pending approval.

    ``decided_by`` is bound to the authenticated operator (the workflow enforces
    the owner check); the request body carries no identity/authorisation field.
    """
    svc = RichardBoundaryService(db)
    result, access = await svc.submit_decision(
        operator, report_id, approve=body.approve, reason=body.reason,
        richard_input_value=body.richard_input_value, scope_action=body.scope_action,
        authority_granted=body.authority_granted, spend_limit=body.spend_limit,
        release_scope=body.release_scope, expiry_seconds=body.expiry_seconds,
        single_use=body.single_use)
    _access_to_http(access)
    return _decision_to_http(result)


@router.post("/reports/{report_id}/resume")
async def resume_report(
    report_id: UUID,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Resume a report's paused mission from its safe checkpoint."""
    svc = RichardBoundaryService(db)
    result, access = await svc.resume(operator, report_id)
    _access_to_http(access)
    return _resume_to_http(result)


@router.get("/checkpoints")
async def list_checkpoints(
    operator: CurrentUserId,
    workspace_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List safe checkpoints (summaries only) the operator owns (Repair 10)."""
    svc = RichardBoundaryService(db)
    return await svc.list_checkpoints(
        operator, workspace_id=workspace_id, task_id=task_id,
        limit=limit, offset=offset)


@router.get("/resume-actions")
async def list_resume_actions(
    operator: CurrentUserId,
    workspace_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List resume actions in workspaces the operator owns (Repair 10)."""
    svc = RichardBoundaryService(db)
    return await svc.list_resume_actions(
        operator, workspace_id=workspace_id, task_id=task_id,
        limit=limit, offset=offset)


@router.get("/reports/{report_id}/audit")
async def get_boundary_audit_trail(
    report_id: UUID,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return the redacted audit trail for one boundary flow (Repair 10)."""
    svc = RichardBoundaryService(db)
    trail, access = await svc.get_audit_trail(operator, report_id)
    _access_to_http(access)
    return trail


@router.get("/sessions/{session_id}/status")
async def get_session_status(
    session_id: UUID,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return the live status of a mission session the operator owns."""
    svc = RichardBoundaryService(db)
    status, access = await svc.session_status(operator, session_id)
    _access_to_http(access)
    return status
