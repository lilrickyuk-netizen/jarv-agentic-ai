"""
JARV Backend - Self-evolution tools (Repair 12e-3d)

propose_rule_improvement, propose_runbook_improvement,
propose_agent_instruction_update, propose_tool_selection_update,
propose_operating_plan_update, propose_swarm_strategy_update,
create_self_evolution_record, verify_self_evolution_change,
approve_safe_self_evolution_change, reject_self_evolution_change,
list_self_evolution_history, rollback_self_evolution_change.

All of them work through app.core.evolution.engine on the calling workspace:
proposals are safety-checked and verified at once, only verified changes are
applied, every application saves the previous state and is versioned, and
any applied change can be rolled back. Changes that would weaken safety,
authority, logging, verification, boundaries or limits are blocked for good;
changes to protected rules (and rollbacks that would disable one) pause for
Richard's approval.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.evolution.engine import TYPES, evolution_engine, view
from app.core.tools import ToolContext, ToolResult
from app.tools._scoped import ScopedTool, workspace_owner


class _EvolutionTool(ScopedTool):
    _category = "self_evolution"
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS


class _Proposal(BaseModel):
    title: str = Field(..., min_length=3, max_length=480)
    reasoning: str = Field(..., min_length=3, description="Why: the evidence (experiences, failures, metrics)")
    expected_benefit: str = Field("", description="What should improve, and how it will be measured")


async def _propose(db, context: ToolContext, etype: str, target: Dict[str, Any], change: Dict[str, Any],
                   data: Dict[str, Any]):
    record = await evolution_engine.propose(
        db, context.workspace_id, evolution_type=etype, target=target,
        change={k: v for k, v in change.items() if v is not None}, title=data["title"], reasoning=data["reasoning"],
        expected_benefit=data.get("expected_benefit") or "", proposed_by=f"agent:{context.agent_id}" if context.agent_id
        else "agent", task_id=context.task_id)
    verification = None
    if record.status != "blocked":
        result = await evolution_engine.verify(db, context.workspace_id, record)
        verification = {"passed": result.passed, "recommendation": result.recommendation, "checks": result.tests_run}
    text = {"blocked": "Blocked by the safety guard (can never be applied)",
            "verified": "Verified; ready to apply", "needs_approval": "Verified; needs Richard's approval",
            "failed_verification": "Failed verification"}.get(record.status, record.status)
    return {**view(record), "verification": verification}, f"{etype} change {record.status}: {text}"


# ----- proposals ----------------------------------------------------------------------------

class _RuleInput(_Proposal):
    name: str = Field(..., description="Rule name (existing to change, new to create)")
    rule_type: Optional[str] = Field(None, description="workflow, coding, naming, review, ...")
    description: Optional[str] = None
    content: Optional[Dict[str, Any]] = None
    priority: Optional[int] = Field(None, ge=1, le=10)
    active: Optional[bool] = None


class ProposeRuleImprovementTool(_EvolutionTool):
    _name = "propose_rule_improvement"
    _description = "Propose a new or changed workspace rule; it is safety-checked and verified at once."
    _input = _RuleInput

    async def act(self, db, context, owner, data):
        return await _propose(db, context, "rule", {"name": data["name"]},
                              {"type": data.get("rule_type"), "description": data.get("description"),
                               "content": data.get("content"), "priority": data.get("priority"),
                               "active": data.get("active")}, data)


class _RunbookInput(_Proposal):
    name: str
    steps: Optional[List[Any]] = Field(None, description="Strings or {action, detail}")
    description: Optional[str] = None
    prerequisites: Optional[List[str]] = None
    expected_outcome: Optional[str] = None
    runbook_type: Optional[str] = None


class ProposeRunbookImprovementTool(_EvolutionTool):
    _name = "propose_runbook_improvement"
    _description = "Propose a new or improved runbook (steps, prerequisites, expected outcome); never auto-executing."
    _input = _RunbookInput

    async def act(self, db, context, owner, data):
        return await _propose(db, context, "runbook", {"name": data["name"]},
                              {k: data.get(k) for k in ("steps", "description", "prerequisites", "expected_outcome",
                                                        "runbook_type")}, data)


class _AgentInput(_Proposal):
    agent: str = Field(..., description="Registered agent name, e.g. coding_agent")
    instructions: str = Field(..., min_length=10, max_length=4000)
    strategy: Optional[Dict[str, Any]] = None


class ProposeAgentInstructionUpdateTool(_EvolutionTool):
    _name = "propose_agent_instruction_update"
    _description = ("Propose standing instructions for one agent in this workspace; once applied they are given "
                    "to the agent below the system and safety rules.")
    _input = _AgentInput

    async def act(self, db, context, owner, data):
        return await _propose(db, context, "agent_instruction", {"agent": data["agent"]},
                              {"instructions": data["instructions"], "strategy": data.get("strategy")}, data)


class _ToolInput(_Proposal):
    name: str = Field(..., description="Rule name")
    agent: Optional[str] = Field(None, description="Limit the rule to one agent")
    recommended_tools: List[str] = Field(default_factory=list)
    blocked_tools: List[str] = Field(default_factory=list, description="Never safety tools")


class ProposeToolSelectionUpdateTool(_EvolutionTool):
    _name = "propose_tool_selection_update"
    _description = "Propose which tools an agent should prefer or stop using here (it can narrow tools, never add)."
    _input = _ToolInput

    async def act(self, db, context, owner, data):
        return await _propose(db, context, "tool_selection", {"name": data["name"], "agent": data.get("agent")},
                              {"agent": data.get("agent"), "recommended_tools": data["recommended_tools"],
                               "blocked_tools": data["blocked_tools"]}, data)


class _PlanInput(_Proposal):
    plan_id: str
    objectives: Optional[List[Any]] = None
    strategies: Optional[List[Any]] = None
    milestones: Optional[List[Any]] = None


class ProposeOperatingPlanUpdateTool(_EvolutionTool):
    _name = "propose_operating_plan_update"
    _description = "Propose changes to an operating plan's objectives, strategies or milestones (by title)."
    _input = _PlanInput

    async def act(self, db, context, owner, data):
        return await _propose(db, context, "operating_plan", {"plan_id": data["plan_id"]},
                              {k: data.get(k) for k in ("objectives", "strategies", "milestones")}, data)


class _SwarmInput(_Proposal):
    coordination_strategy: Optional[str] = Field(None, description="parallel, sequential, hierarchical, pipeline")
    max_parallel_sub_agents: Optional[int] = Field(None, ge=1, description="Never above the swarm limit")
    preferred_leads: Optional[Dict[str, str]] = Field(None, description="{task kind: lead agent}")
    notes: Optional[str] = None


class ProposeSwarmStrategyUpdateTool(_EvolutionTool):
    _name = "propose_swarm_strategy_update"
    _description = "Propose how swarms coordinate here (strategy, parallelism within limits, preferred leads)."
    _input = _SwarmInput

    async def act(self, db, context, owner, data):
        return await _propose(db, context, "swarm_strategy", {},
                              {k: data.get(k) for k in ("coordination_strategy", "max_parallel_sub_agents",
                                                        "preferred_leads", "notes")}, data)


class _RecordInput(_Proposal):
    evolution_type: str = Field(..., description=", ".join(TYPES))
    target: Dict[str, Any] = Field(default_factory=dict)
    change: Dict[str, Any] = Field(..., description="For a workflow note: {note}")


class CreateSelfEvolutionRecordTool(_EvolutionTool):
    _name = "create_self_evolution_record"
    _description = "Record any self-evolution change (including a workflow note) for verification."
    _input = _RecordInput

    async def act(self, db, context, owner, data):
        return await _propose(db, context, data["evolution_type"], data["target"], data["change"], data)


# ----- lifecycle ------------------------------------------------------------------------------

class _IdInput(BaseModel):
    record_id: str


class _ReasonInput(_IdInput):
    reason: str = Field(..., min_length=3)


class VerifySelfEvolutionChangeTool(_EvolutionTool):
    _name = "verify_self_evolution_change"
    _description = "Re-run verification of a proposed change against the live component."
    _input = _IdInput
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        record = await evolution_engine.get(db, context.workspace_id, data["record_id"])
        result = await evolution_engine.verify(db, context.workspace_id, record)
        return ({**view(record), "verification": {"passed": result.passed, "recommendation": result.recommendation,
                                                  "checks": result.tests_run, "warnings": result.warnings}},
                f"Verification {'passed' if result.passed else 'failed'} ({result.recommendation})")


class _GatedTool(_EvolutionTool):
    """Runs the action; a change that needs Richard pauses with an approval request instead of failing."""

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if context.db_session is None or context.workspace_id is None:
            return self.create_result(success=False, error_message=f"{self._name} needs a workspace.")
        approved = context.approval_granted or self._name in (context.approved_tools or [])
        try:
            data = self._input(**(input_data or {})).model_dump()
            result, text = await self.act(context.db_session, context, await workspace_owner(context),
                                          {**data, "_richard_approved": approved})
        except PermissionError as exc:
            return self.create_result(success=False, error_message=str(exc),
                                      result_data={"blocked": True, "requires_approval": True, "reason": str(exc),
                                                   "tool": self._name})
        except (LookupError, ValueError) as exc:
            return self.create_result(success=False, error_message=str(exc))
        return self.create_result(success=True, result_data=result, output_text=text)


class ApproveSafeSelfEvolutionChangeTool(_GatedTool):
    _name = "approve_safe_self_evolution_change"
    _description = ("Apply a verified change. Safe changes apply at once; protected-rule changes need Richard's "
                    "approval; blocked or unverified changes are refused.")
    _input = _IdInput
    _authority = AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    async def act(self, db, context, owner, data):
        record = await evolution_engine.get(db, context.workspace_id, data["record_id"])
        await evolution_engine.approve(db, context.workspace_id, record, approved_by=owner,
                                       richard_approved=data["_richard_approved"])
        return view(record), f"Applied as version {(record.meta_data or {}).get('version')}"


class RejectSelfEvolutionChangeTool(_EvolutionTool):
    _name = "reject_self_evolution_change"
    _description = "Reject a proposed change with a reason."
    _input = _ReasonInput

    async def act(self, db, context, owner, data):
        record = await evolution_engine.get(db, context.workspace_id, data["record_id"])
        await evolution_engine.reject(db, context.workspace_id, record, data["reason"])
        return view(record), "Rejected"


class _HistoryInput(BaseModel):
    evolution_type: Optional[str] = None
    status: Optional[str] = Field(None, description="proposed, verified, needs_approval, applied, rolled_back, "
                                                    "rejected, blocked, failed_verification")
    component: Optional[str] = Field(None, description="e.g. rule:branch names")
    limit: int = Field(25, ge=1, le=200)


class ListSelfEvolutionHistoryTool(_EvolutionTool):
    _name = "list_self_evolution_history"
    _description = "This workspace's self-evolution changes with their status, versions and rollbacks."
    _input = _HistoryInput
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        rows = await evolution_engine.history(db, [context.workspace_id], evolution_type=data.get("evolution_type"),
                                              status=data.get("status"), component=data.get("component"),
                                              limit=data["limit"])
        return ({"records": [view(r) for r in rows], "stats": await evolution_engine.stats(db, context.workspace_id)},
                f"{len(rows)} self-evolution record(s)")


class RollbackSelfEvolutionChangeTool(_GatedTool):
    _name = "rollback_self_evolution_change"
    _description = "Restore the component to its state before an applied change (newest change first)."
    _input = _ReasonInput
    _authority = AuthorityLevel.LEVEL_4_SYSTEM_CHANGES

    async def act(self, db, context, owner, data):
        record = await evolution_engine.get(db, context.workspace_id, data["record_id"])
        await evolution_engine.rollback(db, context.workspace_id, record, data["reason"],
                                        richard_approved=data["_richard_approved"], rolled_back_by=owner)
        return view(record), "Rolled back"


EVOLUTION_TOOLS = [
    ProposeRuleImprovementTool, ProposeRunbookImprovementTool, ProposeAgentInstructionUpdateTool,
    ProposeToolSelectionUpdateTool, ProposeOperatingPlanUpdateTool, ProposeSwarmStrategyUpdateTool,
    CreateSelfEvolutionRecordTool, VerifySelfEvolutionChangeTool, ApproveSafeSelfEvolutionChangeTool,
    RejectSelfEvolutionChangeTool, ListSelfEvolutionHistoryTool, RollbackSelfEvolutionChangeTool,
]
