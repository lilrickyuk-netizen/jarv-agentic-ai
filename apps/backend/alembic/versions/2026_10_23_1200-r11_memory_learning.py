"""Repair 11: memory isolation, taxonomy, provenance, and verified learning.

Adds to ``memories`` the workspace foreign key (previously only inside the
``context`` JSON, so searches could not be isolated), the 23-category taxonomy,
confidence, provenance, version, embedding model, and the parent-agent /
sub-agent / approval / checkpoint / boundary-input references required by the
design. Adds the verified-learning lifecycle columns to ``experience_records``.

Existing rows are backfilled: ``workspace_id`` from ``context->>'workspace_id'``
and ``memory_category`` from ``memory_type`` (PostgreSQL only; SQLite test
databases are created from the models).

Revision ID: r11_memory_learning
Revises: r13_source_attribution
Create Date: 2026-10-23 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "r11_memory_learning"
down_revision = "r13_source_attribution"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_REFERENCE_COLUMNS = (
    "parent_agent_id", "sub_agent_id", "approval_id", "checkpoint_id", "boundary_input_id",
)

# memory_type -> category backfill for rows written before this revision.
_CATEGORY_BACKFILL = {
    "task": ("task_result", "task", "delegation", "conversation", "agent_output"),
    "incident": ("incident", "self_healing", "monitoring", "rollback"),
    "infrastructure": ("infrastructure", "launch", "deployment", "devops", "security"),
    "content": ("content", "marketing", "documentation"),
    "customer": ("customer", "support", "customer_support"),
    "business": ("business", "finance", "legal", "growth", "analytics"),
    "asset": ("asset", "creation", "source"),
    "experience": ("experience", "learning", "verified_learning", "lesson"),
    "self_evolution": ("self_evolution", "evolution"),
    "swarm": ("swarm", "sub_agent"),
    "onboarding": ("onboarding",),
    "community": ("community",),
    "partnership": ("partnership", "partnerships"),
    "sales": ("sales",),
    "revenue": ("revenue",),
    "decision": ("decision",),
    "boundary": ("boundary", "hard_boundary"),
    "approval": ("approval",),
    "checkpoint": ("checkpoint", "resume"),
    "richard_boundary_operator": ("richard", "richard_boundary_operator", "richard_boundary_input"),
    "company_operating": ("company_operating", "operating_plan", "standup", "daily_loop"),
}


def upgrade() -> None:
    op.add_column("memories", sa.Column("workspace_id", _UUID, nullable=True))
    op.create_foreign_key(
        "fk_memories_workspace_id", "memories", "workspaces",
        ["workspace_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_memories_workspace_id", "memories", ["workspace_id"])
    op.add_column("memories", sa.Column(
        "memory_category", sa.String(50), nullable=False, server_default="global"))
    op.create_index("ix_memories_memory_category", "memories", ["memory_category"])
    op.add_column("memories", sa.Column(
        "confidence_score", sa.Float(), nullable=False, server_default="0.5"))
    op.add_column("memories", sa.Column("source_ref", sa.String(255), nullable=True))
    op.add_column("memories", sa.Column(
        "version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("memories", sa.Column("embedding_model", sa.String(120), nullable=True))
    op.create_index("ix_memories_embedding_model", "memories", ["embedding_model"])
    for column in _REFERENCE_COLUMNS:
        op.add_column("memories", sa.Column(column, _UUID, nullable=True))
        op.create_index(f"ix_memories_{column}", "memories", [column])

    op.add_column("experience_records", sa.Column("workspace_id", _UUID, nullable=True))
    op.create_foreign_key(
        "fk_experience_records_workspace_id", "experience_records", "workspaces",
        ["workspace_id"], ["id"], ondelete="CASCADE",
    )
    op.create_index("ix_experience_records_workspace_id", "experience_records", ["workspace_id"])
    op.add_column("experience_records", sa.Column("agent_name", sa.String(100), nullable=True))
    op.create_index("ix_experience_records_agent_name", "experience_records", ["agent_name"])
    op.add_column("experience_records", sa.Column(
        "lesson_status", sa.String(20), nullable=False, server_default="candidate"))
    op.create_index("ix_experience_records_lesson_status", "experience_records", ["lesson_status"])
    op.add_column("experience_records", sa.Column("lesson_key", sa.String(64), nullable=True))
    op.create_index("ix_experience_records_lesson_key", "experience_records", ["lesson_key"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Backfill workspace ownership from the legacy JSON context, keeping only
    # well-formed UUIDs that reference a workspace that still exists.
    op.execute(
        """
        UPDATE memories AS m
        SET workspace_id = w.id
        FROM workspaces AS w
        WHERE m.workspace_id IS NULL
          AND (m.context::jsonb ->> 'workspace_id') ~*
              '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
          AND w.id = (m.context::jsonb ->> 'workspace_id')::uuid
        """
    )
    for category, types in _CATEGORY_BACKFILL.items():
        bind.execute(
            sa.text("UPDATE memories SET memory_category = :category WHERE memory_type IN :types")
            .bindparams(sa.bindparam("types", expanding=True)),
            {"category": category, "types": list(types)},
        )
    op.execute(
        "UPDATE memories SET memory_category = 'workspace' "
        "WHERE memory_category = 'global' AND workspace_id IS NOT NULL "
        "AND memory_type NOT IN ('global')"
    )
    # Pre-existing lessons were never verified; keep them as candidates and
    # mark validated rows (if any were set by hand) as verified.
    op.execute(
        "UPDATE experience_records SET lesson_status = 'verified' "
        "WHERE is_validated = true AND is_active = true"
    )


def downgrade() -> None:
    for name in ("lesson_key", "lesson_status", "agent_name"):
        op.drop_index(f"ix_experience_records_{name}", table_name="experience_records")
        op.drop_column("experience_records", name)
    op.drop_index("ix_experience_records_workspace_id", table_name="experience_records")
    op.drop_constraint("fk_experience_records_workspace_id", "experience_records", type_="foreignkey")
    op.drop_column("experience_records", "workspace_id")

    for column in _REFERENCE_COLUMNS:
        op.drop_index(f"ix_memories_{column}", table_name="memories")
        op.drop_column("memories", column)
    op.drop_index("ix_memories_embedding_model", table_name="memories")
    op.drop_column("memories", "embedding_model")
    op.drop_column("memories", "version")
    op.drop_column("memories", "source_ref")
    op.drop_column("memories", "confidence_score")
    op.drop_index("ix_memories_memory_category", table_name="memories")
    op.drop_column("memories", "memory_category")
    op.drop_index("ix_memories_workspace_id", table_name="memories")
    op.drop_constraint("fk_memories_workspace_id", "memories", type_="foreignkey")
    op.drop_column("memories", "workspace_id")
