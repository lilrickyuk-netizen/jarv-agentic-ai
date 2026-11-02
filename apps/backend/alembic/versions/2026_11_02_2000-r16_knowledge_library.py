"""Upgrade 1a: source documentation library for the specialist agents; HNSW index for memory search.

Revision ID: r16_knowledge_library
Revises: r12_mission_runtime
Create Date: 2026-11-02 20:00:00.000000

knowledge_sources holds each documentation source (licence, licence class, version, fetch status);
knowledge_chunks holds its passages with a 1536-dimension embedding (HNSW, cosine) and a generated English
full-text vector (GIN). HNSW needs pgvector 0.5.0 or later; JARV's database runs 0.5.1. The memories index
moves from IVFFlat (100 lists built on a near-empty table) to HNSW.
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "r16_knowledge_library"
down_revision = "r12_mission_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("publisher", sa.String(200), nullable=False),
        sa.Column("licence", sa.String(120), nullable=True),
        sa.Column("licence_evidence", sa.Text(), nullable=True),
        sa.Column("licence_class", sa.String(20), nullable=False, server_default="link_only"),
        sa.Column("agents", sa.JSON(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("url", "workspace_id", name="uq_knowledge_sources_url_workspace"),
    )
    op.create_index("ix_knowledge_sources_workspace_id", "knowledge_sources", ["workspace_id"])
    op.create_index("ix_knowledge_sources_created_at", "knowledge_sources", ["created_at"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("heading_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("embedding_model", sa.String(120), nullable=True),
        sa.Column("tsv", postgresql.TSVECTOR(),
                  sa.Computed("to_tsvector('english', coalesce(heading_path, '') || ' ' || content)",
                              persisted=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_knowledge_chunks_embedding_hnsw", "knowledge_chunks", ["embedding"],
                    postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})
    op.create_index("ix_knowledge_chunks_tsv", "knowledge_chunks", ["tsv"], postgresql_using="gin")
    op.create_index("ix_knowledge_chunks_source_active", "knowledge_chunks", ["source_id", "is_active"])
    op.create_index("ix_knowledge_chunks_embedding_model", "knowledge_chunks", ["embedding_model"])
    op.create_index("ix_knowledge_chunks_created_at", "knowledge_chunks", ["created_at"])

    op.drop_index("ix_memories_embedding_ivfflat", table_name="memories")
    op.create_index("ix_memories_embedding_hnsw", "memories", ["embedding"],
                    postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})


def downgrade() -> None:
    op.drop_index("ix_memories_embedding_hnsw", table_name="memories")
    op.create_index("ix_memories_embedding_ivfflat", "memories", ["embedding"], postgresql_using="ivfflat",
                    postgresql_with={"lists": 100}, postgresql_ops={"embedding": "vector_cosine_ops"})
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_sources")
