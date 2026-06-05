"""
JARV Backend - PartnershipsAgent

Drafts partner shortlists, outreach messages, and partnership proposals.

This agent does NOT fabricate identified partners, outreach/response counts, or
claim anything was sent. It makes NO binding offers. When an LLM provider is
configured it produces a real model-generated DRAFT (clearly labelled,
unverified). When no provider is configured it returns an honest limitation.
Output is a DRAFT only; no binding offers, nothing sent, no external action.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class PartnershipsAgentInput(BaseModel):
    """PartnershipsAgent input"""
    operation: str = Field(..., description="identify, reach_out, negotiate, finalize")
    partner_type: str = Field(..., description="technology, distribution, strategic")
    criteria: Dict[str, Any] = Field(default_factory=dict)


class PartnershipsAgentOutput(BaseModel):
    """PartnershipsAgent output (honest; no fabricated partners/counts; draft only)."""
    operation: str = ""
    partner_type: str = ""
    draft: str = ""
    provider_used: Optional[str] = None
    external_action_taken: bool = False
    limitations: List[str] = []


class PartnershipsAgent(AgentBase):
    """
    PartnershipsAgent - Identifies and manages strategic partnerships
    """

    @property
    def name(self) -> str:
        return "partnerships"

    @property
    def role(self) -> str:
        return "Identifies and manages strategic partnerships"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return PartnershipsAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return PartnershipsAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> list[str]:
        return ['crm_create_contact', 'email_send', 'file_write', 'memory_retrieve']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            operation = (input_data.get("operation") or "identify").strip()
            partner_type = helpers.task_text(input_data, "partner_type", "operation")

            self.logger.info(f"Drafting partnership {operation} for {partner_type}")

            limitations: List[str] = [
                "Drafts only; no binding offers; nothing sent.",
            ]
            draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            prompt = (
                f"Draft partnership material for a '{operation}' step targeting "
                f"'{partner_type}' partners. Context / criteria:\n\n{partner_type}\n\n"
                "Produce: (1) a candidate partner shortlist described as suggested "
                "categories/profiles to research (not confirmed contacts), "
                "(2) a draft outreach message, and (3) an outline for a partnership "
                "proposal. Write in Markdown for human review. Do not invent real "
                "company names, contacts, or commitments, and make no binding offers."
            )

            if helpers.provider_configured():
                res = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system=(
                        "You are a careful partnerships strategist drafting material "
                        "for human review. Never claim anything was sent; make no "
                        "binding offers; never fabricate partner names or response "
                        "counts."
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
                    f"Drafted partnership {operation} material for {partner_type} "
                    f"({len(draft)} chars) via {provider_used}; nothing sent."
                )
            else:
                output_text = (
                    f"No partnership {operation} draft generated for {partner_type}: "
                    + (limitations[-1] if limitations else "no provider available")
                )

            return self.create_result(
                success=True,
                result_data={
                    "operation": operation,
                    "partner_type": partner_type,
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
            self.logger.error(f"partnerships task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
