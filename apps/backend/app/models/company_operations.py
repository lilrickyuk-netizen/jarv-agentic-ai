"""
JARV Backend - Company Operations Models

AI standups, KPIs, revenue operations, and operational feeds.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime, Date, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from decimal import Decimal

from app.models.base import Base, TimestampMixin, UUIDMixin


class AIStandup(Base, UUIDMixin, TimestampMixin):
    """AI standup model for automated team standups"""

    __tablename__ = "ai_standups"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Agent
    agent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Standup date
    standup_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Standup content
    yesterday_accomplishments: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    today_plans: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    blockers: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    needs_help_with: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Metrics
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_in_progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_planned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Status
    mood: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    agent: Mapped[Optional["Agent"]] = relationship("Agent")

    def __repr__(self) -> str:
        return f"<AIStandup(id={self.id}, date={self.standup_date}, agent_id={self.agent_id})>"


class KPIRecord(Base, UUIDMixin, TimestampMixin):
    """KPI record model for tracking key performance indicators"""

    __tablename__ = "kpi_records"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # KPI information
    kpi_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    kpi_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Value
    value: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=4),
        nullable=False,
    )
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Target
    target_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=20, scale=4),
        nullable=True,
    )
    target_met: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Time period
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="daily",
    )

    # Metadata
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")

    def __repr__(self) -> str:
        return f"<KPIRecord(id={self.id}, name={self.kpi_name}, value={self.value})>"


class RevenueOperation(Base, UUIDMixin, TimestampMixin):
    """Revenue operation model for revenue tracking and management"""

    __tablename__ = "revenue_operations"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Operation information
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    operation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Financial data
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # Details
    customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    product_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")

    def __repr__(self) -> str:
        return f"<RevenueOperation(id={self.id}, type={self.operation_type}, amount={self.amount})>"


class LiveOperationsFeedItem(Base, UUIDMixin, TimestampMixin):
    """Live operations feed item model for real-time operation updates"""

    __tablename__ = "live_operations_feed_items"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Feed item information
    item_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # References
    related_agent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    related_task_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Status
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_action: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Action tracking
    action_taken: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_taken_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    action_taken_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    related_agent: Mapped[Optional["Agent"]] = relationship("Agent")
    related_task: Mapped[Optional["Task"]] = relationship("Task")
    action_by_user: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<LiveOperationsFeedItem(id={self.id}, type={self.item_type}, severity={self.severity})>"


class RiskRegisterItem(Base, UUIDMixin, TimestampMixin):
    """Risk register item model for risk management"""

    __tablename__ = "risk_register_items"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Risk information
    risk_title: Mapped[str] = mapped_column(String(500), nullable=False)
    risk_description: Mapped[str] = mapped_column(Text, nullable=False)
    risk_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Risk assessment
    probability: Mapped[str] = mapped_column(String(50), nullable=False)
    impact: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Mitigation
    mitigation_strategy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mitigation_actions: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    owner_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")
    is_mitigated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Tracking
    identified_date: Mapped[date] = mapped_column(Date, nullable=False)
    review_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    closed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    owner: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<RiskRegisterItem(id={self.id}, title={self.risk_title}, score={self.risk_score})>"


class DecisionLogItem(Base, UUIDMixin, TimestampMixin):
    """Decision log item model for decision tracking"""

    __tablename__ = "decision_log_items"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Decision information
    decision_title: Mapped[str] = mapped_column(String(500), nullable=False)
    decision_description: Mapped[str] = mapped_column(Text, nullable=False)
    decision_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Context
    problem_statement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alternatives_considered: Mapped[Optional[List[str]]] = mapped_column(
        JSON,
        nullable=True,
    )
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Decision details
    decision_made_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Impact
    impact_assessment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stakeholders: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reversed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reversal_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    decided_by: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<DecisionLogItem(id={self.id}, title={self.decision_title})>"
