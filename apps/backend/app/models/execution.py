"""
JARV Backend - Execution Models

Command execution and file change tracking.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class CommandRun(Base, UUIDMixin, TimestampMixin):
    """Command run model for command execution tracking"""

    __tablename__ = "command_runs"

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

    # Command information
    command: Mapped[str] = mapped_column(Text, nullable=False)
    command_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    working_directory: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Environment
    environment_variables: Mapped[Optional[Dict[str, str]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Execution
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

    # Results
    exit_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stdout: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stderr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

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

    # Safety
    is_dangerous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    safety_checks: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent")
    session: Mapped[Optional["AgentSession"]] = relationship("AgentSession")
    approval: Mapped[Optional["Approval"]] = relationship("Approval")

    def __repr__(self) -> str:
        return f"<CommandRun(id={self.id}, type={self.command_type}, success={self.success})>"


class FileChange(Base, UUIDMixin, TimestampMixin):
    """File change model for file modification tracking"""

    __tablename__ = "file_changes"

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

    # File information
    file_path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Change information
    change_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)

    # Content
    previous_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diff: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    file_size_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_size_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lines_added: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lines_removed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

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

    # Execution
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Backup
    backup_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    can_rollback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent")
    session: Mapped[Optional["AgentSession"]] = relationship("AgentSession")
    approval: Mapped[Optional["Approval"]] = relationship("Approval")

    def __repr__(self) -> str:
        return f"<FileChange(id={self.id}, path={self.file_path}, type={self.change_type})>"
