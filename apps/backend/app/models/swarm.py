"""
JARV Backend - Swarm Models

Swarm management, subagent tracking, and swarm operations.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from decimal import Decimal

from app.models.base import Base, TimestampMixin, UUIDMixin


class SwarmRun(Base, UUIDMixin, TimestampMixin):
    """Swarm run model for swarm execution tracking"""

    __tablename__ = "swarm_runs"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Parent agent
    parent_agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Session
    session_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Swarm information
    swarm_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    swarm_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    # Configuration
    max_subagents: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    actual_subagents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coordination_strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="parallel",
    )

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Results
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metrics
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_api_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=6),
        default=0,
        nullable=False,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    parent_agent: Mapped["Agent"] = relationship("Agent")
    session: Mapped[Optional["AgentSession"]] = relationship("AgentSession")
    subagents: Mapped[List["SubAgent"]] = relationship(
        "SubAgent",
        back_populates="swarm_run",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<SwarmRun(id={self.id}, type={self.swarm_type}, status={self.status})>"


class SubAgent(Base, UUIDMixin, TimestampMixin):
    """SubAgent model for temporary swarm agents"""

    __tablename__ = "subagents"

    # Swarm run
    swarm_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("swarm_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Agent information
    subagent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subagent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    role: Mapped[str] = mapped_column(String(100), nullable=False)
    specialization: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Configuration
    model_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="idle")

    # Execution
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Results
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metrics
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    api_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=6),
        default=0,
        nullable=False,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    swarm_run: Mapped["SwarmRun"] = relationship("SwarmRun", back_populates="subagents")
    tasks: Mapped[List["SubAgentTask"]] = relationship(
        "SubAgentTask",
        back_populates="subagent",
        cascade="all, delete-orphan",
    )
    logs: Mapped[List["SubAgentLog"]] = relationship(
        "SubAgentLog",
        back_populates="subagent",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<SubAgent(id={self.id}, name={self.subagent_name}, role={self.role})>"


class SubAgentTask(Base, UUIDMixin, TimestampMixin):
    """SubAgent task model for subagent task tracking"""

    __tablename__ = "subagent_tasks"

    # SubAgent
    subagent_id: Mapped[UUID] = mapped_column(
        ForeignKey("subagents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Task information
    task_description: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # Execution
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Results
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    subagent: Mapped["SubAgent"] = relationship("SubAgent", back_populates="tasks")

    def __repr__(self) -> str:
        return f"<SubAgentTask(id={self.id}, type={self.task_type}, status={self.status})>"


class SubAgentLog(Base, UUIDMixin, TimestampMixin):
    """SubAgent log model for subagent execution logs"""

    __tablename__ = "subagent_logs"

    # SubAgent
    subagent_id: Mapped[UUID] = mapped_column(
        ForeignKey("subagents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Log information
    log_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    log_message: Mapped[str] = mapped_column(Text, nullable=False)
    log_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Context
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Timestamp
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    # Relationships
    subagent: Mapped["SubAgent"] = relationship("SubAgent", back_populates="logs")

    def __repr__(self) -> str:
        return f"<SubAgentLog(id={self.id}, level={self.log_level}, subagent_id={self.subagent_id})>"


class SwarmCostRecord(Base, UUIDMixin, TimestampMixin):
    """Swarm cost record model for swarm cost tracking"""

    __tablename__ = "swarm_cost_records"

    # Swarm run
    swarm_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("swarm_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Cost breakdown
    model_costs: Mapped[Dict[str, Decimal]] = mapped_column(JSON, nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=6),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # Usage breakdown
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_api_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    total_subagents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    swarm_run: Mapped["SwarmRun"] = relationship("SwarmRun")

    def __repr__(self) -> str:
        return f"<SwarmCostRecord(id={self.id}, total_cost={self.total_cost})>"


class SwarmLimitPolicy(Base, UUIDMixin, TimestampMixin):
    """Swarm limit policy model for swarm resource limits"""

    __tablename__ = "swarm_limit_policies"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Policy information
    policy_name: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Limits
    max_subagents: Mapped[int] = mapped_column(Integer, nullable=False)
    max_concurrent_swarms: Mapped[int] = mapped_column(Integer, nullable=False)
    max_cost_per_swarm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=2),
        nullable=True,
    )
    max_duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Enforcement
    enforcement_level: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="strict",
    )
    violation_action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="terminate",
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
        return f"<SwarmLimitPolicy(id={self.id}, name={self.policy_name})>"
