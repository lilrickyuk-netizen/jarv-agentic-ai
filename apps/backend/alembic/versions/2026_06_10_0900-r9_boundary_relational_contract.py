"""Repair 9: relational boundary contract (workspace/task/mission/cross-record FKs)

Adds the Design section 17 workspace/task-centric relational contract to the
hard-boundary / approval / checkpoint / resume models. Repair 8 stored mission
scope (workspace_id, task_id, boundary_report_id, approval_id, decided_by,
expires_at) inside JSON ``context`` / ``action_details`` / ``state_snapshot`` /
``meta_data`` fields. Repair 9 promotes that scope to real, indexed foreign-key
columns so records are queryable and integrity-enforced relationally rather than
by JSON inspection.

Compatibility / backfill strategy (no fabrication):
  1. Every new column is added NULLABLE with ondelete=SET NULL, so existing rows
     stay valid and deleting a workspace/task/report never erases decision or
     audit history.
  2. Existing rows are backfilled from their JSON fields ONLY where the JSON holds
     a valid UUID (or, for resume_actions, derived from the already-backfilled
     parent SafeCheckpoint). Unresolvable historic values are left NULL.
  3. No row is deleted and no id is invented to satisfy a constraint.

Revision ID: r9_boundary_relational
Revises: d784fd7cd498
Create Date: 2026-06-10 09:00:00.000000
"""
from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "r9_boundary_relational"
down_revision = "d784fd7cd498"
branch_labels = None
depends_on = None


# --------------------------------------------------------------------------- #
# New columns per table: (column_name, referenced_table, ondelete)
# All are nullable UUID FK columns except approval_windows.expires_at (DateTime).
# --------------------------------------------------------------------------- #
_FK_COLUMNS = {
    "boundary_reports": [
        ("workspace_id", "workspaces", "SET NULL"),
        ("task_id", "tasks", "SET NULL"),
        ("created_by", "users", "SET NULL"),
    ],
    "boundary_approvals": [
        ("workspace_id", "workspaces", "SET NULL"),
        ("task_id", "tasks", "SET NULL"),
        ("boundary_report_id", "boundary_reports", "SET NULL"),
        ("decided_by", "users", "SET NULL"),
    ],
    "approval_windows": [
        ("approval_id", "boundary_approvals", "SET NULL"),
        ("boundary_report_id", "boundary_reports", "SET NULL"),
        ("workspace_id", "workspaces", "SET NULL"),
        ("task_id", "tasks", "SET NULL"),
        ("decided_by", "users", "SET NULL"),
    ],
    "safe_checkpoints": [
        ("workspace_id", "workspaces", "SET NULL"),
        ("task_id", "tasks", "SET NULL"),
        ("boundary_report_id", "boundary_reports", "SET NULL"),
        ("approval_id", "boundary_approvals", "SET NULL"),
    ],
    "resume_actions": [
        ("approval_id", "boundary_approvals", "SET NULL"),
        ("boundary_report_id", "boundary_reports", "SET NULL"),
        ("workspace_id", "workspaces", "SET NULL"),
        ("task_id", "tasks", "SET NULL"),
    ],
    "richard_boundary_inputs": [
        ("boundary_report_id", "boundary_reports", "SET NULL"),
        ("workspace_id", "workspaces", "SET NULL"),
        ("task_id", "tasks", "SET NULL"),
    ],
}


def _idx(table: str, col: str) -> str:
    return f"ix_{table}_{col}"


def _fk(table: str, col: str) -> str:
    return f"fk_{table}_{col}"


# --------------------------------------------------------------------------- #
# Schema upgrade
# --------------------------------------------------------------------------- #
def upgrade() -> None:
    for table, cols in _FK_COLUMNS.items():
        with op.batch_alter_table(table, schema=None) as batch:
            for col, ref_table, ondelete in cols:
                batch.add_column(sa.Column(col, sa.UUID(), nullable=True))
                batch.create_foreign_key(
                    _fk(table, col), ref_table, [col], ["id"], ondelete=ondelete
                )
                batch.create_index(_idx(table, col), [col], unique=False)
        # expires_at is a plain (non-FK) datetime column on approval_windows.
        if table == "approval_windows":
            with op.batch_alter_table(table, schema=None) as batch:
                batch.add_column(
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
                )

    _backfill_from_json()


