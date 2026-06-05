"""
JARV Backend - CommunityAgent

Drafts community replies, posts, and announcements.

This agent does NOT fabricate engagement scores, reach, or sentiment, and it
NEVER posts or moderates anything. When an LLM provider is configured it
produces a real model-generated DRAFT (clearly labelled, unverified). When no
provider is configured it returns an honest limitation. Output is a DRAFT only;
nothing is posted or moderated and no external action is taken.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class CommunityAgentInput(BaseModel):
    """CommunityAgent input"""
    action: str = Field(..., description="post, respond, moderate, analyze")
    platform: str = Field(default="forum")
    content: str = Field(default="")
    target_audience: str = Field(default="all")


class CommunityAgentOutput(BaseModel):
    """CommunityAgent output (honest; no fabricated engagement; draft only)."""
    action: str = ""
    platform: str = ""
    draft: str = ""
    provider_used: Optional[str] = None
    external_action_taken: bool = False
    limitations: List[str] = []


class CommunityAgent(AgentBase):
    """
    CommunityAgent - Manages community engagement, forums, and user relationships
    """

    @property
    def name(self) -> str:
        return "community"

    @property
    def role(self) -> str:
        return "Manages community engagement, forums, and user relationships"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CommunityAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CommunityAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_5_NETWORK_ACCESS

    @property
    def default_tools(self) -> list[str]:
        return ['http_get', 'http_post', 'memory_retrieve', 'slack_send']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            action = (input_data.get("action") or "post").strip()
            platform = (input_data.get("platform") or "forum").strip()
            content = helpers.task_text(input_data, "content", "action")
            target_audience = (input_data.get("target_audience") or "all").strip()

            self.logger.info(f"Drafting community {action} for {platform}")

            limitations: List[str] = ["Draft only; nothing posted or moderated."]
            draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            prompt = (
                f"Draft a community {action} for the '{platform}' platform, aimed at "
                f"the '{target_audience}' audience. Topic / context:\n\n{content}\n\n"
                "Write a clear, friendly, on-brand message ready for human review. "
                "Do not invent facts, metrics, or commitments."
            )

            if helpers.provider_configured():
                res = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system=(
                        "You are a careful community manager drafting a message for "
                        "human review. Produce a DRAFT only; never claim to have "
                        "posted or moderated anything; never fabricate engagement."
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
                    f"Drafted community {action} for {platform} "
                    f"({len(draft)} chars) via {provider_used}; nothing posted."
                )
            else:
                output_text = (
                    f"No community {action} draft generated for {platform}: "
                    + (limitations[-1] if limitations else "no provider available")
                )

            return self.create_result(
                success=True,
                result_data={
                    "action": action,
                    "platform": platform,
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
            self.logger.error(f"community task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
