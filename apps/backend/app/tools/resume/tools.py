"""
JARV Backend - Checkpoint & Resume Tools (real implementations)

Design-aligned tools:
  - checkpoint.create   (persist a real SafeCheckpoint)
  - checkpoint.get      (read a SafeCheckpoint; missing -> truthful not-found)
  - resume.plan         (derive a resume plan from a real checkpoint + approval state)
  - resume.execute      (restore checkpoint state into the agent session; persist a
                         ResumeAction; success ONLY if restoration truly occurred)

resume.execute does NOT fake mission continuation. It performs real, verifiable
state restoration onto the AgentSession row (variables, current step, execution
stack) and records a ResumeAction. Autonomous re-driving of the mission by a
workflow engine is out of scope for this repair and is reported as a documented
limitation, not as completed work. When the checkpoint or its session is missing,
or an approval is still pending, it returns a truthful blocked result naming the
exact missing requirement.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Type
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolBase, ToolContext, ToolResult


# --------------------------------------------------------------------------- #
# checkpoint.create
# --------------------------------------------------------------------------- #

class CheckpointCreateInput(BaseModel):
    checkpoint_name: str = Field(..., description="Human label for the checkpoint")
    checkpoint_type: str = Field("safe_point", description="manual|safe_point|pre_boundary|...")
    state_snapshot: Dict[str, Any] = Field(default_factory=dict, description="Serializable state")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Execution variables")
    message_history: List[Dict[str, Any]] = Field(default_factory=list)
    is_safe_state: bool = Field(True)
    verification_status: str = Field("verified", description="verified|unverified|warning")
    can_resume_from: bool = Field(True)
    safety_checks_passed: List[str] = Field(default_factory=list)
    resume_actions_available: List[str] = Field(default_factory=list)


class CheckpointRefOutput(BaseModel):
    persisted: bool
    checkpoint_id: Optional[str] = None
    blocked: Optional[bool] = None
    reason: Optional[str] = None


class CheckpointCreateTool(ToolBase):
    """Persist a real SafeCheckpoint (requires DB session + session_id)."""

    @property
    def name(self) -> str:
        return "checkpoint.create"

    @property
    def description(self) -> str:
        return ("Create and persist a SafeCheckpoint capturing safe execution state. "
                "Requires a real DB session and the session id.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CheckpointCreateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CheckpointRefOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def category(self) -> str:
        return "resume"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        missing: List[str] = []
        if getattr(context, "db_session", None) is None:
            missing.append("db_session")
        if getattr(context, "session_id", None) is None:
            missing.append("session_id")
        if missing:
            reason = "missing required persistence context: " + ", ".join(missing)
            return self.create_result(
                success=False, result_data={"persisted": False, "blocked": True, "reason": reason},
                output_text=f"NOT PERSISTED: {reason}")

        from app.models.boundary import SafeCheckpoint
        session = context.db_session
        try:
            cp = SafeCheckpoint(
                session_id=context.session_id,
                checkpoint_name=input_data["checkpoint_name"],
                checkpoint_type=input_data["checkpoint_type"],
                is_safe_state=bool(input_data["is_safe_state"]),
                state_snapshot=input_data.get("state_snapshot") or {},
                variables=input_data.get("variables") or {},
                message_history=input_data.get("message_history") or [],
                verification_status=input_data["verification_status"],
                safety_checks_passed=input_data.get("safety_checks_passed") or [],
                safety_warnings=[],
                can_resume_from=bool(input_data["can_resume_from"]),
                resume_actions_available=input_data.get("resume_actions_available") or [],
            )
            session.add(cp)
            await session.commit()
            await session.refresh(cp)
            return self.create_result(
                success=True,
                result_data={"persisted": True, "checkpoint_id": str(cp.id),
                             "can_resume_from": cp.can_resume_from},
                output_text=f"SafeCheckpoint {cp.id} persisted.")
        except Exception as e:  # noqa: BLE001
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return self.create_result(
                success=False, result_data={"persisted": False, "reason": f"persistence failed: {e}"},
                error_message=str(e), output_text="NOT PERSISTED: database error")


# --------------------------------------------------------------------------- #
# checkpoint.get
# --------------------------------------------------------------------------- #

class CheckpointGetInput(BaseModel):
    checkpoint_id: str = Field(..., description="SafeCheckpoint id (UUID)")


class CheckpointGetOutput(BaseModel):
    found: bool
    checkpoint: Optional[Dict[str, Any]] = None


class CheckpointGetTool(ToolBase):
    """Read a SafeCheckpoint by id. Missing -> truthful not-found."""

    @property
    def name(self) -> str:
        return "checkpoint.get"

    @property
    def description(self) -> str:
        return "Retrieve a persisted SafeCheckpoint by id; returns found=false if it does not exist."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CheckpointGetInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CheckpointGetOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "resume"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if getattr(context, "db_session", None) is None:
            return self.create_result(
                success=False,
                result_data={"found": False, "reason": "missing required persistence context: db_session"},
                output_text="NO DB SESSION")
        from app.models.boundary import SafeCheckpoint
        session = context.db_session
        try:
            cid = UUID(str(input_data["checkpoint_id"]))
        except Exception:
            return self.create_result(success=True, result_data={"found": False, "reason": "invalid checkpoint_id"},
                                      output_text="invalid checkpoint_id")
        row = (await session.execute(
            select(SafeCheckpoint).where(SafeCheckpoint.id == cid))).scalar_one_or_none()
        if row is None:
            return self.create_result(success=True, result_data={"found": False},
                                      output_text=f"Checkpoint {cid} not found.")
        return self.create_result(
            success=True,
            result_data={"found": True, "checkpoint": {
                "id": str(row.id), "checkpoint_name": row.checkpoint_name,
                "checkpoint_type": row.checkpoint_type, "is_safe_state": row.is_safe_state,
                "can_resume_from": row.can_resume_from,
                "resume_actions_available": row.resume_actions_available,
                "verification_status": row.verification_status,
                "session_id": str(row.session_id)}},
            output_text=f"Checkpoint {cid} found.")


# --------------------------------------------------------------------------- #
# resume.plan
# --------------------------------------------------------------------------- #

class ResumePlanInput(BaseModel):
    checkpoint_id: str = Field(..., description="SafeCheckpoint id to plan a resume from")


class ResumePlanOutput(BaseModel):
    can_resume: bool
    reason: Optional[str] = None
    plan_steps: List[str] = Field(default_factory=list)
    blocked_on_approvals: List[str] = Field(default_factory=list)


class ResumePlanTool(ToolBase):
    """Derive a resume plan from a real checkpoint + current approval state (read-only)."""

    @property
    def name(self) -> str:
        return "resume.plan"

    @property
    def description(self) -> str:
        return ("Produce a resume plan from a persisted checkpoint, factoring in any pending approvals "
                "for the checkpoint's session. Read-only; does not modify state.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResumePlanInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResumePlanOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "resume"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if getattr(context, "db_session", None) is None:
            return self.create_result(
                success=False,
                result_data={"can_resume": False, "reason": "missing required persistence context: db_session"},
                output_text="NO DB SESSION")
        from app.models.boundary import SafeCheckpoint, BoundaryApproval
        session = context.db_session
        try:
            cid = UUID(str(input_data["checkpoint_id"]))
        except Exception:
            return self.create_result(success=True, result_data={"can_resume": False, "reason": "invalid checkpoint_id"},
                                      output_text="invalid checkpoint_id")
        cp = (await session.execute(
            select(SafeCheckpoint).where(SafeCheckpoint.id == cid))).scalar_one_or_none()
        if cp is None:
            return self.create_result(success=True,
                                      result_data={"can_resume": False, "reason": "checkpoint not found"},
                                      output_text=f"Checkpoint {cid} not found; cannot plan resume.")
        if not cp.can_resume_from:
            return self.create_result(success=True,
                                      result_data={"can_resume": False, "reason": "checkpoint is not resumable"},
                                      output_text="Checkpoint is not marked resumable.")

        # Real approval state for the checkpoint's session.
        pending = (await session.execute(
            select(BoundaryApproval).where(
                BoundaryApproval.session_id == cp.session_id,
                BoundaryApproval.status == "pending"))).scalars().all()
        blocked_on = [str(a.id) for a in pending]

        pending_steps = []
        snap = cp.state_snapshot or {}
        if isinstance(snap, dict) and isinstance(snap.get("pending_steps"), list):
            pending_steps = [str(s) for s in snap["pending_steps"]]

        if blocked_on:
            return self.create_result(
                success=True,
                result_data={"can_resume": False, "reason": "pending approvals must be decided first",
                             "blocked_on_approvals": blocked_on, "plan_steps": []},
                output_text=f"Resume blocked on {len(blocked_on)} pending approval(s).")

        plan_steps = (["restore checkpoint state into agent session"]
                      + [f"resume action: {a}" for a in (cp.resume_actions_available or [])]
                      + [f"continue pending step: {s}" for s in pending_steps]
                      + ["continue mission"])
        return self.create_result(
            success=True,
            result_data={"can_resume": True, "plan_steps": plan_steps, "blocked_on_approvals": []},
            output_text=f"Resume plan with {len(plan_steps)} step(s).")


# --------------------------------------------------------------------------- #
# resume.execute
# --------------------------------------------------------------------------- #

class ResumeExecuteInput(BaseModel):
    checkpoint_id: str = Field(..., description="SafeCheckpoint id to resume from")
    resume_reason: str = Field("resume after boundary cleared", description="Why resuming")
    executed_by: Optional[str] = Field(None, description="User id initiating resume")


class ResumeExecuteOutput(BaseModel):
    success: bool
    restored: bool
    resume_action_id: Optional[str] = None
    blocked: Optional[bool] = None
    reason: Optional[str] = None
    limitation: Optional[str] = None


_RESUME_LIMITATION = (
    "resume.execute restores the persisted checkpoint state (variables, current step, execution "
    "stack) into the agent session and records a ResumeAction. It does NOT itself re-drive the "
    "mission through a workflow engine (that subsystem is out of scope for this repair); mission "
    "continuation must be triggered by the orchestrator after restoration."
)


class ResumeExecuteTool(ToolBase):
    """Restore checkpoint state into the agent session and record a ResumeAction.

    Success is reported ONLY when real state restoration occurred. If the checkpoint
    or its agent session is missing, or a pending approval blocks resume, a truthful
    blocked result is returned stating the exact missing requirement.
    """

    @property
    def name(self) -> str:
        return "resume.execute"

    @property
    def description(self) -> str:
        return ("Resume from a checkpoint by restoring its state into the agent session and recording a "
                "ResumeAction. Blocked (with the exact missing requirement) if the checkpoint/session is "
                "missing or an approval is still pending. Does not fake mission continuation.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResumeExecuteInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResumeExecuteOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def category(self) -> str:
        return "resume"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if getattr(context, "db_session", None) is None:
            return self.create_result(
                success=False,
                result_data={"success": False, "restored": False, "blocked": True,
                             "reason": "missing required persistence context: db_session",
                             "limitation": _RESUME_LIMITATION},
                output_text="NO DB SESSION: cannot resume")
        from app.models.boundary import SafeCheckpoint, BoundaryApproval, ResumeAction
        from app.models.session import AgentSession
        session = context.db_session
        try:
            cid = UUID(str(input_data["checkpoint_id"]))
        except Exception:
            return self.create_result(
                success=False,
                result_data={"success": False, "restored": False, "reason": "invalid checkpoint_id"},
                output_text="invalid checkpoint_id")

        cp = (await session.execute(
            select(SafeCheckpoint).where(SafeCheckpoint.id == cid))).scalar_one_or_none()
        if cp is None:
            return self.create_result(
                success=False,
                result_data={"success": False, "restored": False, "blocked": True,
                             "reason": f"checkpoint {cid} not found", "limitation": _RESUME_LIMITATION},
                output_text=f"BLOCKED: checkpoint {cid} not found.")

        # Pending approvals for this session block resume.
        pending = (await session.execute(
            select(BoundaryApproval).where(
                BoundaryApproval.session_id == cp.session_id,
                BoundaryApproval.status == "pending"))).scalars().all()
        if pending:
            ids = ", ".join(str(a.id) for a in pending)
            return self.create_result(
                success=False,
                result_data={"success": False, "restored": False, "blocked": True,
                             "reason": f"pending approval(s) must be decided before resume: {ids}",
                             "limitation": _RESUME_LIMITATION},
                output_text="BLOCKED: pending approval(s) before resume.")

        # Real state restoration requires an existing agent session row.
        sess_row = (await session.execute(
            select(AgentSession).where(AgentSession.id == cp.session_id))).scalar_one_or_none()
        if sess_row is None:
            return self.create_result(
                success=False,
                result_data={"success": False, "restored": False, "blocked": True,
                             "reason": (f"no agent_session {cp.session_id} to restore state into; resume "
                                        "cannot occur without the session row"),
                             "limitation": _RESUME_LIMITATION},
                output_text="BLOCKED: no agent session to restore.")

        try:
            snap = cp.state_snapshot or {}
            sess_row.variables = cp.variables or {}
            if isinstance(snap, dict):
                if snap.get("current_step") is not None:
                    sess_row.current_step = str(snap["current_step"])
                if isinstance(snap.get("execution_stack"), list):
                    sess_row.execution_stack = snap["execution_stack"]
            sess_row.is_resumed = True
            sess_row.resumed_at = datetime.utcnow()
            sess_row.status = "active"

            executed_by = None
            if input_data.get("executed_by"):
                try:
                    executed_by = UUID(str(input_data["executed_by"]))
                except Exception:
                    executed_by = None

            action = ResumeAction(
                session_id=cp.session_id,
                checkpoint_id=cp.id,
                action_type="resume_from_checkpoint",
                action_description=input_data.get("resume_reason") or "resume",
                action_details={"restored_variables": list((cp.variables or {}).keys()),
                                "checkpoint_name": cp.checkpoint_name},
                executed_at=datetime.utcnow(),
                executed_by=executed_by,
                success=True,
                result={"restored": True, "session_id": str(cp.session_id)},
            )
            session.add(action)
            await session.commit()
            await session.refresh(action)
            return self.create_result(
                success=True,
                result_data={"success": True, "restored": True, "resume_action_id": str(action.id),
                             "session_id": str(cp.session_id),
                             "restored_variables": list((cp.variables or {}).keys()),
                             "limitation": _RESUME_LIMITATION},
                output_text=f"Resumed: state restored into session {cp.session_id}; ResumeAction {action.id} recorded.")
        except Exception as e:  # noqa: BLE001
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return self.create_result(
                success=False,
                result_data={"success": False, "restored": False, "reason": f"resume failed: {e}",
                             "limitation": _RESUME_LIMITATION},
                error_message=str(e), output_text="RESUME FAILED: database error")
