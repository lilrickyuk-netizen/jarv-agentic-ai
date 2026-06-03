"""
JARV Backend - Workspace Model

Dynamic project workspaces with configuration and state.
"""
from typing import List, Optional, Dict, Any
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class Workspace(Base, UUIDMixin, TimestampMixin):
    """Workspace model for dynamic project environments"""

    __tablename__ = "workspaces"

    # Basic information
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    # Owner
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Configuration
    workspace_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="general",
        index=True,
    )
    authority_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )
    config: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    # Swarm settings
    max_subagents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50,
    )
    active_subagent_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    # Features enabled
    swarm_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    self_evolution_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    company_mode_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Company operating layer
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company_mission: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_structure: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Statistics
    total_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="workspaces")
    agents: Mapped[List["Agent"]] = relationship(
        "Agent",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    tasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[List["AgentSession"]] = relationship(
        "AgentSession",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    company_roles: Mapped[List["CompanyRole"]] = relationship(
        "CompanyRole",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Workspace(id={self.id}, name={self.name}, type={self.workspace_type})>"
