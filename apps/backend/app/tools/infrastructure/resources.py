"""
JARV Backend - Resource Management Tools

Tools for provisioning, scaling, monitoring, and terminating infrastructure resources.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from decimal import Decimal
import logging
from contextlib import asynccontextmanager
from uuid import UUID
import psutil

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.database import AsyncSessionLocal
from app.models.operations import InfrastructureResource

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _resource_db(context: ToolContext):
    if context.db_session is not None:
        yield context.db_session
    else:
        async with AsyncSessionLocal() as session:
            yield session


# ===== RESOURCE PROVISION TOOL =====

class ResourceProvisionInput(BaseModel):
    """Input schema for resource provision tool"""
    resource_name: str = Field(..., description="Name for the resource")
    resource_type: str = Field(..., description="Type of resource (vm, container, database, etc.)")
    provider: str = Field(..., description="Cloud provider (aws, azure, gcp, local)")
    region: Optional[str] = Field(None, description="Region to provision in")
    config: Optional[dict] = Field(None, description="Resource configuration (instance type, size, etc.)")
    capacity: Optional[dict] = Field(None, description="Resource capacity (cpu, memory, storage)")
    description: Optional[str] = Field(None, description="Resource description")
    tags: Optional[dict] = Field(None, description="Resource tags")


class ResourceProvisionOutput(BaseModel):
    """Output schema for resource provision tool"""
    resource_id: str = Field(..., description="ID of provisioned resource")
    resource_name: str = Field(..., description="Name of the resource")
    provider_resource_id: str = Field(..., description="Provider-specific resource ID")
    status: str = Field(..., description="Resource status")


class ResourceProvisionTool(ToolBase):
    """Tool for provisioning infrastructure resources"""

    @property
    def name(self) -> str:
        return "resource_provision"

    @property
    def description(self) -> str:
        return "Provision new infrastructure resources (VMs, containers, databases) on cloud providers."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResourceProvisionInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResourceProvisionOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute resource provisioning"""
        return self.create_result(
            success=False,
            error_message=("No infrastructure provider adapter is installed; "
                           "no resource was provisioned or recorded."),
        )


# ===== RESOURCE SCALE TOOL =====

class ResourceScaleInput(BaseModel):
    """Input schema for resource scale tool"""
    resource_id: str = Field(..., description="ID of resource to scale")
    scale_action: Optional[str] = Field(None, description="Scale action (up, down, auto)")
    scale_type: Optional[str] = Field(None, description="Scale type (vertical, horizontal)")
    target_config: Optional[dict] = Field(None, description="Target configuration (size, instances, etc.)")
    new_capacity: Optional[dict] = Field(None, description="New capacity (cpu, memory, storage)")


class ResourceScaleOutput(BaseModel):
    """Output schema for resource scale tool"""
    resource_id: str = Field(..., description="ID of scaled resource")
    scale_action: str = Field(..., description="Scale action performed")
    old_config: dict = Field(..., description="Previous configuration")
    new_config: dict = Field(..., description="New configuration")


class ResourceScaleTool(ToolBase):
    """Tool for scaling infrastructure resources"""

    @property
    def name(self) -> str:
        return "resource_scale"

    @property
    def description(self) -> str:
        return "Scale infrastructure resources up or down based on demand."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResourceScaleInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResourceScaleOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute resource scaling"""
        return self.create_result(
            success=False,
            error_message="No infrastructure scaling adapter is installed; resource state was not changed.",
        )


# ===== RESOURCE HEALTH CHECK TOOL =====

class ResourceHealthCheckInput(BaseModel):
    """Input schema for resource health check tool"""
    resource_id: str = Field(..., description="ID of resource to check")
    include_metrics: bool = Field(default=True, description="Include performance metrics")
    check_connectivity: bool = Field(default=True, description="Check network connectivity")
    check_performance: bool = Field(default=True, description="Check performance metrics")


class ResourceHealthCheckOutput(BaseModel):
    """Output schema for resource health check tool"""
    resource_id: str = Field(..., description="ID of checked resource")
    health_status: str = Field(..., description="Health status (healthy, degraded, unhealthy)")
    checks: dict = Field(..., description="Individual health check results")
    metrics: Optional[dict] = Field(None, description="Performance metrics if requested")


class ResourceHealthCheckTool(ToolBase):
    """Tool for checking resource health"""

    @property
    def name(self) -> str:
        return "resource_health_check"

    @property
    def description(self) -> str:
        return "Check health status of infrastructure resources with optional performance metrics."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResourceHealthCheckInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResourceHealthCheckOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute resource health check"""
        try:
            resource_id = input_data["resource_id"]
            include_metrics = input_data.get("include_metrics", True)
            check_connectivity = input_data.get("check_connectivity", True)
            check_performance = input_data.get("check_performance", True)

            async with _resource_db(context) as db:
                result = await db.execute(
                    select(InfrastructureResource).where(
                        InfrastructureResource.id == UUID(resource_id),
                        InfrastructureResource.workspace_id == context.workspace_id,
                    )
                )
                resource = result.scalar_one_or_none()

                if not resource:
                    return self.create_result(
                        success=False,
                        error_message=f"Resource not found: {resource_id}",
                    )

                if resource.provider != "local" or resource.resource_type not in ("host", "local"):
                    return self.create_result(
                        success=False,
                        error_message=f"No health-check adapter is configured for provider '{resource.provider}'.",
                    )
                metrics_path = (resource.config or {}).get("metrics_path", "/")
                metrics = {}
                checks = {"host_snapshot": True}
                if include_metrics or check_performance:
                    vm = psutil.virtual_memory()
                    metrics = {
                        "cpu_usage": psutil.cpu_percent(interval=0.1),
                        "memory_usage": vm.percent,
                        "memory_available_bytes": vm.available,
                        "disk_usage": psutil.disk_usage(metrics_path).percent,
                        "disk_path": metrics_path,
                    }
                if check_connectivity:
                    checks["connectivity"] = "not_probed"
                health_status = "healthy" if metrics else "unknown"
                resource.health = health_status
                resource.last_health_check = datetime.utcnow()
                await db.flush()

            logger.info(f"Health check completed for resource: {resource_id} ({health_status})")

            result_data = {
                "resource_id": resource_id,
                "health_status": health_status,
                "checks": checks,
                "metrics": metrics,
                "checked_at": datetime.utcnow().isoformat(),
                "data_source": "host_snapshot",
                "limitations": ["Only this process host was measured; external services and cloud health were not probed."],
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Health check: {health_status}",
            )

        except Exception as e:
            logger.error(f"Error checking resource health: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to check resource health: {str(e)}",
            )


