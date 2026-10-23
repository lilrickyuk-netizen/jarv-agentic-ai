"""Repair 10: persisted API credentials and webhook registrations.

Revision ID: r10_api_integrations
Revises: r10_approval_expiry
Create Date: 2026-10-20 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "r10_api_integrations"
down_revision = "r10_approval_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_credentials",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("service_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_credentials_owner_id", "api_credentials", ["owner_id"])
    op.create_index("ix_api_credentials_workspace_id", "api_credentials", ["workspace_id"])
    op.create_index("ix_api_credentials_agent_id", "api_credentials", ["agent_id"])
    op.create_index("ix_api_credentials_service_name", "api_credentials", ["service_name"])
    op.create_index("ix_api_credentials_is_active", "api_credentials", ["is_active"])

    op.create_table(
        "webhook_endpoints",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("secret_hash", sa.String(64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_endpoints_owner_id", "webhook_endpoints", ["owner_id"])
    op.create_index("ix_webhook_endpoints_workspace_id", "webhook_endpoints", ["workspace_id"])
    op.create_index("ix_webhook_endpoints_agent_id", "webhook_endpoints", ["agent_id"])
    op.create_index("ix_webhook_endpoints_is_active", "webhook_endpoints", ["is_active"])


def downgrade() -> None:
    op.drop_index("ix_webhook_endpoints_is_active", table_name="webhook_endpoints")
    op.drop_index("ix_webhook_endpoints_agent_id", table_name="webhook_endpoints")
    op.drop_index("ix_webhook_endpoints_workspace_id", table_name="webhook_endpoints")
    op.drop_index("ix_webhook_endpoints_owner_id", table_name="webhook_endpoints")
    op.drop_table("webhook_endpoints")
    op.drop_index("ix_api_credentials_is_active", table_name="api_credentials")
    op.drop_index("ix_api_credentials_service_name", table_name="api_credentials")
    op.drop_index("ix_api_credentials_agent_id", table_name="api_credentials")
    op.drop_index("ix_api_credentials_workspace_id", table_name="api_credentials")
    op.drop_index("ix_api_credentials_owner_id", table_name="api_credentials")
    op.drop_table("api_credentials")