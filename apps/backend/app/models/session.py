"""
JARV Backend - Agent Session Model

Agent execution sessions with state, checkpoints, and resume capability.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentSession(Base, UUIDMixin, TimestampMixin):
    """Agent session model for tracking agent execution sessions"""

    __tablename__ = "agent_sessions"

    # Basic information
    session_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    session_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="standard",
        index=True,
    )

    # References
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        index=True,
    )
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_resumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    paused_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Execution state
    current_step: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    execution_stack: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSON,
        nullable=True,
    )
    variables: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Messages and logs
    messages: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    execution_logs: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # Metrics
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_api_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tool_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Context
    initial_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="sessions")
    agent: Mapped["Agent"] = relationship("Agent", back_populates="sessions")
    checkpoints: Mapped[List["CheckpointState"]] = relationship(
        "CheckpointState",
        back_populates="session",
        cascade="all, delete-orphan",
    )
    approvals: Mapped[List["Approval"]] = relationship(
        "Approval",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AgentSession(id={self.id}, agent_id={self.agent_id}, status={self.status})>"


class CheckpointState(Base, UUIDMixin, TimestampMixin):
    """Checkpoint state for session resume functionality"""

    __tablename__ = "checkpoint_states"

    # Session
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Checkpoint information
    checkpoint_name: Mapped[str] = mapped_column(String(255), nullable=False)
    checkpoint_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="manual",
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # State snapshot
    execution_state: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    variables: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    message_history: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
    )

    # Metrics at checkpoint
    tokens_used_at_checkpoint: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    api_calls_at_checkpoint: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # Resume tracking
    was_resumed_from: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    resumed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    session: Mapped["AgentSession"] = relationship(
        "AgentSession",
        back_populates="checkpoints",
    )

    def __repr__(self) -> str:
        return f"<CheckpointState(id={self.id}, name={self.checkpoint_name}, session_id={self.session_id})>"
