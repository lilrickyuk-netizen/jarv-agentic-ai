"""
JARV Backend - SelfEvolutionAgent

Proposes improvement ideas for JARV's behaviour from experience.

This agent NEVER applies, activates, versions, or rolls back any change. It has
no access to the verified self-evolution pipeline (a separate subsystem that
owns change application, versioning, verification, and rollback). Everything
this agent produces is a PROPOSAL ONLY. When an LLM provider is configured it
drafts improvement proposals via the model router; otherwise it returns an
honest limited response. There are no fabricated impact scores, no false
"evolution applied" claims, and no false rollback_available guarantees.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class SelfEvolutionAgentInput(BaseModel):
    """SelfEvolutionAgent input"""
    trigger: str = Field(..., description="What triggered evolution: success, failure, pattern")
    context: Dict[str, Any] = Field(default_factory=dict)
    proposed_changes: list[str] = Field(default_factory=list)


class SelfEvolutionAgentOutput(BaseModel):
    """SelfEvolutionAgent output (honest; proposals only, never applied)."""
    trigger: str = ""
    applied: bool = False
    proposals: List[str] = Field(default_factory=list)
    rationale: str = ""
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class SelfEvolutionAgent(AgentBase):
    """
    SelfEvolutionAgent - Improves JARV's behavior from experience with safety guards
    """

    @property
    def name(self) -> str:
        return "self_evolution"

    @property
    def role(self) -> str:
        return "Improves JARV's behavior from experience with safety guards"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SelfEvolutionAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SelfEvolutionAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_8_FINANCIAL

    @property
    def default_tools(self) -> list[str]:
        return ['experience_log_success', 'experience_query_pattern', 'memory_search']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            trigger = input_data.get("trigger", "pattern")
            proposed_changes = list(input_data.get("proposed_changes", []) or [])

            self.logger.info(f"Self-evolution proposal drafting triggered by: {trigger}")

            # This agent can ONLY propose. Applying/activating/versioning/
            # rolling-back a change is owned by the verified self-evolution
            # pipeline, which is a separate subsystem not wired in here.
            limitations: List[str] = [
                "These are PROPOSALS ONLY. Applying, activating, versioning, or "
                "rolling back any change requires the verified self-evolution "
                "pipeline (a separate subsystem) and was NOT performed by this "
                "agent. No change was applied.",
                "No safety/verification gate was run here; proposals must pass "
                "the pipeline's safety checks before any change is considered.",
            ]

            proposals: List[str] = []
            rationale = ""
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            # Caller-supplied candidate changes are carried forward as proposals
            # (honestly, with no claim they were applied).
            for c in proposed_changes:
                s = str(c).strip()
                if s:
                    proposals.append(s)

            if helpers.provider_configured():
                ctx_text = "; ".join(
                    f"{k}={v}" for k, v in (input_data.get("context") or {}).items()
                ) or "(no context supplied)"
                seed = ("Candidate changes from caller: " + "; ".join(proposals)) if proposals else ""
                prompt = (
                    f"JARV self-evolution trigger: {trigger}. Context: {ctx_text}. "
                    f"{seed}\n\n"
                    "Propose concrete, safe improvement ideas to JARV's "
                    "workflows, runbooks, prompts, or strategies. Do NOT propose "
                    "anything that weakens safety, authority, logging, or "
                    "boundaries. Respond in plain text: a short rationale "
                    "paragraph, then a line 'PROPOSALS:' followed by one "
                    "proposal per line prefixed with '- '."
                )
                llm = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You propose self-improvement ideas only. You cannot "
                           "apply changes and must never claim you did. Never "
                           "propose weakening safety, authority, or logging.",
                    temperature=self.config.temperature,
                    max_tokens=900,
                )
                if llm is not None:
                    provider_used = llm["provider_used"]
                    tokens = llm["tokens"]
                    rationale, model_proposals = self._split_proposals(llm["text"])
                    proposals.extend(model_proposals)
                    limitations.append(
                        "Proposals are model-generated and unverified; review "
                        "before routing any through the self-evolution pipeline."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; "
                        "returned only caller-supplied proposals (if any)."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            if not proposals:
                proposals = [
                    "Configure an LLM provider to generate improvement "
                    "proposals, then route accepted ones through the verified "
                    "self-evolution pipeline for safety review and application.",
                ]

            output_text = (
                f"Self-evolution[{trigger}]: {len(proposals)} PROPOSAL(s) drafted "
                f"(applied=False); provider={provider_used or 'none'}; "
                f"{len(limitations)} limitation(s) noted."
            )

            return self.create_result(
                success=True,
                result_data={
                    "trigger": trigger,
                    "applied": False,
                    "proposals": proposals,
                    "rationale": rationale,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
                requires_approval=True,
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"self_evolution task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )

    @staticmethod
    def _split_proposals(text: str) -> tuple[str, List[str]]:
        """Split model text into (rationale, proposals) honestly."""
        if not text:
            return "", []
        marker = "PROPOSALS:"
        idx = text.upper().find(marker)
        if idx == -1:
            return text.strip(), []
        rationale = text[:idx].strip()
        block = text[idx + len(marker):]
        out: List[str] = []
        for line in block.splitlines():
            s = line.strip().lstrip("-*0123456789. ").strip()
            if s:
                out.append(s)
        return rationale, out
