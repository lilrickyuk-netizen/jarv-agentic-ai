"""Retain source author and license details for ingested research.

Revision ID: r13_source_attribution
Revises: r13_agent_knowledge
Create Date: 2026-10-21 16:15:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "r13_source_attribution"
down_revision = "r13_agent_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_knowledge", sa.Column("source_license", sa.String(100), nullable=True))
    op.add_column("agent_knowledge", sa.Column("source_author", sa.String(255), nullable=True))
    op.add_column("agent_knowledge", sa.Column("source_author_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_knowledge", "source_author_url")
    op.drop_column("agent_knowledge", "source_author")
    op.drop_column("agent_knowledge", "source_license")