"""
JARV Backend - Operations Models

Incidents, audit logs, infrastructure, backups, deployments, and authority policies.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from decimal import Decimal

from app.models.base import Base, TimestampMixin, UUIDMixin


class Incident(Base, UUIDMixin, TimestampMixin):
    """Incident model for incident tracking"""

    __tablename__ = "incidents"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Incident information
    incident_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Classification
    severity: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")

    # Impact
    affected_systems: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    affected_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impact_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Assignment
    assigned_to: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_team: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Timeline
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Resolution
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Post-mortem
    post_mortem_completed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    post_mortem_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    assignee: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<Incident(id={self.id}, number={self.incident_number}, severity={self.severity})>"


class AuditLog(Base, UUIDMixin, TimestampMixin):
    """Audit log model for security and compliance auditing"""

    __tablename__ = "audit_logs"

    # Scope
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Actor
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Action
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Target
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    target_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Details
    before_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    after_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    changes: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)

    # Result
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Context
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    session_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Security
    authority_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    required_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Timestamp
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    user: Mapped[Optional["User"]] = relationship("User")
    agent: Mapped[Optional["Agent"]] = relationship("Agent")
    session: Mapped[Optional["AgentSession"]] = relationship("AgentSession")

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, actor={self.actor_type})>"


class InfrastructureResource(Base, UUIDMixin, TimestampMixin):
    """Infrastructure resource model for infrastructure tracking"""

    __tablename__ = "infrastructure_resources"

    # Workspace
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Resource information
    resource_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Provider
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    region: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    zone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Configuration
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    capacity: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    tags_list: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")
    health: Mapped[str] = mapped_column(String(50), nullable=False, default="healthy")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Cost
    hourly_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=6),
        nullable=True,
    )
    monthly_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=2),
        nullable=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # Monitoring
    last_health_check: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    uptime_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Ownership
    managed_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    manager: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<InfrastructureResource(id={self.id}, name={self.resource_name}, type={self.resource_type})>"


class BackupRecord(Base, UUIDMixin, TimestampMixin):
    """Backup record model for backup tracking"""

    __tablename__ = "backup_records"

    # Workspace
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Backup information
    backup_name: Mapped[str] = mapped_column(String(255), nullable=False)
    backup_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Source
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Storage
    storage_location: Mapped[str] = mapped_column(Text, nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    backup_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
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
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Retention
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Verification
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")

    def __repr__(self) -> str:
        return f"<BackupRecord(id={self.id}, name={self.backup_name}, status={self.status})>"


class DeploymentRecord(Base, UUIDMixin, TimestampMixin):
    """Deployment record model for deployment tracking"""

    __tablename__ = "deployment_records"

    # Workspace
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Deployment information
    deployment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    deployment_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    environment: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # Details
    commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    branch: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    changes: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

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
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Actor
    deployed_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    deployed_by_agent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Result
    deployment_logs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Rollback
    can_rollback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rolled_back: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rollback_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    deployer: Mapped[Optional["User"]] = relationship("User")
    deploying_agent: Mapped[Optional["Agent"]] = relationship("Agent")

    def __repr__(self) -> str:
        return f"<DeploymentRecord(id={self.id}, name={self.deployment_name}, status={self.status})>"


class AuthorityPolicy(Base, UUIDMixin, TimestampMixin):
    """Authority policy model for authority level policies"""

    __tablename__ = "authority_policies"

    # Scope
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Policy information
    policy_name: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Rules
    rules: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    default_authority_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )

    # Overrides
    level_overrides: Mapped[Optional[Dict[str, int]]] = mapped_column(JSON, nullable=True)
    approval_requirements: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # Enforcement
    enforcement_mode: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="strict",
    )
    violation_action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="block",
    )

    # Ownership
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<AuthorityPolicy(id={self.id}, name={self.policy_name}, type={self.policy_type})>"

