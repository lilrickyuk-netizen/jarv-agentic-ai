"""Outbound sales prospecting (Upgrade 6): companies found, the people who decide, the outreach sent and received,
and the opt-outs that are never contacted again. Every row belongs to one workspace, so one product's customers
never mix with another's."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin

EMAIL_STATUSES = ("verified", "risky", "guess", "invalid", "unchecked")
PROSPECT_STAGES = ("new", "drafted", "approved", "contacted", "replied", "interested", "objection",
                   "not_interested", "opted_out", "bounced", "won", "lost")
MESSAGE_STATUSES = ("draft", "approved", "sent", "failed", "cancelled", "received")


class ProspectCompany(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "prospect_companies"
    __table_args__ = (UniqueConstraint("workspace_id", "source_ref", name="uq_prospect_companies_workspace_source"),)

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    area: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="openstreetmap")
    source_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    signals: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    published_emails: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    fit_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="found", index=True)


class Prospect(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "prospects"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prospect_companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    found_on: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    email_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unchecked")
    email_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="new", index=True)
    deal_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True)
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class OutreachMessage(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "outreach_messages"

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    prospect_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prospects.id", ondelete="CASCADE"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="out")
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    send_after_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    classification: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class OutreachSuppression(Base, UUIDMixin, TimestampMixin):
    """An address or a whole domain that is never emailed again (opted out, bounced, or asked by Richard)."""

    __tablename__ = "outreach_suppressions"
    __table_args__ = (UniqueConstraint("workspace_id", "value", name="uq_outreach_suppressions_workspace_value"),)

    workspace_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(320), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="email")  # email or domain
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="opted out")
