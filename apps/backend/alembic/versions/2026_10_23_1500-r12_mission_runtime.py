"""Repair 12a: worker lease and heartbeat for queued missions.

Revision ID: r12_mission_runtime
Revises: r11_memory_learning
Create Date: 2026-10-23 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "r12_mission_runtime"
down_revision = "r11_memory_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("lease_owner", sa.String(160), nullable=True))
    op.add_column("tasks", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_heartbeat_at", "tasks", ["heartbeat_at"])
    # Missions written before this revision were marked "approved" by the old
    # approval endpoint and never resumed. Return them to the approval queue so
    # approving them again actually runs them.
    op.execute("UPDATE tasks SET status = 'blocked' WHERE task_type = 'command' AND status = 'approved'")


def downgrade() -> None:
    op.drop_index("ix_tasks_heartbeat_at", table_name="tasks")
    op.drop_column("tasks", "heartbeat_at")
    op.drop_column("tasks", "lease_owner")
