"""
JARV Backend - Agent Model

Agent instances with configuration, state, and execution history.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class Agent(Base, UUIDMixin, TimestampMixin):
    """Agent model for agent instances in workspaces"""

    __tablename__ = "agents"

    # Basic information
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_subagent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parent_agent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Configuration
    config: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="anthropic",
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="claude-sonnet-4",
    )

    # Authority and permissions
    authority_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )
    allowed_tools: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    blocked_tools: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # State
    current_state: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="idle",
        index=True,
    )
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Statistics
    total_executions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_executions: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failed_executions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Company operating layer
    company_role_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("company_roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="agents")
    parent_agent: Mapped[Optional["Agent"]] = relationship(
        "Agent",
        foreign_keys="[Agent.parent_agent_id]",
        remote_side="[Agent.id]",
        back_populates="subagents",
    )
    subagents: Mapped[List["Agent"]] = relationship(
        "Agent",
        back_populates="parent_agent",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[List["AgentSession"]] = relationship(
        "AgentSession",
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    memories: Mapped[List["Memory"]] = relationship(
        "Memory",
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    tool_uses: Mapped[List["ToolUse"]] = relationship(
        "ToolUse",
        back_populates="agent",
        cascade="all, delete-orphan",
    )
    company_role: Mapped[Optional["CompanyRole"]] = relationship(
        "CompanyRole",
        back_populates="agents",
    )

    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, name={self.name}, type={self.agent_type})>"
