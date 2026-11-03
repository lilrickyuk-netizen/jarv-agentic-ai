"""The Artifact Intelligence Graph (Upgrade 3): what each requirement rests on.

Nodes are the things a mission produces or relies on (a requirement, a file, a command, a check, a decision, the
mission itself), one row per workspace and key. Edges say how they relate (a file implements a requirement, a
command verifies it, a check contradicts a decision, a file was changed by a mission) and carry their evidence,
so "what proves this?" and "what did this change touch?" are answered by a query, not a summary.
"""
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

NODE_KINDS = ("requirement", "file", "command", "check", "decision", "mission", "knowledge")
RELATIONS = ("implements", "verifies", "claims", "contradicts", "changed_by", "run_in", "required_by",
             "informed_by", "supersedes")


class ArtifactNode(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "artifact_nodes"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "key", name="uq_artifact_nodes_workspace_kind_key"),)

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attrs: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    task_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)


class ArtifactEdge(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "artifact_edges"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation", "task_id", name="uq_artifact_edges_link"),
        Index("ix_artifact_edges_target", "target_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifact_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifact_nodes.id", ondelete="CASCADE"), nullable=False)
    relation: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    task_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    evidence: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
