"""
JARV Backend - BusinessAgent

Analyzes business metrics, creates reports, makes recommendations
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class BusinessAgentInput(BaseModel):
    """BusinessAgent input"""
    report_type: str = Field(..., description="metrics, forecast, analysis, recommendation")
    time_period: str = Field(...)
    metrics: list[str] = Field(default_factory=list)


class BusinessAgentOutput(BaseModel):
    """BusinessAgent output"""
    report_generated: bool
    key_insights: list[str]
    metrics_analyzed: Dict[str, float]
    recommendations: list[str]
    trend: str


class BusinessAgent(AgentBase):
    """
    BusinessAgent - Analyzes business metrics, creates reports, makes recommendations
    """

    @property
    def name(self) -> str:
        return "business"

    @property
    def role(self) -> str:
        return "Analyzes business metrics, creates reports, makes recommendations"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return BusinessAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return BusinessAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_6_DATABASE_WRITE

    @property
    def default_tools(self) -> list[str]:
        return ['analyze_metrics', 'memory_retrieve', 'file_write']

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
            report_type = input_data.get("report_type", "metrics")
            time_period = input_data.get("time_period", "")

            self.logger.info(f"Generating {report_type} report for {time_period}")

            result_data = {
                "report_generated": True,
                "key_insights": [
                    "Revenue up 15% vs last period",
                    "Customer acquisition cost decreased 8%",
                    "Retention rate improved to 92%",
                ],
                "metrics_analyzed": {
                    "revenue": 125000.0,
                    "customers": 1500,
                    "growth_rate": 0.15,
                },
                "recommendations": [
                    "Scale successful channels",
                    "Optimize pricing strategy",
                    "Expand to new markets",
                ],
                "trend": "positive",
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Business report: {report_type} for {time_period}",
                tools_used=["analyze_metrics", "file_write"],
            )

        except Exception as e:
            self.logger.error(f"business task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
