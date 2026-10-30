"""
JARV Backend - Assets API

Authenticated, owner-scoped endpoints for the Assets page: the assets in the
user's workspaces and their statistics, a workspace's asset library with
licences and attributions, licence checks, licence-checked downloads into the
workspace, and the manifest and licence files (app.core.assets.library).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.assets import library
from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.models.assets import Asset
from app.models.workspace import Workspace

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


class AssetStats(BaseModel):
    total_assets: int
    active_assets: int
    by_type: dict[str, int]
    by_licence: dict[str, int]
    total_downloads: int
    total_views: int


def _owned_ids(user_id: str):
    return select(Workspace.id).where(Workspace.owner_id == UUID(str(user_id)))


async def _workspace(db: AsyncSession, user_id: str, workspace_id: UUID) -> Workspace:
    ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id,
                                                   Workspace.owner_id == UUID(str(user_id))))).scalar_one_or_none()
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.get("/list", response_model=List[AssetInfo])
async def list_assets(user_id: CurrentUserId, asset_type: Optional[str] = None, is_active: Optional[bool] = True,
                      limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Assets in the user's workspaces, newest first."""
    query = select(Asset).where(Asset.workspace_id.in_(_owned_ids(user_id)))
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if is_active is not None:
        query = query.where(Asset.is_active == is_active)
    rows = (await db.execute(query.order_by(Asset.created_at.desc()).limit(max(1, min(limit, 500))))).scalars().all()
    return [AssetInfo(
        id=str(a.id), workspace_id=str(a.workspace_id), asset_name=a.asset_name, asset_type=a.asset_type,
        category=a.category, description=a.description, file_size=a.file_size, mime_type=a.mime_type,
        is_active=bool(a.is_active), is_public=bool(a.is_public), license_type=a.license_type,
        download_count=a.download_count or 0, view_count=a.view_count or 0, tags=a.tags or [],
        created_at=(a.created_at or datetime.now(timezone.utc)).isoformat()) for a in rows]


@router.get("/stats", response_model=AssetStats)
async def get_asset_stats(user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    """Statistics over the assets in the user's workspaces."""
    rows = (await db.execute(select(Asset).where(Asset.workspace_id.in_(_owned_ids(user_id))))).scalars().all()
    by_type: Dict[str, int] = {}
    by_licence: Dict[str, int] = {}
    for a in rows:
        by_type[a.asset_type] = by_type.get(a.asset_type, 0) + 1
        key = a.license_type or "unknown"
        by_licence[key] = by_licence.get(key, 0) + 1
    return AssetStats(total_assets=len(rows), active_assets=sum(1 for a in rows if a.is_active), by_type=by_type,
                      by_licence=by_licence, total_downloads=sum(a.download_count or 0 for a in rows),
                      total_views=sum(a.view_count or 0 for a in rows))


@router.get("/{workspace_id}/library")
async def workspace_library(workspace_id: UUID, user_id: CurrentUserId,
                            db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _workspace(db, user_id, workspace_id)
    return {"assets": [library.asset_view(a) for a in await library.list_assets(db, workspace_id)]}


class LicenceCheck(BaseModel):
    licence: Optional[str] = None
    url: Optional[str] = None
    commercial: bool = True


@router.post("/licence-check")
async def licence_check(body: LicenceCheck, user_id: CurrentUserId) -> Dict[str, Any]:
    return library.check_licence(body.licence, body.url, commercial=body.commercial)


class Download(BaseModel):
    url: str
    licence: Optional[str] = None
    author: Optional[str] = None
    source_page: Optional[str] = None
    folder: str = "assets"
    filename: Optional[str] = None
    commercial: bool = True


@router.post("/{workspace_id}/download")
async def download(workspace_id: UUID, body: Download, user_id: CurrentUserId,
                   db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    ws = await _workspace(db, user_id, workspace_id)
    try:
        row = await library.download(db, ws, body.url, folder=body.folder, filename=body.filename,
                                     licence=body.licence, author=body.author, source_page=body.source_page,
                                     commercial=body.commercial, created_by=UUID(str(user_id)))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    await db.commit()
    return library.asset_view(row)


class SourceRecord(BaseModel):
    source_page: Optional[str] = None
    author: Optional[str] = None
    licence: Optional[str] = Field(None, description="Corrected licence id or name")


@router.post("/{workspace_id}/assets/{asset_id}/source")
async def save_source(workspace_id: UUID, asset_id: UUID, body: SourceRecord, user_id: CurrentUserId,
                      db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _workspace(db, user_id, workspace_id)
    try:
        row = await library.save_source(db, workspace_id, asset_id, source_page=body.source_page, author=body.author,
                                        licence=body.licence)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return library.asset_view(row)


@router.post("/{workspace_id}/manifest")
async def manifest(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    ws = await _workspace(db, user_id, workspace_id)
    try:
        result = {"manifest": await library.write_manifest(db, ws), "licences": await library.write_licence_file(db, ws)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.commit()
    return result
