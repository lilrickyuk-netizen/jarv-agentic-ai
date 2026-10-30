"""
JARV Backend - Remaining infrastructure tools (Repair 12e-4b)

check_ssl_certificate and check_domain_dns (the real TLS and DNS checks under
the design's names), generate_nginx_config, generate_docker_compose,
validate_cloud_config, estimate_infrastructure_cost and
scale_service_with_budget_boundary. Generated files go into the workspace
folder and never overwrite the project's own files; scaling runs on the
deployment server only within the approved budget and replica limit, and
otherwise pauses for Richard.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.agents.base import AuthorityLevel
from app.core.infra import configs
from app.tools._scoped import ScopedTool
from app.tools.infrastructure.monitoring import DNSVerifyTool, SSLCheckTool


class CheckSslCertificateTool(SSLCheckTool):
    """The TLS certificate check (expiry, issuer, chain) under the design's name."""

    @property
    def name(self) -> str:
        return "check_ssl_certificate"


class CheckDomainDnsTool(DNSVerifyTool):
    """The DNS record check under the design's name."""

    @property
    def name(self) -> str:
        return "check_domain_dns"


class _InfraTool(ScopedTool):
    _category = "infrastructure"
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS


async def _workspace(db, context):
    from app.models.workspace import Workspace

    return (await db.execute(select(Workspace).where(Workspace.id == context.workspace_id))).scalar_one()


def _folder(workspace) -> Path:
    from app.core.workspaces import fs_inspector

    host = (workspace.config or {}).get("root_path")
    container = fs_inspector.host_to_container(host) if host else None
    if container is None or not container.is_dir():
        raise ValueError("This workspace has no folder")
    return container.resolve()


class _Nginx(BaseModel):
    domain: str
    routes: Dict[str, str] = Field(..., description="{path: service:port}, e.g. {\"/\": \"web:3000\", \"/api\": \"api:8000\"}")
    websocket_paths: List[str] = Field(default_factory=list)
    max_body_mb: int = Field(20, ge=1, le=1024)
    rate_per_second: int = Field(10, ge=1, le=1000)
    write: bool = Field(True, description="Save to infra/nginx/<domain>.conf in the workspace")


class GenerateNginxConfigTool(_InfraTool):
    _name = "generate_nginx_config"
    _description = ("Generate a production nginx server config for a domain (HTTPS redirect, ACME path, TLS 1.2/1.3, "
                    "security headers, rate limit, proxy/WebSocket headers) and validate it.")
    _input = _Nginx

    async def act(self, db, context, owner, data):
        text = configs.generate_nginx(data["domain"], data["routes"], websocket_paths=data["websocket_paths"],
                                      max_body_mb=data["max_body_mb"], rate_per_second=data["rate_per_second"])
        issues = configs.check_nginx(text)
        path = None
        if data["write"]:
            root = _folder(await _workspace(db, context))
            target = root / "infra" / "nginx" / f"{data['domain'].lower()}.conf"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            path = target.relative_to(root).as_posix()
        return {"config": text, "file": path, "issues": issues}, f"nginx config for {data['domain']}" + (
            f" written to {path}" if path else "")


class _Compose(BaseModel):
    app_name: Optional[str] = None
    write: bool = Field(True, description="Save as docker-compose.generated.yml (never replaces docker-compose.yml)")


class GenerateDockerComposeTool(_InfraTool):
    _name = "generate_docker_compose"
    _description = ("Generate a docker-compose file for the workspace's detected stack (app service, PostgreSQL and "
                    "Redis when used), with health checks and secrets referenced from .env.")
    _input = _Compose

    async def act(self, db, context, owner, data):
        import asyncio

        from app.core.agents.workspace_ops import detect_project

        ws = await _workspace(db, context)
        root = _folder(ws)
        detected = await asyncio.to_thread(detect_project, root)
        text, notes = await asyncio.to_thread(configs.generate_compose, root, detected, data.get("app_name") or ws.slug)
        issues = configs.check_compose(text, configs.documented_vars(root))
        path = None
        if data["write"]:
            (root / "docker-compose.generated.yml").write_text(text, encoding="utf-8")
            path = "docker-compose.generated.yml"
        return {"compose": text, "file": path, "notes": notes, "issues": issues, "stack": detected.get("stack")}, (
            f"compose generated for {', '.join(detected.get('stack') or [])}" + (f" ({path})" if path else ""))


class _Validate(BaseModel):
    pass


