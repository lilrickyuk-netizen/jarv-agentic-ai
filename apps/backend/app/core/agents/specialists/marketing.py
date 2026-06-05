"""
JARV Backend - MarketingAgent

Produces marketing campaign copy/plans as model-generated DRAFTS only.

This agent does NOT send, post, publish, or schedule anything. There is no
external marketing/social/email channel wired into standalone agent execution,
so no campaign is dispatched and no real reach/impressions are measured. When
an LLM provider is configured it drafts campaign copy and labels it as an
unverified, model-generated draft. When no provider is configured it returns an
honest limitation. There are no fabricated reach, impression, or scheduling
numbers anywhere in the output.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class MarketingAgentInput(BaseModel):
    """MarketingAgent input"""
    campaign_type: str = Field(..., description="email, social, content, ads")
    target_audience: str = Field(...)
    message: str = Field(...)
    channels: list[str] = Field(default_factory=list)


class MarketingAgentOutput(BaseModel):
    """MarketingAgent output (honest; draft only, no fabricated metrics)."""
    campaign_type: str = ""
    target_audience: str = ""
    channels_requested: List[str] = Field(default_factory=list)
    draft: str = ""
    draft_produced: bool = False
    external_action_taken: bool = False
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class MarketingAgent(AgentBase):
    """
    MarketingAgent - drafts marketing campaign copy/plans (DRAFT only).
    """

    @property
    def name(self) -> str:
        return "marketing"

    @property
    def role(self) -> str:
        return "Creates marketing content, campaigns, and strategies"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return MarketingAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return MarketingAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> list[str]:
        return ['file_write', 'http_post', 'memory_retrieve']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            campaign_type = input_data.get("campaign_type", "email")
            target_audience = input_data.get("target_audience", "general")
            channels = list(input_data.get("channels", []) or [])
            instruction = helpers.task_text(input_data, "message", "target_audience")

            self.logger.info(
                f"Drafting {campaign_type} campaign copy for {target_audience}"
            )

            limitations: List[str] = [
                "This is a marketing DRAFT only; nothing was sent, posted, "
                "published, or scheduled, and no real reach/impressions were "
                "measured (no external channel is wired into this agent).",
            ]
            draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if helpers.provider_configured():
                prompt = (
                    f"Draft a {campaign_type} marketing campaign.\n"
                    f"Target audience: {target_audience}\n"
                    f"Core message: {instruction or '(none provided)'}\n"
                    f"Channels requested: {', '.join(channels) if channels else '(none specified)'}\n\n"
                    "Produce campaign copy and a simple plan (hook, body, CTA, "
                    "and per-channel adaptation). Do NOT invent reach, impression, "
                    "ROI, or conversion numbers."
                )
                result = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You are a marketing copywriter. Output a usable draft. "
                           "Never fabricate performance metrics or claim the "
                           "campaign was published.",
                    temperature=self.config.temperature,
                )
                if result is not None and result.get("text"):
                    draft = result["text"]
                    provider_used = result["provider_used"]
                    tokens = result["tokens"]
                    limitations.append(
                        "The draft is model-generated and UNVERIFIED; review for "
                        "accuracy, brand voice, and compliance before any use."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no "
                        "draft could be generated."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())
                limitations.append(
                    "No real campaign, reach, or metrics exist; configure a "
                    "provider to generate a draft."
                )

            draft_produced = bool(draft)
            if draft_produced:
                output_text = (
                    f"Marketing DRAFT for {campaign_type} campaign "
                    f"(audience={target_audience}); provider={provider_used}; "
                    "not sent/posted/published; no reach measured."
                )
            else:
                output_text = (
                    f"No marketing draft produced for {campaign_type} campaign; "
                    f"{len(limitations)} limitation(s) noted. Nothing was sent or "
                    "published."
                )

            return self.create_result(
                success=True,
                result_data={
                    "campaign_type": campaign_type,
                    "target_audience": target_audience,
                    "channels_requested": channels,
                    "draft": draft,
                    "draft_produced": draft_produced,
                    "external_action_taken": False,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"marketing task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
