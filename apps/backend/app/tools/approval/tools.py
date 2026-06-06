"""
JARV Backend - Approval Tools (real implementations)

Design-aligned approval tools:
  - approval.request        (persist a pending BoundaryApproval)
  - approval.status         (read persisted approval state)
  - approval.list_pending   (list real pending approvals)
  - approval.grant          (record an approval decision; requires authorised context)
  - approval.reject         (record a rejection decision; requires authorised context)

grant/reject require an EXPLICIT authorised decision context: a real decider id
plus authorized=True. Approval is never inferred from the tool call itself, never
defaulted, and never silent. Each decision persists who decided, when, and the
decision. Repeated decisions are handled idempotently.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Type
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.tools.base import ToolBase, ToolContext, ToolResult


def _missing(context: ToolContext, *, need_user: bool, need_session: bool) -> Optional[str]:
    missing: List[str] = []
    if getattr(context, "db_session", None) is None:
        missing.append("db_session")
    if need_user and getattr(context, "user_id", None) is None:
        missing.append("user_id")
    if need_session and getattr(context, "session_id", None) is None:
        missing.append("session_id")
    if missing:
        return "missing required persistence context: " + ", ".join(missing)
    return None


# --------------------------------------------------------------------------- #
# approval.request
# --------------------------------------------------------------------------- #

class ApprovalRequestInput(BaseModel):
    approval_type: str = Field(..., description="e.g. spend, account_setup, live_release, banking")
    action_description: str = Field(..., description="What action needs approval")
    action_details: Dict[str, Any] = Field(default_factory=dict)
    richard_input_type: str = Field("approval", description="approval|password|payment|signature|...")
    requires_direct_input: bool = Field(False, description="Richard must enter a value directly")
    input_prompt: Optional[str] = Field(None, description="Prompt shown to Richard")


class ApprovalRefOutput(BaseModel):
    persisted: bool
    approval_id: Optional[str] = None
    status: Optional[str] = None
    blocked: Optional[bool] = None
    reason: Optional[str] = None


class ApprovalRequestTool(ToolBase):
    """Persist a real pending BoundaryApproval (requires DB session, user, session)."""

    @property
    def name(self) -> str:
        return "approval.request"

    @property
    def description(self) -> str:
        return ("Create a pending approval request (BoundaryApproval). Requires a real DB session, "
                "the requesting user id and the session id.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ApprovalRequestInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ApprovalRefOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def category(self) -> str:
        return "approval"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        reason = _missing(context, need_user=True, need_session=True)
        if reason:
            return self.create_result(
                success=False,
                result_data={"persisted": False, "blocked": True, "reason": reason},
                output_text=f"NOT PERSISTED: {reason}",
            )
        from app.models.boundary import BoundaryApproval
        session = context.db_session
        try:
            approval = BoundaryApproval(
                user_id=context.user_id,
                session_id=context.session_id,
                approval_type=input_data["approval_type"],
                action_description=input_data["action_description"],
                action_details=input_data.get("action_details") or {},
                richard_input_type=input_data["richard_input_type"],
                requires_direct_input=bool(input_data["requires_direct_input"]),
                input_prompt=input_data.get("input_prompt"),
                status="pending",
                approved=None,
            )
            session.add(approval)
            await session.commit()
            await session.refresh(approval)
            return self.create_result(
                success=True,
                result_data={"persisted": True, "approval_id": str(approval.id),
                             "status": approval.status},
                output_text=f"Approval {approval.id} requested (pending).",
            )
        except Exception as e:  # noqa: BLE001
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return self.create_result(
                success=False, result_data={"persisted": False, "reason": f"persistence failed: {e}"},
                error_message=str(e), output_text="NOT PERSISTED: database error",
            )


# --------------------------------------------------------------------------- #
# approval.status
# --------------------------------------------------------------------------- #

class ApprovalStatusInput(BaseModel):
    approval_id: str = Field(..., description="BoundaryApproval id (UUID)")


class ApprovalStatusOutput(BaseModel):
    found: bool
    approval: Optional[Dict[str, Any]] = None


class ApprovalStatusTool(ToolBase):
    """Read persisted approval state. Missing -> truthful not-found."""

    @property
    def name(self) -> str:
        return "approval.status"

    @property
    def description(self) -> str:
        return "Read the persisted status of an approval by id; found=false if it does not exist."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ApprovalStatusInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ApprovalStatusOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "approval"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if getattr(context, "db_session", None) is None:
            return self.create_result(
                success=False,
                result_data={"found": False, "reason": "missing required persistence context: db_session"},
                output_text="NO DB SESSION",
            )
        from app.models.boundary import BoundaryApproval
        session = context.db_session
        try:
            aid = UUID(str(input_data["approval_id"]))
        except Exception:
            return self.create_result(success=True, result_data={"found": False, "reason": "invalid approval_id"},
                                      output_text="invalid approval_id")
        row = (await session.execute(
            select(BoundaryApproval).where(BoundaryApproval.id == aid))).scalar_one_or_none()
        if row is None:
            return self.create_result(success=True, result_data={"found": False},
                                      output_text=f"Approval {aid} not found.")
        return self.create_result(
            success=True,
            result_data={"found": True, "approval": {
                "id": str(row.id), "status": row.status, "approved": row.approved,
                "approval_type": row.approval_type,
                "approved_at": row.approved_at.isoformat() if row.approved_at else None,
                "response_message": row.response_message,
                "decided_by": (row.meta_data or {}).get("decided_by"),
            }},
            output_text=f"Approval {aid} status={row.status}.",
        )


# --------------------------------------------------------------------------- #
# approval.list_pending
# --------------------------------------------------------------------------- #

class ApprovalListPendingInput(BaseModel):
    session_id: Optional[str] = Field(None, description="Filter by session id")
    user_id: Optional[str] = Field(None, description="Filter by user id")
    limit: int = Field(50, ge=1, le=500)


class ApprovalListPendingOutput(BaseModel):
    count: int
    approvals: List[Dict[str, Any]]


class ApprovalListPendingTool(ToolBase):
    """List real pending approvals. Empty -> truthful empty list."""

    @property
    def name(self) -> str:
        return "approval.list_pending"

    @property
    def description(self) -> str:
        return "List pending approvals from the database, optionally filtered by session or user."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ApprovalListPendingInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ApprovalListPendingOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "approval"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if getattr(context, "db_session", None) is None:
            return self.create_result(
                success=False,
                result_data={"count": 0, "approvals": [],
                             "reason": "missing required persistence context: db_session"},
                output_text="NO DB SESSION",
            )
        from app.models.boundary import BoundaryApproval
        session = context.db_session
        q = select(BoundaryApproval).where(BoundaryApproval.status == "pending")
        if input_data.get("session_id"):
            try:
                q = q.where(BoundaryApproval.session_id == UUID(str(input_data["session_id"])))
            except Exception:
                pass
        if input_data.get("user_id"):
            try:
                q = q.where(BoundaryApproval.user_id == UUID(str(input_data["user_id"])))
            except Exception:
                pass
        q = q.order_by(BoundaryApproval.created_at.desc()).limit(int(input_data.get("limit", 50)))
        rows = (await session.execute(q)).scalars().all()
        approvals = [{"id": str(r.id), "approval_type": r.approval_type,
                      "action_description": r.action_description, "status": r.status}
                     for r in rows]
        return self.create_result(success=True, result_data={"count": len(approvals), "approvals": approvals},
                                  output_text=f"{len(approvals)} pending approval(s).")


# --------------------------------------------------------------------------- #
# approval.grant / approval.reject (shared decision logic)
# --------------------------------------------------------------------------- #

class ApprovalDecisionInput(BaseModel):
    approval_id: str = Field(..., description="BoundaryApproval id (UUID)")
    decided_by: str = Field(..., description="User id of the authorised decider (UUID)")
    authorized: bool = Field(False, description="Must be explicitly True to authorise the decision")
    response_message: Optional[str] = Field(None, description="Decision note")
    richard_input_value: Optional[str] = Field(None, description="Value entered by Richard, if any")


class ApprovalDecisionOutput(BaseModel):
    decided: bool
    approval_id: Optional[str] = None
    status: Optional[str] = None
    blocked: Optional[bool] = None
    reason: Optional[str] = None
    already_decided: Optional[bool] = None


async def _decide(tool: ToolBase, input_data: Dict[str, Any], context: ToolContext,
                  *, approve: bool) -> ToolResult:
    # Explicit authorised decision context is REQUIRED. No silent/default approval.
    if not input_data.get("authorized") or not input_data.get("decided_by"):
        reason = ("explicit authorised decision context required: both 'authorized=true' and a "
                  "'decided_by' user id must be supplied. Approval is never inferred or defaulted.")
        return tool.create_result(
            success=False,
            result_data={"decided": False, "blocked": True, "reason": reason},
            output_text=f"BLOCKED: {reason}",
        )
    if getattr(context, "db_session", None) is None:
        return tool.create_result(
            success=False,
            result_data={"decided": False, "reason": "missing required persistence context: db_session"},
            output_text="NO DB SESSION: cannot persist decision",
        )
    from app.models.boundary import BoundaryApproval
    session = context.db_session
    try:
        aid = UUID(str(input_data["approval_id"]))
    except Exception:
        return tool.create_result(success=True, result_data={"decided": False, "reason": "invalid approval_id"},
                                  output_text="invalid approval_id")
    row = (await session.execute(
        select(BoundaryApproval).where(BoundaryApproval.id == aid))).scalar_one_or_none()
    if row is None:
        return tool.create_result(success=True, result_data={"decided": False, "reason": "approval not found"},
                                  output_text=f"Approval {aid} not found.")

    # Idempotent: a previously-decided approval is not silently overwritten.
    if row.status in ("approved", "rejected") or row.approved is not None:
        return tool.create_result(
            success=True,
            result_data={"decided": False, "already_decided": True, "approval_id": str(row.id),
                         "status": row.status, "reason": "approval already decided"},
            output_text=f"Approval {aid} already {row.status}.",
        )

    try:
        row.approved = bool(approve)
        row.status = "approved" if approve else "rejected"
        row.approved_at = datetime.utcnow()
        row.response_message = input_data.get("response_message")
        if input_data.get("richard_input_value") is not None:
            row.richard_input_value = str(input_data["richard_input_value"])
        meta = dict(row.meta_data or {})
        meta["decided_by"] = str(input_data["decided_by"])
        meta["decided_at"] = row.approved_at.isoformat()
        meta["decision"] = row.status
        row.meta_data = meta
        await session.commit()
        await session.refresh(row)
        return tool.create_result(
            success=True,
            result_data={"decided": True, "approval_id": str(row.id), "status": row.status,
                         "decided_by": meta["decided_by"]},
            output_text=f"Approval {aid} {row.status} by {meta['decided_by']}.",
        )
    except Exception as e:  # noqa: BLE001
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return tool.create_result(success=False, result_data={"decided": False, "reason": f"persistence failed: {e}"},
                                  error_message=str(e), output_text="DECISION NOT PERSISTED: database error")


class ApprovalGrantTool(ToolBase):
    """Record an approval decision. Requires explicit authorised decision context."""

    @property
    def name(self) -> str:
        return "approval.grant"

    @property
    def description(self) -> str:
        return ("Grant a pending approval. Requires authorized=true and a decided_by user id; "
                "persists who decided and when. No silent or default approval.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ApprovalDecisionInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ApprovalDecisionOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def category(self) -> str:
        return "approval"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        return await _decide(self, input_data, context, approve=True)


class ApprovalRejectTool(ToolBase):
    """Record a rejection decision. Requires explicit authorised decision context."""

    @property
    def name(self) -> str:
        return "approval.reject"

    @property
    def description(self) -> str:
        return ("Reject a pending approval. Requires authorized=true and a decided_by user id; "
                "persists who decided and when. No silent or default rejection.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ApprovalDecisionInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ApprovalDecisionOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def category(self) -> str:
        return "approval"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        return await _decide(self, input_data, context, approve=False)
