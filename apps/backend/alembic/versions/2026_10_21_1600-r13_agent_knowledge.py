"""Add source-attributed, versioned specialist knowledge.

Revision ID: r13_agent_knowledge
Revises: r10_local_crm
Create Date: 2026-10-21 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "r13_agent_knowledge"
down_revision = "r10_local_crm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_knowledge",
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("knowledge_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_title", sa.String(500), nullable=False),
        sa.Column("source_publisher", sa.String(200), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("previous_version_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["previous_version_id"], ["agent_knowledge.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_name", "knowledge_key", "version",
                            name="uq_agent_knowledge_version"),
    )
    op.create_index("ix_agent_knowledge_agent_name", "agent_knowledge", ["agent_name"])
    op.create_index("ix_agent_knowledge_is_active", "agent_knowledge", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_agent_knowledge_is_active", table_name="agent_knowledge")
    op.drop_index("ix_agent_knowledge_agent_name", table_name="agent_knowledge")
    op.drop_table("agent_knowledge")