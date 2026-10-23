"""
JARV Backend - Deployment Tools

Tools for deploying services, checking status, rolling back, and viewing logs.
"""
from typing import Dict, Any, Type, Optional
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tools import ToolBase, ToolConfig, ToolContext, ToolResult
from app.core.agents.base import AuthorityLevel
from app.core.database import AsyncSessionLocal
from app.models.operations import DeploymentRecord

logger = logging.getLogger(__name__)


# ===== SERVICE DEPLOY TOOL =====

class ServiceDeployInput(BaseModel):
    """Input schema for service deploy tool"""
    deployment_name: str = Field(..., description="Name for the deployment")
    deployment_type: str = Field(..., description="Type of deployment (application, service, microservice)")
    environment: str = Field(..., description="Target environment (dev, staging, production)")
    version: str = Field(..., description="Version to deploy")
    commit_sha: Optional[str] = Field(None, description="Git commit SHA")
    branch: Optional[str] = Field(None, description="Git branch")
    changes: Optional[list] = Field(None, description="List of changes in this deployment")


class ServiceDeployOutput(BaseModel):
    """Output schema for service deploy tool"""
    deployment_id: str = Field(..., description="ID of deployment")
    deployment_name: str = Field(..., description="Name of deployment")
    status: str = Field(..., description="Deployment status")
    started_at: datetime = Field(..., description="Deployment start time")


class ServiceDeployTool(ToolBase):
    """Tool for deploying services"""

    @property
    def name(self) -> str:
        return "service_deploy"

    @property
    def description(self) -> str:
        return "Deploy applications and services to specified environments."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ServiceDeployInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ServiceDeployOutput

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
        """Execute service deployment"""
        return self.create_result(
            success=False,
            error_message="No deployment provider adapter is installed; no deployment record or live change was created.",
        )


# ===== DEPLOYMENT STATUS TOOL =====

class DeploymentStatusInput(BaseModel):
    """Input schema for deployment status tool"""
    deployment_id: Optional[str] = Field(None, description="Specific deployment ID (optional)")
    environment: Optional[str] = Field(None, description="Filter by environment")
    status: Optional[str] = Field(None, description="Filter by status")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum number of deployments")


class DeploymentStatusOutput(BaseModel):
    """Output schema for deployment status tool"""
    deployments: list = Field(..., description="List of deployments")
    total_count: int = Field(..., description="Total number of deployments")


class DeploymentStatusTool(ToolBase):
    """Tool for checking deployment status"""

    @property
    def name(self) -> str:
        return "deployment_status"

    @property
    def description(self) -> str:
        return "Check status of deployments with optional filtering."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return DeploymentStatusInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return DeploymentStatusOutput

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
        """Execute deployment status check"""
        try:
            deployment_id = input_data.get("deployment_id")
            environment = input_data.get("environment")
            status = input_data.get("status")
            limit = input_data["limit"]

            # Build query
            async with AsyncSessionLocal() as db:
                query = select(DeploymentRecord)

                conditions = []
                if deployment_id:
                    conditions.append(DeploymentRecord.id == deployment_id)
                if context.workspace_id:
                    conditions.append(DeploymentRecord.workspace_id == context.workspace_id)
                else:
                    conditions.append(DeploymentRecord.workspace_id.is_(None))
                if environment:
                    conditions.append(DeploymentRecord.environment == environment)
                if status:
                    conditions.append(DeploymentRecord.status == status)

                if conditions:
                    query = query.where(and_(*conditions))

                query = query.order_by(DeploymentRecord.created_at.desc()).limit(limit)

                result = await db.execute(query)
                deployments = result.scalars().all()

                # Convert to dict
                deployment_list = [
                    {
                        "deployment_id": str(d.id),
                        "deployment_name": d.deployment_name,
                        "deployment_type": d.deployment_type,
                        "environment": d.environment,
                        "version": d.version,
                        "status": d.status,
                        "success": d.success,
                        "commit_sha": d.commit_sha,
                        "branch": d.branch,
                        "started_at": d.started_at.isoformat(),
                        "completed_at": d.completed_at.isoformat() if d.completed_at else None,
                        "duration_seconds": d.duration_seconds,
                        "can_rollback": d.can_rollback,
                        "rolled_back": d.rolled_back,
                        "error_message": d.error_message,
                    }
                    for d in deployments
                ]

            result_data = {
                "deployments": deployment_list,
                "total_count": len(deployment_list),
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Found {len(deployment_list)} deployments",
            )

        except Exception as e:
            logger.error(f"Error getting deployment status: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to get deployment status: {str(e)}",
            )


