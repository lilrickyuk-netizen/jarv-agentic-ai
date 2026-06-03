"""Initial setup - Enable pgvector extension

Revision ID: 2026_06_03_0001
Revises:
Create Date: 2026-06-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2026_06_03_0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable pgvector extension for vector embeddings"""
    # Create pgvector extension if it doesn't exist
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')


def downgrade() -> None:
    """Remove pgvector extension"""
    op.execute('DROP EXTENSION IF EXISTS vector')
