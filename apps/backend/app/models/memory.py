"""
JARV Backend - Memory Model

Agent memory storage with vector embeddings for semantic search.
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

from app.models.base import Base, TimestampMixin, UUIDMixin


class Memory(Base, UUIDMixin, TimestampMixin):
    """Memory model for agent memory storage with vector embeddings"""

    __tablename__ = "memories"

    # Agent
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Memory content
    memory_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Vector embedding (1536 dimensions for OpenAI embeddings)
    embedding: Mapped[Optional[Vector]] = mapped_column(
        Vector(1536),
        nullable=True,
    )

    # Importance and relevance
    importance_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        index=True,
    )
    access_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Expiration
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    is_permanent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="memories")
    session: Mapped[Optional["AgentSession"]] = relationship("AgentSession")
    task: Mapped[Optional["Task"]] = relationship("Task")

    # Indexes for vector similarity search
    __table_args__ = (
        Index(
            "ix_memories_embedding_ivfflat",
            embedding,
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<Memory(id={self.id}, type={self.memory_type}, agent_id={self.agent_id})>"
