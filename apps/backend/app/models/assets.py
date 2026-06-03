"""
JARV Backend - Asset Models

Asset management and licensing tracking.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime, date
from sqlalchemy import String, Boolean, Integer, Text, ForeignKey, JSON, DateTime, Date, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from decimal import Decimal

from app.models.base import Base, TimestampMixin, UUIDMixin


class Asset(Base, UUIDMixin, TimestampMixin):
    """Asset model for digital asset management"""

    __tablename__ = "assets"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Asset information
    asset_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Location
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    storage_location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Ownership
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    owned_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Licensing
    license_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    license_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("asset_licences.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Usage tracking
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Tags and metadata
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[created_by],
    )
    owner: Mapped[Optional["User"]] = relationship("User", foreign_keys=[owned_by])
    licence: Mapped[Optional["AssetLicence"]] = relationship("AssetLicence")

    def __repr__(self) -> str:
        return f"<Asset(id={self.id}, name={self.asset_name}, type={self.asset_type})>"


class AssetLicence(Base, UUIDMixin, TimestampMixin):
    """Asset licence model for asset licensing"""

    __tablename__ = "asset_licences"

    # Workspace
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Licence information
    licence_name: Mapped[str] = mapped_column(String(255), nullable=False)
    licence_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    licence_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Provider
    provider: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Terms
    terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    restrictions: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    permitted_uses: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Dates
    purchased_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    activation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Cost
    cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=2),
        nullable=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_expired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Usage limits
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Metadata
    purchased_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    purchaser: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<AssetLicence(id={self.id}, name={self.licence_name}, type={self.licence_type})>"
