"""
JARV Backend - Assets API

RESTful API endpoints for digital asset management.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.models.assets import Asset

router = APIRouter(prefix="/api/assets", tags=["assets"])


class AssetInfo(BaseModel):
    id: str
    workspace_id: str
    asset_name: str
    asset_type: str
    category: str | None
    description: str | None
    file_size: int | None
    mime_type: str | None
    is_active: bool
    is_public: bool
    license_type: str | None
    download_count: int
    view_count: int
    tags: List[str]
    created_at: str

    class Config:
        from_attributes = True


class AssetStats(BaseModel):
    total_assets: int
    active_assets: int
    by_type: dict[str, int]
    total_downloads: int
    total_views: int


@router.get("/list", response_model=List[AssetInfo])
async def list_assets(
    asset_type: Optional[str] = None,
    is_active: Optional[bool] = True,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """List assets with optional filtering."""
    query = select(Asset)
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if is_active is not None:
        query = query.where(Asset.is_active == is_active)
    query = query.order_by(Asset.created_at.desc()).limit(limit)

    result = db.execute(query)
    assets = result.scalars().all()

    return [
        AssetInfo(
            id=str(asset.id),
            workspace_id=str(asset.workspace_id),
            asset_name=asset.asset_name,
            asset_type=asset.asset_type,
            category=asset.category,
            description=asset.description,
            file_size=asset.file_size,
            mime_type=asset.mime_type,
            is_active=asset.is_active,
            is_public=asset.is_public,
            license_type=asset.license_type,
            download_count=asset.download_count,
            view_count=asset.view_count,
            tags=asset.tags or [],
            created_at=asset.created_at.isoformat() if asset.created_at else datetime.now().isoformat(),
        )
        for asset in assets
    ]


@router.get("/stats", response_model=AssetStats)
async def get_asset_stats(db: Session = Depends(get_db)):
    """Get aggregated statistics for assets."""
    result = db.execute(select(Asset))
    all_assets = result.scalars().all()

    total_assets = len(all_assets)
    active_assets = sum(1 for a in all_assets if a.is_active)

    by_type: dict[str, int] = {}
    for asset in all_assets:
        by_type[asset.asset_type] = by_type.get(asset.asset_type, 0) + 1

    total_downloads = sum(a.download_count for a in all_assets)
    total_views = sum(a.view_count for a in all_assets)

    return AssetStats(
        total_assets=total_assets,
        active_assets=active_assets,
        by_type=by_type,
        total_downloads=total_downloads,
        total_views=total_views,
    )
