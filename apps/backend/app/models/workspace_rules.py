"""
JARV Backend - Workspace Rules Models

Workspace rules and runbooks for workspace-specific behavior.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class WorkspaceRule(Base, UUIDMixin, TimestampMixin):
    """Workspace rule model for workspace-specific rules"""

    __tablename__ = "workspace_rules"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Rule information
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    rule_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Rule content
    rule_content: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    conditions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    actions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # Versioning
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Metadata
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship("User")
    versions: Mapped[List["WorkspaceRuleVersion"]] = relationship(
        "WorkspaceRuleVersion",
        back_populates="rule",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<WorkspaceRule(id={self.id}, name={self.rule_name}, type={self.rule_type})>"


class WorkspaceRuleVersion(Base, UUIDMixin, TimestampMixin):
    """Workspace rule version model for rule versioning"""

    __tablename__ = "workspace_rule_versions"

    # Rule
    rule_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspace_rules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Version information
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Rule content snapshot
    rule_content: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    conditions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    actions: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Change tracking
    changed_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    rule: Mapped["WorkspaceRule"] = relationship(
        "WorkspaceRule",
        back_populates="versions",
    )
    changed_by_user: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<WorkspaceRuleVersion(id={self.id}, rule_id={self.rule_id}, version={self.version_number})>"


class WorkspaceRunbook(Base, UUIDMixin, TimestampMixin):
    """Workspace runbook model for workspace-specific procedures"""

    __tablename__ = "workspace_runbooks"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Runbook information
    runbook_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    runbook_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Content
    steps: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    triggers: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Usage statistics
    execution_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<WorkspaceRunbook(id={self.id}, name={self.runbook_name})>"


class WorkspaceScan(Base, UUIDMixin, TimestampMixin):
    """Workspace scan model for workspace health and analysis"""

    __tablename__ = "workspace_scans"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Scan information
    scan_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scan_status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Scan results
    findings: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSON,
        nullable=True,
    )
    issues: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    recommendations: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Metrics
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    triggered_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    triggered_by_user: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<WorkspaceScan(id={self.id}, type={self.scan_type}, status={self.scan_status})>"
