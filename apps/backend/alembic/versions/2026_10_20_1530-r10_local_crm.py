"""Repair 10: persist local workspace-scoped CRM contacts and deals.

Revision ID: r10_local_crm
Revises: r10_api_integrations
Create Date: 2026-10-20 15:30:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "r10_local_crm"
down_revision = "r10_api_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbound_message_drafts",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("channel_type", sa.String(20), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("thread_reference", sa.String(255), nullable=True),
        sa.Column("meta_data", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("owner_id", "workspace_id", "agent_id", "channel_type", "destination", "status"):
        op.create_index(f"ix_outbound_message_drafts_{column}", "outbound_message_drafts", [column])

    op.create_table(
        "calendar_events",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("attendees", sa.JSON(), nullable=False),
        sa.Column("reminders", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("owner_id", "workspace_id", "agent_id", "start_time", "is_active"):
        op.create_index(f"ix_calendar_events_{column}", "calendar_events", [column])

    op.create_table(
        "crm_contacts",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(100), nullable=True),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("owner_id", "workspace_id", "agent_id", "name", "email", "company", "is_active"):
        op.create_index(f"ix_crm_contacts_{column}", "crm_contacts", [column])

    op.create_table(
        "crm_deals",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("stage", sa.String(100), nullable=False, server_default="prospecting"),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["crm_contacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("owner_id", "workspace_id", "agent_id", "contact_id", "title", "stage", "is_active"):
        op.create_index(f"ix_crm_deals_{column}", "crm_deals", [column])


def downgrade() -> None:
    for column in ("status", "destination", "channel_type", "agent_id", "workspace_id", "owner_id"):
        op.drop_index(f"ix_outbound_message_drafts_{column}", table_name="outbound_message_drafts")
    op.drop_table("outbound_message_drafts")
    for column in ("is_active", "start_time", "agent_id", "workspace_id", "owner_id"):
        op.drop_index(f"ix_calendar_events_{column}", table_name="calendar_events")
    op.drop_table("calendar_events")
    for column in ("is_active", "stage", "title", "contact_id", "agent_id", "workspace_id", "owner_id"):
        op.drop_index(f"ix_crm_deals_{column}", table_name="crm_deals")
    op.drop_table("crm_deals")
    for column in ("is_active", "company", "email", "name", "agent_id", "workspace_id", "owner_id"):
        op.drop_index(f"ix_crm_contacts_{column}", table_name="crm_contacts")
    op.drop_table("crm_contacts")