"""
JARV Backend - OnboardingAgent

Drafts onboarding flows and welcome / activation emails.

This agent does NOT fabricate predicted completion rates, estimated times, or
claim anything was deployed. When an LLM provider is configured it produces a
real model-generated DRAFT (clearly labelled, unverified). When no provider is
configured it returns an honest limitation. Output is a DRAFT only; not
deployed and no external action is taken.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class OnboardingAgentInput(BaseModel):
    """OnboardingAgent input"""
    user_type: str = Field(..., description="new_user, power_user, admin")
    product: str = Field(...)
    customization: Dict[str, Any] = Field(default_factory=dict)


class OnboardingAgentOutput(BaseModel):
    """OnboardingAgent output (honest; no fabricated metrics; draft only)."""
    user_type: str = ""
    product: str = ""
    draft: str = ""
    provider_used: Optional[str] = None
    external_action_taken: bool = False
    limitations: List[str] = []


class OnboardingAgent(AgentBase):
    """
    OnboardingAgent - Creates onboarding experiences and user education
    """

    @property
    def name(self) -> str:
        return "onboarding"

    @property
    def role(self) -> str:
        return "Creates onboarding experiences and user education"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return OnboardingAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return OnboardingAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def default_tools(self) -> list[str]:
        return ['file_write', 'memory_retrieve', 'http_post']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            user_type = (input_data.get("user_type") or "new_user").strip()
            product = helpers.task_text(input_data, "product", "user_type")

            self.logger.info(f"Drafting onboarding for {user_type} on {product}")

            limitations: List[str] = ["Draft only; not deployed."]
            draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            prompt = (
                f"Draft an onboarding flow for a '{user_type}' of the following "
                f"product:\n\n{product}\n\n"
                "Include: (1) a step-by-step onboarding flow with a short description "
                "per step, and (2) a welcome email plus a follow-up activation email. "
                "Write in Markdown, ready for human review. Do not invent metrics, "
                "completion rates, or features the product may not have."
            )

            if helpers.provider_configured():
                res = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system=(
                        "You are a careful onboarding designer producing a DRAFT for "
                        "human review. Never claim anything was deployed; never "
                        "fabricate completion rates or engagement metrics."
                    ),
                    temperature=self.config.temperature,
                )
                if res is not None and res.get("text"):
                    draft = res["text"]
                    provider_used = res["provider_used"]
                    tokens = res["tokens"]
                    limitations.append(
                        "Model-generated DRAFT, unverified; no external action taken."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no draft "
                        "was generated."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            if draft:
                output_text = (
                    f"Drafted onboarding for {user_type} on '{product}' "
                    f"({len(draft)} chars) via {provider_used}; not deployed."
                )
            else:
                output_text = (
                    f"No onboarding draft generated for {user_type} on '{product}': "
                    + (limitations[-1] if limitations else "no provider available")
                )

            return self.create_result(
                success=True,
                result_data={
                    "user_type": user_type,
                    "product": product,
                    "draft": draft,
                    "provider_used": provider_used,
                    "external_action_taken": False,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
            )

        except Exception as e:
            self.logger.error(f"onboarding task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
