"""Workflows and councils: workflow_runs, one row per chain of missions run on LangGraph.

Revision ID: r19_workflow_runs
Revises: r18_sales_prospecting
Create Date: 2026-11-10 13:00:00.000000

A workflow run is a chain of missions done by a council of specialists, with Richard's approval gates between them.
LangGraph's Postgres checkpointer keeps the graph's own state in its tables (created by its setup, on first use);
this table is what the dashboard, the voice and the scheduler read.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "r19_workflow_runs"
down_revision = "r18_sales_prospecting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("template", sa.String(60), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("product", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("current_step", sa.String(60), nullable=True),
        sa.Column("waiting_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("stopped_reason", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("workspace_id", "user_id", "template", "status", "waiting_task_id", "created_at"):
        op.create_index(f"ix_workflow_runs_{column}", "workflow_runs", [column])


def downgrade() -> None:
    for column in ("workspace_id", "user_id", "template", "status", "waiting_task_id", "created_at"):
        op.drop_index(f"ix_workflow_runs_{column}", table_name="workflow_runs")
    op.drop_table("workflow_runs")
