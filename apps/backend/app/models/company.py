"""
JARV Backend - Company Operating Layer Models

Company roles, departments, and organizational structure.
"""
from typing import Optional, Dict, Any, List
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class CompanyRole(Base, UUIDMixin, TimestampMixin):
    """Company role model for company operating layer"""

    __tablename__ = "company_roles"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Role information
    role_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Hierarchy
    parent_role_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("company_roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Responsibilities
    responsibilities: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    kpis: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    authority_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)

    # Configuration
    config: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    skills_required: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_automated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Statistics
    total_agents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    workspace: Mapped["Workspace"] = relationship(
        "Workspace",
        back_populates="company_roles",
    )
    parent_role: Mapped[Optional["CompanyRole"]] = relationship(
        "CompanyRole",
        foreign_keys="[CompanyRole.parent_role_id]",
        remote_side="[CompanyRole.id]",
        back_populates="child_roles",
    )
    child_roles: Mapped[List["CompanyRole"]] = relationship(
        "CompanyRole",
        back_populates="parent_role",
        cascade="all, delete-orphan",
    )
    agents: Mapped[List["Agent"]] = relationship(
        "Agent",
        back_populates="company_role",
    )

    def __repr__(self) -> str:
        return f"<CompanyRole(id={self.id}, name={self.role_name}, type={self.role_type})>"
