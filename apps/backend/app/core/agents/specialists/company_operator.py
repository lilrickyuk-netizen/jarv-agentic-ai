"""
JARV Backend - CompanyOperatorAgent

Runs the autonomous company layer for a workspace through the company tools
(app.tools.company.operations, backed by app.core.company_ops): operating
plans, daily loops, weekly plans, standups, KPIs, risks, decisions and the
operations feed, all persisted and computed from the workspace's real work.

- With a model provider and a workspace, it works through those tools itself.
- Without a provider but with a workspace, it runs the requested operation
  directly (daily loop, standup, plan create/update, weekly plan, or a progress
  review with ranked next actions).
- With no database session at all it can only draft text, and says so;
  nothing is presented as saved.
"""
from typing import Dict, Any, List, Optional, Type
import logging

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel
from app.core.agents.specialists import _helpers as helpers

logger = logging.getLogger(__name__)


class CompanyOperatorAgentInput(BaseModel):
    """CompanyOperatorAgent input"""
    operation: str = Field(..., description="review_progress, run_daily_loop, standup, create_plan, update_plan, "
                                            "weekly_plan, next_actions")
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
        from app.core.tools.base import ToolConfig
        from app.tools.company.operations import COMPANY_TOOLS

        return [tool(ToolConfig()).name for tool in COMPANY_TOOLS] + [
            "generate_task_plan", "update_roadmap", "update_launch_checklist", "summarise_experience"]

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        if self.tools_enabled(context) and (input_data.get("details") or {}).get("goal"):
            outcome = await self.use_tools(context, _brief(input_data), instructions=_INSTRUCTIONS, max_steps=16)
            return self.result_from_tools(outcome, mode="tools", persisted=True)
        if context.db_session is not None and context.workspace_id is not None:
            return await self._operate(input_data, context)
        return await self._draft(input_data, context)

    async def _operate(self, input_data: Dict[str, Any], context: AgentContext) -> AgentResult:
        """Run the requested company operation on the workspace's persisted records."""
        from sqlalchemy import select

        from app.core.company_ops.service import company_ops, loop_view, plan_view, standup_view, weekly_view
        from app.models.workspace import Workspace

        db, ws = context.db_session, context.workspace_id
        operation = str(input_data.get("operation") or "review_progress").lower()
        details = input_data.get("details") or {}
        owner = (await db.execute(select(Workspace.owner_id).where(Workspace.id == ws))).scalar_one_or_none()
        try:
            if operation in ("run_daily_loop", "daily_loop"):
                loop = await company_ops.run_daily_loop(db, ws, loop_date=details.get("date"))
                data, text, tools = {"daily_loop": loop_view(loop)}, loop.summary, ["run_daily_operating_loop"]
            elif operation == "standup":
                row = await company_ops.create_standup(db, ws, standup_date=details.get("date"))
                data = {"standup": standup_view(row)}
                text = (f"Standup: {row.tasks_completed} done, {row.tasks_in_progress} in progress, "
                        f"{len(row.blockers)} blocker(s)")
                tools = ["create_ai_standup"]
            elif operation == "create_plan" and details.get("name") and details.get("start_date") and details.get("end_date"):
                plan = await company_ops.create_operating_plan(
                    db, ws, name=details["name"], plan_type=details.get("plan_type", "operations"),
                    start=details["start_date"], end=details["end_date"], description=details.get("description"),
                    objectives=details.get("objectives"), strategies=details.get("strategies"),
                    milestones=details.get("milestones"), created_by=owner)
                data, text, tools = {"operating_plan": plan_view(plan)}, f"Operating plan '{plan.plan_name}' created", \
                    ["create_operating_plan"]
            elif operation == "update_plan" and details.get("plan_id"):
                plan = await company_ops.update_operating_plan(
                    db, ws, details["plan_id"], change_summary=details.get("change_summary") or "updated by company operator",
                    objectives=details.get("objectives"), milestones=details.get("milestones"),
                    strategies=details.get("strategies"), status=details.get("status"), changed_by=owner)
                data = {"operating_plan": plan_view(plan)}
                text = f"Plan v{plan.current_version}: {plan.completion_percentage:g}% done"
                tools = ["update_operating_plan"]
            elif operation == "weekly_plan":
                plan = await company_ops.create_weekly_plan(
                    db, ws, week_of=details.get("week_of"), objectives=details.get("objectives"),
                    priorities=details.get("priorities"), deliverables=details.get("deliverables"), created_by=owner)
                data, text, tools = {"weekly_plan": weekly_view(plan)}, f"Week {plan.week_number} plan created", \
                    ["create_weekly_execution_plan"]
            else:
                overview = await company_ops.overview(db, ws)
                actions = overview["next_best_actions"]
                data = {**overview, "next_actions": [a["action"] for a in actions]}
                text = (f"{len(actions)} next action(s)" + (f"; first: {actions[0]['action']}" if actions else
                                                            "; nothing open needs action"))
                tools = ["decide_next_best_actions"]
        except (LookupError, ValueError) as exc:
            return self.create_result(success=False, result_data={"operation": operation},
                                      error_message=str(exc))
        return self.create_result(success=True, result_data={"operation": operation, "persisted": True, **data},
                                  output_text=text, tools_used=tools)

    async def _draft(self, input_data: Dict[str, Any], context: AgentContext) -> AgentResult:
        """No database session: draft text only, clearly marked as not saved."""
        try:
            operation = input_data.get("operation", "review_progress")
            workspace_id = input_data.get("workspace_id", "")
            details = input_data.get("details", {}) or {}

            self.logger.info(f"Company operation draft: {operation} for workspace {workspace_id}")

            # No database session for this run, so nothing can be saved:
            # everything below is a DRAFT only.
            limitations: List[str] = [
                "This run has no database session, so nothing was saved; run it inside a "
                "workspace mission to create plans, loops, standups and KPIs.",
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
                    "Run this operation inside a workspace mission so the plan, loop and "
                    "next actions are computed from and saved to the workspace's records.",
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


_INSTRUCTIONS = (
    "You run this workspace's company operating layer. Start with decide_next_best_actions to see what is "
    "actually open. Keep the operating plan, weekly plan, KPIs, risk register and decision log current with "
    "the company tools; run the daily loop when asked for a daily review. Record every significant decision with "
    "create_decision_log. Never invent numbers: KPIs come from real measurements. Finish with a short summary "
    "of what changed and what needs Richard.")


def _brief(input_data: Dict[str, Any]) -> str:
    details = input_data.get("details") or {}
    lines = [f"Operation: {input_data.get('operation') or 'review_progress'}", f"Goal: {details.get('goal')}"]
    for key, value in details.items():
        if key != "goal":
            lines.append(f"{key}: {value}")
    return "\n".join(lines)
