"""
JARV Backend - Live Operations Feed API

RESTful API endpoints for live operations feed and real-time updates.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime, timedelta

from app.core.database import get_db
from app.models.company_operations import LiveOperationsFeedItem

router = APIRouter(prefix="/api/operations-feed", tags=["operations-feed"])


class FeedItemInfo(BaseModel):
    id: str
    workspace_id: str
    item_type: str
    severity: str
    title: str
    message: str
    related_agent_id: str | None
    related_task_id: str | None
    is_read: bool
    is_archived: bool
    requires_action: bool
    action_taken: str | None
    action_taken_at: str | None
    action_taken_by: str | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class FeedStats(BaseModel):
    total_items: int
    unread_items: int
    requires_action_items: int
    by_severity: dict[str, int]
    by_type: dict[str, int]
    recent_activity_count: int


@router.get("/list", response_model=List[FeedItemInfo])
async def list_feed_items(
    workspace_id: Optional[UUID] = None,
    item_type: Optional[str] = None,
    severity: Optional[str] = None,
    is_read: Optional[bool] = None,
    is_archived: Optional[bool] = False,
    requires_action: Optional[bool] = None,
    hours: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    List live operations feed items with optional filtering.

    Args:
        workspace_id: Filter by workspace
        item_type: Filter by item type
        severity: Filter by severity level
        is_read: Filter by read status
        is_archived: Include archived items (default false)
        requires_action: Filter items requiring action
        hours: Filter items from last N hours
        limit: Maximum number of items to return

    Returns:
        List of feed items
    """
    query = select(LiveOperationsFeedItem)

    if workspace_id:
        query = query.where(LiveOperationsFeedItem.workspace_id == workspace_id)
    if item_type:
        query = query.where(LiveOperationsFeedItem.item_type == item_type)
    if severity:
        query = query.where(LiveOperationsFeedItem.severity == severity)
    if is_read is not None:
        query = query.where(LiveOperationsFeedItem.is_read == is_read)
    if is_archived is not None:
        query = query.where(LiveOperationsFeedItem.is_archived == is_archived)
    if requires_action is not None:
        query = query.where(LiveOperationsFeedItem.requires_action == requires_action)
    if hours:
        cutoff_time = datetime.now() - timedelta(hours=hours)
        query = query.where(LiveOperationsFeedItem.created_at >= cutoff_time)

    query = query.order_by(LiveOperationsFeedItem.created_at.desc()).limit(limit)

    result = db.execute(query)
    items = result.scalars().all()

    return [
        FeedItemInfo(
            id=str(item.id),
            workspace_id=str(item.workspace_id),
            item_type=item.item_type,
            severity=item.severity,
            title=item.title,
            message=item.message,
            related_agent_id=str(item.related_agent_id) if item.related_agent_id else None,
            related_task_id=str(item.related_task_id) if item.related_task_id else None,
            is_read=item.is_read,
            is_archived=item.is_archived,
            requires_action=item.requires_action,
            action_taken=item.action_taken,
            action_taken_at=item.action_taken_at.isoformat() if item.action_taken_at else None,
            action_taken_by=str(item.action_taken_by) if item.action_taken_by else None,
            created_at=item.created_at.isoformat() if item.created_at else datetime.now().isoformat(),
            updated_at=item.updated_at.isoformat() if item.updated_at else datetime.now().isoformat(),
        )
        for item in items
    ]


@router.get("/{item_id}", response_model=FeedItemInfo)
async def get_feed_item(
    item_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific feed item.

    Args:
        item_id: UUID of the feed item

    Returns:
        Feed item information
    """
    query = select(LiveOperationsFeedItem).where(LiveOperationsFeedItem.id == item_id)
    result = db.execute(query)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Feed item not found")

    return FeedItemInfo(
        id=str(item.id),
        workspace_id=str(item.workspace_id),
        item_type=item.item_type,
        severity=item.severity,
        title=item.title,
        message=item.message,
        related_agent_id=str(item.related_agent_id) if item.related_agent_id else None,
        related_task_id=str(item.related_task_id) if item.related_task_id else None,
        is_read=item.is_read,
        is_archived=item.is_archived,
        requires_action=item.requires_action,
        action_taken=item.action_taken,
        action_taken_at=item.action_taken_at.isoformat() if item.action_taken_at else None,
        action_taken_by=str(item.action_taken_by) if item.action_taken_by else None,
        created_at=item.created_at.isoformat() if item.created_at else datetime.now().isoformat(),
        updated_at=item.updated_at.isoformat() if item.updated_at else datetime.now().isoformat(),
    )


@router.get("/stats", response_model=FeedStats)
async def get_feed_stats(
    workspace_id: Optional[UUID] = None,
    hours: Optional[int] = 24,
    db: Session = Depends(get_db)
):
    """
    Get aggregated statistics for operations feed.

    Args:
        workspace_id: Optional workspace filter
        hours: Time window for recent activity (default 24 hours)

    Returns:
        Feed statistics including counts by severity and type
    """
    query = select(LiveOperationsFeedItem)
    if workspace_id:
        query = query.where(LiveOperationsFeedItem.workspace_id == workspace_id)
    query = query.where(LiveOperationsFeedItem.is_archived == False)

    result = db.execute(query)
    all_items = result.scalars().all()

    # Calculate statistics
    total_items = len(all_items)
    unread_items = sum(1 for item in all_items if not item.is_read)
    requires_action_items = sum(1 for item in all_items if item.requires_action)

    # By severity
    by_severity = {}
    for item in all_items:
        by_severity[item.severity] = by_severity.get(item.severity, 0) + 1

    # By type
    by_type = {}
    for item in all_items:
        by_type[item.item_type] = by_type.get(item.item_type, 0) + 1

    # Recent activity (last N hours)
    cutoff_time = datetime.now() - timedelta(hours=hours)
    recent_activity_count = sum(
        1 for item in all_items
        if item.created_at and item.created_at >= cutoff_time
    )

    return FeedStats(
        total_items=total_items,
        unread_items=unread_items,
        requires_action_items=requires_action_items,
        by_severity=by_severity,
        by_type=by_type,
        recent_activity_count=recent_activity_count,
    )


@router.patch("/{item_id}/mark-read")
async def mark_feed_item_read(
    item_id: UUID,
    is_read: bool = True,
    db: Session = Depends(get_db)
):
    """
    Mark a feed item as read or unread.

    Args:
        item_id: UUID of the feed item
        is_read: Read status to set

    Returns:
        Success message
    """
    query = select(LiveOperationsFeedItem).where(LiveOperationsFeedItem.id == item_id)
    result = db.execute(query)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Feed item not found")

    item.is_read = is_read
    item.updated_at = datetime.now()
    db.commit()

    return {"success": True, "message": f"Feed item marked as {'read' if is_read else 'unread'}"}


@router.patch("/{item_id}/archive")
async def archive_feed_item(
    item_id: UUID,
    is_archived: bool = True,
    db: Session = Depends(get_db)
):
    """
    Archive or unarchive a feed item.

    Args:
        item_id: UUID of the feed item
        is_archived: Archive status to set

    Returns:
        Success message
    """
    query = select(LiveOperationsFeedItem).where(LiveOperationsFeedItem.id == item_id)
    result = db.execute(query)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=404, detail="Feed item not found")

    item.is_archived = is_archived
    item.updated_at = datetime.now()
    db.commit()

    return {"success": True, "message": f"Feed item {'archived' if is_archived else 'unarchived'}"}
