"""
JARV Backend - Agent Strategy Models

Agent strategy versioning and configuration.
"""
from typing import Optional, Dict, Any
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentStrategyVersion(Base, UUIDMixin, TimestampMixin):
    """Agent strategy version model for agent strategy evolution"""

    __tablename__ = "agent_strategy_versions"

    # Agent
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Version information
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Strategy content
    strategy: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Performance metrics
    success_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    average_response_time: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_executions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Change tracking
    changed_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent")
    changed_by_user: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<AgentStrategyVersion(id={self.id}, agent_id={self.agent_id}, version={self.version_number})>"
