"""
JARV Backend - Boundary Tools (real implementations)

Design-aligned boundary tools:
  - boundary.detect                  (detect hard boundaries in real input)
  - boundary.report.create           (persist a BoundaryReport)
  - boundary.report.get              (read one BoundaryReport)
  - boundary.report.list             (list BoundaryReports)
  - boundary.status                  (real boundary/approval state)
  - boundary.recommend_next_action   (derived recommendation, not hardcoded)

All execute through ToolBase.execute. Detection inspects real input. Persistence
uses the DB session carried on the ToolContext; when it is absent the create/list
tools return a truthful blocked result naming the missing requirement rather than
fabricating a record. Missing records return truthful not-found results.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select, func

from app.core.agents.base import AuthorityLevel
from app.core.safety.hard_boundary import detect_hard_boundaries
from app.core.tools.base import ToolBase, ToolContext, ToolResult


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _missing_persistence(context: ToolContext, *, need_agent: bool, need_session: bool,
                         need_user: bool = False) -> Optional[str]:
    """Return a human-readable reason if required persistence inputs are absent."""
    missing: List[str] = []
    if getattr(context, "db_session", None) is None:
        missing.append("db_session")
    if need_agent and getattr(context, "agent_id", None) is None:
        missing.append("agent_id")
    if need_session and getattr(context, "session_id", None) is None:
        missing.append("session_id")
    if need_user and getattr(context, "user_id", None) is None:
        missing.append("user_id")
    if missing:
        return "missing required persistence context: " + ", ".join(missing)
    return None


# --------------------------------------------------------------------------- #
# boundary.detect
# --------------------------------------------------------------------------- #

class BoundaryDetectInput(BaseModel):
    text: Optional[str] = Field(None, description="Free text / mission / instruction to inspect")
    action: Optional[str] = Field(None, description="A specific action description to inspect")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Structured fields to inspect")


class BoundaryDetectOutput(BaseModel):
    detected: List[Dict[str, Any]]
    detected_count: int
    rules_checked: List[str]
    requires_pause: bool
    coverage_limitations: str


class BoundaryDetectTool(ToolBase):
    """Detect Design section 6 hard boundaries in real input (deterministic)."""

    @property
    def name(self) -> str:
        return "boundary.detect"

    @property
    def description(self) -> str:
        return ("Detect hard-boundary signals (Design section 6) in provided text/action/metadata. "
                "Reports which boundary rules were checked, which matched, and coverage limitations.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BoundaryDetectInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BoundaryDetectOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "boundary"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        result = detect_hard_boundaries(
            text=input_data.get("text"),
            action=input_data.get("action"),
            metadata=input_data.get("metadata") or None,
        )
        n = result["detected_count"]
        out = (f"Checked {result['rules_checked_count']} hard-boundary rules; "
               f"{n} matched. requires_pause={result['requires_pause']}.")
        return self.create_result(success=True, result_data=result, output_text=out)


# --------------------------------------------------------------------------- #
# boundary.report.create
# --------------------------------------------------------------------------- #

class BoundaryReportCreateInput(BaseModel):
    boundary_type: str = Field(..., description="Hard-boundary type/key (e.g. delete_production_data)")
    attempted_action: str = Field(..., description="The action that hit the boundary")
    title: Optional[str] = Field(None, description="Short title")
    description: Optional[str] = Field(None, description="Why this is a boundary")
    report_type: str = Field("hard_boundary", description="Report type")
    severity: str = Field("high", description="low|medium|high|critical")
    authority_level_required: int = Field(8, description="Authority level the action needs")
    authority_level_available: int = Field(0, description="Authority level currently available")
    was_blocked: bool = Field(True, description="Whether the blocked action was paused")
    action_taken: str = Field("paused_blocked_action", description="What JARV did")
    context: Dict[str, Any] = Field(default_factory=dict, description="Extra context")


class BoundaryReportRefOutput(BaseModel):
    persisted: bool
    report_id: Optional[str] = None
    blocked: Optional[bool] = None
    reason: Optional[str] = None


class BoundaryReportCreateTool(ToolBase):
    """Persist a real BoundaryReport (requires a DB session, agent_id, session_id)."""

    @property
    def name(self) -> str:
        return "boundary.report.create"

    @property
    def description(self) -> str:
        return ("Create and persist a BoundaryReport for a detected/blocked boundary. "
                "Requires a real DB session plus the executing agent and session ids.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BoundaryReportCreateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BoundaryReportRefOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def category(self) -> str:
        return "boundary"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        reason = _missing_persistence(context, need_agent=True, need_session=True)
        if reason:
            return self.create_result(
                success=False,
                result_data={"persisted": False, "blocked": True, "reason": reason,
                             "recommended_next_action": (
                                 "Invoke this tool through an agent execution context that "
                                 "carries a DB session, agent_id and session_id.")},
                output_text=f"NOT PERSISTED: {reason}",
            )
        from app.models.boundary import BoundaryReport

        session = context.db_session
        try:
            report = BoundaryReport(
                session_id=context.session_id,
                agent_id=context.agent_id,
                report_type=input_data["report_type"],
                severity=input_data["severity"],
                title=input_data.get("title") or input_data["boundary_type"],
                description=input_data.get("description") or input_data["attempted_action"],
                boundary_type=input_data["boundary_type"],
                attempted_action=input_data["attempted_action"],
                authority_level_required=int(input_data["authority_level_required"]),
                authority_level_available=int(input_data["authority_level_available"]),
                context=input_data.get("context") or {},
                was_blocked=bool(input_data["was_blocked"]),
                action_taken=input_data["action_taken"],
                approval_requested=False,
            )
            session.add(report)
            await session.commit()
            await session.refresh(report)
            return self.create_result(
                success=True,
                result_data={"persisted": True, "report_id": str(report.id),
                             "boundary_type": report.boundary_type,
                             "was_blocked": report.was_blocked},
                output_text=f"BoundaryReport {report.id} persisted.",
            )
        except Exception as e:  # noqa: BLE001
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return self.create_result(
                success=False,
                result_data={"persisted": False, "reason": f"persistence failed: {e}"},
                error_message=str(e),
                output_text="NOT PERSISTED: database error",
            )


# --------------------------------------------------------------------------- #
# boundary.report.get
# --------------------------------------------------------------------------- #

class BoundaryReportGetInput(BaseModel):
    report_id: str = Field(..., description="BoundaryReport id (UUID)")


class BoundaryReportGetOutput(BaseModel):
    found: bool
    report: Optional[Dict[str, Any]] = None


class BoundaryReportGetTool(ToolBase):
    """Read one BoundaryReport by id. Missing -> truthful not-found."""

    @property
    def name(self) -> str:
        return "boundary.report.get"

    @property
    def description(self) -> str:
        return "Retrieve a persisted BoundaryReport by id; returns found=false if it does not exist."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BoundaryReportGetInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BoundaryReportGetOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "boundary"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if getattr(context, "db_session", None) is None:
            return self.create_result(
                success=False,
                result_data={"found": False, "reason": "missing required persistence context: db_session"},
                output_text="NO DB SESSION: cannot read boundary reports",
            )
        from app.models.boundary import BoundaryReport
        session = context.db_session
        try:
            rid = UUID(str(input_data["report_id"]))
        except Exception:
            return self.create_result(
                success=True, result_data={"found": False, "reason": "invalid report_id"},
                output_text="invalid report_id",
            )
        row = (await session.execute(
            select(BoundaryReport).where(BoundaryReport.id == rid))).scalar_one_or_none()
        if row is None:
            return self.create_result(success=True, result_data={"found": False},
                                      output_text=f"BoundaryReport {rid} not found.")
        return self.create_result(
            success=True,
            result_data={"found": True, "report": {
                "id": str(row.id), "boundary_type": row.boundary_type,
                "severity": row.severity, "report_type": row.report_type,
                "title": row.title, "was_blocked": row.was_blocked,
                "action_taken": row.action_taken,
                "attempted_action": row.attempted_action,
            }},
            output_text=f"BoundaryReport {rid} found.",
        )


# --------------------------------------------------------------------------- #
# boundary.report.list
# --------------------------------------------------------------------------- #

class BoundaryReportListInput(BaseModel):
    session_id: Optional[str] = Field(None, description="Filter by session id")
    agent_id: Optional[str] = Field(None, description="Filter by agent id")
    limit: int = Field(50, ge=1, le=500)


class BoundaryReportListOutput(BaseModel):
    count: int
    reports: List[Dict[str, Any]]


class BoundaryReportListTool(ToolBase):
    """List BoundaryReports (optionally filtered). Empty -> truthful empty list."""

    @property
    def name(self) -> str:
        return "boundary.report.list"

    @property
    def description(self) -> str:
        return "List persisted BoundaryReports, optionally filtered by session or agent."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BoundaryReportListInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BoundaryReportListOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "boundary"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if getattr(context, "db_session", None) is None:
            return self.create_result(
                success=False,
                result_data={"count": 0, "reports": [],
                             "reason": "missing required persistence context: db_session"},
                output_text="NO DB SESSION: cannot list boundary reports",
            )
        from app.models.boundary import BoundaryReport
        session = context.db_session
        q = select(BoundaryReport)
        if input_data.get("session_id"):
            try:
                q = q.where(BoundaryReport.session_id == UUID(str(input_data["session_id"])))
            except Exception:
                pass
        if input_data.get("agent_id"):
            try:
                q = q.where(BoundaryReport.agent_id == UUID(str(input_data["agent_id"])))
            except Exception:
                pass
        q = q.order_by(BoundaryReport.created_at.desc()).limit(int(input_data.get("limit", 50)))
        rows = (await session.execute(q)).scalars().all()
        reports = [{"id": str(r.id), "boundary_type": r.boundary_type, "severity": r.severity,
                    "was_blocked": r.was_blocked, "action_taken": r.action_taken} for r in rows]
        return self.create_result(
            success=True, result_data={"count": len(reports), "reports": reports},
            output_text=f"{len(reports)} boundary report(s).",
        )


# --------------------------------------------------------------------------- #
# boundary.status
# --------------------------------------------------------------------------- #

class BoundaryStatusInput(BaseModel):
    session_id: Optional[str] = Field(None, description="Scope status to a session id")


class BoundaryStatusOutput(BaseModel):
    persistence_available: bool
    total_reports: int
    blocked_reports: int
    pending_approvals: int


class BoundaryStatusTool(ToolBase):
    """Report real boundary/approval state derived from the database."""

    @property
    def name(self) -> str:
        return "boundary.status"

    @property
    def description(self) -> str:
        return ("Report current boundary state: counts of boundary reports, blocked reports, "
                "and pending approvals, read from real persistence.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BoundaryStatusInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BoundaryStatusOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "boundary"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if getattr(context, "db_session", None) is None:
            return self.create_result(
                success=True,
                result_data={"persistence_available": False, "total_reports": 0,
                             "blocked_reports": 0, "pending_approvals": 0,
                             "note": "no DB session: state is not available, reported as zero"},
                output_text="No DB session: boundary state unavailable.",
            )
        from app.models.boundary import BoundaryReport, BoundaryApproval
        session = context.db_session
        sid = None
        if input_data.get("session_id"):
            try:
                sid = UUID(str(input_data["session_id"]))
            except Exception:
                sid = None

        rq = select(func.count()).select_from(BoundaryReport)
        bq = select(func.count()).select_from(BoundaryReport).where(BoundaryReport.was_blocked.is_(True))
        pq = select(func.count()).select_from(BoundaryApproval).where(BoundaryApproval.status == "pending")
        if sid is not None:
            rq = rq.where(BoundaryReport.session_id == sid)
            bq = bq.where(BoundaryReport.session_id == sid)
            pq = pq.where(BoundaryApproval.session_id == sid)

        total = int((await session.execute(rq)).scalar() or 0)
        blocked = int((await session.execute(bq)).scalar() or 0)
        pending = int((await session.execute(pq)).scalar() or 0)
        return self.create_result(
            success=True,
            result_data={"persistence_available": True, "total_reports": total,
                         "blocked_reports": blocked, "pending_approvals": pending},
            output_text=(f"reports={total} blocked={blocked} pending_approvals={pending}"),
        )


# --------------------------------------------------------------------------- #
# boundary.recommend_next_action
# --------------------------------------------------------------------------- #

class BoundaryRecommendInput(BaseModel):
    text: Optional[str] = Field(None, description="Text/action to inspect for boundaries")
    action: Optional[str] = Field(None, description="Specific action description")
    boundary_type: Optional[str] = Field(None, description="A pre-detected boundary type, if known")
    approval_id: Optional[str] = Field(None, description="Approval id to factor into the recommendation")


class BoundaryRecommendOutput(BaseModel):
    requires_pause: bool
    recommended_next_action: str
    detected: List[Dict[str, Any]]
    based_on: Dict[str, Any]


class BoundaryRecommendNextActionTool(ToolBase):
    """Recommend the next action, derived from detection + current approval state."""

    @property
    def name(self) -> str:
        return "boundary.recommend_next_action"

    @property
    def description(self) -> str:
        return ("Recommend JARV's next action for a potential boundary, derived from real detection "
                "and (if a DB session + approval_id are supplied) the persisted approval state.")

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BoundaryRecommendInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BoundaryRecommendOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_0_READ_ONLY

    @property
    def category(self) -> str:
        return "boundary"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        # Real detection from input (or a supplied boundary_type).
        detection = detect_hard_boundaries(
            text=input_data.get("text"),
            action=input_data.get("action"),
            metadata=None,
        )
        detected = list(detection["detected"])
        explicit_type = input_data.get("boundary_type")
        if explicit_type and not any(d["key"] == explicit_type for d in detected):
            detected.append({"key": explicit_type, "title": explicit_type, "matched_patterns": ["explicit"]})

        requires_pause = len(detected) > 0

        # Factor in real approval state if available.
        approval_state: Optional[str] = None
        approval_id = input_data.get("approval_id")
        if requires_pause and approval_id and getattr(context, "db_session", None) is not None:
            from app.models.boundary import BoundaryApproval
            try:
                aid = UUID(str(approval_id))
                row = (await context.db_session.execute(
                    select(BoundaryApproval).where(BoundaryApproval.id == aid))).scalar_one_or_none()
                if row is not None:
                    approval_state = row.status
            except Exception:  # noqa: BLE001
                approval_state = None

        # Derive recommendation from the detected state (not hardcoded success).
        if not requires_pause:
            rec = "No hard boundary detected in the provided input. Safe to proceed under normal authority checks."
        elif approval_state == "approved":
            rec = ("Boundary previously detected but a matching approval is APPROVED: resume the blocked "
                   "action from the safe checkpoint, then continue the mission.")
        elif approval_state in ("rejected",):
            rec = ("Approval was REJECTED: do not perform the blocked action; record the boundary outcome "
                   "and continue only with safe parallel work.")
        else:
            titles = ", ".join(d["title"] for d in detected)
            rec = (f"Pause ONLY the blocked action ({titles}); create a BoundaryReport, create a Safe "
                   f"Checkpoint, request boundary approval from Richard, and continue safe parallel work "
                   f"while waiting.")

        return self.create_result(
            success=True,
            result_data={
                "requires_pause": requires_pause,
                "recommended_next_action": rec,
                "detected": detected,
                "based_on": {"detection_rules_checked": detection["rules_checked_count"],
                             "approval_state": approval_state,
                             "coverage_limitations": detection["coverage_limitations"]},
            },
            output_text=rec,
        )
