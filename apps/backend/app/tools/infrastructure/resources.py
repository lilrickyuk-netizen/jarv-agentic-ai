"""
JARV Backend - Resource Management Tools

Tools for provisioning, scaling, monitoring, and terminating infrastructure resources.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from decimal import Decimal
import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
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


# ===== JARV's infrastructure model =====
# JARV runs services with Docker Compose on Richard's deployment server (provider "vps"). Provisioning
# starts a service of a deployed app there; scaling changes its replicas under the budget rules of
# scale_service_with_budget_boundary; terminating stops it and keeps its data. A resource Richard bought
# elsewhere (a domain, a managed database) is recorded with provider "external" so its cost counts
# toward the monthly budget. Opening cloud accounts and buying resources stay with Richard: account
# setup and spending are hard boundaries.

SERVER_PROVIDERS = {"vps", "server"}


def _service_spec(config: Optional[dict], resource_name: str) -> Dict[str, Any]:
    config = dict(config or {})
    environment = config.get("environment", "staging")
    if environment not in ("staging", "production"):
        raise ValueError("config.environment is staging or production")
    return {"service": config.get("service") or resource_name, "environment": environment,
            "app": config.get("app"), "compose_file": config.get("compose_file"),
            "replicas": int(config.get("replicas", 1))}


def _monthly(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    amount = Decimal(str(value))
    if amount < 0:
        raise ValueError("monthly_cost cannot be negative")
    return amount.quantize(Decimal("0.01"))


async def _owned_resource(db: AsyncSession, context: ToolContext, resource_id: str) -> InfrastructureResource:
    """A resource of the calling workspace, by its id or its resource_id string."""
    clauses = [InfrastructureResource.resource_id == resource_id]
    try:
        clauses.append(InfrastructureResource.id == UUID(str(resource_id)))
    except ValueError:
        pass
    from sqlalchemy import or_

    row = (await db.execute(select(InfrastructureResource).where(
        or_(*clauses), InfrastructureResource.workspace_id == context.workspace_id))).scalar_one_or_none()
    if row is None:
        raise LookupError(f"No resource '{resource_id}' in this workspace")
    return row


async def _scale(db: AsyncSession, context: ToolContext, spec: Dict[str, Any], replicas: int, approved: bool,
                 record_name: str) -> Dict[str, Any]:
    from app.tools.infra_config import scale_service

    data = {k: v for k, v in spec.items() if v is not None}
    data["replicas"] = replicas
    result, _text = await scale_service(db, context, data, approved=approved, record_name=record_name)
    return result


def _outcome(tool: ToolBase, exc: Exception) -> ToolResult:
    """PermissionError is a pause for Richard's approval (the shape every gated tool returns); others fail."""
    if isinstance(exc, PermissionError):
        result = tool._blocked_result(str(exc))
        result.error_message = str(exc)
        return result
    return tool.create_result(success=False, error_message=str(exc))


# ===== RESOURCE PROVISION TOOL =====