# ===== DEPLOYMENT ROLLBACK TOOL =====

class DeploymentRollbackInput(BaseModel):
    """Input schema for deployment rollback tool"""
    deployment_id: str = Field(..., description="ID of deployment to rollback")
    reason: str = Field(..., description="Reason for rollback")


class DeploymentRollbackOutput(BaseModel):
    """Output schema for deployment rollback tool"""
    deployment_id: str = Field(..., description="ID of rolled back deployment")
    rollback_deployment_id: str = Field(..., description="ID of new rollback deployment")
    status: str = Field(..., description="Rollback status")


class DeploymentRollbackTool(ToolBase):
    """Tool for rolling back deployments"""

    @property
    def name(self) -> str:
        return "deployment_rollback"

    @property
    def description(self) -> str:
        return "Rollback a deployment to previous version."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return DeploymentRollbackInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return DeploymentRollbackOutput

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
        """Execute deployment rollback"""
        return self.create_result(
            success=False,
            error_message="No deployment rollback adapter is installed; no rollback or deployment record was created.",
        )


# ===== DEPLOYMENT LOGS TOOL =====

class DeploymentLogsInput(BaseModel):
    """Input schema for deployment logs tool"""
    deployment_id: str = Field(..., description="ID of deployment")
    lines: Optional[int] = Field(None, ge=1, le=10000, description="Number of log lines to retrieve")
    tail: Optional[int] = Field(None, ge=1, le=10000, description="Number of log lines to retrieve (alias)")
    level: Optional[str] = Field(None, description="Filter by log level (info, warn, error)")


class DeploymentLogsOutput(BaseModel):
    """Output schema for deployment logs tool"""
    deployment_id: str = Field(..., description="ID of deployment")
    logs: str = Field(..., description="Deployment logs")
    line_count: int = Field(..., description="Number of log lines")


class DeploymentLogsTool(ToolBase):
    """Tool for viewing deployment logs"""

    @property
    def name(self) -> str:
        return "deployment_logs"

    @property
    def description(self) -> str:
        return "View logs from a deployment for debugging and monitoring."

    @property
    def input_schema(self) -> Type[BaseModel]:
        return DeploymentLogsInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return DeploymentLogsOutput

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
        """Execute deployment logs retrieval"""
        try:
            deployment_id = input_data["deployment_id"]
            lines = input_data.get("lines") or input_data.get("tail", 100)
            level = input_data.get("level")

            # Fetch deployment from database
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(DeploymentRecord).where(DeploymentRecord.id == deployment_id)
                )
                deployment = result.scalar_one_or_none()

                if not deployment:
                    return self.create_result(
                        success=False,
                        error_message=f"Deployment not found: {deployment_id}",
                    )

                # Get logs from deployment record
                logs = deployment.deployment_logs or "No logs available"

                # In real implementation, would fetch from logging service
                # and apply filtering by level and lines

            log_lines = logs.split('\n')
            line_count = len(log_lines)

            result_data = {
                "deployment_id": deployment_id,
                "logs": logs,
                "line_count": line_count,
                "requested_lines": lines,
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Retrieved {line_count} log lines for deployment {deployment_id}",
            )

        except Exception as e:
            logger.error(f"Error retrieving deployment logs: {str(e)}")
            return self.create_result(
                success=False,
                error_message=f"Failed to retrieve deployment logs: {str(e)}",
            )
