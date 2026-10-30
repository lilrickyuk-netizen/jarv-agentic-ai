"""
JARV Backend - SelfEvolutionAgent

Improves JARV's way of working in a workspace through the verified
self-evolution pipeline (app.core.evolution.engine, via the self-evolution
tools): it proposes changes to rules, runbooks, agent instructions, tool
selection, operating plans and swarm strategy from the workspace's
experience; every proposal is safety-checked and verified; only verified,
safe changes are applied (protected-rule changes wait for Richard); every
applied change is versioned and can be rolled back.

- With a model provider and a workspace, it works through those tools.
- Without a provider but inside a workspace, the caller's proposed changes are
  recorded as workflow changes and verified (applied only when the input asks).
- With no database session it can only draft text, and says nothing was saved.
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
        from app.core.tools.base import ToolConfig
        from app.tools.evolution import EVOLUTION_TOOLS

        return ['experience_log_success', 'experience_query_pattern', 'memory_search',
                'summarise_experience', 'extract_lesson', 'list_experience_records'] + [
            tool(ToolConfig()).name for tool in EVOLUTION_TOOLS]

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        if self.tools_enabled(context):
            outcome = await self.use_tools(context, _brief(input_data), instructions=_INSTRUCTIONS, max_steps=16)
            return self.result_from_tools(outcome, mode="tools")
        if context.db_session is not None and context.workspace_id is not None and input_data.get("proposed_changes"):
            return await self._record(input_data, context)
        return await self._draft(input_data, context)

    async def _record(self, input_data: Dict[str, Any], context: AgentContext) -> AgentResult:
        """Record the caller's proposed changes as workflow changes, verify them, and apply if asked."""
        from app.core.evolution.engine import evolution_engine, view

        db, ws = context.db_session, context.workspace_id
        trigger = str(input_data.get("trigger") or "pattern")
        apply = bool((input_data.get("context") or {}).get("apply"))
        records = []
        for text in [str(c).strip() for c in input_data.get("proposed_changes") or [] if str(c).strip()]:
            record = await evolution_engine.propose(
                db, ws, evolution_type="workflow", target={}, change={"note": text}, title=text[:200],
                reasoning=f"Proposed after a {trigger}", expected_benefit="", proposed_by="self_evolution",
                trigger=trigger, task_id=context.task_id)
            if record.status != "blocked":
                await evolution_engine.verify(db, ws, record)
                if apply and record.status == "verified":
                    await evolution_engine.approve(db, ws, record)
            records.append(view(record))
        applied = [r for r in records if r["status"] == "applied"]
        blocked = [r for r in records if r["status"] == "blocked"]
        return self.create_result(
            success=True,
            result_data={"trigger": trigger, "applied": bool(applied), "records": records,
                         "proposals": [r["title"] for r in records], "rationale": "", "provider_used": None,
                         "limitations": [f"{len(blocked)} proposal(s) blocked by the safety guard"] if blocked else []},
            output_text=(f"{len(records)} change(s) recorded: {len(applied)} applied, {len(blocked)} blocked, "
                         f"{len(records) - len(applied) - len(blocked)} awaiting approval or review"),
            tools_used=["create_self_evolution_record", "verify_self_evolution_change"]
            + (["approve_safe_self_evolution_change"] if applied else []))

    async def _draft(self, input_data: Dict[str, Any], context: AgentContext) -> AgentResult:
        """No database session: draft proposals as text only."""
        try:
            trigger = input_data.get("trigger", "pattern")
            proposed_changes = list(input_data.get("proposed_changes", []) or [])

            self.logger.info(f"Self-evolution proposal drafting triggered by: {trigger}")

            # No database session: nothing can be recorded, verified or applied.
            limitations: List[str] = [
                "This run has no database session, so these proposals were not recorded, "
                "verified or applied; run inside a workspace to use the self-evolution pipeline.",
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
                    "Run this inside a workspace with recorded experience so proposals can be "
                    "drawn from real outcomes and verified before they are applied.",
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


_INSTRUCTIONS = (
    "Improve how this workspace works, from evidence. Start with summarise_experience and "
    "list_self_evolution_history. Propose specific changes with the propose_* tools (rules, runbooks, agent "
    "instructions, tool selection, operating plan, swarm strategy), each with the evidence in its reasoning. "
    "Apply only changes that verified as safe (approve_safe_self_evolution_change); protected-rule changes wait "
    "for Richard. Never propose weakening safety, authority, logging, audit, approvals, verification, secrets or "
    "limits: such changes are blocked. Roll back an applied change that made outcomes worse. Finish with what "
    "you proposed, applied and rolled back.")


def _brief(input_data: Dict[str, Any]) -> str:
    lines = [f"Trigger: {input_data.get('trigger') or 'pattern'}"]
    for key, value in (input_data.get("context") or {}).items():
        lines.append(f"{key}: {value}")
    for change in input_data.get("proposed_changes") or []:
        lines.append(f"Candidate change: {change}")
    return "\n".join(lines)
