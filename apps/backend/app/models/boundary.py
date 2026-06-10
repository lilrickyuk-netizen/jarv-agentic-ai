"""
JARV Backend - Boundary Models

Richard Boundary Operator models, approval windows, safe checkpoints.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class BoundaryReport(Base, UUIDMixin, TimestampMixin):
    """Boundary report model for boundary violation reporting"""

    __tablename__ = "boundary_reports"

    # Session
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Agent
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relational scope (Repair 9). Workspace/task/mission scope are real FK columns
    # now, not JSON-only. Nullable + SET NULL so historic rows (which carried scope
    # only in `context`) remain valid and so deleting a workspace/task never silently
    # erases boundary decision history (the hard mission ownership cascade is the
    # existing session_id FK above).
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Report information
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Boundary details
    boundary_type: Mapped[str] = mapped_column(String(50), nullable=False)
    attempted_action: Mapped[str] = mapped_column(Text, nullable=False)
    authority_level_required: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_level_available: Mapped[int] = mapped_column(Integer, nullable=False)

    # Context
    context: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    stack_trace: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Response
    was_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    action_taken: Mapped[str] = mapped_column(String(100), nullable=False)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Approval
    approval_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    approval_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_approvals.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    session: Mapped["AgentSession"] = relationship("AgentSession")
    agent: Mapped["Agent"] = relationship("Agent")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    task: Mapped[Optional["Task"]] = relationship("Task")
    created_by_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by]
    )
    # boundary_reports.approval_id -> boundary_approvals is one of TWO FKs between
    # these tables (the other is boundary_approvals.boundary_report_id, added in
    # Repair 9), so foreign_keys must be explicit to disambiguate the mapper.
    approval: Mapped[Optional["BoundaryApproval"]] = relationship(
        "BoundaryApproval", foreign_keys=[approval_id], post_update=True
    )

    def __repr__(self) -> str:
        return f"<BoundaryReport(id={self.id}, type={self.report_type}, severity={self.severity})>"


class BoundaryApproval(Base, UUIDMixin, TimestampMixin):
    """Boundary approval model for Richard Boundary Operator approvals"""

    __tablename__ = "boundary_approvals"

    # User and session
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relational scope (Repair 9). An approval belongs to exactly one BoundaryReport
    # and inherits its workspace/task scope. Nullable + SET NULL for historic rows
    # and to preserve decision history when a report/task/workspace is removed.
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # use_alter breaks the boundary_reports <-> boundary_approvals FK cycle for
    # metadata table-sorting (the reverse FK is boundary_reports.approval_id).
    boundary_report_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_reports.id", ondelete="SET NULL", use_alter=True,
                   name="fk_boundary_approvals_boundary_report_id"),
        nullable=True,
        index=True,
    )
    # The authenticated owner who decided this approval. Bound to the trusted
    # identity in the workflow; never to caller-supplied input.
    decided_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Approval request
    approval_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    action_details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Richard input
    richard_input_type: Mapped[str] = mapped_column(String(50), nullable=False)
    requires_direct_input: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    input_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    approved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Response
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    response_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    richard_input_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Execution
    executed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    execution_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Window
    approval_window_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("approval_windows.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    decided_by_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[decided_by]
    )
    session: Mapped["AgentSession"] = relationship("AgentSession")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    task: Mapped[Optional["Task"]] = relationship("Task")
    boundary_report: Mapped[Optional["BoundaryReport"]] = relationship(
        "BoundaryReport", foreign_keys=[boundary_report_id]
    )
    # boundary_approvals.approval_window_id -> approval_windows is one of TWO FKs
    # between these tables (the other is approval_windows.approval_id, added in
    # Repair 9); foreign_keys must be explicit.
    approval_window: Mapped[Optional["ApprovalWindow"]] = relationship(
        "ApprovalWindow", foreign_keys=[approval_window_id], post_update=True
    )

    def __repr__(self) -> str:
        return f"<BoundaryApproval(id={self.id}, type={self.approval_type}, status={self.status})>"


class ApprovalWindow(Base, UUIDMixin, TimestampMixin):
    """Approval window model for batched approval requests"""

    __tablename__ = "approval_windows"

    # Session
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # User
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relational scope (Repair 9). A window belongs to the approval/decision it
    # authorises and carries the exact workspace/task scope as real columns.
    # use_alter breaks the boundary_approvals <-> approval_windows FK cycle for
    # metadata table-sorting (the reverse FK is boundary_approvals.approval_window_id).
    approval_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_approvals.id", ondelete="SET NULL", use_alter=True,
                   name="fk_approval_windows_approval_id"),
        nullable=True,
        index=True,
    )
    # use_alter also breaks the third leg of the BR->BA->AW->BR cycle.
    boundary_report_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_reports.id", ondelete="SET NULL", use_alter=True,
                   name="fk_approval_windows_boundary_report_id"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Real expiry column (was JSON-only) so scope/expiry can be queried + enforced
    # relationally, not only from meta_data.
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Window information
    window_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    total_approvals: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timing
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    session: Mapped["AgentSession"] = relationship("AgentSession")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    decided_by_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[decided_by]
    )
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    task: Mapped[Optional["Task"]] = relationship("Task")
    boundary_report: Mapped[Optional["BoundaryReport"]] = relationship(
        "BoundaryReport", foreign_keys=[boundary_report_id]
    )
    approval: Mapped[Optional["BoundaryApproval"]] = relationship(
        "BoundaryApproval", foreign_keys=[approval_id], post_update=True
    )

    def __repr__(self) -> str:
        return f"<ApprovalWindow(id={self.id}, type={self.window_type}, status={self.status})>"


class SafeCheckpoint(Base, UUIDMixin, TimestampMixin):
    """Safe checkpoint model for safe state snapshots"""

    __tablename__ = "safe_checkpoints"

    # Session
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relational scope (Repair 9). A checkpoint belongs to one session and
    # optionally one task, and references the boundary/approval it was captured for.
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    boundary_report_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    approval_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_approvals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Checkpoint information
    checkpoint_name: Mapped[str] = mapped_column(String(255), nullable=False)
    checkpoint_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_safe_state: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # State
    state_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    variables: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    message_history: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False)

    # Safety verification
    verification_status: Mapped[str] = mapped_column(String(50), nullable=False)
    safety_checks_passed: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    safety_warnings: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # Resume capability
    can_resume_from: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resume_actions_available: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    session: Mapped["AgentSession"] = relationship("AgentSession")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    task: Mapped[Optional["Task"]] = relationship("Task")
    boundary_report: Mapped[Optional["BoundaryReport"]] = relationship(
        "BoundaryReport", foreign_keys=[boundary_report_id]
    )
    approval: Mapped[Optional["BoundaryApproval"]] = relationship(
        "BoundaryApproval", foreign_keys=[approval_id]
    )

    def __repr__(self) -> str:
        return f"<SafeCheckpoint(id={self.id}, name={self.checkpoint_name}, safe={self.is_safe_state})>"


class ResumeAction(Base, UUIDMixin, TimestampMixin):
    """Resume action model for tracking resume actions"""

    __tablename__ = "resume_actions"

    # Session
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Checkpoint
    checkpoint_id: Mapped[UUID] = mapped_column(
        ForeignKey("safe_checkpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relational scope (Repair 9). A resume action references the approval that
    # authorised it and the boundary/workspace/task it resumed.
    approval_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_approvals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    boundary_report_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Action information
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    action_details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Execution
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    executed_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Result
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    session: Mapped["AgentSession"] = relationship("AgentSession")
    checkpoint: Mapped["SafeCheckpoint"] = relationship("SafeCheckpoint")
    executed_by_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[executed_by]
    )
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    task: Mapped[Optional["Task"]] = relationship("Task")
    approval: Mapped[Optional["BoundaryApproval"]] = relationship(
        "BoundaryApproval", foreign_keys=[approval_id]
    )
    boundary_report: Mapped[Optional["BoundaryReport"]] = relationship(
        "BoundaryReport", foreign_keys=[boundary_report_id]
    )

    def __repr__(self) -> str:
        return f"<ResumeAction(id={self.id}, type={self.action_type}, success={self.success})>"


class RichardBoundaryInput(Base, UUIDMixin, TimestampMixin):
    """Richard boundary input model for tracking Richard's boundary inputs"""

    __tablename__ = "richard_boundary_inputs"

    # User
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Session
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relational scope (Repair 9). Richard's input belongs to a boundary decision
    # and carries its workspace/task scope as real columns.
    boundary_report_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_reports.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Input information
    input_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    input_category: Mapped[str] = mapped_column(String(50), nullable=False)
    input_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # Value
    input_value: Mapped[str] = mapped_column(Text, nullable=False)
    input_format: Mapped[str] = mapped_column(String(50), nullable=False)

    # Context
    context: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    related_approval_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("boundary_approvals.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Validation
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
    session: Mapped["AgentSession"] = relationship("AgentSession")
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    task: Mapped[Optional["Task"]] = relationship("Task")
    boundary_report: Mapped[Optional["BoundaryReport"]] = relationship(
        "BoundaryReport", foreign_keys=[boundary_report_id]
    )
    related_approval: Mapped[Optional["BoundaryApproval"]] = relationship(
        "BoundaryApproval", foreign_keys=[related_approval_id]
    )

    def __repr__(self) -> str:
        return f"<RichardBoundaryInput(id={self.id}, type={self.input_type})>"