class ValidateCloudConfigTool(_InfraTool):
    _name = "validate_cloud_config"
    _description = ("Check the workspace's compose files, Dockerfiles and nginx configs for errors and unsafe settings "
                    "(privileged containers, writable Docker socket, inline secrets, unpinned images, root users, "
                    "missing TLS files, undocumented variables).")
    _input = _Validate
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        import asyncio

        root = _folder(await _workspace(db, context))
        result = await asyncio.to_thread(configs.validate_folder, root)
        return result, (f"{len(result['files'])} config file(s): {result['errors']} error(s), "
                        f"{result['warnings']} warning(s)")


class EstimateInfrastructureCostTool(_InfraTool):
    _name = "estimate_infrastructure_cost"
    _description = ("Monthly infrastructure cost from configured fixed costs, recorded resources and AI model usage, "
                    "against the approved monthly budget.")
    _input = _Validate
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        result = await configs.estimate_monthly(db, context.workspace_id)
        budget = f" of {result['budget']:.2f} budget" if result["budget"] else " (no budget set)"
        return result, f"About {result['monthly_total']:.2f} USD/month{budget}"


class _Scale(BaseModel):
    service: str
    replicas: int = Field(..., ge=0, le=50)
    environment: str = Field("staging", description="staging or production")
    app: Optional[str] = None
    compose_file: Optional[str] = None


class ScaleServiceWithBudgetBoundaryTool(_InfraTool):
    _name = "scale_service_with_budget_boundary"
    _description = ("Scale a service of the deployed app to N replicas on the deployment server. Within the approved "
                    "monthly budget and replica limit it runs; beyond them it pauses for Richard.")
    _input = _Scale
    _authority = AuthorityLevel.LEVEL_7_DEPLOYMENT
    _gated = True

    async def act(self, db, context, owner, data):
        return await scale_service(db, context, data, approved=bool(data["_approved"]))


async def scale_service(db, context, data, *, approved: bool, record_name: str = "scale"):
    """Scale one service of the workspace's deployed app; beyond the budget or replica limit it needs approval.

    Shared by scale_service_with_budget_boundary and the resource tools. PermissionError means Richard's
    approval is needed; ValueError means the request cannot be carried out.
    """
    from app.core.deploy import DeployError
    from app.tools import deploy as deploy_tools

    if data["environment"] not in ("staging", "production"):
        raise ValueError("environment is staging or production")
    try:
        project = await deploy_tools._project(db, context, data, data["environment"])
        deployer = deploy_tools._deployer()
        current = await deployer.replicas(project["app"], data["environment"], data["service"],
                                          project["compose_file"])
    except DeployError as exc:
        raise ValueError(str(exc)) from None
    costs = await configs.estimate_monthly(db, context.workspace_id)
    decision = configs.scaling_decision(costs["monthly_total"], current, data["replicas"])
    if decision["needs_approval"] and not approved:
        raise PermissionError("Scaling needs Richard's approval: " + "; ".join(decision["reasons"]))
    try:
        result = await deployer.scale(project["app"], data["environment"], data["service"], data["replicas"],
                                      project["compose_file"])
    except DeployError as exc:
        raise ValueError(str(exc)) from None
    from app.models.operations import DeploymentRecord

    now = datetime.now(timezone.utc)
    db.add(DeploymentRecord(
        id=uuid4(), workspace_id=context.workspace_id, deployment_name=f"{record_name} {data['service']}"[:255],
        deployment_type=record_name, environment=data["environment"], version=f"{current}->{data['replicas']}",
        status="succeeded", success=True, started_at=now, completed_at=now, duration_seconds=0,
        deployment_logs="\n\n".join(result["log"])[-20000:], can_rollback=True, rolled_back=False,
        meta_data={"service": data["service"], "previous_replicas": current, "replicas": data["replicas"],
                   "cost": decision, "approved_by": "richard" if decision["needs_approval"] else "budget"},
        created_at=now, updated_at=now))
    await db.flush()
    return {**{k: v for k, v in result.items() if k != "log"}, "cost": decision}, (
        f"{data['service']} scaled {current} -> {data['replicas']} in {data['environment']}")


INFRA_CONFIG_TOOLS = [
    CheckSslCertificateTool, CheckDomainDnsTool, GenerateNginxConfigTool, GenerateDockerComposeTool,
    ValidateCloudConfigTool, EstimateInfrastructureCostTool, ScaleServiceWithBudgetBoundaryTool,
]
