"""
JARV Backend - LegalAgent

Drafts compliance, policy, and terms text (e.g. TOS, privacy policy, NDA).

This agent does NOT fabricate page counts, claim compliance was checked, or
produce a finished legal document. It is NOT legal advice and cannot make final
legal decisions. When an LLM provider is configured it produces a real
model-generated DRAFT (clearly labelled, unverified) that REQUIRES qualified
human legal review. When no provider is configured it returns an honest
limitation. Output is a DRAFT only; no external action is taken.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class LegalAgentInput(BaseModel):
    """LegalAgent input"""
    document_type: str = Field(..., description="TOS, privacy_policy, NDA, contract")
    parties: list[str] = Field(default_factory=list)
    jurisdiction: str = Field(default="US")
    custom_terms: Dict[str, Any] = Field(default_factory=dict)


class LegalAgentOutput(BaseModel):
    """LegalAgent output (honest; no fabricated pages/compliance; draft only)."""
    document_type: str = ""
    jurisdiction: str = ""
    draft: str = ""
    provider_used: Optional[str] = None
    external_action_taken: bool = False
    review_needed: bool = True
    limitations: List[str] = []


class LegalAgent(AgentBase):
    """
    LegalAgent - Drafts legal and compliance documents
    """

    @property
    def name(self) -> str:
        return "legal"

    @property
    def role(self) -> str:
        return "Drafts legal and compliance documents"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return LegalAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return LegalAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def default_tools(self) -> list[str]:
        return ['file_read', 'file_write', 'memory_retrieve']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            doc_type = (input_data.get("document_type") or "TOS").strip()
            jurisdiction = (input_data.get("jurisdiction") or "US").strip()
            parties = input_data.get("parties") or []
            custom_terms = input_data.get("custom_terms") or {}

            self.logger.info(f"Drafting legal document: {doc_type} ({jurisdiction})")

            limitations: List[str] = [
                "Draft only; not legal advice; requires human / qualified legal "
                "review before any use.",
            ]
            draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            parties_str = ", ".join(str(p) for p in parties) if parties else "unspecified"
            terms_str = (
                "; ".join(f"{k}={v}" for k, v in custom_terms.items())
                if isinstance(custom_terms, dict) and custom_terms else "none provided"
            )
            prompt = (
                f"Draft a '{doc_type}' document for jurisdiction '{jurisdiction}'.\n"
                f"Parties: {parties_str}\n"
                f"Custom terms: {terms_str}\n\n"
                "Produce a clear, structured DRAFT in Markdown intended for review by "
                "a qualified lawyer. Include a prominent note that the draft is not "
                "legal advice and must be reviewed by qualified counsel. Do not "
                "fabricate case law, statutes, or guarantees of compliance."
            )

            if helpers.provider_configured():
                res = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system=(
                        "You are a careful legal drafting assistant. You are NOT a "
                        "lawyer and cannot give legal advice or make final legal "
                        "decisions. Produce a DRAFT for qualified human legal review "
                        "only; never claim compliance was verified."
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
                    f"Drafted {doc_type} for {jurisdiction} "
                    f"({len(draft)} chars) via {provider_used}; "
                    "DRAFT only, requires qualified legal review."
                )
            else:
                output_text = (
                    f"No {doc_type} draft generated for {jurisdiction}: "
                    + (limitations[-1] if limitations else "no provider available")
                )

            return self.create_result(
                success=True,
                result_data={
                    "document_type": doc_type,
                    "jurisdiction": jurisdiction,
                    "draft": draft,
                    "provider_used": provider_used,
                    "external_action_taken": False,
                    "review_needed": True,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
                requires_approval=True,
            )

        except Exception as e:
            self.logger.error(f"legal task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
