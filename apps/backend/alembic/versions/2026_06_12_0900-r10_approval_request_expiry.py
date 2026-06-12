"""Repair 10: approval request expiry (boundary_approvals.expires_at)

Repair 10 makes the approval gate operational: a pending BoundaryApproval now
carries a real ``expires_at`` instant. After it passes, the request can no
longer be approved and can never authorise a resume — it is marked "expired"
honestly. (The ApprovalWindow already gained its own real ``expires_at`` in
Repair 9; this column covers the PENDING request itself.)

Compatibility:
  * The column is added NULLABLE; historic rows keep expires_at = NULL, which
    means "no time-based expiry" — exactly their pre-Repair-10 behaviour. No
    value is fabricated for them.
  * Downgrade drops only this column; no data outside it is touched.

Revision ID: r10_approval_expiry
Revises: r9_boundary_relational
Create Date: 2026-06-12 09:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "r10_approval_expiry"
down_revision = "r9_boundary_relational"
branch_labels = None
depends_on = None

_TABLE = "boundary_approvals"
_COLUMN = "expires_at"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(timezone=True),
                                        nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if _COLUMN in existing:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
