"""
JARV Backend - Company Structure

Manages company organizational structure, roles, and departments.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


class RoleCreate(BaseModel):
    """Schema for creating a company role"""
    workspace_id: UUID
    role_name: str = Field(..., min_length=1, max_length=255)
    role_type: str
    department: Optional[str] = None
    description: Optional[str] = None
    parent_role_id: Optional[UUID] = None
    level: int = Field(default=1, ge=1, le=10)
    responsibilities: List[str] = Field(default_factory=list)
    kpis: Optional[Dict[str, Any]] = None
    authority_level: int = Field(default=3, ge=0, le=10)
    skills_required: List[str] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)


class RoleResult(BaseModel):
    """Company role result"""
    id: UUID
    workspace_id: UUID
    role_name: str
    role_type: str
    department: Optional[str]
    description: Optional[str]
    parent_role_id: Optional[UUID]
    level: int
    responsibilities: List[str]
    kpis: Optional[Dict[str, Any]]
    authority_level: int
    config: Dict[str, Any]
    skills_required: List[str]
    is_active: bool
    is_automated: bool
    total_agents: int
    tasks_completed: int


class OrganizationChart(BaseModel):
    """Organization chart structure"""
    workspace_id: UUID
    total_roles: int
    total_departments: int
    max_depth: int
    departments: Dict[str, List[RoleResult]]
    hierarchy: List[Dict[str, Any]]


class CompanyStructure:
    """
    Manages company organizational structure.

    Handles roles, departments, hierarchy, and organizational charts.
    """

    def __init__(self):
        """Initialize company structure manager"""
        self.logger = logging.getLogger("company.structure")

        # Standard departments
        self.standard_departments = [
            "executive",
            "engineering",
            "product",
            "marketing",
            "sales",
            "support",
            "operations",
            "finance",
            "hr",
        ]

        # Standard roles by department
        self.standard_roles = self._create_standard_roles()

    def _create_standard_roles(self) -> Dict[str, List[Dict[str, Any]]]:
        """Create standard role templates"""
        return {
            "executive": [
                {
                    "role_name": "CEO",
                    "role_type": "executive",
                    "level": 1,
                    "authority_level": 10,
                    "responsibilities": ["Strategic direction", "Company vision", "Major decisions"],
                },
                {
                    "role_name": "CTO",
                    "role_type": "executive",
                    "level": 2,
                    "authority_level": 9,
                    "responsibilities": ["Technology strategy", "Engineering oversight", "Technical decisions"],
                },
            ],
            "engineering": [
                {
                    "role_name": "Engineering Manager",
                    "role_type": "manager",
                    "level": 3,
                    "authority_level": 7,
                    "responsibilities": ["Team management", "Sprint planning", "Code reviews"],
                },
                {
                    "role_name": "Senior Engineer",
                    "role_type": "individual_contributor",
                    "level": 4,
                    "authority_level": 5,
                    "responsibilities": ["Feature development", "Architecture", "Mentoring"],
                },
            ],
            "product": [
                {
                    "role_name": "Product Manager",
                    "role_type": "manager",
                    "level": 3,
                    "authority_level": 6,
                    "responsibilities": ["Product strategy", "Roadmap", "Requirements"],
                },
            ],
        }

    async def create_role(
        self,
        role: RoleCreate,
    ) -> UUID:
        """
        Create a company role.

        In production: Insert into CompanyRole table.

        Args:
            role: Role creation data

        Returns:
            Role ID
        """
        try:
            # In production: Insert into database
            # from app.models.company import CompanyRole as DBRole
            # from app.core.database import get_db
            # async with get_db() as db:
            #     db_role = DBRole(
            #         workspace_id=role.workspace_id,
            #         role_name=role.role_name,
            #         role_type=role.role_type,
            #         department=role.department,
            #         description=role.description,
            #         parent_role_id=role.parent_role_id,
            #         level=role.level,
            #         responsibilities=role.responsibilities,
            #         kpis=role.kpis,
            #         authority_level=role.authority_level,
            #         skills_required=role.skills_required,
            #         config=role.config,
            #     )
            #     db.add(db_role)
            #     await db.commit()
            #     role_id = db_role.id

            from uuid import uuid4
            role_id = uuid4()

            self.logger.info(
                f"Created role: {role.role_name}",
                extra={
                    "role_id": str(role_id),
                    "workspace_id": str(role.workspace_id),
                    "department": role.department,
                }
            )

            return role_id

        except Exception as e:
            self.logger.error(
                f"Failed to create role: {e}",
                extra={"role_name": role.role_name},
                exc_info=True
            )
            raise

    async def get_role(self, role_id: UUID) -> Optional[RoleResult]:
        """Get role by ID"""
        # In production: Query database
        return None

    async def list_roles(
        self,
        workspace_id: UUID,
        department: Optional[str] = None,
        role_type: Optional[str] = None,
        parent_role_id: Optional[UUID] = None,
    ) -> List[RoleResult]:
        """List roles with filters"""
        # In production: Query database
        return []

    async def get_organization_chart(
        self,
        workspace_id: UUID,
    ) -> OrganizationChart:
        """
        Get organization chart for workspace.

        Args:
            workspace_id: Workspace ID

        Returns:
            OrganizationChart with hierarchy
        """
        try:
            # In production: Query all roles and build hierarchy
            # from app.models.company import CompanyRole as DBRole
            # from app.core.database import get_db
            # async with get_db() as db:
            #     roles = await db.execute(
            #         select(DBRole).where(DBRole.workspace_id == workspace_id)
            #     )
            #
            #     # Build hierarchy tree
            #     hierarchy = self._build_hierarchy(roles)
            #
            #     # Group by department
            #     departments = self._group_by_department(roles)

            chart = OrganizationChart(
                workspace_id=workspace_id,
                total_roles=0,
                total_departments=0,
                max_depth=0,
                departments={},
                hierarchy=[],
            )

            return chart

        except Exception as e:
            self.logger.error(
                f"Failed to get organization chart: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            raise

    def _build_hierarchy(self, roles: List[RoleResult]) -> List[Dict[str, Any]]:
        """Build hierarchical structure from flat role list"""
        role_map = {role.id: role for role in roles}
        hierarchy = []

        # Find root roles (no parent)
        for role in roles:
            if not role.parent_role_id:
                hierarchy.append(self._build_role_tree(role, role_map))

        return hierarchy

    def _build_role_tree(
        self,
        role: RoleResult,
        role_map: Dict[UUID, RoleResult],
    ) -> Dict[str, Any]:
        """Recursively build role tree"""
        tree = {
            "role": role,
            "children": [],
        }

        # Find child roles
        for child_id, child_role in role_map.items():
            if child_role.parent_role_id == role.id:
                tree["children"].append(self._build_role_tree(child_role, role_map))

        return tree

    async def initialize_standard_structure(
        self,
        workspace_id: UUID,
    ) -> Dict[str, UUID]:
        """
        Initialize standard company structure.

        Args:
            workspace_id: Workspace ID

        Returns:
            Dict mapping role names to role IDs
        """
        try:
            role_ids = {}

            # Create executive roles
            for role_template in self.standard_roles.get("executive", []):
                role = RoleCreate(
                    workspace_id=workspace_id,
                    department="executive",
                    **role_template
                )
                role_id = await self.create_role(role)
                role_ids[role_template["role_name"]] = role_id

            # Create other departments
            for dept, role_templates in self.standard_roles.items():
                if dept == "executive":
                    continue

                for role_template in role_templates:
                    role = RoleCreate(
                        workspace_id=workspace_id,
                        department=dept,
                        **role_template
                    )
                    role_id = await self.create_role(role)
                    role_ids[role_template["role_name"]] = role_id

            self.logger.info(
                f"Initialized standard structure with {len(role_ids)} roles",
                extra={"workspace_id": str(workspace_id)}
            )

            return role_ids

        except Exception as e:
            self.logger.error(
                f"Failed to initialize structure: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            raise


# Global company structure instance
_company_structure = CompanyStructure()


async def create_role(role: RoleCreate) -> UUID:
    """Global function to create a role"""
    return await _company_structure.create_role(role)


async def get_organization_chart(workspace_id: UUID) -> OrganizationChart:
    """Global function to get organization chart"""
    return await _company_structure.get_organization_chart(workspace_id)
