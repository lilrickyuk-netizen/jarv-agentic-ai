"""Versioned, source-attributed knowledge assigned to lead agents."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AgentKnowledge(Base, UUIDMixin, TimestampMixin):
    """One immutable version of verified specialist knowledge."""

    __tablename__ = "agent_knowledge"
    __table_args__ = (
        UniqueConstraint("agent_name", "knowledge_key", "version",
                         name="uq_agent_knowledge_version"),
    )

    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    knowledge_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    source_license: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_author_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    previous_version_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_knowledge.id", ondelete="SET NULL"),
        nullable=True,
    )