# --------------------------------------------------------------------------- #
# Backfill from existing JSON fields (real values only; never fabricated)
# --------------------------------------------------------------------------- #
def _uuid_or_none(value):
    if value is None or value == "":
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _as_dict(value):
    """JSON column may deserialize to dict (preferred) or arrive as a str."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _backfill_from_json() -> None:
    bind = op.get_bind()

    # boundary_reports.context -> workspace_id / task_id / created_by
    rows = bind.execute(
        sa.text("SELECT id, context FROM boundary_reports")
    ).fetchall()
    for rid, ctx in rows:
        c = _as_dict(ctx)
        sets = {
            "workspace_id": _uuid_or_none(c.get("workspace_id")),
            "task_id": _uuid_or_none(c.get("task_id")),
            "created_by": _uuid_or_none(c.get("user_id")),
        }
        _apply(bind, "boundary_reports", rid, sets)

    # boundary_approvals.action_details + meta_data
    rows = bind.execute(
        sa.text("SELECT id, action_details, meta_data FROM boundary_approvals")
    ).fetchall()
    for rid, details, meta in rows:
        d = _as_dict(details)
        m = _as_dict(meta)
        sets = {
            "workspace_id": _uuid_or_none(d.get("workspace_id")),
            "task_id": _uuid_or_none(d.get("task_id")),
            "boundary_report_id": _uuid_or_none(d.get("boundary_report_id")),
            "decided_by": _uuid_or_none(m.get("decided_by")),
        }
        _apply(bind, "boundary_approvals", rid, sets)

    # approval_windows.meta_data -> all scope columns + expires_at
    rows = bind.execute(
        sa.text("SELECT id, meta_data FROM approval_windows")
    ).fetchall()
    for rid, meta in rows:
        m = _as_dict(meta)
        sets = {
            "approval_id": _uuid_or_none(m.get("approval_id")),
            "boundary_report_id": _uuid_or_none(m.get("boundary_report_id")),
            "workspace_id": _uuid_or_none(m.get("workspace_id")),
            "task_id": _uuid_or_none(m.get("task_id")),
            "decided_by": _uuid_or_none(m.get("decided_by")),
        }
        _apply(bind, "approval_windows", rid, sets)
        dt = _parse_dt(m.get("expires_at"))
        if dt is not None:
            bind.execute(
                sa.text("UPDATE approval_windows SET expires_at = :v WHERE id = :id"),
                {"v": dt, "id": rid},
            )

    # safe_checkpoints.state_snapshot
    rows = bind.execute(
        sa.text("SELECT id, state_snapshot FROM safe_checkpoints")
    ).fetchall()
    for rid, snap in rows:
        s = _as_dict(snap)
        sets = {
            "workspace_id": _uuid_or_none(s.get("workspace_id")),
            "task_id": _uuid_or_none(s.get("task_id")),
            "boundary_report_id": _uuid_or_none(s.get("boundary_report_id")),
            "approval_id": _uuid_or_none(s.get("approval_id")),
        }
        _apply(bind, "safe_checkpoints", rid, sets)

    # richard_boundary_inputs.context
    rows = bind.execute(
        sa.text("SELECT id, context FROM richard_boundary_inputs")
    ).fetchall()
    for rid, ctx in rows:
        c = _as_dict(ctx)
        sets = {
            "boundary_report_id": _uuid_or_none(c.get("boundary_report_id")),
            "workspace_id": _uuid_or_none(c.get("workspace_id")),
            "task_id": _uuid_or_none(c.get("task_id")),
        }
        _apply(bind, "richard_boundary_inputs", rid, sets)

    # resume_actions: derive scope from the (now backfilled) parent SafeCheckpoint.
    # This is a real relational derivation via the existing checkpoint_id FK, not
    # fabrication. approval_id also derivable from the checkpoint.
    rows = bind.execute(
        sa.text(
            "SELECT ra.id, sc.workspace_id, sc.task_id, sc.boundary_report_id, "
            "sc.approval_id FROM resume_actions ra "
            "JOIN safe_checkpoints sc ON ra.checkpoint_id = sc.id"
        )
    ).fetchall()
    for rid, ws, tid, brid, apid in rows:
        sets = {
            "workspace_id": _uuid_or_none(ws),
            "task_id": _uuid_or_none(tid),
            "boundary_report_id": _uuid_or_none(brid),
            "approval_id": _uuid_or_none(apid),
        }
        _apply(bind, "resume_actions", rid, sets)


def _apply(bind, table: str, row_id, sets: dict) -> None:
    """UPDATE only the columns whose backfilled value is non-null."""
    sets = {k: v for k, v in sets.items() if v is not None}
    if not sets:
        return
    assignments = ", ".join(f"{k} = :{k}" for k in sets)
    params = dict(sets)
    params["__id"] = row_id
    bind.execute(
        sa.text(f"UPDATE {table} SET {assignments} WHERE id = :__id"), params
    )


# --------------------------------------------------------------------------- #
# Schema downgrade (drops only what this migration added; no data loss beyond
# the new columns themselves)
# --------------------------------------------------------------------------- #
def downgrade() -> None:
    # approval_windows.expires_at first (plain column).
    with op.batch_alter_table("approval_windows", schema=None) as batch:
        batch.drop_column("expires_at")

    for table, cols in _FK_COLUMNS.items():
        with op.batch_alter_table(table, schema=None) as batch:
            for col, _ref, _ondelete in cols:
                batch.drop_index(_idx(table, col))
                # On SQLite batch-recreate the inline FK is dropped with the column;
                # on Postgres drop the named FK constraint before the column.
                if bind_is_postgres():
                    batch.drop_constraint(_fk(table, col), type_="foreignkey")
                batch.drop_column(col)


def bind_is_postgres() -> bool:
    try:
        return op.get_bind().dialect.name == "postgresql"
    except Exception:  # noqa: BLE001
        return False
