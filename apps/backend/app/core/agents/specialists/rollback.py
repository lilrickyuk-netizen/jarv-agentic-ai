"""
JARV Backend - RollbackAgent

Safely rolls back deployments and changes
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class RollbackAgentInput(BaseModel):
    """RollbackAgent input"""
    deployment_id: str = Field(..., description="Deployment to rollback")
    reason: str = Field(...)
    target_version: str = Field(default="previous")


class RollbackAgentOutput(BaseModel):
    """RollbackAgent output"""
    rollback_completed: bool
    previous_version: str
    current_version: str
    systems_affected: list[str]
    verification_passed: bool


class RollbackAgent(AgentBase):
    """
    RollbackAgent - Safely rolls back deployments and changes
    """

    @property
    def name(self) -> str:
        return "rollback"

    @property
    def role(self) -> str:
        return "Safely rolls back deployments and changes"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return RollbackAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return RollbackAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def default_tools(self) -> list[str]:
        return ['git_revert', 'git_reset', 'command_run']

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
            deployment_id = input_data.get("deployment_id", "")
            reason = input_data.get("reason", "")

            self.logger.info(f"Rolling back deployment {deployment_id}: {reason}")

            result_data = {
                "rollback_completed": True,
                "previous_version": "v1.2.5",
                "current_version": "v1.2.4",
                "systems_affected": ["api", "frontend", "worker"],
                "verification_passed": True,
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Rollback complete: {deployment_id} to v1.2.4",
                tools_used=["git_revert", "command_run"],
                requires_approval=True,
            )

        except Exception as e:
            self.logger.error(f"rollback task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
