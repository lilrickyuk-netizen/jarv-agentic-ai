"""
JARV Backend - Operating Plan Models

Operating plans, daily loops, and execution plans for company operating layer.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class OperatingPlan(Base, UUIDMixin, TimestampMixin):
    """Operating plan model for workspace operating plans"""

    __tablename__ = "operating_plans"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Plan information
    plan_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    plan_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Time period
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Plan content
    objectives: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    strategies: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    milestones: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Progress tracking
    completion_percentage: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    objectives_completed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    objectives_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Metadata
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship("User")
    versions: Mapped[List["OperatingPlanVersion"]] = relationship(
        "OperatingPlanVersion",
        back_populates="plan",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<OperatingPlan(id={self.id}, name={self.plan_name}, status={self.status})>"


class OperatingPlanVersion(Base, UUIDMixin, TimestampMixin):
    """Operating plan version model for plan versioning"""

    __tablename__ = "operating_plan_versions"

    # Plan
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("operating_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Version information
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Plan content snapshot
    objectives: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False)
    strategies: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False)
    milestones: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, nullable=False)

    # Change tracking
    changed_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    change_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    plan: Mapped["OperatingPlan"] = relationship(
        "OperatingPlan",
        back_populates="versions",
    )
    changed_by_user: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<OperatingPlanVersion(id={self.id}, plan_id={self.plan_id}, version={self.version_number})>"


class DailyOperatingLoop(Base, UUIDMixin, TimestampMixin):
    """Daily operating loop model for daily workspace operations"""

    __tablename__ = "daily_operating_loops"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Date
    loop_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    # Activities
    activities: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    completed_activities: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Metrics
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    issues_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blockers: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    # Summary
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    highlights: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    concerns: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")

    def __repr__(self) -> str:
        return f"<DailyOperatingLoop(id={self.id}, date={self.loop_date}, status={self.status})>"


class WeeklyExecutionPlan(Base, UUIDMixin, TimestampMixin):
    """Weekly execution plan model for weekly workspace planning"""

    __tablename__ = "weekly_execution_plans"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Week information
    week_start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    # Plan content
    objectives: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    priorities: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    deliverables: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")

    # Progress tracking
    completion_percentage: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    objectives_completed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Review
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

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
        return f"<WeeklyExecutionPlan(id={self.id}, week={self.week_number}, year={self.year})>"
