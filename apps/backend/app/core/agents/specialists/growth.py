"""
JARV Backend - GrowthAgent

Drafts growth-experiment IDEAS as model-generated advisory output only.

This agent does NOT run any experiment, change any product, or move any real
metric. There is no experimentation/analytics platform wired into standalone
agent execution, so no experiment is executed and no real impact is measured.
When an LLM provider is configured it drafts candidate growth experiments and
labels them as unverified model output. When no provider is configured it
returns an honest limitation. There are no fabricated impact, lift, or
conversion numbers anywhere in the output.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class GrowthAgentInput(BaseModel):
    """GrowthAgent input"""
    growth_metric: str = Field(..., description="acquisition, activation, retention, revenue")
    current_value: float = Field(...)
    target_value: float = Field(...)
    timeframe: str = Field(default="30d")


class GrowthAgentOutput(BaseModel):
    """GrowthAgent output (honest; experiment ideas only, no fabricated metrics)."""
    growth_metric: str = ""
    current_value: float = 0.0
    target_value: float = 0.0
    timeframe: str = ""
    gap: Optional[float] = None
    experiment_ideas: str = ""
    ideas_produced: bool = False
    experiment_run: bool = False
    external_action_taken: bool = False
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class GrowthAgent(AgentBase):
    """
    GrowthAgent - drafts growth-experiment ideas (advisory only).
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
        try:
            metric = input_data.get("growth_metric", "acquisition")
            current = input_data.get("current_value", 0.0)
            target = input_data.get("target_value", 0.0)
            timeframe = input_data.get("timeframe", "30d")

            self.logger.info(f"Drafting growth experiments for {metric}")

            # Arithmetic on the caller-supplied numbers only (clearly labelled as
            # derived from provided inputs, not a measured outcome).
            gap: Optional[float] = None
            try:
                gap = float(target) - float(current)
            except (TypeError, ValueError):
                gap = None

            limitations: List[str] = [
                "No experiment was run and no product/metric was changed; these "
                "are candidate ideas only and no real growth metrics were "
                "measured (no experimentation platform is wired into this agent).",
            ]
            if gap is not None:
                limitations.append(
                    "The 'gap' value is simple arithmetic on the caller-supplied "
                    "current/target values, not a measured or projected outcome."
                )

            ideas = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if helpers.provider_configured():
                prompt = (
                    f"Propose growth-experiment ideas for the metric '{metric}'.\n"
                    f"Caller-supplied current value: {current}\n"
                    f"Caller-supplied target value: {target}\n"
                    f"Timeframe: {timeframe}\n\n"
                    "List candidate experiments with hypothesis, the lever they "
                    "test, and how to measure them. Do NOT invent expected lift, "
                    "impact, or conversion numbers."
                )
                result = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You are a growth strategist proposing testable "
                           "experiments. Never fabricate metrics or claim an "
                           "experiment was executed.",
                    temperature=self.config.temperature,
                )
                if result is not None and result.get("text"):
                    ideas = result["text"]
                    provider_used = result["provider_used"]
                    tokens = result["tokens"]
                    limitations.append(
                        "The ideas are model-generated and UNVERIFIED; validate "
                        "feasibility and design proper experiments before acting."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no "
                        "experiment ideas could be generated."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            ideas_produced = bool(ideas)
            if ideas_produced:
                output_text = (
                    f"Growth experiment IDEAS for '{metric}'; provider="
                    f"{provider_used}; no experiment run; no real metrics measured."
                )
            else:
                output_text = (
                    f"No growth experiment ideas produced for '{metric}'; "
                    f"{len(limitations)} limitation(s) noted. No experiment was run."
                )

            return self.create_result(
                success=True,
                result_data={
                    "growth_metric": metric,
                    "current_value": current,
                    "target_value": target,
                    "timeframe": timeframe,
                    "gap": gap,
                    "experiment_ideas": ideas,
                    "ideas_produced": ideas_produced,
                    "experiment_run": False,
                    "external_action_taken": False,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"growth task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
