"""
JARV Backend - Approval Model

Approval requests for Richard Boundary Operator actions.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class Approval(Base, UUIDMixin, TimestampMixin):
    """Approval model for Richard Boundary Operator actions"""

    __tablename__ = "approvals"

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

    # Approval request
    approval_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    action_details: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Authority level required
    authority_level_required: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )

    # Response
    approved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    response_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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
    execution_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timeout
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    is_expired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="approvals")
    session: Mapped["AgentSession"] = relationship(
        "AgentSession",
        back_populates="approvals",
    )

    def __repr__(self) -> str:
        return f"<Approval(id={self.id}, type={self.approval_type}, status={self.status})>"
