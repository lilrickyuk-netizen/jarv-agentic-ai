"""Source documentation for the specialist agents: one row per source, its text split into searchable passages.

A source is official documentation an expert in the field would look things up in. Its text is kept only when its
licence allows that (``licence_class == "store"``); a ``link_only`` source is listed and found by its title, and its
text is read live when an agent needs it. Every version of a passage is kept; a re-fetched source with different text
gets a new version and the old passages go inactive. Passages carry the model id of their embedding, so vectors from
different models are never compared.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (JSON, Boolean, Computed, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

LICENCE_STORE = "store"
LICENCE_LINK_ONLY = "link_only"


class KnowledgeSource(Base, UUIDMixin, TimestampMixin):
    """One documentation source and the agents that use it."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (UniqueConstraint("url", "workspace_id", name="uq_knowledge_sources_url_workspace"),)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    licence: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    licence_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    licence_class: Mapped[str] = mapped_column(String(20), nullable=False, default=LICENCE_LINK_ONLY)
    agents: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class KnowledgeChunk(Base, UUIDMixin, TimestampMixin):
    """One passage of a source, under its heading path, with its embedding and full-text vector."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        Index("ix_knowledge_chunks_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_knowledge_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_knowledge_chunks_source_active", "source_id", "is_active"),
    )

    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heading_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[Optional[List[float]]] = mapped_column(Vector(1536), nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    tsv: Mapped[Optional[str]] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(heading_path, '') || ' ' || content)", persisted=True),
        nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
