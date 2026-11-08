"""Upgrade 6: outbound sales prospecting (prospect_companies, prospects, outreach_messages, outreach_suppressions).

Revision ID: r18_sales_prospecting
Revises: r17_artifact_graph
Create Date: 2026-11-08 10:00:00.000000

The Sales agent's prospecting pipeline: companies found from open data with the buying signals read from their own
sites, the one or two people who decide, each address checked, outreach drafted for Richard's approval and sent
inside a daily limit, replies handled, and opt-outs kept for good. All rows are per workspace.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "r18_sales_prospecting"
down_revision = "r17_artifact_graph"
branch_labels = None
depends_on = None


def _uuid(name: str, target: str, ondelete: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _times():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "prospect_companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        _uuid("workspace_id", "workspaces.id", "CASCADE"),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("category", sa.String(120), nullable=True),
        sa.Column("area", sa.String(200), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="openstreetmap"),
        sa.Column("source_ref", sa.String(200), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False),
        sa.Column("published_emails", sa.JSON(), nullable=False),
        sa.Column("fit_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="found"),
        *_times(),
        sa.UniqueConstraint("workspace_id", "source_ref", name="uq_prospect_companies_workspace_source"),
    )
    for column in ("workspace_id", "domain", "status", "created_at"):
        op.create_index(f"ix_prospect_companies_{column}", "prospect_companies", [column])

    op.create_table(
        "prospects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        _uuid("workspace_id", "workspaces.id", "CASCADE"),
        _uuid("company_id", "prospect_companies.id", "CASCADE"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(200), nullable=True),
        sa.Column("found_on", sa.String(500), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("email_status", sa.String(20), nullable=False, server_default="unchecked"),
        sa.Column("email_evidence", sa.Text(), nullable=True),
        sa.Column("stage", sa.String(30), nullable=False, server_default="new"),
        _uuid("deal_id", "crm_deals.id", "SET NULL", nullable=True),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_times(),
    )
    for column in ("workspace_id", "company_id", "email", "stage", "created_at"):
        op.create_index(f"ix_prospects_{column}", "prospects", [column])

    op.create_table(
        "outreach_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        _uuid("workspace_id", "workspaces.id", "CASCADE"),
        _uuid("prospect_id", "prospects.id", "CASCADE"),
        sa.Column("direction", sa.String(10), nullable=False, server_default="out"),
        sa.Column("step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("send_after_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("classification", sa.String(30), nullable=True),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_id", sa.String(500), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        *_times(),
    )
    for column in ("workspace_id", "prospect_id", "status", "sent_at", "created_at"):
        op.create_index(f"ix_outreach_messages_{column}", "outreach_messages", [column])

    op.create_table(
        "outreach_suppressions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        _uuid("workspace_id", "workspaces.id", "CASCADE"),
        sa.Column("value", sa.String(320), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False, server_default="email"),
        sa.Column("reason", sa.String(200), nullable=False, server_default="opted out"),
        *_times(),
        sa.UniqueConstraint("workspace_id", "value", name="uq_outreach_suppressions_workspace_value"),
    )
    for column in ("workspace_id", "created_at"):
        op.create_index(f"ix_outreach_suppressions_{column}", "outreach_suppressions", [column])


def downgrade() -> None:
    op.drop_table("outreach_suppressions")
    op.drop_table("outreach_messages")
    op.drop_table("prospects")
    op.drop_table("prospect_companies")
