"""
JARV Backend - Self Evolution Models

Experience records, self-evolution tracking, and verification results.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class ExperienceRecord(Base, UUIDMixin, TimestampMixin):
    """Experience record model for agent learning from experience"""

    __tablename__ = "experience_records"

    # Agent
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Context
    session_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Experience information
    experience_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Situation-Action-Result
    situation: Mapped[str] = mapped_column(Text, nullable=False)
    action_taken: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)

    # Learning
    lesson_learned: Mapped[str] = mapped_column(Text, nullable=False)
    applicable_contexts: Mapped[List[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    # Application
    times_applied: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Status
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent")
    session: Mapped[Optional["AgentSession"]] = relationship("AgentSession")
    task: Mapped[Optional["Task"]] = relationship("Task")

    def __repr__(self) -> str:
        return f"<ExperienceRecord(id={self.id}, type={self.experience_type}, outcome={self.outcome})>"


class SelfEvolutionRecord(Base, UUIDMixin, TimestampMixin):
    """Self evolution record model for tracking agent self-improvement"""

    __tablename__ = "self_evolution_records"

    # Agent
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Evolution information
    evolution_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Changes
    previous_state: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    new_state: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    changes: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    # Reason
    trigger: Mapped[str] = mapped_column(String(100), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    expected_benefit: Mapped[str] = mapped_column(Text, nullable=False)

    # Verification
    requires_verification: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    verification_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
    )

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="proposed")
    is_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Impact assessment
    actual_benefit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    performance_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_successful: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Rollback
    is_rolled_back: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rollback_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent")
    verification: Mapped[Optional["VerificationResult"]] = relationship(
        "VerificationResult",
        back_populates="evolution_record",
        uselist=False,
    )

    def __repr__(self) -> str:
        return f"<SelfEvolutionRecord(id={self.id}, type={self.evolution_type}, status={self.status})>"


class VerificationResult(Base, UUIDMixin, TimestampMixin):
    """Verification result model for verifying self-evolution changes"""

    __tablename__ = "verification_results"

    # Evolution record
    evolution_record_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("self_evolution_records.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Verification information
    verification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    verifier: Mapped[str] = mapped_column(String(100), nullable=False)

    # Tests
    tests_run: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    tests_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tests_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Results
    overall_status: Mapped[str] = mapped_column(String(50), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Details
    findings: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    issues: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    warnings: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    # Recommendations
    recommendation: Mapped[str] = mapped_column(String(50), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)

    # Timing
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    evolution_record: Mapped[Optional["SelfEvolutionRecord"]] = relationship(
        "SelfEvolutionRecord",
        foreign_keys=[evolution_record_id],
        back_populates="verification",
    )

    def __repr__(self) -> str:
        return f"<VerificationResult(id={self.id}, status={self.overall_status}, passed={self.passed})>"
