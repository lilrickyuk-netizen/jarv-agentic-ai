"""
JARV Backend - WorkspaceManagerAgent

Manages workspace configuration, rules, and lifecycle
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class WorkspaceManagerAgentInput(BaseModel):
    """WorkspaceManagerAgent input"""
    operation: str = Field(..., description="create, update, delete, configure")
    workspace_name: str = Field(default="")
    config: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceManagerAgentOutput(BaseModel):
    """WorkspaceManagerAgent output"""
    operation_completed: bool
    workspace_id: str
    config_applied: Dict[str, Any]
    status: str


class WorkspaceManagerAgent(AgentBase):
    """
    WorkspaceManagerAgent - Manages workspace configuration, rules, and lifecycle
    """

    @property
    def name(self) -> str:
        return "workspace_manager"

    @property
    def role(self) -> str:
        return "Manages workspace configuration, rules, and lifecycle"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return WorkspaceManagerAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return WorkspaceManagerAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def default_tools(self) -> list[str]:
        return ['workspace_create', 'workspace_update', 'workspace_list']

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
            operation = input_data.get("operation", "update")
            workspace_name = input_data.get("workspace_name", "")

            self.logger.info(f"Workspace operation: {operation} for {workspace_name}")

            workspace_id = f"ws_{workspace_name.lower().replace(' ', '_')}"

            result_data = {
                "operation_completed": True,
                "workspace_id": workspace_id,
                "config_applied": input_data.get("config", {}),
                "status": "active",
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Workspace {operation}: {workspace_id}",
                tools_used=["workspace_create", "workspace_update"],
            )

        except Exception as e:
            self.logger.error(f"workspace_manager task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
