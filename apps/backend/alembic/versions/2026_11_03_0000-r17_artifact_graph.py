"""Upgrade 3: the Artifact Intelligence Graph (artifact_nodes, artifact_edges).

Revision ID: r17_artifact_graph
Revises: r16_knowledge_library
Create Date: 2026-11-03 00:00:00.000000

Two plain tables tie each requirement to the files, commands, checks and decisions behind it. A recursive SQL
query walks them; no graph database is needed (Apache AGE is still a release candidate for PostgreSQL 17).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "r17_artifact_graph"
down_revision = "r16_knowledge_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("attrs", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "kind", "key", name="uq_artifact_nodes_workspace_kind_key"),
    )
    op.create_index("ix_artifact_nodes_workspace_id", "artifact_nodes", ["workspace_id"])
    op.create_index("ix_artifact_nodes_kind", "artifact_nodes", ["kind"])
    op.create_index("ix_artifact_nodes_task_id", "artifact_nodes", ["task_id"])
    op.create_index("ix_artifact_nodes_created_at", "artifact_nodes", ["created_at"])

    op.create_table(
        "artifact_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("artifact_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("artifact_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation", sa.String(30), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_id", "target_id", "relation", "task_id", name="uq_artifact_edges_link"),
    )
    op.create_index("ix_artifact_edges_workspace_id", "artifact_edges", ["workspace_id"])
    op.create_index("ix_artifact_edges_source_id", "artifact_edges", ["source_id"])
    op.create_index("ix_artifact_edges_target", "artifact_edges", ["target_id"])
    op.create_index("ix_artifact_edges_relation", "artifact_edges", ["relation"])
    op.create_index("ix_artifact_edges_task_id", "artifact_edges", ["task_id"])
    op.create_index("ix_artifact_edges_created_at", "artifact_edges", ["created_at"])


def downgrade() -> None:
    op.drop_table("artifact_edges")
    op.drop_table("artifact_nodes")
