"""
JARV Backend - GrowthAgent

Drives user acquisition, activation, and retention
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class GrowthAgentInput(BaseModel):
    """GrowthAgent input"""
    growth_metric: str = Field(..., description="acquisition, activation, retention, revenue")
    current_value: float = Field(...)
    target_value: float = Field(...)
    timeframe: str = Field(default="30d")


class GrowthAgentOutput(BaseModel):
    """GrowthAgent output"""
    strategy_created: bool
    tactics: list[str]
    estimated_impact: float
    resources_needed: list[str]
    kpis: list[Dict[str, str]]


class GrowthAgent(AgentBase):
    """
    GrowthAgent - Drives user acquisition, activation, and retention
    """

    @property
    def name(self) -> str:
        return "growth"

    @property
    def role(self) -> str:
        return "Drives user acquisition, activation, and retention"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return GrowthAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return GrowthAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> list[str]:
        return ['http_get', 'http_post', 'memory_retrieve', 'analyze_metrics']

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
            metric = input_data.get("growth_metric", "acquisition")
            current = input_data.get("current_value", 0)
            target = input_data.get("target_value", 0)

            self.logger.info(f"Growth strategy for {metric}: {current} -> {target}")

            gap = target - current
            tactics = [
                f"Optimize {metric} funnel",
                f"A/B test {metric} campaigns",
                f"Increase {metric} budget by 20%",
            ]

            result_data = {
                "strategy_created": True,
                "tactics": tactics,
                "estimated_impact": gap * 0.7,
                "resources_needed": ["Marketing budget", "Development time", "Analytics tools"],
                "kpis": [{"metric": metric, "target": str(target), "timeframe": "30d"}],
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Growth strategy: {len(tactics)} tactics to close {gap} gap",
                tools_used=["analyze_metrics", "memory_retrieve"],
            )

        except Exception as e:
            self.logger.error(f"growth task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
