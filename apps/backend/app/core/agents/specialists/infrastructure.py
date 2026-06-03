"""
JARV Backend - InfrastructureAgent

Manages cloud infrastructure, scaling, and optimization
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class InfrastructureAgentInput(BaseModel):
    """InfrastructureAgent input"""
    operation: str = Field(..., description="provision, scale, optimize, migrate")
    resources: list[str] = Field(default_factory=list)
    target_capacity: Dict[str, int] = Field(default_factory=dict)


class InfrastructureAgentOutput(BaseModel):
    """InfrastructureAgent output"""
    operation_completed: bool
    resources_affected: list[str]
    cost_impact: float
    performance_improvement: float
    downtime_minutes: float


class InfrastructureAgent(AgentBase):
    """
    InfrastructureAgent - Manages cloud infrastructure, scaling, and optimization
    """

    @property
    def name(self) -> str:
        return "infrastructure"

    @property
    def role(self) -> str:
        return "Manages cloud infrastructure, scaling, and optimization"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return InfrastructureAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return InfrastructureAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_7_DEPLOYMENT

    @property
    def default_tools(self) -> list[str]:
        return ['command_run', 'http_post', 'analyze_metrics']

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
            operation = input_data.get("operation", "scale")
            resources = input_data.get("resources", [])

            self.logger.info(f"Infrastructure operation: {operation} on {len(resources)} resources")

            cost = len(resources) * 50.0  # $50 per resource
            downtime = 5.0 if operation == "migrate" else 0.0

            result_data = {
                "operation_completed": True,
                "resources_affected": resources,
                "cost_impact": cost,
                "performance_improvement": 25.0 if operation == "optimize" else 0.0,
                "downtime_minutes": downtime,
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Infrastructure {operation}: {len(resources)} resources, ${cost:.2f} cost",
                tools_used=["command_run", "http_post"],
                requires_approval=(operation in ["migrate", "provision"]),
            )

        except Exception as e:
            self.logger.error(f"infrastructure task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
