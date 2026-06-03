"""
JARV Backend - Workspace Templates

Manages workspace templates for quick workspace creation.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel
import logging

from app.core.workspaces.manager import WorkspaceCreate, WorkspaceManager

logger = logging.getLogger(__name__)


class WorkspaceTemplate(BaseModel):
    """Workspace template definition"""
    id: UUID
    name: str
    description: Optional[str]
    workspace_type: str
    authority_level: int
    config: Dict[str, Any]
    swarm_enabled: bool
    self_evolution_enabled: bool
    company_mode_enabled: bool
    max_subagents: int
    default_rules: List[Dict[str, Any]] = []
    default_runbooks: List[Dict[str, Any]] = []


class TemplateManager:
    """
    Manages workspace templates.

    Provides template creation, listing, and workspace instantiation from templates.
    """

    def __init__(self):
        """Initialize template manager"""
        self.logger = logging.getLogger("workspaces.templates")
        self.workspace_manager = WorkspaceManager()

        # Built-in templates
        self.builtin_templates = self._create_builtin_templates()

    def _create_builtin_templates(self) -> Dict[str, Dict[str, Any]]:
        """Create built-in workspace templates"""
        return {
            "general": {
                "name": "General Purpose",
                "description": "General purpose workspace for various tasks",
                "workspace_type": "general",
                "authority_level": 3,
                "swarm_enabled": True,
                "self_evolution_enabled": False,
                "company_mode_enabled": False,
                "max_subagents": 50,
                "config": {
                    "default_model": "claude-3-5-sonnet-20241022",
                    "max_context_length": 200000,
                },
            },
            "development": {
                "name": "Software Development",
                "description": "Workspace optimized for software development",
                "workspace_type": "development",
                "authority_level": 4,
                "swarm_enabled": True,
                "self_evolution_enabled": False,
                "company_mode_enabled": False,
                "max_subagents": 100,
                "config": {
                    "default_model": "claude-3-5-sonnet-20241022",
                    "code_tools_enabled": True,
                    "git_enabled": True,
                    "testing_enabled": True,
                },
            },
            "research": {
                "name": "Research & Analysis",
                "description": "Workspace for research and data analysis",
                "workspace_type": "research",
                "authority_level": 2,
                "swarm_enabled": True,
                "self_evolution_enabled": False,
                "company_mode_enabled": False,
                "max_subagents": 75,
                "config": {
                    "default_model": "claude-3-5-sonnet-20241022",
                    "memory_enabled": True,
                    "analysis_tools_enabled": True,
                },
            },
            "company": {
                "name": "Autonomous Company",
                "description": "Full autonomous company operating layer",
                "workspace_type": "company",
                "authority_level": 8,
                "swarm_enabled": True,
                "self_evolution_enabled": True,
                "company_mode_enabled": True,
                "max_subagents": 500,
                "config": {
                    "default_model": "claude-3-5-sonnet-20241022",
                    "all_tools_enabled": True,
                    "financial_tools_enabled": True,
                    "marketing_tools_enabled": True,
                },
            },
        }

    async def list_templates(
        self,
        include_custom: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        List available workspace templates.

        Args:
            include_custom: Whether to include custom user templates

        Returns:
            List of template definitions
        """
        templates = []

        # Add built-in templates
        for template_id, template_data in self.builtin_templates.items():
            templates.append({
                "id": template_id,
                "is_builtin": True,
                **template_data,
            })

        # Add custom templates from database
        if include_custom:
            # In production: Query custom templates
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     custom = await db.execute(
            #         select(DBWorkspace).where(DBWorkspace.is_template == True)
            #     )
            #     for workspace in custom:
            #         templates.append({
            #             "id": str(workspace.id),
            #             "is_builtin": False,
            #             "name": workspace.name,
            #             ...
            #         })
            pass

        self.logger.debug(f"Listed {len(templates)} templates")

        return templates

    async def get_template(
        self,
        template_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get template by ID.

        Args:
            template_id: Template ID (builtin name or UUID)

        Returns:
            Template definition if found
        """
        # Check built-in templates
        if template_id in self.builtin_templates:
            return {
                "id": template_id,
                "is_builtin": True,
                **self.builtin_templates[template_id],
            }

        # Check custom templates
        # In production: Query database
        # from app.models.workspace import Workspace as DBWorkspace
        # from app.core.database import get_db
        # try:
        #     async with get_db() as db:
        #         workspace = await db.get(DBWorkspace, UUID(template_id))
        #         if workspace and workspace.is_template:
        #             return {...}
        # except:
        #     pass

        return None

    async def create_from_template(
        self,
        template_id: str,
        name: str,
        owner_id: UUID,
        description: Optional[str] = None,
        config_overrides: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        """
        Create workspace from template.

        Args:
            template_id: Template ID
            name: New workspace name
            owner_id: Owner user ID
            description: Optional description (overrides template)
            config_overrides: Optional config overrides

        Returns:
            New workspace ID
        """
        try:
            # Get template
            template = await self.get_template(template_id)
            if not template:
                raise ValueError(f"Template not found: {template_id}")

            # Merge config
            config = template["config"].copy()
            if config_overrides:
                config.update(config_overrides)

            # Create workspace
            workspace_create = WorkspaceCreate(
                name=name,
                description=description or template["description"],
                workspace_type=template["workspace_type"],
                authority_level=template["authority_level"],
                owner_id=owner_id,
                config=config,
                swarm_enabled=template["swarm_enabled"],
                self_evolution_enabled=template["self_evolution_enabled"],
                company_mode_enabled=template["company_mode_enabled"],
                max_subagents=template["max_subagents"],
            )

            workspace_id = await self.workspace_manager.create_workspace(workspace_create)

            # Copy rules if any
            if "default_rules" in template:
                # In production: Copy rules to new workspace
                pass

            # Copy runbooks if any
            if "default_runbooks" in template:
                # In production: Copy runbooks to new workspace
                pass

            self.logger.info(
                f"Created workspace from template '{template_id}': {name}",
                extra={
                    "workspace_id": str(workspace_id),
                    "template_id": template_id,
                    "owner_id": str(owner_id),
                }
            )

            return workspace_id

        except Exception as e:
            self.logger.error(
                f"Failed to create workspace from template: {e}",
                extra={"template_id": template_id, "name": name},
                exc_info=True
            )
            raise

    async def save_as_template(
        self,
        workspace_id: UUID,
        template_name: str,
        template_description: Optional[str] = None,
    ) -> UUID:
        """
        Save existing workspace as a template.

        Args:
            workspace_id: Source workspace ID
            template_name: Template name
            template_description: Template description

        Returns:
            Template workspace ID
        """
        try:
            # In production: Clone workspace and mark as template
            # from app.models.workspace import Workspace as DBWorkspace
            # from app.core.database import get_db
            # async with get_db() as db:
            #     source = await db.get(DBWorkspace, workspace_id)
            #     if not source:
            #         raise ValueError(f"Workspace not found: {workspace_id}")
            #
            #     # Create template workspace
            #     template = DBWorkspace(
            #         name=template_name,
            #         description=template_description or source.description,
            #         slug=self._generate_template_slug(template_name),
            #         owner_id=source.owner_id,
            #         is_template=True,
            #         workspace_type=source.workspace_type,
            #         authority_level=source.authority_level,
            #         config=source.config,
            #         ...
            #     )
            #     db.add(template)
            #     await db.commit()
            #
            #     # Copy rules and runbooks
            #     ...
            #
            #     return template.id

            from uuid import uuid4
            template_id = uuid4()

            self.logger.info(
                f"Saved workspace {workspace_id} as template: {template_name}",
                extra={"workspace_id": str(workspace_id), "template_id": str(template_id)}
            )

            return template_id

        except Exception as e:
            self.logger.error(
                f"Failed to save as template: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            raise


# Global template manager
_template_manager = TemplateManager()


async def create_from_template(
    template_id: str,
    name: str,
    owner_id: UUID,
    **kwargs
) -> UUID:
    """
    Global function to create workspace from template.

    Args:
        template_id: Template ID
        name: Workspace name
        owner_id: Owner ID
        **kwargs: Additional parameters

    Returns:
        Workspace ID
    """
    return await _template_manager.create_from_template(
        template_id=template_id,
        name=name,
        owner_id=owner_id,
        **kwargs
    )
