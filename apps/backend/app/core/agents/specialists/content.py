"""
JARV Backend - ContentAgent

Drafts blog posts, tutorials, changelogs, and educational content.

This agent does NOT fabricate SEO/readability scores, word counts, or claim
anything was published. When an LLM provider is configured it produces a real
model-generated DRAFT (clearly labelled, unverified). When no provider is
configured it returns an honest limitation instead of fake content. Nothing is
ever published; the output is a DRAFT only and no external action is taken.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class ContentAgentInput(BaseModel):
    """ContentAgent input"""
    content_type: str = Field(..., description="blog, tutorial, case_study, whitepaper")
    topic: str = Field(...)
    target_audience: str = Field(default="general")
    length: str = Field(default="medium")


class ContentAgentOutput(BaseModel):
    """ContentAgent output (honest; no fabricated scores; draft only)."""
    content_type: str = ""
    topic: str = ""
    draft: str = ""
    provider_used: Optional[str] = None
    external_action_taken: bool = False
    limitations: List[str] = []


class ContentAgent(AgentBase):
    """
    ContentAgent - Drafts blog posts, articles, and educational content
    """

    @property
    def name(self) -> str:
        return "content"

    @property
    def role(self) -> str:
        return "Creates blog posts, articles, and educational content"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return ContentAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return ContentAgentOutput

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
        try:
            content_type = (input_data.get("content_type") or "blog").strip()
            topic = helpers.task_text(input_data, "topic", "content_type")
            target_audience = (input_data.get("target_audience") or "general").strip()
            length = (input_data.get("length") or "medium").strip()

            self.logger.info(f"Drafting {content_type} about {topic}")

            limitations: List[str] = []
            draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            prompt = (
                f"Write a {length} {content_type} for a {target_audience} audience "
                f"on the following topic:\n\n{topic}\n\n"
                "Produce clean, ready-to-edit prose in Markdown. Do not invent "
                "statistics, customer quotes, or sources you cannot support."
            )

            if helpers.provider_configured():
                res = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system=(
                        "You are a careful content writer. Produce an honest DRAFT. "
                        "Never fabricate metrics, citations, or claims."
                    ),
                    temperature=self.config.temperature,
                )
                if res is not None and res.get("text"):
                    draft = res["text"]
                    provider_used = res["provider_used"]
                    tokens = res["tokens"]
                    limitations.append(
                        "Model-generated DRAFT, unverified; no external action taken. "
                        "Draft only, not published."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no draft "
                        "was generated."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())
                limitations.append("Draft only, not published.")

            if draft:
                output_text = (
                    f"Drafted {content_type} on '{topic}' "
                    f"({len(draft)} chars) via {provider_used}; DRAFT, not published."
                )
            else:
                output_text = (
                    f"No {content_type} draft generated for '{topic}': "
                    + (limitations[0] if limitations else "no provider available")
                )

            return self.create_result(
                success=True,
                result_data={
                    "content_type": content_type,
                    "topic": topic,
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
            self.logger.error(f"content task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
