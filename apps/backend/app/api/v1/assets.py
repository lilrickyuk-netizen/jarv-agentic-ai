"""
JARV Backend - Asset Management API

RESTful API endpoints for asset creation, management, and retrieval.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.core.assets.manager import (
    get_asset_manager,
    AssetType,
    AssetStatus,
    AssetMetadata,
)
from app.core.assets.templates import get_template_library, TemplateCategory
from app.core.auth import get_current_user

router = APIRouter(prefix="/assets", tags=["assets"])


class CreateAssetRequest(BaseModel):
    """Request to create an asset"""
    name: str
    asset_type: AssetType
    workspace_id: str
    tags: List[str] = Field(default_factory=list)
    description: str = ""
    custom_fields: dict = Field(default_factory=dict)


class UpdateAssetRequest(BaseModel):
    """Request to update an asset"""
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[AssetStatus] = None
    custom_fields: Optional[dict] = None


class AssetResponse(BaseModel):
    """Asset response model"""
    asset_id: str
    name: str
    asset_type: str
    status: str
    file_path: str
    file_size: int
    mime_type: str
    created_at: datetime
    updated_at: datetime
    created_by: str
    workspace_id: str
    version: int
    tags: List[str]
    description: str
    dimensions: Optional[dict] = None
    duration: Optional[float] = None
    page_count: Optional[int] = None


class TemplateResponse(BaseModel):
    """Template response model"""
    template_id: str
    name: str
    category: str
    description: str
    asset_type: str
    dimensions: dict
    placeholders: List[str]
    preview_url: str
    tags: List[str]


@router.post("/", response_model=AssetResponse)
async def create_asset(
    file: UploadFile = File(...),
    name: str = Form(...),
    asset_type: str = Form(...),
    workspace_id: str = Form(...),
    tags: str = Form(""),
    description: str = Form(""),
    current_user = Depends(get_current_user),
):
    """
    Create a new asset by uploading a file.

    Requires authentication.
    """
    try:
        manager = get_asset_manager()

        # Parse tags
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        # Read file content
        file_content = await file.read()

        # Create asset
        metadata = manager.create_asset(
            name=name,
            asset_type=AssetType(asset_type),
            workspace_id=workspace_id,
            created_by=str(current_user.id),
            file_content=file_content,
            mime_type=file.content_type or "application/octet-stream",
            tags=tag_list,
            description=description,
        )

        return AssetResponse(
            asset_id=metadata.asset_id,
            name=metadata.name,
            asset_type=metadata.asset_type.value,
            status=metadata.status.value,
            file_path=metadata.file_path,
            file_size=metadata.file_size,
            mime_type=metadata.mime_type,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            created_by=metadata.created_by,
            workspace_id=metadata.workspace_id,
            version=metadata.version,
            tags=metadata.tags,
            description=metadata.description,
            dimensions=metadata.dimensions,
            duration=metadata.duration,
            page_count=metadata.page_count,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create asset: {str(e)}")


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: str,
    current_user = Depends(get_current_user),
):
    """Get asset metadata by ID"""
    manager = get_asset_manager()
    metadata = manager.get_asset(asset_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Asset not found")

    return AssetResponse(
        asset_id=metadata.asset_id,
        name=metadata.name,
        asset_type=metadata.asset_type.value,
        status=metadata.status.value,
        file_path=metadata.file_path,
        file_size=metadata.file_size,
        mime_type=metadata.mime_type,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
        created_by=metadata.created_by,
        workspace_id=metadata.workspace_id,
        version=metadata.version,
        tags=metadata.tags,
        description=metadata.description,
        dimensions=metadata.dimensions,
        duration=metadata.duration,
        page_count=metadata.page_count,
    )


@router.get("/{asset_id}/download")
async def download_asset(
    asset_id: str,
    version: Optional[int] = None,
    current_user = Depends(get_current_user),
):
    """Download asset file content"""
    manager = get_asset_manager()
    metadata = manager.get_asset(asset_id)

    if not metadata:
        raise HTTPException(status_code=404, detail="Asset not found")

    content = manager.get_asset_content(asset_id, version)

    if not content:
        raise HTTPException(status_code=404, detail="Asset content not found")

    return Response(
        content=content,
        media_type=metadata.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{metadata.name}"'
        },
    )


@router.put("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: str,
    request: UpdateAssetRequest,
    current_user = Depends(get_current_user),
):
    """Update asset metadata"""
    manager = get_asset_manager()

    metadata = manager.update_asset(
        asset_id=asset_id,
        updated_by=str(current_user.id),
        name=request.name,
        description=request.description,
        tags=request.tags,
        status=request.status,
        custom_fields=request.custom_fields,
    )

    if not metadata:
        raise HTTPException(status_code=404, detail="Asset not found")

    return AssetResponse(
        asset_id=metadata.asset_id,
        name=metadata.name,
        asset_type=metadata.asset_type.value,
        status=metadata.status.value,
        file_path=metadata.file_path,
        file_size=metadata.file_size,
        mime_type=metadata.mime_type,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
        created_by=metadata.created_by,
        workspace_id=metadata.workspace_id,
        version=metadata.version,
        tags=metadata.tags,
        description=metadata.description,
        dimensions=metadata.dimensions,
        duration=metadata.duration,
        page_count=metadata.page_count,
    )


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: str,
    current_user = Depends(get_current_user),
):
    """Delete (archive) an asset"""
    manager = get_asset_manager()

    success = manager.delete_asset(asset_id)

    if not success:
        raise HTTPException(status_code=404, detail="Asset not found")

    return {"message": "Asset archived successfully", "asset_id": asset_id}


@router.get("/", response_model=List[AssetResponse])
async def search_assets(
    workspace_id: Optional[str] = None,
    asset_type: Optional[AssetType] = None,
    tags: Optional[str] = None,
    status: Optional[AssetStatus] = None,
    search: Optional[str] = None,
    current_user = Depends(get_current_user),
):
    """Search for assets"""
    manager = get_asset_manager()

    # Parse tags
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    results = manager.search_assets(
        workspace_id=workspace_id,
        asset_type=asset_type,
        tags=tag_list,
        status=status,
        search_text=search,
    )

    return [
        AssetResponse(
            asset_id=m.asset_id,
            name=m.name,
            asset_type=m.asset_type.value,
            status=m.status.value,
            file_path=m.file_path,
            file_size=m.file_size,
            mime_type=m.mime_type,
            created_at=m.created_at,
            updated_at=m.updated_at,
            created_by=m.created_by,
            workspace_id=m.workspace_id,
            version=m.version,
            tags=m.tags,
            description=m.description,
            dimensions=m.dimensions,
            duration=m.duration,
            page_count=m.page_count,
        )
        for m in results
    ]


@router.get("/stats/system")
async def get_asset_stats(
    current_user = Depends(get_current_user),
):
    """Get asset system statistics"""
    manager = get_asset_manager()
    return manager.get_stats()


@router.get("/templates/", response_model=List[TemplateResponse])
async def list_templates(
    category: Optional[TemplateCategory] = None,
    asset_type: Optional[str] = None,
    tags: Optional[str] = None,
    current_user = Depends(get_current_user),
):
    """List available asset templates"""
    library = get_template_library()

    # Parse tags
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    templates = library.list_templates(
        category=category,
        asset_type=asset_type,
        tags=tag_list,
    )

    return [
        TemplateResponse(
            template_id=t.template_id,
            name=t.name,
            category=t.category.value,
            description=t.description,
            asset_type=t.asset_type,
            dimensions=t.dimensions,
            placeholders=t.placeholders,
            preview_url=t.preview_url,
            tags=t.tags,
        )
        for t in templates
    ]


@router.get("/templates/stats")
async def get_template_stats(
    current_user = Depends(get_current_user),
):
    """Get template library statistics"""
    library = get_template_library()
    return library.get_template_stats()
