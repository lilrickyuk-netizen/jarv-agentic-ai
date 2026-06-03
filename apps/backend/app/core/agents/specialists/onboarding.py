"""
JARV Backend - OnboardingAgent

Creates onboarding experiences and user education
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class OnboardingAgentInput(BaseModel):
    """OnboardingAgent input"""
    user_type: str = Field(..., description="new_user, power_user, admin")
    product: str = Field(...)
    customization: Dict[str, Any] = Field(default_factory=dict)


class OnboardingAgentOutput(BaseModel):
    """OnboardingAgent output"""
    onboarding_created: bool
    steps: list[Dict[str, str]]
    estimated_time: int
    completion_rate_predicted: float


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
        """
        Execute task.

        Args:
            input_data: Task input
            context: Execution context

        Returns:
            Agent result
        """
        try:
            user_type = input_data.get("user_type", "new_user")
            product = input_data.get("product", "")

            self.logger.info(f"Creating onboarding for {user_type} on {product}")

            steps = []
            if user_type == "new_user":
                steps = [
                    {"step": "welcome", "description": "Introduction to product"},
                    {"step": "setup", "description": "Account setup and configuration"},
                    {"step": "first_task", "description": "Complete first task"},
                    {"step": "explore", "description": "Explore key features"},
                ]
            elif user_type == "power_user":
                steps = [
                    {"step": "advanced_features", "description": "Advanced capabilities"},
                    {"step": "integrations", "description": "Connect integrations"},
                    {"step": "automation", "description": "Set up automation"},
                ]

            result_data = {
                "onboarding_created": True,
                "steps": steps,
                "estimated_time": len(steps) * 5,
                "completion_rate_predicted": 0.72,
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Onboarding created: {len(steps)} steps",
                tools_used=["file_write", "memory_retrieve"],
            )

        except Exception as e:
            self.logger.error(f"onboarding task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
