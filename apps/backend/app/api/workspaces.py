"""
JARV Backend - Workspace Management API

Endpoints for managing dynamic project workspaces.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from datetime import datetime
from uuid import UUID
import logging

from app.core.database import get_db
from app.models.workspace import Workspace
from app.models.task import Task
from app.models.agent import Agent
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceInfo(BaseModel):
    """Workspace information response"""
    id: str
    name: str
    description: Optional[str]
    slug: str
    owner_id: str
    is_active: bool
    is_archived: bool
    workspace_type: str
    authority_level: int
    max_subagents: int
    active_subagent_count: int
    swarm_enabled: bool
    self_evolution_enabled: bool
    company_mode_enabled: bool
    company_name: Optional[str]
    total_tasks: int
    completed_tasks: int
    total_tokens_used: int
    created_at: datetime
    updated_at: datetime


class WorkspaceStats(BaseModel):
    """Workspace statistics"""
    total_workspaces: int
    active_workspaces: int
    archived_workspaces: int
    total_tasks_across_all: int
    total_agents_across_all: int
    company_mode_workspaces: int


class WorkspaceCreate(BaseModel):
    """Create workspace request"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    slug: str = Field(..., min_length=1, max_length=100)
    workspace_type: str = Field(default="general")
    authority_level: int = Field(default=3, ge=0, le=10)
    swarm_enabled: bool = True
    company_mode_enabled: bool = False
    company_name: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    """Update workspace request"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    authority_level: Optional[int] = Field(None, ge=0, le=10)
    swarm_enabled: Optional[bool] = None
    company_mode_enabled: Optional[bool] = None


@router.get(
    "/list",
    response_model=List[WorkspaceInfo],
    summary="List all workspaces",
    description="Get list of all workspaces with their current status"
)
async def list_workspaces(
    active_only: bool = False,
    include_archived: bool = False,
    db: Session = Depends(get_db),
) -> List[WorkspaceInfo]:
    """
    List all workspaces.

    Args:
        active_only: Only return active workspaces
        include_archived: Include archived workspaces
        db: Database session

    Returns:
        List of workspace information
    """
    try:
        query = select(Workspace)

        if active_only:
            query = query.where(Workspace.is_active == True)

        if not include_archived:
            query = query.where(Workspace.is_archived == False)

        query = query.order_by(Workspace.created_at.desc())

        result = await db.execute(query)
        workspaces = result.scalars().all()

        return [
            WorkspaceInfo(
                id=str(ws.id),
                name=ws.name,
                description=ws.description,
                slug=ws.slug,
                owner_id=str(ws.owner_id),
                is_active=ws.is_active,
                is_archived=ws.is_archived,
                workspace_type=ws.workspace_type,
                authority_level=ws.authority_level,
                max_subagents=ws.max_subagents,
                active_subagent_count=ws.active_subagent_count,
                swarm_enabled=ws.swarm_enabled,
                self_evolution_enabled=ws.self_evolution_enabled,
                company_mode_enabled=ws.company_mode_enabled,
                company_name=ws.company_name,
                total_tasks=ws.total_tasks,
                completed_tasks=ws.completed_tasks,
                total_tokens_used=ws.total_tokens_used,
                created_at=ws.created_at,
                updated_at=ws.updated_at,
            )
            for ws in workspaces
        ]

    except Exception as e:
        logger.error(f"Error listing workspaces: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list workspaces: {str(e)}"
        )


@router.get(
    "/stats",
    response_model=WorkspaceStats,
    summary="Get workspace statistics",
    description="Get aggregated statistics across all workspaces"
)
async def get_workspace_stats(db: Session = Depends(get_db)) -> WorkspaceStats:
    """
    Get workspace statistics.

    Args:
        db: Database session

    Returns:
        Workspace statistics
    """
    try:
        # Count workspaces (async session: use select + execute)
        total_workspaces = (
            await db.execute(select(func.count(Workspace.id)))
        ).scalar()
        active_workspaces = (
            await db.execute(
                select(func.count(Workspace.id)).where(
                    Workspace.is_active == True,
                    Workspace.is_archived == False,
                )
            )
        ).scalar()
        archived_workspaces = (
            await db.execute(
                select(func.count(Workspace.id)).where(
                    Workspace.is_archived == True
                )
            )
        ).scalar()
        company_mode_workspaces = (
            await db.execute(
                select(func.count(Workspace.id)).where(
                    Workspace.company_mode_enabled == True
                )
            )
        ).scalar()

        # Count tasks across all workspaces
        total_tasks = (await db.execute(select(func.count(Task.id)))).scalar()

        # Count agents across all workspaces
        total_agents = (await db.execute(select(func.count(Agent.id)))).scalar()

        return WorkspaceStats(
            total_workspaces=total_workspaces or 0,
            active_workspaces=active_workspaces or 0,
            archived_workspaces=archived_workspaces or 0,
            total_tasks_across_all=total_tasks or 0,
            total_agents_across_all=total_agents or 0,
            company_mode_workspaces=company_mode_workspaces or 0,
        )

    except Exception as e:
        logger.error(f"Error getting workspace stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workspace stats: {str(e)}"
        )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceInfo,
    summary="Get workspace details",
    description="Get detailed information about a specific workspace"
)
async def get_workspace(
    workspace_id: UUID,
    db: Session = Depends(get_db),
) -> WorkspaceInfo:
    """
    Get workspace details.

    Args:
        workspace_id: Workspace UUID
        db: Database session

    Returns:
        Workspace information

    Raises:
        404: If workspace not found
    """
    try:
        result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace '{workspace_id}' not found"
            )

        return WorkspaceInfo(
            id=str(workspace.id),
            name=workspace.name,
            description=workspace.description,
            slug=workspace.slug,
            owner_id=str(workspace.owner_id),
            is_active=workspace.is_active,
            is_archived=workspace.is_archived,
            workspace_type=workspace.workspace_type,
            authority_level=workspace.authority_level,
            max_subagents=workspace.max_subagents,
            active_subagent_count=workspace.active_subagent_count,
            swarm_enabled=workspace.swarm_enabled,
            self_evolution_enabled=workspace.self_evolution_enabled,
            company_mode_enabled=workspace.company_mode_enabled,
            company_name=workspace.company_name,
            total_tasks=workspace.total_tasks,
            completed_tasks=workspace.completed_tasks,
            total_tokens_used=workspace.total_tokens_used,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting workspace: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workspace: {str(e)}"
        )


@router.post(
    "/create",
    response_model=WorkspaceInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Create new workspace",
    description="Create a new workspace with specified configuration"
)
async def create_workspace(
    workspace: WorkspaceCreate,
    db: Session = Depends(get_db),
) -> WorkspaceInfo:
    """
    Create new workspace.

    Args:
        workspace: Workspace creation data
        db: Database session

    Returns:
        Created workspace information

    Raises:
        400: If slug already exists
    """
    try:
        # Check if slug exists
        existing = (
            await db.execute(select(Workspace).where(Workspace.slug == workspace.slug))
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Workspace with slug '{workspace.slug}' already exists"
            )

        # Owner: use a real seeded user (operators authenticate via the Redis
        # user store; workspaces are owned by the first persisted user).
        owner_id = (await db.execute(select(User.id).limit(1))).scalar_one_or_none()
        if owner_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No user exists to own the workspace. Seed a user first.",
            )

        new_workspace = Workspace(
            name=workspace.name,
            description=workspace.description,
            slug=workspace.slug,
            owner_id=owner_id,
            workspace_type=workspace.workspace_type,
            authority_level=workspace.authority_level,
            swarm_enabled=workspace.swarm_enabled,
            company_mode_enabled=workspace.company_mode_enabled,
            company_name=workspace.company_name,
        )

        db.add(new_workspace)
        await db.commit()
        await db.refresh(new_workspace)

        return WorkspaceInfo(
            id=str(new_workspace.id),
            name=new_workspace.name,
            description=new_workspace.description,
            slug=new_workspace.slug,
            owner_id=str(new_workspace.owner_id),
            is_active=new_workspace.is_active,
            is_archived=new_workspace.is_archived,
            workspace_type=new_workspace.workspace_type,
            authority_level=new_workspace.authority_level,
            max_subagents=new_workspace.max_subagents,
            active_subagent_count=new_workspace.active_subagent_count,
            swarm_enabled=new_workspace.swarm_enabled,
            self_evolution_enabled=new_workspace.self_evolution_enabled,
            company_mode_enabled=new_workspace.company_mode_enabled,
            company_name=new_workspace.company_name,
            total_tasks=new_workspace.total_tasks,
            completed_tasks=new_workspace.completed_tasks,
            total_tokens_used=new_workspace.total_tokens_used,
            created_at=new_workspace.created_at,
            updated_at=new_workspace.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating workspace: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create workspace: {str(e)}"
        )


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceInfo,
    summary="Update workspace",
    description="Update workspace configuration"
)
async def update_workspace(
    workspace_id: UUID,
    workspace_update: WorkspaceUpdate,
    db: Session = Depends(get_db),
) -> WorkspaceInfo:
    """
    Update workspace.

    Args:
        workspace_id: Workspace UUID
        workspace_update: Fields to update
        db: Database session

    Returns:
        Updated workspace information

    Raises:
        404: If workspace not found
    """
    try:
        result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace '{workspace_id}' not found"
            )

        # Update fields
        if workspace_update.name is not None:
            workspace.name = workspace_update.name
        if workspace_update.description is not None:
            workspace.description = workspace_update.description
        if workspace_update.is_active is not None:
            workspace.is_active = workspace_update.is_active
        if workspace_update.is_archived is not None:
            workspace.is_archived = workspace_update.is_archived
        if workspace_update.authority_level is not None:
            workspace.authority_level = workspace_update.authority_level
        if workspace_update.swarm_enabled is not None:
            workspace.swarm_enabled = workspace_update.swarm_enabled
        if workspace_update.company_mode_enabled is not None:
            workspace.company_mode_enabled = workspace_update.company_mode_enabled

        await db.commit()
        await db.refresh(workspace)

        return WorkspaceInfo(
            id=str(workspace.id),
            name=workspace.name,
            description=workspace.description,
            slug=workspace.slug,
            owner_id=str(workspace.owner_id),
            is_active=workspace.is_active,
            is_archived=workspace.is_archived,
            workspace_type=workspace.workspace_type,
            authority_level=workspace.authority_level,
            max_subagents=workspace.max_subagents,
            active_subagent_count=workspace.active_subagent_count,
            swarm_enabled=workspace.swarm_enabled,
            self_evolution_enabled=workspace.self_evolution_enabled,
            company_mode_enabled=workspace.company_mode_enabled,
            company_name=workspace.company_name,
            total_tasks=workspace.total_tasks,
            completed_tasks=workspace.completed_tasks,
            total_tokens_used=workspace.total_tokens_used,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating workspace: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update workspace: {str(e)}"
        )


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete workspace",
    description="Delete a workspace and all associated data"
)
async def delete_workspace(
    workspace_id: UUID,
    db: Session = Depends(get_db),
) -> None:
    """
    Delete workspace.

    Args:
        workspace_id: Workspace UUID
        db: Database session

    Raises:
        404: If workspace not found
    """
    try:
        result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalar_one_or_none()

        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace '{workspace_id}' not found"
            )

        await db.delete(workspace)
        await db.commit()

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting workspace: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete workspace: {str(e)}"
        )
