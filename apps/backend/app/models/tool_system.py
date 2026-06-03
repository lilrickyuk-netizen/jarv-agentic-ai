"""
JARV Backend - Tool System Models

Tool registry, tool runs, and tool selection rules.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from decimal import Decimal

from app.models.base import Base, TimestampMixin, UUIDMixin


class Tool(Base, UUIDMixin, TimestampMixin):
    """Tool model for tool registry"""

    __tablename__ = "tools"

    # Tool information
    tool_name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    tool_group: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tool_version: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Configuration
    config_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_schema: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Authority requirements
    minimum_authority_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_dangerous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Usage statistics
    total_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    average_duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Metadata
    documentation_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    runs: Mapped[List["ToolRun"]] = relationship(
        "ToolRun",
        back_populates="tool",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Tool(id={self.id}, name={self.tool_name}, group={self.tool_group})>"


class ToolRun(Base, UUIDMixin, TimestampMixin):
    """Tool run model for tool execution tracking"""

    __tablename__ = "tool_runs"

    # Tool
    tool_id: Mapped[UUID] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Agent and session
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Execution
    input_params: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

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
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Authority
    authority_level_used: Mapped[int] = mapped_column(Integer, nullable=False)
    required_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    approval_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("approvals.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cost tracking
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=6),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    tool: Mapped["Tool"] = relationship("Tool", back_populates="runs")
    agent: Mapped["Agent"] = relationship("Agent")
    session: Mapped[Optional["AgentSession"]] = relationship("AgentSession")
    approval: Mapped[Optional["Approval"]] = relationship("Approval")

    def __repr__(self) -> str:
        return f"<ToolRun(id={self.id}, tool_id={self.tool_id}, status={self.status})>"


class ToolSelectionRule(Base, UUIDMixin, TimestampMixin):
    """Tool selection rule model for automatic tool selection"""

    __tablename__ = "tool_selection_rules"

    # Workspace
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Agent (if agent-specific)
    agent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Rule information
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Rule logic
    conditions: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    recommended_tools: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    blocked_tools: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    # Priority
    priority: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Usage statistics
    times_applied: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Metadata
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    agent: Mapped[Optional["Agent"]] = relationship("Agent")
    creator: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<ToolSelectionRule(id={self.id}, name={self.rule_name}, type={self.rule_type})>"
