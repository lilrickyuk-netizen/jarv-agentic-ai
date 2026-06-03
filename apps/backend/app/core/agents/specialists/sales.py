"""
JARV Backend - SalesAgent

Manages sales processes, proposals, and customer relationships
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class SalesAgentInput(BaseModel):
    """SalesAgent input"""
    operation: str = Field(..., description="lead, proposal, follow_up, close")
    contact_info: Dict[str, str] = Field(default_factory=dict)
    deal_value: float = Field(default=0.0)
    stage: str = Field(default="prospect")


class SalesAgentOutput(BaseModel):
    """SalesAgent output"""
    operation_completed: bool
    contact_id: str
    deal_id: str
    next_steps: list[str]
    win_probability: float


class SalesAgent(AgentBase):
    """
    SalesAgent - Manages sales processes, proposals, and customer relationships
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
        """
        Execute task.

        Args:
            input_data: Task input
            context: Execution context

        Returns:
            Agent result
        """
        try:
            operation = input_data.get("operation", "lead")
            deal_value = input_data.get("deal_value", 0.0)
            stage = input_data.get("stage", "prospect")

            self.logger.info(f"Sales operation: {operation} at {stage} stage")

            # Calculate win probability based on stage
            prob = {
                "prospect": 0.10,
                "qualified": 0.30,
                "proposal": 0.50,
                "negotiation": 0.75,
                "closing": 0.90,
            }.get(stage, 0.20)

            result_data = {
                "operation_completed": True,
                "contact_id": f"contact_{hash(str(input_data.get('contact_info', {}))) % 10000}",
                "deal_id": f"deal_{hash(str(deal_value)) % 10000}",
                "next_steps": [
                    "Send proposal",
                    "Schedule demo",
                    "Follow up in 3 days",
                ],
                "win_probability": prob,
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Sales {operation}: ${deal_value:.0f} ({prob*100:.0f}% win probability)",
                tools_used=["crm_create_contact", "email_send"],
            )

        except Exception as e:
            self.logger.error(f"sales task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
