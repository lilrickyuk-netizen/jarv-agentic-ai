"""
JARV Backend - Workspace Management Tools

Workspace management: create, delete, list, switch, info, update.
"""
from typing import Dict, Any, Type, List, Optional
from pydantic import BaseModel, Field
from uuid import UUID, uuid4
import logging
import re
from sqlalchemy import func, select

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.models.agent import Agent
from app.models.session import AgentSession
from app.models.task import Task
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


def _workspace_scope(context: ToolContext):
    if context.db_session is None:
        raise ValueError("Workspace database session is unavailable")
    if context.user_id is None:
        raise PermissionError("Authenticated user context is required")
    return context.db_session, UUID(str(context.user_id))


# ===== WORKSPACE CREATE TOOL =====

class WorkspaceCreateInput(BaseModel):
    """Input schema for workspace create tool"""
    name: str = Field(..., description="Workspace name")
    description: Optional[str] = Field(None, description="Workspace description")
    settings: Optional[Dict[str, Any]] = Field(None, description="Workspace settings")


class WorkspaceCreateOutput(BaseModel):
    """Output schema for workspace create tool"""
    workspace_id: str = Field(..., description="Created workspace ID")
    name: str = Field(..., description="Workspace name")
    message: str = Field(..., description="Status message")


class WorkspaceCreateTool(ToolBase):
    """Tool for creating new workspace"""

    @property
    def name(self) -> str:
        return "workspace_create"

    @property
    def description(self) -> str:
        return "Create a new workspace for organizing projects and data."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceCreateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceCreateOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace create"""
        name = input_data["name"]
        description = input_data.get("description")
        settings = input_data.get("settings") or {}

        try:
            db, user_id = _workspace_scope(context)
            base_slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"
            slug = base_slug[:90]
            suffix = 1
            while (await db.execute(
                select(Workspace.id).where(Workspace.slug == slug)
            )).scalar_one_or_none() is not None:
                slug = f"{base_slug[:88]}-{suffix}"
                suffix += 1
            workspace = Workspace(
                id=uuid4(),
                owner_id=user_id,
                name=name,
                slug=slug,
                description=description,
                workspace_type="project",
                authority_level=int(context.metadata.get("authority_level", 3)),
                config=settings,
                is_active=True,
            )
            db.add(workspace)
            await db.flush()
            workspace_id = str(workspace.id)
            logger.info(f"Creating workspace: {name}")

            return self.create_result(
                success=True,
                result_data={
                    "workspace_id": workspace_id,
                    "name": name,
                    "message": f"Workspace '{name}' created successfully",
                },
                output_text=f"Created workspace: {name}",
            )
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to create workspace: {str(e)}")


# ===== WORKSPACE DELETE TOOL =====

class WorkspaceDeleteInput(BaseModel):
    """Input schema for workspace delete tool"""
    workspace_id: str = Field(..., description="Workspace ID to delete")
    force: bool = Field(default=False, description="Force delete with all data")


class WorkspaceDeleteOutput(BaseModel):
    """Output schema for workspace delete tool"""
    workspace_id: str = Field(..., description="Deleted workspace ID")
    message: str = Field(..., description="Status message")


class WorkspaceDeleteTool(ToolBase):
    """Tool for deleting workspace"""

    @property
    def name(self) -> str:
        return "workspace_delete"

    @property
    def description(self) -> str:
        return "Delete a workspace and optionally all its data."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceDeleteInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceDeleteOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    @property
    def requires_approval(self) -> bool:
        return True  # Destructive operation

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace delete"""
        workspace_id = input_data["workspace_id"]
        force = input_data["force"]

        try:
            db, user_id = _workspace_scope(context)
            workspace = (await db.execute(select(Workspace).where(
                Workspace.id == UUID(workspace_id), Workspace.owner_id == user_id
            ))).scalar_one_or_none()
            if workspace is None:
                return self.create_result(success=False, error_message="Owned workspace not found")
            await db.delete(workspace)
            await db.flush()
            logger.info(f"Deleting workspace: {workspace_id}")

            return self.create_result(
                success=True,
                result_data={
                    "workspace_id": workspace_id,
                    "message": f"Workspace deleted successfully",
                },
                output_text=f"Deleted workspace: {workspace_id}",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to delete workspace: {str(e)}")


# ===== WORKSPACE LIST TOOL =====

class WorkspaceListInput(BaseModel):
    """Input schema for workspace list tool"""
    user_id: Optional[str] = Field(None, description="Filter by user ID")
    limit: int = Field(default=50, description="Maximum workspaces to return")


class WorkspaceInfo(BaseModel):
    """Workspace information"""
    workspace_id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str


class WorkspaceListOutput(BaseModel):
    """Output schema for workspace list tool"""
    workspaces: List[WorkspaceInfo] = Field(..., description="List of workspaces")
    count: int = Field(..., description="Number of workspaces")


class WorkspaceListTool(ToolBase):
    """Tool for listing workspaces"""

    @property
    def name(self) -> str:
        return "workspace_list"

    @property
    def description(self) -> str:
        return "List all available workspaces."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceListInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceListOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace list"""
        user_id = input_data.get("user_id")
        limit = input_data["limit"]

        try:
            db, owner_id = _workspace_scope(context)
            if user_id is not None and UUID(user_id) != owner_id:
                return self.create_result(success=False, error_message="Cannot list another user's workspaces")
            rows = (await db.execute(
                select(Workspace).where(Workspace.owner_id == owner_id)
                .order_by(Workspace.created_at.desc()).limit(max(1, min(limit, 100)))))
            workspaces = [{
                "workspace_id": str(row.id),
                "name": row.name,
                "description": row.description,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            } for row in rows.scalars().all()]

            return self.create_result(
                success=True,
                result_data={"workspaces": workspaces, "count": len(workspaces)},
                output_text=f"Found {len(workspaces)} workspace(s)",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to list workspaces: {str(e)}")


# ===== WORKSPACE SWITCH TOOL =====

class WorkspaceSwitchInput(BaseModel):
    """Input schema for workspace switch tool"""
    workspace_id: str = Field(..., description="Workspace ID to switch to")


class WorkspaceSwitchOutput(BaseModel):
    """Output schema for workspace switch tool"""
    workspace_id: str = Field(..., description="Current workspace ID")
    name: str = Field(..., description="Workspace name")
    message: str = Field(..., description="Status message")


class WorkspaceSwitchTool(ToolBase):
    """Tool for switching active workspace"""

    @property
    def name(self) -> str:
        return "workspace_switch"

    @property
    def description(self) -> str:
        return "Switch to a different workspace."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceSwitchInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceSwitchOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace switch"""
        workspace_id = input_data["workspace_id"]

        try:
            db, user_id = _workspace_scope(context)
            if context.session_id is None:
                return self.create_result(
                    success=False,
                    error_message="A persisted agent session is required to switch workspaces.",
                )
            workspace = (await db.execute(select(Workspace).where(
                Workspace.id == UUID(workspace_id), Workspace.owner_id == user_id
            ))).scalar_one_or_none()
            session = (await db.execute(select(AgentSession).where(
                AgentSession.id == context.session_id,
                AgentSession.user_id == user_id,
            ))).scalar_one_or_none()
            if workspace is None or session is None:
                return self.create_result(success=False, error_message="Owned workspace or session not found")
            session.workspace_id = workspace.id
            await db.flush()
            logger.info(f"Switching to workspace: {workspace_id}")

            return self.create_result(
                success=True,
                result_data={
                    "workspace_id": workspace_id,
                    "name": workspace.name,
                    "message": f"Switched to workspace: {workspace_id}",
                },
                output_text=f"Switched to workspace: {workspace_id}",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to switch workspace: {str(e)}")


# ===== WORKSPACE INFO TOOL =====

class WorkspaceInfoInput(BaseModel):
    """Input schema for workspace info tool"""
    workspace_id: str = Field(..., description="Workspace ID")


class WorkspaceInfoOutput(BaseModel):
    """Output schema for workspace info tool"""
    workspace_id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    settings: Dict[str, Any]
    stats: Dict[str, int]


class WorkspaceInfoTool(ToolBase):
    """Tool for getting workspace information"""

    @property
    def name(self) -> str:
        return "workspace_info"

    @property
    def description(self) -> str:
        return "Get detailed information about a workspace."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceInfoInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceInfoOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_1_BASIC_TOOLS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace info"""
        workspace_id = input_data["workspace_id"]

        try:
            db, user_id = _workspace_scope(context)
            workspace = (await db.execute(select(Workspace).where(
                Workspace.id == UUID(workspace_id), Workspace.owner_id == user_id
            ))).scalar_one_or_none()
            if workspace is None:
                return self.create_result(success=False, error_message="Owned workspace not found")
            task_count = int((await db.execute(
                select(func.count()).select_from(Task).where(Task.workspace_id == workspace.id)
            )).scalar_one())
            agent_count = int((await db.execute(
                select(func.count()).select_from(Agent).where(Agent.workspace_id == workspace.id)
            )).scalar_one())
            info = {
                "workspace_id": str(workspace.id),
                "name": workspace.name,
                "description": workspace.description,
                "created_at": workspace.created_at.isoformat(),
                "updated_at": workspace.updated_at.isoformat(),
                "settings": workspace.config or {},
                "stats": {"tasks": task_count, "files": 0, "agents": agent_count},
            }

            return self.create_result(
                success=True,
                result_data=info,
                output_text=f"Retrieved info for workspace: {workspace_id}",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to get workspace info: {str(e)}")


# ===== WORKSPACE UPDATE TOOL =====

class WorkspaceUpdateInput(BaseModel):
    """Input schema for workspace update tool"""
    workspace_id: str = Field(..., description="Workspace ID")
    name: Optional[str] = Field(None, description="New name")
    description: Optional[str] = Field(None, description="New description")
    settings: Optional[Dict[str, Any]] = Field(None, description="Updated settings")


class WorkspaceUpdateOutput(BaseModel):
    """Output schema for workspace update tool"""
    workspace_id: str
    updated_fields: List[str]
    message: str


class WorkspaceUpdateTool(ToolBase):
    """Tool for updating workspace"""

    @property
    def name(self) -> str:
        return "workspace_update"

    @property
    def description(self) -> str:
        return "Update workspace name, description, or settings."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceUpdateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceUpdateOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "workspace"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute workspace update"""
        workspace_id = input_data["workspace_id"]
        name = input_data.get("name")
        description = input_data.get("description")
        settings = input_data.get("settings")

        try:
            db, user_id = _workspace_scope(context)
            workspace = (await db.execute(select(Workspace).where(
                Workspace.id == UUID(workspace_id), Workspace.owner_id == user_id
            ))).scalar_one_or_none()
            if workspace is None:
                return self.create_result(success=False, error_message="Owned workspace not found")
            updated_fields = []
            if name is not None:
                if not name.strip():
                    return self.create_result(success=False, error_message="Workspace name cannot be empty")
                workspace.name = name.strip()
                updated_fields.append("name")
            if description is not None:
                workspace.description = description
                updated_fields.append("description")
            if settings is not None:
                workspace.config = settings
                updated_fields.append("settings")
            await db.flush()

            logger.info(f"Updating workspace {workspace_id}: {updated_fields}")

            return self.create_result(
                success=True,
                result_data={
                    "workspace_id": workspace_id,
                    "updated_fields": updated_fields,
                    "message": f"Updated {len(updated_fields)} field(s)",
                },
                output_text=f"Updated workspace: {workspace_id}",
            )
        except PermissionError as e:
            return self.create_result(success=False, error_message=str(e))
        except Exception as e:
            return self.create_result(success=False, error_message=f"Failed to update workspace: {str(e)}")
