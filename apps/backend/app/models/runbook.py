"""
JARV Backend - Runbook Models

Runbooks and runbook versions for operational procedures.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class Runbook(Base, UUIDMixin, TimestampMixin):
    """Runbook model for operational procedures"""

    __tablename__ = "runbooks"

    # Basic information
    runbook_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    runbook_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Scope
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Content
    steps: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    prerequisites: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    expected_outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Triggers
    trigger_conditions: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSON,
        nullable=True,
    )
    auto_execute: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Usage statistics
    execution_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_duration_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship("User")
    versions: Mapped[List["RunbookVersion"]] = relationship(
        "RunbookVersion",
        back_populates="runbook",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Runbook(id={self.id}, name={self.runbook_name}, type={self.runbook_type})>"


class RunbookVersion(Base, UUIDMixin, TimestampMixin):
    """Runbook version model for runbook versioning"""

    __tablename__ = "runbook_versions"

    # Runbook
    runbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("runbooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Version information
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Content snapshot
    steps: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False)
    prerequisites: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    expected_outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Change tracking
    changed_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changes: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)

    # Verification
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    runbook: Mapped["Runbook"] = relationship("Runbook", back_populates="versions")
    changed_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[changed_by],
    )
    verified_by_user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[verified_by],
    )

    def __repr__(self) -> str:
        return f"<RunbookVersion(id={self.id}, runbook_id={self.runbook_id}, version={self.version_number})>"
