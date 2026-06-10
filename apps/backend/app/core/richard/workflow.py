"""
JARV Backend - Richard Boundary Operator Workflow (Repair 8)

This module connects the real Repair-7 pieces (hard-boundary detection,
BoundaryReport / BoundaryApproval / SafeCheckpoint / ResumeAction persistence)
into the end-to-end safety loop the Design (section 6) and CLAUDE.md require:

    mission hits a hard boundary
      -> ONLY the blocked action pauses (safe parallel work continues elsewhere)
      -> a real BoundaryReport is persisted
      -> a real SafeCheckpoint is persisted (captures how to resume)
      -> a real pending BoundaryApproval is persisted
      -> Richard is asked only for the exact blocked decision
      -> Richard's AUTHENTICATED decision is recorded (decided_by is bound to the
         authenticated current user, NOT to caller-supplied tool input)
      -> an ApprovalWindow with EXACT scope is created on approval
      -> the mission RESUMES from the checkpoint and the blocked action runs
      -> the mission finishes / partially finishes / fails honestly
      -> no mission is silently abandoned

Everything here uses real database persistence on a real AsyncSession. There is
no fake workflow, no fake Richard decision, no caller-supplied identity trust, no
fake approval window, and no fake resume success. When a precondition is missing
the methods return a truthful blocked/expired/rejected result naming the exact
reason rather than fabricating success.

Authority model: JARV is private single-user software owned by Richard. The
"authenticated current user" is the trusted identity (FastAPI auth dependency /
ToolContext.user_id). A boundary decision is authorised only when the
authenticated user matches the owner who initiated the mission (the approval's
``user_id``). Mismatched or unauthenticated decisions are blocked.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import UUID, uuid4, uuid5, NAMESPACE_DNS

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.boundary import (
    ApprovalWindow,
    BoundaryApproval,
    BoundaryReport,
    ResumeAction,
    RichardBoundaryInput,
    SafeCheckpoint,
)
from app.models.operations import AuditLog
from app.models.session import AgentSession

logger = logging.getLogger(__name__)


# Mission / approval states. These are the ONLY honest terminal/intermediate
# states; "planned" is never a terminal status (Repair 8 requirement).
WAITING = "waiting_on_richard"
RESUMED = "resumed"
COMPLETED = "completed"
PARTIAL = "partial"
FAILED = "failed"
REJECTED = "rejected"
EXPIRED = "expired"


def coerce_user_id(value: Any) -> Optional[UUID]:
    """Coerce an authenticated identity to a stable UUID.

    Operators may authenticate with a username-derived subject (e.g.
    "admin_richard") rather than a UUID; mirror app.core.auth.get_current_user so
    the same operator always maps to the same UUID. Returns None for empty input.
    """
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return uuid5(NAMESPACE_DNS, f"jarv-user-{value}")


class RichardBoundaryWorkflow:
    """Coordinator for the full hard-boundary -> decision -> resume loop.

    One instance wraps one real AsyncSession. All persistence is real; all
    failures roll back and are reported honestly.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = logging.getLogger("richard.workflow")

    # ------------------------------------------------------------------ #
    # Session / agent helpers
    # ------------------------------------------------------------------ #

    async def ensure_orchestrator_agent(self, workspace_id: UUID,
                                        name: str = "orchestrator") -> Agent:
        """Get-or-create the real Agent row that owns mission sessions.

        AgentSession.agent_id is a non-null FK, so a real Agent row must exist.
        The orchestrator genuinely is an agent; this is a real row, not a fake.
        """
        existing = (await self.db.execute(
            select(Agent).where(Agent.name == name, Agent.workspace_id == workspace_id)
        )).scalars().first()
        if existing is not None:
            return existing
        agent = Agent(
            name=name, agent_type="core", workspace_id=workspace_id,
            description="Core orchestration agent (owns mission sessions)",
            is_active=True, authority_level=9, allowed_tools=[], blocked_tools=[],
        )
        self.db.add(agent)
        await self.db.flush()
        return agent

    async def ensure_session(
        self,
        *,
        session_id: Optional[UUID],
        user_id: UUID,
        workspace_id: UUID,
        agent_id: Optional[UUID],
        initial_prompt: Optional[str] = None,
        session_name: Optional[str] = None,
    ) -> AgentSession:
        """Get-or-create the AgentSession that represents the mission."""
        if session_id is not None:
            row = (await self.db.execute(
                select(AgentSession).where(AgentSession.id == session_id)
            )).scalar_one_or_none()
            if row is not None:
                return row
        if agent_id is None:
            agent = await self.ensure_orchestrator_agent(workspace_id)
            agent_id = agent.id
        sess = AgentSession(
            id=session_id or uuid4(),
            user_id=user_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            session_type="mission",
            session_name=session_name or "mission",
            status="active",
            messages=[],
            execution_logs=[],
            initial_prompt=initial_prompt,
        )
        self.db.add(sess)
        await self.db.flush()
        return sess

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #

    async def _audit(self, *, workspace_id: Optional[UUID], user_id: Optional[UUID],
                     agent_id: Optional[UUID], session_id: Optional[UUID],
                     action: str, description: str, success: bool,
                     target_type: str, target_id: Optional[str],
                     required_approval: bool = False,
                     meta: Optional[Dict[str, Any]] = None) -> None:
        """Write a real, redacted AuditLog row (never raises)."""
        try:
            from app.core.security import redact_secrets

            self.db.add(AuditLog(
                workspace_id=workspace_id, user_id=user_id, agent_id=agent_id,
                session_id=session_id, actor_type="richard_workflow",
                action=action, action_category="boundary",
                description=str(description)[:1000],
                target_type=target_type, target_id=target_id,
                success=success, required_approval=required_approval,
                meta_data=redact_secrets(meta or {}),
                occurred_at=datetime.utcnow(),
            ))
            await self.db.flush()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(f"audit write skipped: {exc}")

    # ------------------------------------------------------------------ #
    # STEP 3 - hard-boundary interception
    # ------------------------------------------------------------------ #

    async def handle_hard_boundary(
        self,
        *,
        session_id: UUID,
        agent_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        blocked_action: str,
        boundary_type: str,
        reason: str,
        severity: str = "high",
        requested_authority_level: int = 8,
        available_authority_level: int = 0,
        safe_work_continuing: Optional[List[str]] = None,
        resume_snapshot: Optional[Dict[str, Any]] = None,
        task_id: Optional[UUID] = None,
        approval_type: str = "boundary",
        input_prompt: Optional[str] = None,
        detection: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist the pause: BoundaryReport + SafeCheckpoint + pending approval.

        Only the blocked action is paused; the caller continues safe work. Returns
        the persisted ids and ``status='waiting_on_richard'``. Idempotent: if an
        unresolved boundary for the same (session, task, boundary_type) already
        exists, its ids are returned instead of creating duplicates.
        """
        # Idempotency: reuse an existing unresolved boundary for this exact action.
        existing = (await self.db.execute(
            select(BoundaryReport).where(
                BoundaryReport.session_id == session_id,
                BoundaryReport.boundary_type == boundary_type,
                BoundaryReport.resolution.is_(None),
            ).order_by(BoundaryReport.created_at.desc())
        )).scalars().first()
        if existing is not None:
            ctx = existing.context or {}
            if str(ctx.get("task_id")) == str(task_id):
                self.logger.info(
                    f"handle_hard_boundary idempotent reuse: report {existing.id}")
                return {
                    "status": WAITING,
                    "idempotent": True,
                    "boundary_report_id": str(existing.id),
                    "approval_id": str(existing.approval_id) if existing.approval_id else None,
                    "checkpoint_id": ctx.get("checkpoint_id"),
                    "session_id": str(session_id),
                }

        try:
            # 1) BoundaryReport - records the 15 Design section 6 fields available
            #    on the model; workspace/task/mission ids live in context (the
            #    model is session/agent-centric, see AUDIT_AGAINST_DESIGN.md section 9).
            report = BoundaryReport(
                session_id=session_id,
                agent_id=agent_id,
                report_type="hard_boundary",
                severity=severity,
                title=f"Hard boundary: {boundary_type}",
                description=reason,
                boundary_type=boundary_type,
                attempted_action=blocked_action,
                authority_level_required=int(requested_authority_level),
                authority_level_available=int(available_authority_level),
                context={
                    "workspace_id": str(workspace_id),
                    "user_id": str(user_id),
                    "task_id": str(task_id) if task_id else None,
                    "safe_work_continuing": list(safe_work_continuing or []),
                    "detection": detection or {},
                },
                was_blocked=True,
                action_taken="paused_blocked_action",
                approval_requested=True,
            )
            self.db.add(report)
            await self.db.flush()

            # 2) Pending BoundaryApproval - Richard is asked ONLY for this decision.
            approval = BoundaryApproval(
                user_id=user_id,
                session_id=session_id,
                approval_type=approval_type,
                action_description=blocked_action,
                action_details={
                    "boundary_type": boundary_type,
                    "boundary_report_id": str(report.id),
                    "workspace_id": str(workspace_id),
                    "task_id": str(task_id) if task_id else None,
                    "requested_authority_level": int(requested_authority_level),
                },
                richard_input_type=approval_type,
                requires_direct_input=False,
                input_prompt=input_prompt or f"Approve blocked action: {blocked_action}",
                status="pending",
                approved=None,
            )
            self.db.add(approval)
            await self.db.flush()

            # 3) SafeCheckpoint - captures exactly how to resume the blocked action.
            snap = dict(resume_snapshot or {})
            snap.setdefault("workspace_id", str(workspace_id))
            snap.setdefault("user_id", str(user_id))
            snap.setdefault("session_agent_id", str(agent_id))
            snap["boundary_type"] = boundary_type
            snap["boundary_report_id"] = str(report.id)
            snap["approval_id"] = str(approval.id)
            snap["task_id"] = str(task_id) if task_id else None
            checkpoint = SafeCheckpoint(
                session_id=session_id,
                checkpoint_name=f"pre-boundary:{boundary_type}",
                checkpoint_type="pre_boundary",
                is_safe_state=True,
                state_snapshot=snap,
                variables=snap.get("variables") or {},
                message_history=[],
                verification_status="verified",
                safety_checks_passed=["paused_blocked_action", "safe_state_captured"],
                safety_warnings=[],
                can_resume_from=True,
                resume_actions_available=["restore_state", "execute_blocked_action",
                                          "continue_dependent_tasks"],
                meta_data={"approval_id": str(approval.id),
                           "boundary_report_id": str(report.id)},
            )
            self.db.add(checkpoint)
            await self.db.flush()

            # Cross-link: report -> approval; report.context -> checkpoint id.
            report.approval_id = approval.id
            rctx = dict(report.context or {})
            rctx["checkpoint_id"] = str(checkpoint.id)
            report.context = rctx

            # 4) Pause the session for ONLY the blocked action (safe work elsewhere
            #    continues; the session is not abandoned, it is paused+resumable).
            sess = (await self.db.execute(
                select(AgentSession).where(AgentSession.id == session_id)
            )).scalar_one_or_none()
            if sess is not None:
                sess.is_paused = True
                sess.paused_at = datetime.utcnow()
                sess.status = "paused"
                sess.current_step = f"waiting_on_richard:{boundary_type}"

            await self.db.commit()

            await self._audit(
                workspace_id=workspace_id, user_id=user_id, agent_id=agent_id,
                session_id=session_id, action="hard_boundary_paused",
                description=f"Paused blocked action '{blocked_action}' ({boundary_type}); "
                            f"report+checkpoint+approval persisted.",
                success=True, target_type="boundary_report", target_id=str(report.id),
                required_approval=True,
                meta={"approval_id": str(approval.id), "checkpoint_id": str(checkpoint.id),
                      "task_id": str(task_id) if task_id else None})

            return {
                "status": WAITING,
                "idempotent": False,
                "boundary_report_id": str(report.id),
                "approval_id": str(approval.id),
                "checkpoint_id": str(checkpoint.id),
                "session_id": str(session_id),
            }
        except Exception as e:  # noqa: BLE001
            await self._safe_rollback()
            self.logger.error(f"handle_hard_boundary failed: {e}", exc_info=True)
            return {"status": "error", "persisted": False, "reason": f"persistence failed: {e}"}

    # ------------------------------------------------------------------ #
    # STEP 5/6/7 - authenticated Richard decision + RichardBoundaryInput + window
    # ------------------------------------------------------------------ #

    async def record_richard_decision(
        self,
        *,
        approval_id: UUID,
        authenticated_user_id: Any,
        approve: bool,
        reason: Optional[str] = None,
        richard_input_value: Optional[str] = None,
        scope_action: Optional[str] = None,
        authority_granted: Optional[int] = None,
        spend_limit: Optional[float] = None,
        release_scope: Optional[str] = None,
        expiry_seconds: Optional[int] = 3600,
        single_use: bool = True,
        max_uses: int = 1,
    ) -> Dict[str, Any]:
        """Record Richard's AUTHENTICATED decision and (on approve) open a scoped window.

        ``authenticated_user_id`` MUST come from trusted execution context (the
        FastAPI auth dependency / ToolContext.user_id), never from caller-supplied
        decision fields. The decision is authorised only when the authenticated
        user matches the mission owner (approval.user_id). ``decided_by`` is bound
        to the authenticated user; any caller-supplied identity is ignored.
        """
        auth_uid = coerce_user_id(authenticated_user_id)
        if auth_uid is None:
            return {"decided": False, "blocked": True,
                    "reason": "unauthenticated: no authenticated user in trusted context"}

        approval = (await self.db.execute(
            select(BoundaryApproval).where(BoundaryApproval.id == approval_id)
        )).scalar_one_or_none()
        if approval is None:
            return {"decided": False, "blocked": True, "reason": "approval not found"}

        # Bind to the authenticated identity: only the mission owner may decide.
        if approval.user_id != auth_uid:
            await self._audit(
                workspace_id=None, user_id=auth_uid, agent_id=None,
                session_id=approval.session_id, action="boundary_decision_denied",
                description="Authenticated user is not the mission owner; decision refused.",
                success=False, target_type="boundary_approval", target_id=str(approval.id),
                required_approval=True, meta={"reason": "identity_mismatch"})
            await self.db.commit()
            return {"decided": False, "blocked": True,
                    "reason": ("authenticated user is not authorised to decide this approval "
                               "(must be the mission owner)")}

        # Idempotency: a decided approval is not silently overwritten.
        if approval.status in ("approved", "rejected") or approval.approved is not None:
            same = (approval.status == ("approved" if approve else "rejected"))
            window_id = str(approval.approval_window_id) if approval.approval_window_id else None
            return {"decided": False, "already_decided": True, "idempotent": same,
                    "approval_id": str(approval.id), "status": approval.status,
                    "approval_window_id": window_id,
                    "reason": (f"approval already {approval.status}"
                               + ("" if same else "; conflicting decision rejected — "
                                  "request a new approval to change it"))}

        details = approval.action_details or {}
        boundary_type = details.get("boundary_type") or "boundary"
        workspace_id = _maybe_uuid(details.get("workspace_id"))
        task_id = details.get("task_id")
        report_id = details.get("boundary_report_id")
        scope_action = scope_action or approval.action_description
        if authority_granted is None:
            authority_granted = int(details.get("requested_authority_level") or 0)

        try:
            now = datetime.utcnow()
            approval.approved = bool(approve)
            approval.status = "approved" if approve else "rejected"
            approval.approved_at = now
            approval.response_message = reason
            if richard_input_value is not None:
                approval.richard_input_value = str(richard_input_value)
            meta = dict(approval.meta_data or {})
            meta["decided_by"] = str(auth_uid)            # bound to authenticated user
            meta["decided_at"] = now.isoformat()
            meta["decision"] = approval.status
            meta["authenticated"] = True
            approval.meta_data = meta

            # RichardBoundaryInput - structured record of Richard's input (STEP 6).
            rbi = RichardBoundaryInput(
                user_id=auth_uid,
                session_id=approval.session_id,
                input_type=approval.richard_input_type or "approval",
                input_category=boundary_type,
                input_prompt=approval.input_prompt or approval.action_description,
                input_value=(str(richard_input_value) if richard_input_value is not None
                             else approval.status),
                input_format="text",
                context={
                    "decision": approval.status,
                    "approve": bool(approve),
                    "boundary_report_id": report_id,
                    "workspace_id": str(workspace_id) if workspace_id else None,
                    "task_id": task_id,
                    "scope_action": scope_action,
                    "authority_granted": authority_granted,
                    "spend_limit": spend_limit,
                    "reason": reason,
                },
                related_approval_id=approval.id,
                is_validated=True,
                validation_result="authenticated_owner_decision",
            )
            self.db.add(rbi)
            await self.db.flush()

            window_id: Optional[str] = None
            if approve:
                # ApprovalWindow with EXACT scope (STEP 7). Scope lives in meta_data
                # (the model has no dedicated scope columns; this avoids a migration
                # while still enforcing exact scope). NEVER a universal approval.
                expires_at = (now + timedelta(seconds=int(expiry_seconds))
                              if expiry_seconds else None)
                window = ApprovalWindow(
                    session_id=approval.session_id,
                    user_id=auth_uid,
                    window_type=boundary_type,
                    title=f"Approval window: {scope_action}"[:500],
                    description=reason or f"Scoped approval for {scope_action}",
                    status="active",
                    total_approvals=1,
                    approved_count=1,
                    rejected_count=0,
                    opened_at=now,
                    closed_at=None,
                    meta_data={
                        "approval_id": str(approval.id),
                        "boundary_report_id": report_id,
                        "workspace_id": str(workspace_id) if workspace_id else None,
                        "task_id": task_id,
                        "scope_action": scope_action,
                        "boundary_type": boundary_type,
                        "authority_granted": int(authority_granted),
                        "spend_limit": spend_limit,
                        "release_scope": release_scope,
                        "expires_at": expires_at.isoformat() if expires_at else None,
                        "single_use": bool(single_use),
                        "max_uses": 1 if single_use else int(max_uses),
                        "uses": 0,
                        "decided_by": str(auth_uid),
                        "reason": reason,
                    },
                )
                self.db.add(window)
                await self.db.flush()
                approval.approval_window_id = window.id
                window_id = str(window.id)
            else:
                # Rejection creates NO active window; mark the report resolved-rejected.
                if report_id:
                    rep = (await self.db.execute(
                        select(BoundaryReport).where(BoundaryReport.id == _maybe_uuid(report_id))
                    )).scalar_one_or_none()
                    if rep is not None:
                        rep.resolution = "rejected_by_richard"
                        rep.action_taken = "rejected_blocked_action"

            await self.db.commit()

            await self._audit(
                workspace_id=workspace_id, user_id=auth_uid, agent_id=None,
                session_id=approval.session_id,
                action=("boundary_approved" if approve else "boundary_rejected"),
                description=f"Richard {approval.status} '{scope_action}' ({boundary_type}).",
                success=True, target_type="boundary_approval", target_id=str(approval.id),
                required_approval=True,
                meta={"decided_by": str(auth_uid), "approval_window_id": window_id,
                      "scope_action": scope_action})

            return {"decided": True, "approval_id": str(approval.id),
                    "status": approval.status, "decided_by": str(auth_uid),
                    "richard_boundary_input_id": str(rbi.id),
                    "approval_window_id": window_id}
        except Exception as e:  # noqa: BLE001
            await self._safe_rollback()
            self.logger.error(f"record_richard_decision failed: {e}", exc_info=True)
            return {"decided": False, "reason": f"persistence failed: {e}"}

    # ------------------------------------------------------------------ #
    # ApprovalWindow scope validation (STEP 7)
    # ------------------------------------------------------------------ #

    def validate_window(
        self,
        window: ApprovalWindow,
        *,
        action: str,
        workspace_id: Optional[UUID] = None,
        task_id: Optional[str] = None,
        authority_required: int = 0,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Validate an ApprovalWindow against the action being resumed.

        Returns ``{"ok": bool, "reason": str, "expired": bool}``. Enforces:
        active status, not expired, uses < max_uses, matching workspace/task,
        matching action/scope, and authority_required <= authority_granted. An
        out-of-scope or expired window is NEVER usable.
        """
        now = now or datetime.utcnow()
        meta = window.meta_data or {}
        if window.status != "active":
            return {"ok": False, "expired": window.status == "expired",
                    "reason": f"window status is '{window.status}', not active"}
        exp = meta.get("expires_at")
        if exp:
            try:
                if now > datetime.fromisoformat(exp):
                    return {"ok": False, "expired": True, "reason": "approval window expired"}
            except Exception:  # noqa: BLE001
                pass
        max_uses = int(meta.get("max_uses") or 1)
        uses = int(meta.get("uses") or 0)
        if uses >= max_uses:
            return {"ok": False, "expired": False,
                    "reason": f"approval window already used ({uses}/{max_uses})"}
        scope_ws = meta.get("workspace_id")
        if scope_ws and workspace_id is not None and str(scope_ws) != str(workspace_id):
            return {"ok": False, "expired": False, "reason": "workspace out of approval scope"}
        scope_task = meta.get("task_id")
        if scope_task and task_id is not None and str(scope_task) != str(task_id):
            return {"ok": False, "expired": False, "reason": "task out of approval scope"}
        scope_action = meta.get("scope_action")
        if scope_action and action is not None and scope_action != action:
            return {"ok": False, "expired": False, "reason": "action out of approval scope"}
        granted = int(meta.get("authority_granted") or 0)
        if int(authority_required) > granted:
            return {"ok": False, "expired": False,
                    "reason": (f"action needs authority {authority_required} but window grants "
                               f"only {granted}")}
        return {"ok": True, "expired": False, "reason": "in scope"}

    async def _consume_window(self, window: ApprovalWindow) -> None:
        """Increment window usage; close it when single-use/max-uses reached."""
        meta = dict(window.meta_data or {})
        meta["uses"] = int(meta.get("uses") or 0) + 1
        max_uses = int(meta.get("max_uses") or 1)
        if meta["uses"] >= max_uses:
            window.status = "consumed"
            window.closed_at = datetime.utcnow()
        window.meta_data = meta

    # ------------------------------------------------------------------ #
    # STEP 8 - real mission resume
    # ------------------------------------------------------------------ #

    async def resume_mission(
        self,
        *,
        checkpoint_id: UUID,
        authenticated_user_id: Any,
        run_blocked_action: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        run_dependent_task: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        """Resume the mission from a checkpoint and actually re-drive the work.

        Confirms the approval is granted and its ApprovalWindow scope matches,
        restores AgentSession state, executes the previously-blocked action and any
        dependent tasks through the real AgentRunner path (unless callbacks are
        supplied for testing), preserves already-completed safe work, persists a
        ResumeAction, and updates the BoundaryReport / approval / window / session
        and mission status. Honest states only; idempotent on repeat calls.
        """
        auth_uid = coerce_user_id(authenticated_user_id)
        cp = (await self.db.execute(
            select(SafeCheckpoint).where(SafeCheckpoint.id == checkpoint_id)
        )).scalar_one_or_none()
        if cp is None:
            return {"status": "blocked", "resumed": False,
                    "reason": f"checkpoint {checkpoint_id} not found"}
        if not cp.can_resume_from:
            return {"status": "blocked", "resumed": False,
                    "reason": "checkpoint is not resumable"}

        snap = cp.state_snapshot or {}
        approval_id = _maybe_uuid(snap.get("approval_id"))
        report_id = _maybe_uuid(snap.get("boundary_report_id"))
        workspace_id = _maybe_uuid(snap.get("workspace_id"))
        task_id = snap.get("task_id")
        blocked = snap.get("blocked_task") or {}
        blocked_action = blocked.get("description") or snap.get("boundary_type") or ""
        authority_required = int(blocked.get("requested_authority_level")
                                 or snap.get("requested_authority_level") or 0)

        approval = None
        if approval_id is not None:
            approval = (await self.db.execute(
                select(BoundaryApproval).where(BoundaryApproval.id == approval_id)
            )).scalar_one_or_none()
        if approval is None:
            return {"status": "blocked", "resumed": False,
                    "reason": "no approval linked to this checkpoint"}

        # Authenticated owner check (resume is itself an authorised action).
        if auth_uid is not None and approval.user_id != auth_uid:
            return {"status": "blocked", "resumed": False,
                    "reason": "authenticated user is not the mission owner"}

        if approval.status == "pending":
            return {"status": WAITING, "resumed": False,
                    "reason": "approval still pending; cannot resume"}
        if approval.status == "rejected":
            return {"status": REJECTED, "resumed": False,
                    "reason": "approval was rejected; blocked action stays stopped"}

        # Idempotency: if already executed, do not run the blocked action twice.
        if approval.executed:
            return {"status": approval.execution_result.get("mission_status", RESUMED)
                    if isinstance(approval.execution_result, dict) else RESUMED,
                    "resumed": True, "idempotent": True,
                    "reason": "approval already executed; resume is idempotent",
                    "result": approval.execution_result}

        # ApprovalWindow scope + expiry must validate.
        window = None
        if approval.approval_window_id is not None:
            window = (await self.db.execute(
                select(ApprovalWindow).where(ApprovalWindow.id == approval.approval_window_id)
            )).scalar_one_or_none()
        if window is None:
            return {"status": "blocked", "resumed": False,
                    "reason": "no active approval window for this approval"}
        v = self.validate_window(window, action=blocked_action, workspace_id=workspace_id,
                                 task_id=task_id, authority_required=authority_required)
        if not v["ok"]:
            if v["expired"]:
                return {"status": EXPIRED, "resumed": False,
                        "reason": f"cannot resume under expired authority: {v['reason']}"}
            return {"status": "blocked", "resumed": False,
                    "reason": f"approval window does not cover this action: {v['reason']}"}

        sess = (await self.db.execute(
            select(AgentSession).where(AgentSession.id == cp.session_id)
        )).scalar_one_or_none()
        if sess is None:
            return {"status": "blocked", "resumed": False,
                    "reason": f"no agent_session {cp.session_id} to restore into"}

        # Mark executed BEFORE running to make duplicate concurrent resume idempotent.
        approval.executed = True
        approval.executed_at = datetime.utcnow()

        # Restore session state from the checkpoint.
        sess.variables = cp.variables or sess.variables or {}
        if snap.get("current_step") is not None:
            sess.current_step = str(snap["current_step"])
        if isinstance(snap.get("execution_stack"), list):
            sess.execution_stack = snap["execution_stack"]
        sess.is_paused = False
        sess.is_resumed = True
        sess.resumed_at = datetime.utcnow()
        sess.status = "active"

        # Consume the (single-use) window for this resume.
        await self._consume_window(window)

        # Run the previously-blocked action + dependent tasks for real.
        completed_ids = list(snap.get("completed_task_ids") or [])
        dependents = snap.get("dependent_tasks") or []
        ran: List[Dict[str, Any]] = []
        errors: List[str] = []

        try:
            blocked_result = await self._run_step(
                blocked, run_blocked_action, workspace_id, approval.user_id,
                cp.session_id, scope_action=blocked_action)
            ran.append({"task_id": blocked.get("task_id"), "kind": "blocked",
                        "success": bool(blocked_result.get("success")),
                        "output_preview": (blocked_result.get("output_text") or "")[:200]})
            if not blocked_result.get("success"):
                errors.append(f"blocked action failed: {blocked_result.get('error')}")

            blocked_ok = bool(blocked_result.get("success"))
            # Dependent tasks only run if the blocked action succeeded.
            if blocked_ok:
                for dep in dependents:
                    if str(dep.get("task_id")) in {str(c) for c in completed_ids}:
                        continue  # never re-run already-completed safe work
                    dep_result = await self._run_step(
                        dep, run_dependent_task, workspace_id, approval.user_id,
                        cp.session_id, scope_action=None)
                    ran.append({"task_id": dep.get("task_id"), "kind": "dependent",
                                "success": bool(dep_result.get("success")),
                                "output_preview": (dep_result.get("output_text") or "")[:200]})
                    if not dep_result.get("success"):
                        errors.append(f"dependent task {dep.get('task_id')} failed")
        except Exception as e:  # noqa: BLE001
            # Failed resume stays retryable: undo the executed flag, roll back.
            await self._safe_rollback()
            self.logger.error(f"resume_mission execution error: {e}", exc_info=True)
            ap2 = (await self.db.execute(
                select(BoundaryApproval).where(BoundaryApproval.id == approval_id)
            )).scalar_one_or_none()
            if ap2 is not None:
                ap2.executed = False
                ap2.executed_at = None
                await self.db.commit()
            return {"status": FAILED, "resumed": False, "retryable": True,
                    "reason": f"resume execution failed (retryable from checkpoint): {e}"}

        # Derive honest mission status.
        blocked_ok = bool(ran and ran[0]["success"])
        all_ok = blocked_ok and all(r["success"] for r in ran)
        if not blocked_ok:
            mission_status = FAILED
        elif all_ok:
            mission_status = COMPLETED
        else:
            mission_status = PARTIAL

        # Persist ResumeAction (real outcome). Flush to obtain its id before the
        # single commit so we never read ORM attributes after commit (production
        # sessions may expire_on_commit).
        action = ResumeAction(
            session_id=cp.session_id,
            checkpoint_id=cp.id,
            action_type="resume_from_checkpoint",
            action_description=f"Resume after boundary cleared: {blocked_action}"[:1000],
            action_details={"ran": ran, "errors": errors,
                            "restored_variables": list((cp.variables or {}).keys())},
            executed_at=datetime.utcnow(),
            executed_by=auth_uid,
            success=blocked_ok,
            result={"mission_status": mission_status, "ran": ran},
            error_message="; ".join(errors)[:1000] if errors else None,
        )
        self.db.add(action)
        await self.db.flush()
        action_id = action.id

        # Update approval execution result, boundary report, session.
        approval.execution_result = {"mission_status": mission_status,
                                     "resume_action_id": str(action_id),
                                     "ran_count": len(ran)}
        rep = None
        if report_id is not None:
            rep = (await self.db.execute(
                select(BoundaryReport).where(BoundaryReport.id == report_id)
            )).scalar_one_or_none()

        if blocked_ok:
            # The blocked action actually ran and succeeded: this resume is durable.
            if rep is not None:
                rep.resolution = f"resumed_{mission_status}"
                rep.action_taken = "resumed_after_approval"
            sess.status = "completed" if mission_status == COMPLETED else "active"
            if mission_status == COMPLETED:
                sess.ended_at = datetime.utcnow()
            sess.current_step = f"resumed:{mission_status}"
        else:
            # The blocked action ran but FAILED. Do not fake completion and do not
            # lock the mission: leave the boundary report UNRESOLVED and clear the
            # executed flag so the mission stays retryable from this safe checkpoint.
            approval.executed = False
            approval.executed_at = None
            if rep is not None:
                rep.action_taken = "resume_attempt_failed"  # resolution stays None
            sess.status = "active"
            sess.current_step = f"resume_failed_retryable:{blocked_action[:60]}"

        await self.db.commit()

        await self._audit(
            workspace_id=workspace_id, user_id=auth_uid, agent_id=None,
            session_id=cp.session_id, action="mission_resumed",
            description=f"Resumed mission from checkpoint {cp.id}: {mission_status}.",
            success=blocked_ok, target_type="resume_action", target_id=str(action_id),
            required_approval=True,
            meta={"mission_status": mission_status, "ran": ran, "errors": errors})

        return {"status": mission_status, "resumed": blocked_ok, "idempotent": False,
                "retryable": (not blocked_ok),
                "resume_action_id": str(action_id), "ran": ran, "errors": errors,
                "checkpoint_id": str(cp.id), "session_id": str(cp.session_id)}

    async def _run_step(
        self,
        step: Dict[str, Any],
        callback: Optional[Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]],
        workspace_id: Optional[UUID],
        user_id: Optional[UUID],
        session_id: UUID,
        scope_action: Optional[str],
    ) -> Dict[str, Any]:
        """Execute one step via the supplied callback or the real AgentRunner.

        ``scope_action`` is non-None for the blocked action, signalling that this
        step runs under granted approval (approval_granted=True).
        """
        if callback is not None:
            return await callback(step)

        agent_name = step.get("agent") or step.get("assigned_agent")
        description = step.get("description") or scope_action or ""
        if not agent_name:
            return {"success": False, "error": "no agent assigned for step",
                    "output_text": ""}
        from app.core.agents.runner import AgentRunner

        runner = AgentRunner()
        approved_tools = step.get("approved_tools") or []
        result = await runner.run_agent(
            agent_name=agent_name, task=description,
            workspace_id=workspace_id or uuid4(), user_id=user_id,
            db=self.db, session_id=session_id,
            approval_granted=bool(scope_action is not None),
            approved_tools=approved_tools,
        )
        return result

    # ------------------------------------------------------------------ #
    # Read helpers (API support)
    # ------------------------------------------------------------------ #

    async def list_pending_decisions(self, *, workspace_id: Optional[UUID] = None,
                                     limit: int = 100) -> List[Dict[str, Any]]:
        """List pending Richard decisions (pending BoundaryApprovals)."""
        q = select(BoundaryApproval).where(BoundaryApproval.status == "pending")
        q = q.order_by(BoundaryApproval.created_at.desc()).limit(limit)
        rows = (await self.db.execute(q)).scalars().all()
        out: List[Dict[str, Any]] = []
        for r in rows:
            details = r.action_details or {}
            if workspace_id is not None and str(details.get("workspace_id")) != str(workspace_id):
                continue
            out.append({"approval_id": str(r.id), "approval_type": r.approval_type,
                        "action_description": r.action_description,
                        "boundary_type": details.get("boundary_type"),
                        "boundary_report_id": details.get("boundary_report_id"),
                        "task_id": details.get("task_id"),
                        "session_id": str(r.session_id),
                        "created_at": r.created_at.isoformat() if r.created_at else None})
        return out

    async def _safe_rollback(self) -> None:
        try:
            await self.db.rollback()
        except Exception:  # noqa: BLE001
            pass


def _maybe_uuid(value: Any) -> Optional[UUID]:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except Exception:  # noqa: BLE001
        return None
