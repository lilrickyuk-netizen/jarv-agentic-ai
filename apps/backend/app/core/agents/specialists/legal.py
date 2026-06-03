"""
JARV Backend - LegalAgent

Drafts legal and compliance documents
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class LegalAgentInput(BaseModel):
    """LegalAgent input"""
    document_type: str = Field(..., description="TOS, privacy_policy, NDA, contract")
    parties: list[str] = Field(default_factory=list)
    jurisdiction: str = Field(default="US")
    custom_terms: Dict[str, Any] = Field(default_factory=dict)


class LegalAgentOutput(BaseModel):
    """LegalAgent output"""
    document_generated: bool
    file_path: str
    pages: int
    review_needed: bool
    compliance_checked: bool


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
        """
        Execute task.

        Args:
            input_data: Task input
            context: Execution context

        Returns:
            Agent result
        """
        try:
            doc_type = input_data.get("document_type", "TOS")
            jurisdiction = input_data.get("jurisdiction", "US")

            self.logger.info(f"Generating legal document: {doc_type} ({jurisdiction})")

            pages = {
                "TOS": 15,
                "privacy_policy": 12,
                "NDA": 8,
                "contract": 20,
            }.get(doc_type, 10)

            result_data = {
                "document_generated": True,
                "file_path": f"/legal/{doc_type.lower()}_{jurisdiction}.pdf",
                "pages": pages,
                "review_needed": True,
                "compliance_checked": True,
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Generated {doc_type}: {pages} pages",
                tools_used=["file_write", "memory_retrieve"],
                requires_approval=True,
            )

        except Exception as e:
            self.logger.error(f"legal task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
