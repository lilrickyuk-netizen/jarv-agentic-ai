"""
JARV Backend - Richard Boundary Service / Repository (Repair 9)

A focused query + access-control layer for Richard Boundary Operator operations.
It is the single place the API talks to: it enforces workspace/task ownership
isolation on real relational columns, builds the complete boundary-case view (with
secret redaction and no raw checkpoint dumps), and DELEGATES every state-changing
action (decision, resume) to the real Repair-8 ``RichardBoundaryWorkflow``. It
contains NO duplicate approval/resume business logic.

Access model (single-user private system per CLAUDE.md): a user may see and act on
a boundary case only when they own its workspace (Workspace.owner_id) or are the
mission owner who created it (BoundaryReport.created_by). Cross-workspace access is
refused. There is no enterprise tenancy here — workspace isolation simply prevents
accidental cross-project actions and information leakage.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.richard.workflow import RichardBoundaryWorkflow, coerce_user_id
from app.core.security import redact_secrets
from app.models.boundary import (
    ApprovalWindow,
    BoundaryApproval,
    BoundaryReport,
    ResumeAction,
    RichardBoundaryInput,
    SafeCheckpoint,
)
from app.models.session import AgentSession
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

# Access results the API maps to HTTP status codes.
OK = "ok"
NOT_FOUND = "not_found"
FORBIDDEN = "forbidden"


class RichardBoundaryService:
    """Authenticated query/command facade over the real Repair-8 workflow."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.workflow = RichardBoundaryWorkflow(db)

    # ------------------------------------------------------------------ #
    # Ownership / isolation
    # ------------------------------------------------------------------ #

    async def _owned_workspace_ids(self, auth_uid: UUID) -> List[UUID]:
        rows = (await self.db.execute(
            select(Workspace.id).where(Workspace.owner_id == auth_uid)
        )).scalars().all()
        return list(rows)

    def _is_owner(self, report: BoundaryReport, auth_uid: UUID,
                  owned_ws: List[UUID]) -> bool:
        if report.workspace_id is not None and report.workspace_id in owned_ws:
            return True
        # Historic rows may have a null workspace_id; fall back to mission owner.
        return report.created_by == auth_uid

    async def _load_report_checked(
        self, auth_uid: UUID, report_id: UUID
    ) -> Tuple[Optional[BoundaryReport], str]:
        rep = (await self.db.execute(
            select(BoundaryReport).where(BoundaryReport.id == report_id)
        )).scalar_one_or_none()
        if rep is None:
            return None, NOT_FOUND
        owned = await self._owned_workspace_ids(auth_uid)
        if self._is_owner(rep, auth_uid, owned):
            return rep, OK
        return rep, FORBIDDEN

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    async def list_pending(
        self, authenticated_user_id: Any, *, workspace_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Pending decisions in workspaces the authenticated user owns."""
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return []
        owned = await self._owned_workspace_ids(auth_uid)
        q = select(BoundaryApproval).where(BoundaryApproval.status == "pending")
        if workspace_id is not None:
            if workspace_id not in owned:
                return []
            q = q.where(BoundaryApproval.workspace_id == workspace_id)
        else:
            # Only approvals scoped to an owned workspace, plus owner's own missions
            # for historic rows lacking a workspace_id.
            q = q.where(
                (BoundaryApproval.workspace_id.in_(owned) if owned else False)
                | (BoundaryApproval.user_id == auth_uid)
            )
        q = q.order_by(BoundaryApproval.created_at.desc()).limit(limit)
        rows = (await self.db.execute(q)).scalars().all()
        out: List[Dict[str, Any]] = []
        for r in rows:
            details = r.action_details or {}
            out.append({
                "approval_id": str(r.id),
                "approval_type": r.approval_type,
                "action_description": r.action_description,
                "boundary_type": details.get("boundary_type"),
                "boundary_report_id": str(r.boundary_report_id) if r.boundary_report_id else None,
                "workspace_id": str(r.workspace_id) if r.workspace_id else None,
                "task_id": str(r.task_id) if r.task_id else None,
                "session_id": str(r.session_id),
                "status": r.status,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return out

    async def list_reports(
        self, authenticated_user_id: Any, *,
        workspace_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List boundary reports, filtered by REAL relational columns + ownership."""
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return []
        owned = await self._owned_workspace_ids(auth_uid)
        q = select(BoundaryReport)
        # Workspace isolation: only reports in owned workspaces (or owner's own
        # historic null-workspace reports).
        if owned:
            q = q.where(
                BoundaryReport.workspace_id.in_(owned)
                | (BoundaryReport.created_by == auth_uid)
            )
        else:
            q = q.where(BoundaryReport.created_by == auth_uid)
        if workspace_id is not None:
            if workspace_id not in owned:
                return []
            q = q.where(BoundaryReport.workspace_id == workspace_id)
        if task_id is not None:
            q = q.where(BoundaryReport.task_id == task_id)
        if status is not None:
            # "status" filters on resolution: open = unresolved.
            if status in ("open", "pending", "unresolved"):
                q = q.where(BoundaryReport.resolution.is_(None))
            else:
                q = q.where(BoundaryReport.resolution == status)
        if since is not None:
            q = q.where(BoundaryReport.created_at >= since)
        q = q.order_by(BoundaryReport.created_at.desc()).limit(limit).offset(offset)
        rows = (await self.db.execute(q)).scalars().all()
        return [self._report_summary(r) for r in rows]

    def _report_summary(self, r: BoundaryReport) -> Dict[str, Any]:
        return {
            "id": str(r.id),
            "boundary_type": r.boundary_type,
            "severity": r.severity,
            "title": r.title,
            "attempted_action": r.attempted_action,
            "was_blocked": r.was_blocked,
            "action_taken": r.action_taken,
            "resolution": r.resolution,
            "workspace_id": str(r.workspace_id) if r.workspace_id else None,
            "task_id": str(r.task_id) if r.task_id else None,
            "session_id": str(r.session_id),
            "approval_id": str(r.approval_id) if r.approval_id else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }

    async def get_case(
        self, authenticated_user_id: Any, report_id: UUID
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Return the complete, redacted boundary case for one report."""
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return None, FORBIDDEN
        rep, access = await self._load_report_checked(auth_uid, report_id)
        if access != OK:
            return None, access

        approval = None
        if rep.approval_id is not None:
            approval = (await self.db.execute(
                select(BoundaryApproval).where(BoundaryApproval.id == rep.approval_id)
            )).scalar_one_or_none()

        window = None
        if approval is not None and approval.approval_window_id is not None:
            window = (await self.db.execute(
                select(ApprovalWindow).where(ApprovalWindow.id == approval.approval_window_id)
            )).scalar_one_or_none()

        checkpoint = (await self.db.execute(
            select(SafeCheckpoint).where(SafeCheckpoint.boundary_report_id == report_id)
            .order_by(SafeCheckpoint.created_at.desc())
        )).scalars().first()

        rbi = (await self.db.execute(
            select(RichardBoundaryInput)
            .where(RichardBoundaryInput.boundary_report_id == report_id)
            .order_by(RichardBoundaryInput.created_at.desc())
        )).scalars().first()

        resumes = (await self.db.execute(
            select(ResumeAction).where(ResumeAction.boundary_report_id == report_id)
            .order_by(ResumeAction.created_at.asc())
        )).scalars().all()

        ctx = rep.context or {}
        case: Dict[str, Any] = {
            "report": self._report_summary(rep),
            # Free-text/metadata leaves are redacted individually so secrets never
            # leak, WITHOUT corrupting structural integer/id fields (a blanket
            # redact would mangle e.g. authority_level_* keys).
            "description": redact_secrets(rep.description),
            "boundary_type": rep.boundary_type,
            "severity": rep.severity,
            "authority_level_required": rep.authority_level_required,
            "authority_level_available": rep.authority_level_available,
            "safe_work_continuing": list(ctx.get("safe_work_continuing") or []),
            "workflow_state": self._derive_state(rep, approval),
            "pending_approval": self._approval_view(approval),
            "richard_decision": self._decision_view(approval, rbi),
            "approval_window": self._window_view(window),
            "checkpoint": self._checkpoint_summary(checkpoint),
            "resume_history": [self._resume_view(x) for x in resumes],
            "timestamps": {
                "created_at": rep.created_at.isoformat() if rep.created_at else None,
                "updated_at": rep.updated_at.isoformat() if rep.updated_at else None,
            },
            "limitations": [
                "Checkpoint state is summarised, not dumped, to avoid exposing "
                "potentially sensitive resume state.",
                "Sensitive metadata fields are redacted.",
            ],
        }
        return case, OK

    async def get_history(
        self, authenticated_user_id: Any, report_id: UUID
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return None, FORBIDDEN
        rep, access = await self._load_report_checked(auth_uid, report_id)
        if access != OK:
            return None, access
        approvals = (await self.db.execute(
            select(BoundaryApproval).where(BoundaryApproval.boundary_report_id == report_id)
        )).scalars().all()
        windows = (await self.db.execute(
            select(ApprovalWindow).where(ApprovalWindow.boundary_report_id == report_id)
        )).scalars().all()
        checkpoints = (await self.db.execute(
            select(SafeCheckpoint).where(SafeCheckpoint.boundary_report_id == report_id)
        )).scalars().all()
        resumes = (await self.db.execute(
            select(ResumeAction).where(ResumeAction.boundary_report_id == report_id)
        )).scalars().all()
        inputs = (await self.db.execute(
            select(RichardBoundaryInput).where(
                RichardBoundaryInput.boundary_report_id == report_id)
        )).scalars().all()
        # Per-leaf redaction happens in the view builders (window scope, resume
        # error); structural fields are preserved.
        history = {
            "report_id": str(report_id),
            "approvals": [self._approval_view(a) for a in approvals],
            "approval_windows": [self._window_view(w) for w in windows],
            "checkpoints": [self._checkpoint_summary(c) for c in checkpoints],
            "richard_inputs": [self._input_view(i) for i in inputs],
            "resume_actions": [self._resume_view(r) for r in resumes],
        }
        return history, OK

    async def list_checkpoints(
        self, authenticated_user_id: Any, *,
        workspace_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List safe checkpoints in workspaces the authenticated user owns.

        Summaries only — never the raw state_snapshot (Repair 10 redaction rule).
        """
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return []
        owned = await self._owned_workspace_ids(auth_uid)
        own_sessions = select(AgentSession.id).where(AgentSession.user_id == auth_uid)
        q = select(SafeCheckpoint)
        if owned:
            q = q.where(SafeCheckpoint.workspace_id.in_(owned)
                        | SafeCheckpoint.session_id.in_(own_sessions))
        else:
            q = q.where(SafeCheckpoint.session_id.in_(own_sessions))
        if workspace_id is not None:
            if workspace_id not in owned:
                return []
            q = q.where(SafeCheckpoint.workspace_id == workspace_id)
        if task_id is not None:
            q = q.where(SafeCheckpoint.task_id == task_id)
        q = q.order_by(SafeCheckpoint.created_at.desc()).limit(limit).offset(offset)
        rows = (await self.db.execute(q)).scalars().all()
        return [self._checkpoint_summary(c) for c in rows]

    async def list_resume_actions(
        self, authenticated_user_id: Any, *,
        workspace_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List resume actions in workspaces the authenticated user owns."""
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return []
        owned = await self._owned_workspace_ids(auth_uid)
        own_sessions = select(AgentSession.id).where(AgentSession.user_id == auth_uid)
        q = select(ResumeAction)
        if owned:
            q = q.where(ResumeAction.workspace_id.in_(owned)
                        | ResumeAction.session_id.in_(own_sessions))
        else:
            q = q.where(ResumeAction.session_id.in_(own_sessions))
        if workspace_id is not None:
            if workspace_id not in owned:
                return []
            q = q.where(ResumeAction.workspace_id == workspace_id)
        if task_id is not None:
            q = q.where(ResumeAction.task_id == task_id)
        q = q.order_by(ResumeAction.created_at.desc()).limit(limit).offset(offset)
        rows = (await self.db.execute(q)).scalars().all()
        return [self._resume_view(r) for r in rows]

    async def get_audit_trail(
        self, authenticated_user_id: Any, report_id: UUID, *, limit: int = 200,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Return the redacted audit trail for one boundary flow.

        Collects AuditLog rows targeting the report, its approvals, checkpoints
        and resume actions, plus boundary-category entries on the same session.
        Ownership is enforced exactly like get_case.
        """
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return None, FORBIDDEN
        rep, access = await self._load_report_checked(auth_uid, report_id)
        if access != OK:
            return None, access

        from app.models.operations import AuditLog

        related_ids: List[str] = [str(report_id)]
        approvals = (await self.db.execute(
            select(BoundaryApproval.id).where(
                BoundaryApproval.boundary_report_id == report_id))).scalars().all()
        checkpoints = (await self.db.execute(
            select(SafeCheckpoint.id).where(
                SafeCheckpoint.boundary_report_id == report_id))).scalars().all()
        resumes = (await self.db.execute(
            select(ResumeAction.id).where(
                ResumeAction.boundary_report_id == report_id))).scalars().all()
        if rep.approval_id is not None:
            related_ids.append(str(rep.approval_id))
        related_ids += [str(x) for x in approvals]
        related_ids += [str(x) for x in checkpoints]
        related_ids += [str(x) for x in resumes]

        q = select(AuditLog).where(
            AuditLog.target_id.in_(related_ids)
            | ((AuditLog.session_id == rep.session_id)
               & (AuditLog.action_category == "boundary"))
        ).order_by(AuditLog.created_at.asc()).limit(limit)
        rows = (await self.db.execute(q)).scalars().all()
        entries = [{
            "id": str(a.id),
            "action": a.action,
            "action_category": a.action_category,
            "actor_type": a.actor_type,
            "description": redact_secrets(a.description),
            "target_type": a.target_type,
            "target_id": a.target_id,
            "success": a.success,
            "required_approval": a.required_approval,
            "workspace_id": str(a.workspace_id) if a.workspace_id else None,
            "session_id": str(a.session_id) if a.session_id else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        } for a in rows]
        return {"report_id": str(report_id), "entries": entries,
                "entry_count": len(entries)}, OK

    async def session_status(
        self, authenticated_user_id: Any, session_id: UUID
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return None, FORBIDDEN
        sess = (await self.db.execute(
            select(AgentSession).where(AgentSession.id == session_id)
        )).scalar_one_or_none()
        if sess is None:
            return None, NOT_FOUND
        owned = await self._owned_workspace_ids(auth_uid)
        if not (sess.workspace_id in owned or sess.user_id == auth_uid):
            return None, FORBIDDEN
        return {
            "session_id": str(sess.id),
            "status": sess.status,
            "is_paused": sess.is_paused,
            "is_resumed": sess.is_resumed,
            "current_step": sess.current_step,
            "workspace_id": str(sess.workspace_id) if sess.workspace_id else None,
            "paused_at": sess.paused_at.isoformat() if sess.paused_at else None,
            "resumed_at": sess.resumed_at.isoformat() if sess.resumed_at else None,
        }, OK

    # ------------------------------------------------------------------ #
    # Commands — DELEGATE to the real workflow (no duplicate logic)
    # ------------------------------------------------------------------ #

    async def submit_decision(
        self, authenticated_user_id: Any, report_id: UUID, *, approve: bool,
        **kwargs,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Decide a report's pending approval via the real workflow."""
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return None, FORBIDDEN
        rep, access = await self._load_report_checked(auth_uid, report_id)
        if access != OK:
            return None, access
        if rep.approval_id is None:
            return {"decided": False, "reason": "no approval linked to this report"}, NOT_FOUND
        result = await self.workflow.record_richard_decision(
            approval_id=rep.approval_id,
            authenticated_user_id=authenticated_user_id,
            approve=approve,
            **kwargs,
        )
        return result, OK

    async def resume(
        self, authenticated_user_id: Any, report_id: UUID
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Resume a report's mission from its checkpoint via the real workflow."""
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return None, FORBIDDEN
        rep, access = await self._load_report_checked(auth_uid, report_id)
        if access != OK:
            return None, access
        checkpoint = (await self.db.execute(
            select(SafeCheckpoint).where(SafeCheckpoint.boundary_report_id == report_id)
            .order_by(SafeCheckpoint.created_at.desc())
        )).scalars().first()
        if checkpoint is None:
            return {"status": "blocked", "resumed": False,
                    "reason": "no checkpoint for this report"}, NOT_FOUND
        result = await self.workflow.resume_mission(
            checkpoint_id=checkpoint.id, authenticated_user_id=authenticated_user_id)
        return result, OK

    # ------------------------------------------------------------------ #
    # View builders (redaction-friendly, no raw secrets / no full snapshots)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _derive_state(rep: BoundaryReport, approval: Optional[BoundaryApproval]) -> str:
        if rep.resolution:
            return rep.resolution
        if approval is None:
            return "open"
        if approval.status == "pending":
            return "waiting_on_richard"
        if approval.status == "rejected":
            return "rejected"
        if approval.executed:
            return "resumed"
        return f"approved_{approval.status}"

    @staticmethod
    def _approval_view(a: Optional[BoundaryApproval]) -> Optional[Dict[str, Any]]:
        if a is None:
            return None
        return {
            "id": str(a.id),
            "status": a.status,
            "approved": a.approved,
            "approval_type": a.approval_type,
            "action_description": a.action_description,
            "workspace_id": str(a.workspace_id) if a.workspace_id else None,
            "task_id": str(a.task_id) if a.task_id else None,
            "decided_by": str(a.decided_by) if a.decided_by else None,
            "executed": a.executed,
            "approved_at": a.approved_at.isoformat() if a.approved_at else None,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        }

    @staticmethod
    def _decision_view(a: Optional[BoundaryApproval],
                       rbi: Optional[RichardBoundaryInput]) -> Optional[Dict[str, Any]]:
        if a is None or a.status == "pending":
            return None
        return {
            "decision": a.status,
            "decided_by": str(a.decided_by) if a.decided_by else None,
            "decided_at": a.approved_at.isoformat() if a.approved_at else None,
            "richard_boundary_input_id": str(rbi.id) if rbi else None,
            "reason": redact_secrets(a.response_message) if a.response_message else None,
        }

    @staticmethod
    def _window_view(w: Optional[ApprovalWindow]) -> Optional[Dict[str, Any]]:
        if w is None:
            return None
        return {
            "id": str(w.id),
            "status": w.status,
            "approval_id": str(w.approval_id) if w.approval_id else None,
            "workspace_id": str(w.workspace_id) if w.workspace_id else None,
            "task_id": str(w.task_id) if w.task_id else None,
            "decided_by": str(w.decided_by) if w.decided_by else None,
            "expires_at": w.expires_at.isoformat() if w.expires_at else None,
            "scope": redact_secrets(w.meta_data),  # window meta may carry a secret reason
        }

    @staticmethod
    def _checkpoint_summary(c: Optional[SafeCheckpoint]) -> Optional[Dict[str, Any]]:
        if c is None:
            return None
        # Summary ONLY — never the raw state_snapshot (may carry sensitive resume data).
        return {
            "id": str(c.id),
            "checkpoint_name": c.checkpoint_name,
            "checkpoint_type": c.checkpoint_type,
            "is_safe_state": c.is_safe_state,
            "can_resume_from": c.can_resume_from,
            "verification_status": c.verification_status,
            "workspace_id": str(c.workspace_id) if c.workspace_id else None,
            "task_id": str(c.task_id) if c.task_id else None,
            "approval_id": str(c.approval_id) if c.approval_id else None,
            "resume_actions_available": list(c.resume_actions_available or []),
            "state_keys": sorted(list((c.state_snapshot or {}).keys())),
        }

    @staticmethod
    def _input_view(i: RichardBoundaryInput) -> Dict[str, Any]:
        return {
            "id": str(i.id),
            "input_type": i.input_type,
            "input_category": i.input_category,
            "is_validated": i.is_validated,
            "validation_result": i.validation_result,
            "related_approval_id": str(i.related_approval_id) if i.related_approval_id else None,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }

    @staticmethod
    def _resume_view(r: ResumeAction) -> Dict[str, Any]:
        return {
            "id": str(r.id),
            "action_type": r.action_type,
            "success": r.success,
            "checkpoint_id": str(r.checkpoint_id),
            "approval_id": str(r.approval_id) if r.approval_id else None,
            "executed_by": str(r.executed_by) if r.executed_by else None,
            "error_message": redact_secrets(r.error_message) if r.error_message else None,
            "executed_at": r.executed_at.isoformat() if r.executed_at else None,
        }
