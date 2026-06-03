"""
JARV Backend - Tool Use Model

Tool usage tracking and execution history.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class ToolUse(Base, UUIDMixin, TimestampMixin):
    """Tool use model for tracking tool executions"""

    __tablename__ = "tool_uses"

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

    # Tool information
    tool_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    tool_group: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    tool_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Execution
    input_params: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
        index=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="tool_uses")
    session: Mapped[Optional["AgentSession"]] = relationship("AgentSession")
    approval: Mapped[Optional["Approval"]] = relationship("Approval")

    def __repr__(self) -> str:
        return f"<ToolUse(id={self.id}, tool={self.tool_name}, status={self.status})>"
