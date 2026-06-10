"""
JARV Backend - Richard Boundary Operator (legacy facade, Repair 9)

History: this module was originally a persistence-less stub (it built Pydantic
objects and persisted nothing). The REAL hard-boundary -> decision -> approval
window -> resume loop now lives in ``app.core.richard.workflow.RichardBoundaryWorkflow``
(persistence) and ``app.core.richard.service.RichardBoundaryService`` (authenticated
queries + ownership isolation), exposed through ``app/api/richard.py``.

To avoid two competing implementations, Repair 9 turns ``RichardOperator`` into a
THIN COMPATIBILITY FACADE: when constructed with a real DB session its decision and
pending-listing methods DELEGATE to the real workflow/service (no second approval or
resume implementation lives here). The light-weight Pydantic models
(``RichardInput`` / ``RichardDecision`` / ``DecisionType``) are retained because the
advisory ``RichardGuidance`` module imports them; they describe guidance requests,
not authoritative boundary decisions.

The advisory ``submit_input`` helper is preserved for guidance but is deprecated for
real boundary decisions — use ``RichardOperator.decide`` (or the API) instead.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum
import logging
import warnings

logger = logging.getLogger(__name__)


class DecisionType(str, Enum):
    """Type of Richard decision"""
    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"
    MODIFY = "modify"
    DEFER = "defer"


class RichardInput(BaseModel):
    """Input for Richard boundary decision (advisory/guidance record)."""
    input_id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    workspace_id: Optional[UUID] = None
    input_type: str = Field(..., description="Type: approval, guidance, escalation, boundary_check")
    situation_description: str
    requested_action: str
    risk_assessment: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    urgency: str = Field(default="normal", description="low, normal, high, critical")
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    submitted_by: Optional[str] = None  # Agent or user name
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RichardDecision(BaseModel):
    """Decision from Richard operator (advisory/guidance record)."""
    decision_id: UUID = Field(default_factory=uuid4)
    input_id: UUID
    decision_type: DecisionType
    decision_text: str
    reasoning: str
    conditions: List[str] = Field(default_factory=list)
    modifications: Dict[str, Any] = Field(default_factory=dict)
    valid_for_hours: Optional[int] = None
    requires_follow_up: bool = False
    decided_at: datetime = Field(default_factory=datetime.utcnow)
    decided_by: Optional[UUID] = None  # Human operator if applicable
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RichardOperator:
    """Thin compatibility facade over the real Repair-8 Richard workflow.

    Construct with a real ``AsyncSession`` (``RichardOperator(db)``) to delegate
    authoritative boundary operations to ``RichardBoundaryWorkflow`` /
    ``RichardBoundaryService``. The no-argument form is retained for the advisory
    ``RichardGuidance`` import and for guidance-only helpers.
    """

    def __init__(self, db: Optional[Any] = None):
        """Initialize Richard operator.

        Args:
            db: Optional AsyncSession. Required for the real (delegating) methods
                ``decide`` and ``list_pending``; advisory helpers work without it.
        """
        self.db = db
        self.logger = logging.getLogger("richard.operator")

    # ------------------------------------------------------------------ #
    # Real, delegating methods (the single source of truth is the workflow)
    # ------------------------------------------------------------------ #

    async def decide(
        self,
        *,
        approval_id: UUID,
        authenticated_user_id: Any,
        approve: bool,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Record an authenticated boundary decision via the REAL workflow.

        Delegates to ``RichardBoundaryWorkflow.record_richard_decision`` so there is
        exactly one decision implementation. ``decided_by`` is bound to the
        authenticated identity inside the workflow, never to caller input.
        """
        if self.db is None:
            raise RuntimeError(
                "RichardOperator.decide requires a DB session; construct "
                "RichardOperator(db) or call the /api/richard endpoints."
            )
        from app.core.richard.workflow import RichardBoundaryWorkflow

        return await RichardBoundaryWorkflow(self.db).record_richard_decision(
            approval_id=approval_id,
            authenticated_user_id=authenticated_user_id,
            approve=approve,
            **kwargs,
        )

    async def list_pending(
        self,
        *,
        authenticated_user_id: Any,
        workspace_id: Optional[UUID] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List real pending boundary decisions via the REAL service layer."""
        if self.db is None:
            raise RuntimeError(
                "RichardOperator.list_pending requires a DB session; construct "
                "RichardOperator(db) or call the /api/richard endpoints."
            )
        from app.core.richard.service import RichardBoundaryService

        return await RichardBoundaryService(self.db).list_pending(
            authenticated_user_id, workspace_id=workspace_id, limit=limit)

    # ------------------------------------------------------------------ #
    # Advisory / guidance helpers (NOT the authoritative decision path)
    # ------------------------------------------------------------------ #

    async def submit_input(
        self,
        user_id: UUID,
        input_type: str,
        situation_description: str,
        requested_action: str,
        workspace_id: Optional[UUID] = None,
        risk_assessment: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        urgency: str = "normal",
        submitted_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RichardInput:
        """Build an advisory guidance-request record.

        DEPRECATED for real boundary decisions: a genuine hard boundary is created
        and decided through ``RichardBoundaryWorkflow`` / the /api/richard API, which
        persist a BoundaryReport + BoundaryApproval. This advisory helper only
        structures a guidance request for ``RichardGuidance``.
        """
        warnings.warn(
            "RichardOperator.submit_input is advisory only; use the real "
            "RichardBoundaryWorkflow / /api/richard endpoints for boundary decisions.",
            DeprecationWarning,
            stacklevel=2,
        )
        return RichardInput(
            user_id=user_id,
            workspace_id=workspace_id,
            input_type=input_type,
            situation_description=situation_description,
            requested_action=requested_action,
            risk_assessment=risk_assessment or {},
            context=context or {},
            urgency=urgency,
            submitted_by=submitted_by,
            metadata=metadata or {},
        )

    async def get_pending_inputs(
        self,
        urgency: Optional[str] = None,
        input_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return real pending boundary decisions when a DB session is available.

        When constructed with a DB session this delegates to the real workflow
        (proving callers reach it); without one it returns an empty advisory list.
        """
        if self.db is None:
            return []
        from app.core.richard.workflow import RichardBoundaryWorkflow

        return await RichardBoundaryWorkflow(self.db).list_pending_decisions(limit=limit)
