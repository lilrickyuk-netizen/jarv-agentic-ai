"""
JARV Backend - BusinessAgent

Produces business analysis/recommendations as model-generated advisory DRAFTS
only.

This agent does NOT have access to real business systems, financials, or
metrics in standalone agent execution, so it never invents revenue, customer,
or growth-rate numbers. When an LLM provider is configured it drafts analysis
and recommendations from the provided context and labels them as an unverified
advisory draft. When no provider is configured it returns an honest limitation.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class BusinessAgentInput(BaseModel):
    """BusinessAgent input"""
    report_type: str = Field(..., description="metrics, forecast, analysis, recommendation")
    time_period: str = Field(...)
    metrics: list[str] = Field(default_factory=list)


class BusinessAgentOutput(BaseModel):
    """BusinessAgent output (honest; advisory draft, no fabricated metrics)."""
    report_type: str = ""
    time_period: str = ""
    metrics_requested: List[str] = Field(default_factory=list)
    analysis: str = ""
    analysis_produced: bool = False
    external_action_taken: bool = False
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class BusinessAgent(AgentBase):
    """
    BusinessAgent - drafts business analysis/recommendations (advisory only).
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
        try:
            report_type = input_data.get("report_type", "metrics")
            time_period = input_data.get("time_period", "")
            metrics = list(input_data.get("metrics", []) or [])
            instruction = helpers.task_text(input_data, "report_type", "time_period")

            self.logger.info(
                f"Drafting {report_type} business analysis for {time_period}"
            )

            limitations: List[str] = [
                "This is an advisory DRAFT only; it is NOT validated against real "
                "financials or business systems (none are wired into this agent), "
                "and no revenue/customer/growth numbers were measured or invented.",
            ]
            analysis = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if helpers.provider_configured():
                prompt = (
                    f"Provide a {report_type} business analysis for the period "
                    f"'{time_period or '(unspecified)'}'.\n"
                    f"Focus metrics requested: "
                    f"{', '.join(metrics) if metrics else '(none specified)'}\n"
                    f"Context/instruction: {instruction or '(none provided)'}\n\n"
                    "Give qualitative analysis, considerations, and recommended "
                    "next steps. You have NO access to real figures, so do NOT "
                    "fabricate revenue, customer counts, growth rates, or trends; "
                    "frame any quantitative point as an assumption to be verified."
                )
                result = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You are a business analyst. Provide advisory analysis "
                           "only. Never fabricate financial figures or claim "
                           "access to real data.",
                    temperature=self.config.temperature,
                )
                if result is not None and result.get("text"):
                    analysis = result["text"]
                    provider_used = result["provider_used"]
                    tokens = result["tokens"]
                    limitations.append(
                        "The analysis is model-generated and UNVERIFIED; confirm "
                        "all assumptions against real data before acting."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no "
                        "analysis could be generated."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            analysis_produced = bool(analysis)
            if analysis_produced:
                output_text = (
                    f"Business analysis DRAFT ({report_type}, {time_period}); "
                    f"provider={provider_used}; advisory only, not validated "
                    "against real financials."
                )
            else:
                output_text = (
                    f"No business analysis produced ({report_type}, {time_period}); "
                    f"{len(limitations)} limitation(s) noted."
                )

            return self.create_result(
                success=True,
                result_data={
                    "report_type": report_type,
                    "time_period": time_period,
                    "metrics_requested": metrics,
                    "analysis": analysis,
                    "analysis_produced": analysis_produced,
                    "external_action_taken": False,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"business task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
