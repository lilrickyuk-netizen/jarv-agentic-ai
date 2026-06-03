"""
JARV Backend - Business Models

Support tickets, marketing, business plans, sales, and partnerships.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime, Date, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from decimal import Decimal

from app.models.base import Base, TimestampMixin, UUIDMixin


class SupportTicket(Base, UUIDMixin, TimestampMixin):
    """Support ticket model for customer support"""

    __tablename__ = "support_tickets"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Ticket information
    ticket_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Customer
    customer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Classification
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open")

    # Assignment
    assigned_to: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assigned_agent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Resolution
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Timing
    first_response_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    assigned_user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[assigned_to],
    )
    assigned_agent: Mapped[Optional["Agent"]] = relationship("Agent")
    resolver: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[resolved_by],
    )

    def __repr__(self) -> str:
        return f"<SupportTicket(id={self.id}, number={self.ticket_number}, status={self.status})>"


class MarketingCampaign(Base, UUIDMixin, TimestampMixin):
    """Marketing campaign model for marketing campaigns"""

    __tablename__ = "marketing_campaigns"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Campaign information
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    campaign_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Dates
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")

    # Budget
    budget: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=2),
        nullable=True,
    )
    actual_cost: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2),
        default=0,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # Targets
    target_audience: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Performance
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revenue_generated: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2),
        default=0,
        nullable=False,
    )

    # Content
    content: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    assets: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Ownership
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<MarketingCampaign(id={self.id}, name={self.campaign_name}, status={self.status})>"


class BusinessPlan(Base, UUIDMixin, TimestampMixin):
    """Business plan model for business planning"""

    __tablename__ = "business_plans"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Plan information
    plan_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    plan_version: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Time period
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Content
    executive_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    market_analysis: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    financial_projections: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=True,
    )
    strategies: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSON,
        nullable=True,
    )

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Approval
    approved_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Ownership
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[created_by],
    )
    approver: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[approved_by],
    )

    def __repr__(self) -> str:
        return f"<BusinessPlan(id={self.id}, name={self.plan_name}, version={self.plan_version})>"


class SalesRecord(Base, UUIDMixin, TimestampMixin):
    """Sales record model for sales tracking"""

    __tablename__ = "sales_records"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Sale information
    sale_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Customer
    customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Product
    product_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Financial
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    discount: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2),
        default=0,
        nullable=False,
    )
    tax: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2),
        default=0,
        nullable=False,
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2),
        nullable=False,
    )

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    payment_status: Mapped[str] = mapped_column(String(50), nullable=False)
    fulfillment_status: Mapped[str] = mapped_column(String(50), nullable=False)

    # Attribution
    sales_person_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sales_agent_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    campaign_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("marketing_campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    sales_person: Mapped[Optional["User"]] = relationship("User")
    sales_agent: Mapped[Optional["Agent"]] = relationship("Agent")
    campaign: Mapped[Optional["MarketingCampaign"]] = relationship("MarketingCampaign")

    def __repr__(self) -> str:
        return f"<SalesRecord(id={self.id}, sale_id={self.sale_id}, total={self.total})>"


class PartnershipRecord(Base, UUIDMixin, TimestampMixin):
    """Partnership record model for partnership tracking"""

    __tablename__ = "partnership_records"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Partner information
    partner_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    partner_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Contact
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Agreement
    agreement_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    agreement_terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Value
    estimated_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=2),
        nullable=True,
    )
    actual_value: Mapped[Decimal] = mapped_column(
        Numeric(precision=10, scale=2),
        default=0,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    # Ownership
    managed_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    manager: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<PartnershipRecord(id={self.id}, partner={self.partner_name}, type={self.partner_type})>"
