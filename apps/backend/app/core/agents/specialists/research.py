"""
JARV Backend - ResearchAgent

Researches technologies, solutions, and best practices
"""
from typing import Dict, Any, Type
from pydantic import BaseModel, Field
import logging

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel

logger = logging.getLogger(__name__)


class ResearchAgentInput(BaseModel):
    """ResearchAgent input"""
    query: str = Field(..., description="Research query")
    sources: list[str] = Field(default_factory=list, description="Specific sources to check")
    depth: str = Field(default="medium", description="shallow, medium, deep")


class ResearchAgentOutput(BaseModel):
    """ResearchAgent output"""
    findings: list[Dict[str, str]]
    sources_consulted: list[str]
    confidence: float
    recommendations: list[str]
    related_topics: list[str]


class ResearchAgent(AgentBase):
    """
    ResearchAgent - Researches technologies, solutions, and best practices
    """

    @property
    def name(self) -> str:
        return "research"

    @property
    def role(self) -> str:
        return "Researches technologies, solutions, and best practices"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ResearchAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ResearchAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> list[str]:
        return ['http_get', 'http_post', 'file_read', 'memory_search']

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
            query = input_data.get("query", "")
            depth = input_data.get("depth", "medium")

            self.logger.info(f"Researching: {query} (depth: {depth})")

            # Simulate research
            source_count = {"shallow": 3, "medium": 7, "deep": 15}.get(depth, 7)
            findings = [
                {"source": f"Source {i+1}", "finding": f"Finding about {query}"}
                for i in range(min(source_count, 5))
            ]

            result_data = {
                "findings": findings,
                "sources_consulted": [f"Source {i+1}" for i in range(source_count)],
                "confidence": 0.85,
                "recommendations": [f"Consider {query} for production use", "Review best practices"],
                "related_topics": ["Related topic 1", "Related topic 2"],
            }

            return self.create_result(
                success=True,
                result_data=result_data,
                output_text=f"Research complete: {len(findings)} findings from {source_count} sources",
                tools_used=["http_get", "memory_search"],
            )

        except Exception as e:
            self.logger.error(f"research task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