class ResourceProvisionInput(BaseModel):
    """Input schema for resource provision tool"""
    resource_name: str = Field(..., description="Name for the resource")
    resource_type: str = Field("service", description="service on the deployment server, or any type for an external resource")
    provider: str = Field("vps", description="vps (the deployment server) or external (bought elsewhere, tracked for cost)")
    region: Optional[str] = Field(None, description="Region to provision in")
    config: Optional[dict] = Field(None, description="vps: environment, service, app, compose_file, replicas, monthly_cost; external: monthly_cost and any details")
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
        return ("Start a service of a deployed app on the deployment server (provider 'vps'), within the budget, or "
                "record a resource bought elsewhere (provider 'external') so its cost counts toward the budget.")

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
        return False  # gated in run(): production or over budget waits for Richard

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Start a service on the deployment server, or record a resource bought elsewhere."""
        provider = (input_data.get("provider") or "").strip().lower()
        name = input_data["resource_name"]
        try:
            monthly = _monthly((input_data.get("config") or {}).get("monthly_cost"))
            async with _resource_db(context) as db:
                if provider in SERVER_PROVIDERS:
                    if (input_data.get("resource_type") or "service") not in ("service", "container"):
                        raise ValueError("On the deployment server a resource is a service of a deployed app "
                                         "(resource_type 'service'); databases and caches are services too.")
                    spec = _service_spec(input_data.get("config"), name)
                    if spec["environment"] == "production" and not self._has_approval(context):
                        raise PermissionError("Starting a production service waits for Richard's approval.")
                    if monthly:
                        from app.core.infra.configs import estimate_monthly

                        costs = await estimate_monthly(db, context.workspace_id)
                        if costs["budget"] and costs["monthly_total"] + float(monthly) > costs["budget"] \
                                and not self._has_approval(context):
                            raise PermissionError(
                                f"Adding {monthly} a month takes the estimate to "
                                f"{costs['monthly_total'] + float(monthly):.2f}, over the approved budget of "
                                f"{costs['budget']:.2f}: Richard's approval is needed.")
                    result = await _scale(db, context, spec, max(1, spec["replicas"]), self._has_approval(context),
                                          "provision")
                    key = f"vps:{result['app']}-{spec['environment']}:{spec['service']}"
                    status = "running"
                elif provider == "external":
                    if monthly is None:
                        raise ValueError("Recording an external resource needs config.monthly_cost (0 if free)")
                    result, spec = {}, dict(input_data.get("config") or {})
                    key = f"external:{name}:{uuid4().hex[:8]}"
                    status = "recorded"
                else:
                    raise ValueError(
                        f"JARV runs services on your deployment server (provider 'vps'). Opening a {provider or 'cloud'} "
                        "account or buying a resource there is Richard's to do: account setup and spending are hard "
                        "boundaries. Once it exists, record it with provider 'external' and its monthly_cost so it "
                        "counts toward the budget.")
                row = (await db.execute(select(InfrastructureResource).where(
                    InfrastructureResource.resource_id == key))).scalar_one_or_none()
                now = datetime.now(timezone.utc)
                if row is None:
                    row = InfrastructureResource(
                        id=uuid4(), workspace_id=context.workspace_id, resource_name=name,
                        resource_type=input_data.get("resource_type") or "service", resource_id=key,
                        description=input_data.get("description"), provider="vps" if provider in SERVER_PROVIDERS
                        else provider, region=input_data.get("region"), config=spec,
                        capacity={"replicas": result.get("replicas")} if result else input_data.get("capacity"),
                        tags_list=[f"{k}:{v}" for k, v in (input_data.get("tags") or {}).items()],
                        status=status, health="healthy", is_active=True, monthly_cost=monthly, currency="USD",
                        managed_by=context.user_id, meta_data={"provisioned_at": now.isoformat()},
                        created_at=now, updated_at=now)
                    db.add(row)
                else:
                    row.is_active, row.status, row.config, row.updated_at = True, status, spec, now
                    if monthly is not None:
                        row.monthly_cost = monthly
                    if result:
                        row.capacity = {"replicas": result.get("replicas")}
                await db.flush()
                data = {"resource_id": str(row.id), "resource_name": row.resource_name, "provider_resource_id": key,
                        "status": status, "monthly_cost": float(monthly) if monthly is not None else None,
                        **({"replicas": result["replicas"], "previous_replicas": result["previous_replicas"],
                            "cost": result.get("cost")} if result else {})}
                text = (f"{spec['service']} is running on the {spec['environment']} server "
                        f"({result['replicas']} replica(s))" if result
                        else f"Recorded {name} at {monthly} a month; it now counts toward the budget")
                return self.create_result(success=True, result_data=data, output_text=text)
        except (PermissionError, LookupError, ValueError) as exc:
            return _outcome(self, exc)



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
        return "Change the replicas of a service on the deployment server; beyond the budget it waits for Richard."

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
        return False  # gated in run(): production or over budget waits for Richard

    @property
    def category(self) -> str:
        return "infrastructure"

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Change a server service's replicas under the budget rules (beyond them it waits for Richard)."""
        target = {**(input_data.get("new_capacity") or {}), **(input_data.get("target_config") or {})}
        try:
            async with _resource_db(context) as db:
                row = await _owned_resource(db, context, input_data["resource_id"])
                if row.provider != "vps":
                    raise ValueError(f"{row.resource_name} is an external resource; change its plan with "
                                     f"{row.provider} and update its monthly cost with resource_provision.")
                current = int((row.capacity or {}).get("replicas") or 1)
                replicas = target.get("replicas", target.get("instances"))
                if replicas is None:
                    action = (input_data.get("scale_action") or "").lower()
                    if action not in ("up", "down"):
                        raise ValueError("Give target_config.replicas, or scale_action 'up' or 'down'")
                    replicas = current + 1 if action == "up" else max(0, current - 1)
                result = await _scale(db, context, dict(row.config or {}), int(replicas), self._has_approval(context),
                                      "scale")
                old = dict(row.capacity or {})
                row.capacity = {**old, "replicas": result["replicas"]}
                row.status = "running" if result["replicas"] else "stopped"
                row.updated_at = datetime.now(timezone.utc)
                await db.flush()
                return self.create_result(success=True, result_data={
                    "resource_id": str(row.id), "scale_action": f"{result['previous_replicas']} -> {result['replicas']}",
                    "old_config": {"replicas": result["previous_replicas"]}, "new_config": row.capacity,
                    "cost": result.get("cost")},
                    output_text=f"{row.resource_name} scaled {result['previous_replicas']} -> {result['replicas']}")
        except (PermissionError, LookupError, ValueError) as exc:
            return _outcome(self, exc)



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

    async def _check_server_service(self, db: AsyncSession, context: ToolContext,
                                    resource: InfrastructureResource) -> ToolResult:
        """Count the running containers of a deployment-server service against what it should have."""
        from app.core.deploy import DeployError
        from app.tools import deploy as deploy_tools

        spec = dict(resource.config or {})
        expected = int((resource.capacity or {}).get("replicas") or 0)
        try:
            project = await deploy_tools._project(db, context, spec, spec.get("environment", "staging"))
            running = await deploy_tools._deployer().replicas(project["app"], spec.get("environment", "staging"),
                                                             spec["service"], project["compose_file"])
        except (DeployError, KeyError, ValueError) as exc:
            return self.create_result(success=False, error_message=f"Could not check {resource.resource_name}: {exc}")
        if not resource.is_active or expected == 0:
            status = "stopped" if running == 0 else "unexpected"
        elif running >= expected:
            status = "healthy"
        else:
            status = "degraded" if running else "unhealthy"
        resource.health = status
        resource.last_health_check = datetime.utcnow()
        await db.flush()
        return self.create_result(success=True, result_data={
            "resource_id": str(resource.id), "health_status": status,
            "checks": {"running_replicas": running, "expected_replicas": expected},
            "metrics": None, "checked_at": datetime.utcnow().isoformat(), "data_source": "deployment server"},
            output_text=f"{resource.resource_name}: {running} of {expected} replica(s) running ({status})")

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

                if resource.provider == "vps":
                    return await self._check_server_service(db, context, resource)
                if resource.provider == "external":
                    return self.create_result(success=False, error_message=(
                        f"{resource.resource_name} is an external resource, tracked for its cost only; check it with "
                        f"its provider (domains and certificates: check_domain_dns, check_ssl_certificate)."))
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
        return "Stop a service on the deployment server (its data is kept), or end tracking of an external resource."

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

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        """Stop a server service (its data volumes are kept) or end tracking of an external resource."""
        if input_data.get("delete_data"):
            return self._blocked_result(
                "Deleting a resource's data is a hard boundary (deleting production data). Terminating stops the "
                "service and keeps its data; Richard removes data himself.", approvable=False)
        if not self._has_approval(context):
            return _outcome(self, PermissionError("Stopping a resource waits for Richard's approval."))
        try:
            async with _resource_db(context) as db:
                row = await _owned_resource(db, context, input_data["resource_id"])
                now = datetime.now(timezone.utc)
                note = None
                if row.provider == "vps":
                    await _scale(db, context, dict(row.config or {}), 0, True, "terminate")
                    row.capacity = {**(row.capacity or {}), "replicas": 0}
                    row.status = "stopped"
                    note = "Data volumes were kept; provisioning it again starts it with its data."
                else:
                    row.status = "ended"
                    note = f"JARV stopped counting its cost. Cancel it with {row.provider} if you have not already."
                row.is_active = False
                row.updated_at = now
                row.meta_data = {**(row.meta_data or {}), "terminated_at": now.isoformat()}
                await db.flush()
                return self.create_result(success=True, result_data={
                    "resource_id": str(row.id), "resource_name": row.resource_name, "status": row.status,
                    "data_kept": True, "note": note}, output_text=f"{row.resource_name}: {row.status}. {note}")
        except (PermissionError, LookupError, ValueError) as exc:
            return _outcome(self, exc)
