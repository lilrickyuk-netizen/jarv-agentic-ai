"""
JARV Backend - SalesAgent

Drafts sales scripts, outreach sequences, and prospect briefs as
model-generated DRAFTS only.

This agent does NOT send outreach, create CRM contacts/deals, update any
pipeline, or close any deal. There is no CRM/email channel wired into
standalone agent execution, so nothing is dispatched and no real pipeline or
win-probability numbers are produced. When an LLM provider is configured it
drafts the requested sales artifact and labels it as unverified model output.
When no provider is configured it returns an honest limitation.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class SalesAgentInput(BaseModel):
    """SalesAgent input"""
    operation: str = Field(..., description="lead, proposal, follow_up, close")
    contact_info: Dict[str, str] = Field(default_factory=dict)
    deal_value: float = Field(default=0.0)
    stage: str = Field(default="prospect")


class SalesAgentOutput(BaseModel):
    """SalesAgent output (honest; drafts only, no fabricated pipeline)."""
    operation: str = ""
    stage: str = ""
    deal_value: float = 0.0
    draft: str = ""
    draft_produced: bool = False
    outreach_sent: bool = False
    pipeline_updated: bool = False
    external_action_taken: bool = False
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class SalesAgent(AgentBase):
    """
    SalesAgent - drafts sales scripts/sequences/prospect briefs (DRAFT only).
    """

    @property
    def name(self) -> str:
        return "sales"

    @property
    def role(self) -> str:
        return "Manages sales processes, proposals, and customer relationships"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SalesAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SalesAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> list[str]:
        return ['crm_create_contact', 'crm_update_deal', 'email_send', 'file_write']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            operation = input_data.get("operation", "lead")
            deal_value = input_data.get("deal_value", 0.0)
            stage = input_data.get("stage", "prospect")
            contact_info = input_data.get("contact_info", {}) or {}
            instruction = helpers.task_text(input_data, "operation", "stage")

            try:
                deal_value = float(deal_value)
            except (TypeError, ValueError):
                deal_value = 0.0

            self.logger.info(f"Drafting sales artifact: {operation} at {stage} stage")

            limitations: List[str] = [
                "These are sales DRAFTS only; no outreach was sent, no CRM "
                "contact/deal was created, no pipeline was updated, and no deal "
                "was closed (no CRM/email channel is wired into this agent). No "
                "win-probability or pipeline numbers were computed.",
            ]
            draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if helpers.provider_configured():
                contact_desc = (
                    ", ".join(f"{k}={v}" for k, v in contact_info.items())
                    if contact_info else "(no contact details provided)"
                )
                deal_desc = (
                    f"caller-supplied deal value {deal_value}" if deal_value > 0
                    else "no deal value provided"
                )
                prompt = (
                    f"Draft a sales artifact for the '{operation}' operation at the "
                    f"'{stage}' stage.\n"
                    f"Prospect/contact: {contact_desc}\n"
                    f"Deal context: {deal_desc}\n"
                    f"Context/instruction: {instruction or '(none provided)'}\n\n"
                    "Produce the relevant artifact: an outreach script/email, a "
                    "follow-up sequence, or a prospect brief as appropriate. Do "
                    "NOT invent win probabilities, pipeline values, or claim any "
                    "message was sent."
                )
                result = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You are a sales enablement writer. Output usable "
                           "drafts only. Never fabricate pipeline metrics or claim "
                           "outreach was sent.",
                    temperature=self.config.temperature,
                )
                if result is not None and result.get("text"):
                    draft = result["text"]
                    provider_used = result["provider_used"]
                    tokens = result["tokens"]
                    limitations.append(
                        "The draft is model-generated and UNVERIFIED; review and "
                        "personalize before any real outreach."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no "
                        "draft could be generated."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            draft_produced = bool(draft)
            if draft_produced:
                output_text = (
                    f"Sales DRAFT ({operation}, stage={stage}); provider="
                    f"{provider_used}; nothing sent; no pipeline updated."
                )
            else:
                output_text = (
                    f"No sales draft produced ({operation}, stage={stage}); "
                    f"{len(limitations)} limitation(s) noted. Nothing was sent."
                )

            return self.create_result(
                success=True,
                result_data={
                    "operation": operation,
                    "stage": stage,
                    "deal_value": deal_value,
                    "draft": draft,
                    "draft_produced": draft_produced,
                    "outreach_sent": False,
                    "pipeline_updated": False,
                    "external_action_taken": False,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"sales task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
