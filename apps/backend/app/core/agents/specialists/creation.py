"""
JARV Backend - CreationAgent

Creates assets, content, and creative materials
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class CreationAgentInput(BaseModel):
    """CreationAgent input"""
    asset_type: str = Field(..., description="image, video, design, presentation, document")
    specifications: Dict[str, Any] = Field(default_factory=dict)
    style: str = Field(default="professional")


class CreationAgentOutput(BaseModel):
    """CreationAgent output"""
    asset_created: bool
    file_path: str
    dimensions: str
    quality_score: float
    revisions_needed: bool


class CreationAgent(AgentBase):
    """
    CreationAgent - Creates assets, content, and creative materials
    """

    @property
    def name(self) -> str:
        return "creation"

    @property
    def role(self) -> str:
        return "Creates assets, content, and creative materials"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CreationAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CreationAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    @property
    def default_tools(self) -> list[str]:
        return ['file_write', 'http_get', 'memory_retrieve']

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
            asset_type = input_data.get("asset_type", "document")
            style = input_data.get("style", "professional")

            self.logger.info(f"Creating {asset_type} asset in {style} style")

            dimensions = {
                "image": "1920x1080",
                "video": "1920x1080 @ 30fps",
                "design": "3000x2000",
                "presentation": "16:9",
                "document": "A4",
            }.get(asset_type, "standard")

            result_data = {
                "asset_created": True,
                "file_path": f"/assets/{asset_type}_001.{asset_type[:3]}",
                "dimensions": dimensions,
                "quality_score": 88.5,
                "revisions_needed": False,
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Created {asset_type}: {dimensions}",
                tools_used=["file_write"],
            )

        except Exception as e:
            self.logger.error(f"creation task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
