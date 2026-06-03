"""
JARV Backend - Workspace Manager

Manages workspace lifecycle, configuration, and operations.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field
import logging
import re

logger = logging.getLogger(__name__)


class WorkspaceCreate(BaseModel):
    """Schema for creating a workspace"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    workspace_type: str = Field(default="general")
    authority_level: int = Field(default=3, ge=0, le=10)
    owner_id: UUID
    config: Dict[str, Any] = Field(default_factory=dict)
    swarm_enabled: bool = True
    self_evolution_enabled: bool = False
    company_mode_enabled: bool = False
    max_subagents: int = Field(default=50, ge=1, le=1000)


class WorkspaceUpdate(BaseModel):
    """Schema for updating a workspace"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    workspace_type: Optional[str] = None
    authority_level: Optional[int] = Field(None, ge=0, le=10)
    config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    swarm_enabled: Optional[bool] = None
    self_evolution_enabled: Optional[bool] = None
    company_mode_enabled: Optional[bool] = None
    max_subagents: Optional[int] = Field(None, ge=1, le=1000)
    company_name: Optional[str] = None
    company_mission: Optional[str] = None
    company_structure: Optional[Dict[str, Any]] = None


class WorkspaceResult(BaseModel):
    """Schema for workspace retrieval result"""
    id: UUID
    name: str
    description: Optional[str]
    slug: str
    owner_id: UUID
    is_active: bool
    is_template: bool
    is_archived: bool
    workspace_type: str
    authority_level: int
    config: Dict[str, Any]
    max_subagents: int
    active_subagent_count: int
    swarm_enabled: bool
    self_evolution_enabled: bool
    company_mode_enabled: bool
    company_name: Optional[str]
    company_mission: Optional[str]
    company_structure: Optional[Dict[str, Any]]
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
    template_workspaces: int
    total_agents: int
    total_tasks: int
    completed_tasks: int
    total_tokens_used: int
    by_type: Dict[str, int]


class WorkspaceManager:
    """
    Manages workspace lifecycle and operations.

    Handles workspace creation, configuration, activation, archiving, and deletion.
    """

    def __init__(self):
        """Initialize workspace manager"""
        self.logger = logging.getLogger("workspaces.manager")

    def _generate_slug(self, name: str) -> str:
        """
        Generate URL-friendly slug from workspace name.

        Args:
            name: Workspace name

        Returns:
            URL-friendly slug
        """
        # Convert to lowercase and replace spaces/special chars with hyphens
        slug = name.lower()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')

        # Truncate if too long
        if len(slug) > 100:
            slug = slug[:100]

        return slug

    async def create_workspace(
        self,
        workspace: WorkspaceCreate,
    ) -> UUID:
        """
        Create a new workspace.

        In production: Insert into Workspace table.

        Args:
            workspace: Workspace creation data

        Returns:
            Workspace ID
        """
        try:
            # Generate slug
            slug = self._generate_slug(workspace.name)

            # In production: Check for duplicate slug and append number if needed
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     # Check for duplicate
            #     counter = 1
            #     original_slug = slug
            #     while True:
            #         existing = await db.execute(
            #             select(DBWorkspace).where(DBWorkspace.slug == slug)
            #         )
            #         if not existing.first():
            #             break
            #         slug = f"{original_slug}-{counter}"
            #         counter += 1
            #
            #     # Create workspace
            #     db_workspace = DBWorkspace(
            #         name=workspace.name,
            #         description=workspace.description,
            #         slug=slug,
            #         owner_id=workspace.owner_id,
            #         workspace_type=workspace.workspace_type,
            #         authority_level=workspace.authority_level,
            #         config=workspace.config,
            #         max_subagents=workspace.max_subagents,
            #         swarm_enabled=workspace.swarm_enabled,
            #         self_evolution_enabled=workspace.self_evolution_enabled,
            #         company_mode_enabled=workspace.company_mode_enabled,
            #     )
            #     db.add(db_workspace)
            #     await db.commit()
            #     workspace_id = db_workspace.id

            # Placeholder
            from uuid import uuid4
            workspace_id = uuid4()

            self.logger.info(
                f"Created workspace: {workspace.name}",
                extra={
                    "workspace_id": str(workspace_id),
                    "owner_id": str(workspace.owner_id),
                    "type": workspace.workspace_type,
                    "slug": slug,
                }
            )

            return workspace_id

        except Exception as e:
            self.logger.error(
                f"Failed to create workspace: {e}",
                extra={"name": workspace.name},
                exc_info=True
            )
            raise

    async def get_workspace(
        self,
        workspace_id: UUID,
    ) -> Optional[WorkspaceResult]:
        """
        Get workspace by ID.

        In production: Query Workspace table.

        Args:
            workspace_id: Workspace ID

        Returns:
            WorkspaceResult if found
        """
        try:
            # In production: Query database
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     workspace = await db.get(DBWorkspace, workspace_id)
            #     if workspace:
            #         return WorkspaceResult.from_orm(workspace)

            self.logger.debug(
                f"Retrieved workspace {workspace_id}",
                extra={"workspace_id": str(workspace_id)}
            )

            return None

        except Exception as e:
            self.logger.error(
                f"Failed to get workspace: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            return None

    async def get_workspace_by_slug(
        self,
        slug: str,
    ) -> Optional[WorkspaceResult]:
        """
        Get workspace by slug.

        In production: Query Workspace table.

        Args:
            slug: Workspace slug

        Returns:
            WorkspaceResult if found
        """
        try:
            # In production: Query database
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     result = await db.execute(
            #         select(DBWorkspace).where(DBWorkspace.slug == slug)
            #     )
            #     workspace = result.scalar_one_or_none()
            #     if workspace:
            #         return WorkspaceResult.from_orm(workspace)

            self.logger.debug(
                f"Retrieved workspace by slug: {slug}",
                extra={"slug": slug}
            )

            return None

        except Exception as e:
            self.logger.error(
                f"Failed to get workspace by slug: {e}",
                extra={"slug": slug},
                exc_info=True
            )
            return None

    async def update_workspace(
        self,
        workspace_id: UUID,
        updates: WorkspaceUpdate,
    ) -> bool:
        """
        Update workspace.

        In production: Update Workspace table.

        Args:
            workspace_id: Workspace ID
            updates: Fields to update

        Returns:
            True if successful
        """
        try:
            # In production: Update database
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     workspace = await db.get(DBWorkspace, workspace_id)
            #     if not workspace:
            #         return False
            #
            #     # Update fields
            #     for field, value in updates.dict(exclude_unset=True).items():
            #         setattr(workspace, field, value)
            #
            #     # Regenerate slug if name changed
            #     if updates.name:
            #         workspace.slug = self._generate_slug(updates.name)
            #
            #     await db.commit()

            self.logger.info(
                f"Updated workspace {workspace_id}",
                extra={"workspace_id": str(workspace_id)}
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to update workspace: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            return False

    async def delete_workspace(
        self,
        workspace_id: UUID,
        hard_delete: bool = False,
    ) -> bool:
        """
        Delete or archive workspace.

        In production: Archive or delete from Workspace table.

        Args:
            workspace_id: Workspace ID
            hard_delete: If True, permanently delete; if False, archive

        Returns:
            True if successful
        """
        try:
            # In production: Archive or delete
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     workspace = await db.get(DBWorkspace, workspace_id)
            #     if not workspace:
            #         return False
            #
            #     if hard_delete:
            #         await db.delete(workspace)
            #     else:
            #         workspace.is_archived = True
            #         workspace.is_active = False
            #
            #     await db.commit()

            self.logger.info(
                f"{'Deleted' if hard_delete else 'Archived'} workspace {workspace_id}",
                extra={"workspace_id": str(workspace_id), "hard_delete": hard_delete}
            )

            return True

        except Exception as e:
            self.logger.error(
                f"Failed to delete workspace: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            return False

    async def activate_workspace(self, workspace_id: UUID) -> bool:
        """
        Activate a workspace.

        Args:
            workspace_id: Workspace ID

        Returns:
            True if successful
        """
        return await self.update_workspace(
            workspace_id,
            WorkspaceUpdate(is_active=True, is_archived=False)
        )

    async def list_workspaces(
        self,
        owner_id: Optional[UUID] = None,
        workspace_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_archived: Optional[bool] = None,
        is_template: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[WorkspaceResult]:
        """
        List workspaces with filters.

        In production: Query Workspace table.

        Args:
            owner_id: Optional owner filter
            workspace_type: Optional type filter
            is_active: Optional active filter
            is_archived: Optional archived filter
            is_template: Optional template filter
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of workspaces
        """
        try:
            # In production: Query database
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     query = select(DBWorkspace)
            #
            #     if owner_id:
            #         query = query.where(DBWorkspace.owner_id == owner_id)
            #     if workspace_type:
            #         query = query.where(DBWorkspace.workspace_type == workspace_type)
            #     if is_active is not None:
            #         query = query.where(DBWorkspace.is_active == is_active)
            #     if is_archived is not None:
            #         query = query.where(DBWorkspace.is_archived == is_archived)
            #     if is_template is not None:
            #         query = query.where(DBWorkspace.is_template == is_template)
            #
            #     results = await db.execute(
            #         query.order_by(DBWorkspace.updated_at.desc())
            #         .limit(limit)
            #         .offset(offset)
            #     )
            #
            #     return [WorkspaceResult.from_orm(row) for row in results]

            self.logger.debug(
                "Listed workspaces",
                extra={"owner_id": str(owner_id) if owner_id else None, "limit": limit}
            )

            return []

        except Exception as e:
            self.logger.error(
                f"Failed to list workspaces: {e}",
                exc_info=True
            )
            return []

    async def get_workspace_stats(
        self,
        owner_id: Optional[UUID] = None,
    ) -> WorkspaceStats:
        """
        Get workspace statistics.

        In production: Query Workspace table with aggregations.

        Args:
            owner_id: Optional owner filter

        Returns:
            WorkspaceStats
        """
        try:
            # In production: Query database with aggregations
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     query = select(DBWorkspace)
            #     if owner_id:
            #         query = query.where(DBWorkspace.owner_id == owner_id)
            #
            #     # Count by various filters
            #     total = await db.execute(select(func.count()).select_from(query.subquery()))
            #     active = await db.execute(
            #         select(func.count()).select_from(
            #             query.where(DBWorkspace.is_active == True).subquery()
            #         )
            #     )
            #     ...

            stats = WorkspaceStats(
                total_workspaces=0,
                active_workspaces=0,
                archived_workspaces=0,
                template_workspaces=0,
                total_agents=0,
                total_tasks=0,
                completed_tasks=0,
                total_tokens_used=0,
                by_type={},
            )

            self.logger.debug(
                "Retrieved workspace statistics",
                extra={"owner_id": str(owner_id) if owner_id else None}
            )

            return stats

        except Exception as e:
            self.logger.error(
                f"Failed to get workspace stats: {e}",
                exc_info=True
            )
            return WorkspaceStats(
                total_workspaces=0,
                active_workspaces=0,
                archived_workspaces=0,
                template_workspaces=0,
                total_agents=0,
                total_tasks=0,
                completed_tasks=0,
                total_tokens_used=0,
                by_type={},
            )


# Global workspace manager
_workspace_manager = WorkspaceManager()


async def create_workspace(workspace: WorkspaceCreate) -> UUID:
    """
    Global function to create a workspace.

    Args:
        workspace: Workspace creation data

    Returns:
        Workspace ID
    """
    return await _workspace_manager.create_workspace(workspace)


async def get_workspace(workspace_id: UUID) -> Optional[WorkspaceResult]:
    """
    Global function to get a workspace.

    Args:
        workspace_id: Workspace ID

    Returns:
        WorkspaceResult if found
    """
    return await _workspace_manager.get_workspace(workspace_id)
