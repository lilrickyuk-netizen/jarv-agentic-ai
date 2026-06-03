"""
JARV Backend - Boundary Manager

Defines and manages safety boundaries for the system.
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from app.core.agents.base import AuthorityLevel

logger = logging.getLogger(__name__)


class SafetyBoundary(BaseModel):
    """Definition of a safety boundary"""
    name: str
    description: str
    boundary_type: str  # authority, financial, rate, resource, pattern
    enabled: bool = True
    parameters: Dict[str, Any] = Field(default_factory=dict)
    applies_to_users: Optional[List[UUID]] = None
    applies_to_workspaces: Optional[List[UUID]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BoundaryManager:
    """
    Manages safety boundaries across the system.

    Defines, stores, and enforces safety boundaries for users, workspaces, and agents.
    """

    def __init__(self):
        """Initialize boundary manager"""
        self.logger = logging.getLogger("safety.boundaries")

        # Default system boundaries
        self.system_boundaries: Dict[str, SafetyBoundary] = {
            "max_authority_level": SafetyBoundary(
                name="max_authority_level",
                description="Maximum authority level for automated actions",
                boundary_type="authority",
                parameters={
                    "max_level": AuthorityLevel.LEVEL_7_DEPLOYMENT.value,
                    "requires_approval_above": AuthorityLevel.LEVEL_5_NETWORK_ACCESS.value,
                }
            ),
            "financial_transaction_limit": SafetyBoundary(
                name="financial_transaction_limit",
                description="Maximum amount for single financial transaction",
                boundary_type="financial",
                parameters={
                    "max_amount": 1000.0,
                    "currency": "USD",
                    "requires_approval_above": 100.0,
                }
            ),
            "api_rate_limit": SafetyBoundary(
                name="api_rate_limit",
                description="Maximum API calls per time window",
                boundary_type="rate",
                parameters={
                    "max_calls": 1000,
                    "window_minutes": 60,
                    "burst_limit": 100,
                }
            ),
            "token_usage_limit": SafetyBoundary(
                name="token_usage_limit",
                description="Maximum LLM tokens per execution",
                boundary_type="resource",
                parameters={
                    "max_input_tokens": 100000,
                    "max_output_tokens": 50000,
                    "max_total_tokens": 150000,
                }
            ),
            "database_write_limit": SafetyBoundary(
                name="database_write_limit",
                description="Maximum database write operations per execution",
                boundary_type="resource",
                parameters={
                    "max_inserts": 1000,
                    "max_updates": 5000,
                    "max_deletes": 100,
                }
            ),
            "file_operation_limit": SafetyBoundary(
                name="file_operation_limit",
                description="Maximum file operations per execution",
                boundary_type="resource",
                parameters={
                    "max_reads": 100,
                    "max_writes": 50,
                    "max_size_mb": 100,
                }
            ),
        }

    async def get_boundary(self, name: str) -> Optional[SafetyBoundary]:
        """
        Get boundary definition by name.

        Args:
            name: Boundary name

        Returns:
            SafetyBoundary if found
        """
        return self.system_boundaries.get(name)

    async def get_all_boundaries(self) -> List[SafetyBoundary]:
        """
        Get all defined boundaries.

        Returns:
            List of boundaries
        """
        return list(self.system_boundaries.values())

    async def create_boundary(
        self,
        boundary: SafetyBoundary,
    ) -> SafetyBoundary:
        """
        Create a new safety boundary.

        In production: Store in database.

        Args:
            boundary: Boundary to create

        Returns:
            Created boundary
        """
        try:
            # In production: Store in database
            # from app.models.boundary import SafetyBoundary as DBBoundary
            # from app.core.database import get_db
            # async with get_db() as db:
            #     db_boundary = DBBoundary(**boundary.dict())
            #     db.add(db_boundary)
            #     await db.commit()

            self.system_boundaries[boundary.name] = boundary

            self.logger.info(
                f"Created safety boundary: {boundary.name}",
                extra={"boundary_name": boundary.name, "type": boundary.boundary_type}
            )

            return boundary

        except Exception as e:
            self.logger.error(
                f"Failed to create boundary: {e}",
                extra={"boundary_name": boundary.name},
                exc_info=True
            )
            raise

    async def update_boundary(
        self,
        name: str,
        updates: Dict[str, Any],
    ) -> Optional[SafetyBoundary]:
        """
        Update an existing boundary.

        In production: Update database.

        Args:
            name: Boundary name
            updates: Fields to update

        Returns:
            Updated boundary if found
        """
        try:
            boundary = self.system_boundaries.get(name)
            if not boundary:
                return None

            # Update fields
            for key, value in updates.items():
                if hasattr(boundary, key):
                    setattr(boundary, key, value)

            boundary.updated_at = datetime.utcnow()

            # In production: Update database
            # from app.models.boundary import SafetyBoundary as DBBoundary
            # from app.core.database import get_db
            # async with get_db() as db:
            #     db_boundary = await db.get(DBBoundary, name)
            #     for key, value in updates.items():
            #         setattr(db_boundary, key, value)
            #     await db.commit()

            self.logger.info(
                f"Updated safety boundary: {name}",
                extra={"boundary_name": name, "updates": list(updates.keys())}
            )

            return boundary

        except Exception as e:
            self.logger.error(
                f"Failed to update boundary: {e}",
                extra={"boundary_name": name},
                exc_info=True
            )
            return None

    async def delete_boundary(self, name: str) -> bool:
        """
        Delete a boundary.

        In production: Delete from database.

        Args:
            name: Boundary name

        Returns:
            True if deleted
        """
        try:
            if name in self.system_boundaries:
                del self.system_boundaries[name]

                # In production: Delete from database
                # from app.models.boundary import SafetyBoundary as DBBoundary
                # from app.core.database import get_db
                # async with get_db() as db:
                #     boundary = await db.get(DBBoundary, name)
                #     if boundary:
                #         await db.delete(boundary)
                #         await db.commit()

                self.logger.info(
                    f"Deleted safety boundary: {name}",
                    extra={"boundary_name": name}
                )

                return True

            return False

        except Exception as e:
            self.logger.error(
                f"Failed to delete boundary: {e}",
                extra={"boundary_name": name},
                exc_info=True
            )
            return False

    async def get_user_boundaries(
        self,
        user_id: UUID,
    ) -> List[SafetyBoundary]:
        """
        Get boundaries that apply to a specific user.

        In production: Query database for user-specific boundaries.

        Args:
            user_id: User ID

        Returns:
            List of applicable boundaries
        """
        try:
            # In production: Query database
            # from app.models.boundary import SafetyBoundary as DBBoundary
            # from app.core.database import get_db
            # async with get_db() as db:
            #     results = await db.execute(
            #         select(DBBoundary).where(
            #             or_(
            #                 DBBoundary.applies_to_users.contains([user_id]),
            #                 DBBoundary.applies_to_users == None,
            #             )
            #         ).where(DBBoundary.enabled == True)
            #     )
            #     return [SafetyBoundary.from_orm(row) for row in results]

            # Return system boundaries (apply to all users)
            return list(self.system_boundaries.values())

        except Exception as e:
            self.logger.error(
                f"Failed to get user boundaries: {e}",
                extra={"user_id": str(user_id)},
                exc_info=True
            )
            return []

    async def get_workspace_boundaries(
        self,
        workspace_id: UUID,
    ) -> List[SafetyBoundary]:
        """
        Get boundaries that apply to a specific workspace.

        In production: Query database for workspace-specific boundaries.

        Args:
            workspace_id: Workspace ID

        Returns:
            List of applicable boundaries
        """
        try:
            # In production: Query database
            # from app.models.boundary import SafetyBoundary as DBBoundary
            # from app.core.database import get_db
            # async with get_db() as db:
            #     results = await db.execute(
            #         select(DBBoundary).where(
            #             or_(
            #                 DBBoundary.applies_to_workspaces.contains([workspace_id]),
            #                 DBBoundary.applies_to_workspaces == None,
            #             )
            #         ).where(DBBoundary.enabled == True)
            #     )
            #     return [SafetyBoundary.from_orm(row) for row in results]

            # Return system boundaries (apply to all workspaces)
            return list(self.system_boundaries.values())

        except Exception as e:
            self.logger.error(
                f"Failed to get workspace boundaries: {e}",
                extra={"workspace_id": str(workspace_id)},
                exc_info=True
            )
            return []

    async def check_boundary_compliance(
        self,
        boundary_name: str,
        value: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a value complies with a boundary.

        Args:
            boundary_name: Name of boundary to check
            value: Value to check
            context: Additional context

        Returns:
            Tuple of (compliant, violation_message)
        """
        boundary = self.system_boundaries.get(boundary_name)
        if not boundary or not boundary.enabled:
            return True, None

        params = boundary.parameters

        try:
            if boundary.boundary_type == "authority":
                max_level = params.get("max_level", 10)
                if value > max_level:
                    return False, f"Authority level {value} exceeds maximum {max_level}"

            elif boundary.boundary_type == "financial":
                max_amount = params.get("max_amount", 0)
                if value > max_amount:
                    return False, f"Amount ${value:.2f} exceeds limit ${max_amount:.2f}"

            elif boundary.boundary_type == "rate":
                max_calls = params.get("max_calls", 0)
                if value > max_calls:
                    return False, f"Call count {value} exceeds limit {max_calls}"

            elif boundary.boundary_type == "resource":
                # Check various resource limits
                for limit_key, limit_value in params.items():
                    if limit_key.startswith("max_"):
                        resource_name = limit_key[4:]  # Remove "max_" prefix
                        if isinstance(value, dict) and resource_name in value:
                            if value[resource_name] > limit_value:
                                return False, f"{resource_name} {value[resource_name]} exceeds limit {limit_value}"

            return True, None

        except Exception as e:
            self.logger.error(
                f"Error checking boundary compliance: {e}",
                extra={"boundary_name": boundary_name},
                exc_info=True
            )
            # Default to allowing on error
            return True, None
