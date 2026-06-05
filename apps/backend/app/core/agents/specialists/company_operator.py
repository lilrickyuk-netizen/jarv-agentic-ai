"""
JARV Backend - CompanyOperatorAgent

Drafts operating plans and next-action lists for the autonomous company layer.

This agent does NOT fabricate company state. It cannot persist roles, task
assignments, or operating plans: the company DB layer (workspace/role/task
services) is NOT wired into standalone agent execution, so nothing produced
here is written anywhere. When an LLM provider is configured it drafts a plan
via the model router (clearly labelled as an unpersisted draft); otherwise it
returns an honest limited structured response. There are no fabricated
roles_active / tasks_assigned counts and no false "operation completed" claims.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class CompanyOperatorAgentInput(BaseModel):
    """CompanyOperatorAgent input"""
    operation: str = Field(..., description="create_role, assign_task, update_plan, review_progress")
    workspace_id: str = Field(...)
    details: Dict[str, Any] = Field(default_factory=dict)


class CompanyOperatorAgentOutput(BaseModel):
    """CompanyOperatorAgent output (honest; no persisted state, no fabricated counts)."""
    operation: str = ""
    persisted: bool = False
    plan_draft: str = ""
    next_actions: List[str] = Field(default_factory=list)
    provider_used: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)


class CompanyOperatorAgent(AgentBase):
    """
    CompanyOperatorAgent - Operates autonomous company layer with roles and plans
    """

    @property
    def name(self) -> str:
        return "company_operator"

    @property
    def role(self) -> str:
        return "Operates autonomous company layer with roles and plans"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return CompanyOperatorAgentInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return CompanyOperatorAgentOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        return AuthorityLevel.LEVEL_9_SWARM_CREATION

    @property
    def default_tools(self) -> list[str]:
        return ['workspace_create', 'workspace_update', 'memory_store']

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        try:
            operation = input_data.get("operation", "review_progress")
            workspace_id = input_data.get("workspace_id", "")
            details = input_data.get("details", {}) or {}

            self.logger.info(f"Company operation draft: {operation} for workspace {workspace_id}")

            # Persistence is impossible here: the company DB layer (workspace /
            # role / task services) is NOT wired into standalone agent
            # execution. Everything below is a DRAFT only.
            limitations: List[str] = [
                "Role/task/plan PERSISTENCE requires the company DB layer "
                "(workspace, role, and task services) which is NOT wired into "
                "standalone agent execution; nothing was persisted by this run.",
            ]

            plan_draft = ""
            next_actions: List[str] = []
            provider_used: Optional[str] = None
            tokens: Dict[str, int] = {}

            if helpers.provider_configured():
                detail_text = "; ".join(
                    f"{k}={v}" for k, v in details.items()
                ) if details else "(no extra details supplied)"
                prompt = (
                    f"You are JARV's company operator. Operation requested: "
                    f"{operation}. Workspace id: {workspace_id or '(none)'}. "
                    f"Details: {detail_text}.\n\n"
                    "Produce a concise operating-plan DRAFT and a short list of "
                    "concrete next actions. You CANNOT persist anything; this is "
                    "advisory text only. Respond in plain text: a short plan "
                    "paragraph, then a line 'NEXT ACTIONS:' followed by one "
                    "action per line prefixed with '- '."
                )
                llm = await helpers.llm_complete(
                    self.config.model,
                    prompt,
                    system="You draft company operating plans. Never claim a "
                           "change was saved or a role/task was created; you "
                           "have no write access.",
                    temperature=self.config.temperature,
                    max_tokens=900,
                )
                if llm is not None:
                    text = llm["text"]
                    provider_used = llm["provider_used"]
                    tokens = llm["tokens"]
                    plan_draft, next_actions = self._split_plan(text)
                    limitations.append(
                        "Plan draft is model-generated and unverified; review "
                        "before acting on it."
                    )
                else:
                    limitations.append(
                        "An LLM provider is configured but the call failed; "
                        "returned an honest limited response with no plan draft."
                    )
            else:
                limitations.append(helpers.no_provider_limitation())

            if not next_actions:
                next_actions = [
                    "Wire the company DB layer into agent execution so roles, "
                    "tasks, and plans can actually be persisted.",
                    "Re-run this operation with an LLM provider configured to "
                    "obtain a model-drafted operating plan.",
                ]

            output_text = (
                f"Company operation '{operation}' produced a DRAFT only "
                f"(persisted=False); provider={provider_used or 'none'}; "
                f"{len(next_actions)} next action(s); "
                f"{len(limitations)} limitation(s) noted."
            )

            return self.create_result(
                success=True,
                result_data={
                    "operation": operation,
                    "persisted": False,
                    "plan_draft": plan_draft,
                    "next_actions": next_actions,
                    "provider_used": provider_used,
                    "limitations": limitations,
                },
                output_text=output_text,
                tools_used=(["model_router"] if provider_used else []),
                tokens_used=tokens or {},
                requires_approval=True,
            )

        except Exception as e:  # noqa: BLE001
            self.logger.error(f"company_operator task failed: {e}", exc_info=True)
            return self.create_result(
                success=False,
                result_data={},
                error_message=str(e),
            )

    @staticmethod
    def _split_plan(text: str) -> tuple[str, List[str]]:
        """Split model text into (plan_draft, next_actions) honestly."""
        if not text:
            return "", []
        marker = "NEXT ACTIONS:"
        idx = text.upper().find(marker)
        if idx == -1:
            return text.strip(), []
        plan = text[:idx].strip()
        actions_block = text[idx + len(marker):]
        actions: List[str] = []
        for line in actions_block.splitlines():
            s = line.strip().lstrip("-*0123456789. ").strip()
            if s:
                actions.append(s)
        return plan, actions