# ===== RESOURCE STATUS TOOL =====

class ResourceStatusInput(BaseModel):
    """Input schema for resource status tool"""
    resource_id: Optional[str] = Field(None, description="Specific resource ID (optional)")
    resource_type: Optional[str] = Field(None, description="Filter by resource type")
    provider: Optional[str] = Field(None, description="Filter by cloud provider")
    status: Optional[str] = Field(None, description="Filter by status")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum number of resources")


class ResourceStatusOutput(BaseModel):
    """Output schema for resource status tool"""
    resources: list = Field(..., description="List of resources with status")
    total_count: int = Field(..., description="Total number of resources")


class ResourceStatusTool(ToolBase):
    """Tool for checking resource status"""

    @property
    def name(self) -> str:
        return "resource_status"

    @property
    def description(self) -> str:
        return "Get status of infrastructure resources with optional filtering."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResourceStatusInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResourceStatusOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def requires_approval(self) -> bool:
        return False

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute resource status check"""
        try:
            resource_id = input_data.get("resource_id")
            resource_type = input_data.get("resource_type")
            provider = input_data.get("provider")
            status = input_data.get("status")
            limit = input_data.get("limit", 50)

            # Build query
            async with AsyncSessionLocal() as db:
                query = select(InfrastructureResource)

                conditions = []
                if resource_id:
                    conditions.append(InfrastructureResource.id == resource_id)
                if context.workspace_id:
                    conditions.append(InfrastructureResource.workspace_id == context.workspace_id)
                else:
                    conditions.append(InfrastructureResource.workspace_id.is_(None))
                if resource_type:
                    conditions.append(InfrastructureResource.resource_type == resource_type)
                if provider:
                    conditions.append(InfrastructureResource.provider == provider)
                if status:
                    conditions.append(InfrastructureResource.status == status)

                if conditions:
                    query = query.where(and_(*conditions))

                query = query.order_by(InfrastructureResource.created_at.desc()).limit(limit)

                result = await db.execute(query)
                resources = result.scalars().all()

                # Convert to dict
                resource_list = [
                    {
                        "resource_id": str(r.id),
                        "resource_name": r.resource_name,
                        "resource_type": r.resource_type,
                        "provider": r.provider,
                        "region": r.region,
                        "status": r.status,
                        "health": r.health,
                        "is_active": r.is_active,
                        "config": r.config,
                        "last_health_check": r.last_health_check.isoformat() if r.last_health_check else None,
                        "uptime_percentage": float(r.uptime_percentage) if r.uptime_percentage else None,
                        "hourly_cost": float(r.hourly_cost) if r.hourly_cost else None,
                        "monthly_cost": float(r.monthly_cost) if r.monthly_cost else None,
                    }
                    for r in resources
                ]

            result_data = {
                "resources": resource_list,
                "total_count": len(resource_list),
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Found {len(resource_list)} resources",
            )

        except Exception as e:
            logger.error(f"Error getting resource status: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to get resource status: {str(e)}",
            )


# ===== RESOURCE TERMINATE TOOL =====

class ResourceTerminateInput(BaseModel):
    """Input schema for resource terminate tool"""
    resource_id: str = Field(..., description="ID of resource to terminate")
    force: bool = Field(default=False, description="Force termination without cleanup")
    delete_data: bool = Field(default=False, description="Delete associated data")
    backup_before_terminate: bool = Field(default=False, description="Create backup before termination")


class ResourceTerminateOutput(BaseModel):
    """Output schema for resource terminate tool"""
    resource_id: str = Field(..., description="ID of terminated resource")
    resource_name: str = Field(..., description="Name of terminated resource")
    status: str = Field(..., description="Termination status")


class ResourceTerminateTool(ToolBase):
    """Tool for terminating infrastructure resources"""

    @property
    def name(self) -> str:
        return "resource_terminate"

    @property
    def description(self) -> str:
        return "Terminate and decommission infrastructure resources."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResourceTerminateInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResourceTerminateOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def requires_approval(self) -> bool:
        return True

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(
        self,
        input_data: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute resource termination"""
        return self.create_result(
            success=False,
            error_message="No infrastructure termination adapter is installed; resource state and data were not changed.",
        )
