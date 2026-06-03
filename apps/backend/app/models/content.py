"""
JARV Backend - Content Models

Content items, onboarding flows, and community items.
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, UUIDMixin


class ContentItem(Base, UUIDMixin, TimestampMixin):
    """Content item model for content management"""

    __tablename__ = "content_items"

    # Workspace
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Content information
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    # Content
    content_body: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="markdown",
    )
    excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Media
    featured_image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    media_attachments: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Publishing
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    scheduled_publish_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Authorship
    author_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Engagement
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    share_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # SEO
    meta_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    meta_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_keywords: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Metadata
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    author: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<ContentItem(id={self.id}, title={self.title}, type={self.content_type})>"


class OnboardingFlow(Base, UUIDMixin, TimestampMixin):
    """Onboarding flow model for user onboarding"""

    __tablename__ = "onboarding_flows"

    # Workspace
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Flow information
    flow_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    flow_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Configuration
    target_audience: Mapped[str] = mapped_column(String(100), nullable=False)
    prerequisites: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    # Steps
    steps: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_duration_minutes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")

    # Statistics
    total_starts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_completions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    average_completion_time: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )

    # Feedback
    average_rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_ratings: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Ownership
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Metadata
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    creator: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return f"<OnboardingFlow(id={self.id}, name={self.flow_name}, type={self.flow_type})>"


class CommunityItem(Base, UUIDMixin, TimestampMixin):
    """Community item model for community content"""

    __tablename__ = "community_items"

    # Workspace
    workspace_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Item information
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Content
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="markdown",
    )

    # Author
    author_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Publishing
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Moderation
    is_moderated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    moderated_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    moderated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    moderation_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Engagement
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    upvote_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    downvote_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    share_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Parent/Thread
    parent_item_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("community_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    is_reply: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Metadata
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)
    meta_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # Relationships
    workspace: Mapped[Optional["Workspace"]] = relationship("Workspace")
    author: Mapped["User"] = relationship("User", foreign_keys=[author_id])
    moderator: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[moderated_by],
    )
    parent_item: Mapped[Optional["CommunityItem"]] = relationship(
        "CommunityItem",
        foreign_keys="[CommunityItem.parent_item_id]",
        remote_side="[CommunityItem.id]",
        back_populates="replies",
    )
    replies: Mapped[List["CommunityItem"]] = relationship(
        "CommunityItem",
        back_populates="parent_item",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<CommunityItem(id={self.id}, title={self.title}, type={self.item_type})>"
