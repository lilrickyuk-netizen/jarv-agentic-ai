"""
JARV Backend - DevOpsAgent

Manages deployments, CI/CD, and infrastructure operations
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class DevOpsAgentInput(BaseModel):
    """DevOpsAgent input"""
    operation: str = Field(..., description="Operation: deploy, rollback, scale, monitor")
    environment: str = Field(..., description="Target environment")
    config: Dict[str, Any] = Field(default_factory=dict)


class DevOpsAgentOutput(BaseModel):
    """DevOpsAgent output"""
    operation_completed: bool
    deployment_url: str
    status: str
    health_checks_passed: bool
    rollback_available: bool


class DevOpsAgent(AgentBase):
    """
    DevOpsAgent - Manages deployments, CI/CD, and infrastructure operations
    """

    @property
    def name(self) -> str:
        return "devops"

    @property
    def role(self) -> str:
        return "Manages deployments, CI/CD, and infrastructure operations"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return DevOpsAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return DevOpsAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def default_tools(self) -> list[str]:
        return ['command_run', 'file_read', 'file_write', 'git_push']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """
        Execute task.

        Args:
            input_data: Task input
            context: Execution context

        Returns:
            Agent result
        """
        try:
            operation = input_data.get("operation", "deploy")
            environment = input_data.get("environment", "staging")

            self.logger.info(f"Starting {operation} to {environment}")

            # Simulate deployment
            success = operation in ["deploy", "scale", "monitor"]

            result_data = {
                "operation_completed": success,
                "deployment_url": f"https://{environment}.example.com",
                "status": "running" if success else "failed",
                "health_checks_passed": success,
                "rollback_available": operation == "deploy",
            }

            return self.create_result(
                success=success,
                result_data=result_data,
                output_text=f"{operation} to {environment}: {'success' if success else 'failed'}",
                tools_used=["command_run", "http_post"],
                requires_approval=(operation in ["deploy", "rollback"]),
            )

        except Exception as e:
            self.logger.error(f"devops task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
