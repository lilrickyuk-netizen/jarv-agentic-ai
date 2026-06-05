"""
JARV Backend - CreationAgent

Drafts an asset SPECIFICATION / manifest (e.g. for an image, video, design,
presentation, or document).

There is NO asset-download / asset-search tool wired into standalone agent
execution, so this agent NEVER produces a real asset file and NEVER verifies a
licence. It does NOT fabricate file paths, dimensions, quality scores, or
licence records. When an LLM provider is configured it produces a real
model-generated DRAFT spec (clearly labelled, unverified). When no provider is
configured it returns an honest limitation. No asset was downloaded; licence
not verified; no external action is taken.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class CreationAgentInput(BaseModel):
    """CreationAgent input"""
    asset_type: str = Field(..., description="image, video, design, presentation, document")
    specifications: Dict[str, Any] = Field(default_factory=dict)
    style: str = Field(default="professional")


class CreationAgentOutput(BaseModel):
    """CreationAgent output (honest; spec draft only; no asset/licence)."""
    asset_type: str = ""
    style: str = ""
    spec_draft: str = ""
    asset_downloaded: bool = False
    licence_verified: bool = False
    provider_used: Optional[str] = None
    external_action_taken: bool = False
    limitations: List[str] = []


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
        try:
            asset_type = (input_data.get("asset_type") or "document").strip()
            style = (input_data.get("style") or "professional").strip()
            specifications = input_data.get("specifications") or {}

            self.logger.info(f"Drafting {asset_type} asset spec in {style} style")

            limitations: List[str] = [
                "No asset source tool configured; no asset was downloaded; licence "
                "not verified.",
            ]
            spec_draft = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            specs_str = (
                "; ".join(f"{k}={v}" for k, v in specifications.items())
                if isinstance(specifications, dict) and specifications
                else "none provided"
            )
            prompt = (
                f"Draft a detailed asset SPECIFICATION (manifest) for a '{asset_type}' "
                f"in a '{style}' style.\n"
                f"Requested specifications: {specs_str}\n\n"
                "Describe intended dimensions/format, content/composition, style "
                "guidance, and a checklist of what a designer or generation tool would "
                "need to produce it. This is a SPEC only — no asset is produced or "
                "downloaded. Do not fabricate file paths, licences, or quality scores."
            )

            if helpers.provider_configured():
                res = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system=(
                        "You are a careful creative director drafting an asset spec "
                        "for human/tool review. Never claim an asset was produced or "
                        "downloaded; never fabricate licences, file paths, or scores."
                    ),
                    temperature=self.config.temperature,
                )
                if res is not None and res.get("text"):
                    spec_draft = res["text"]
                    provider_used = res["provider_used"]
                    tokens = res["tokens"]
                    limitations.append(
                        "Model-generated DRAFT spec, unverified; no external action "
                        "taken."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; no spec "
                        "draft was generated."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            if spec_draft:
                output_text = (
                    f"Drafted {asset_type} asset spec ({style}) "
                    f"({len(spec_draft)} chars) via {provider_used}; "
                    "no asset downloaded, licence not verified."
                )
            else:
                output_text = (
                    f"No {asset_type} asset spec generated ({style}): "
                    + (limitations[-1] if limitations else "no provider available")
                )

            return self.create_result(
                success=True,
                result_data={
                    "asset_type": asset_type,
                    "style": style,
                    "spec_draft": spec_draft,
                    "asset_downloaded": False,
                    "licence_verified": False,
                    "provider_used": provider_used,
                    "external_action_taken": False,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
            )

        except Exception as e:
            self.logger.error(f"creation task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )
