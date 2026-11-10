"""A workflow run: a chain of missions done by a council of specialists, with Richard's approval gates between them
(Richard, 10 November, from AskRich's Workflow Orchestrator and Councils). The run's state and its pauses are
kept by LangGraph's Postgres checkpointer under the run's id; this row is what the dashboard, the voice and the
scheduler read: which template, which step it is on, and what it waits for."""
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

WORKFLOW_STATUSES = ("running", "waiting_mission", "waiting_approval", "completed", "stopped", "cancelled")


class WorkflowRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workflow_runs"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    template: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    product: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running", index=True)
    current_step: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    waiting_task_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    steps: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stopped_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
