"""
JARV Backend - Swarm tools (Repair 12e-3b)

spawn_sub_agent, assign_sub_agent_task, check_sub_agent_status,
collect_sub_agent_output, dissolve_sub_agent, list_active_sub_agents,
set_max_sub_agent_limit, report_swarm_activity, calculate_swarm_token_cost,
pause_swarm, resume_swarm, cancel_swarm_with_boundary (approval),
attach_sub_agent_log_to_parent_task.

All of them work on the persisted swarm (app.core.swarm) inside the calling
context's workspace, acting for the workspace's owner.

Authority never grows down the chain: a swarm's lead is either the calling
agent itself or a named specialist whose registered authority is capped at
the caller's; every sub-agent is capped at the lead's authority and tools
(enforced in SwarmManager.spawn_sub_agent); sub-agents never spawn sub-agents.
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, List, Optional, Type
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.core.agents.base import AuthorityLevel
from app.core.tools import ToolBase, ToolContext, ToolResult


class _Output(BaseModel):
    data: Dict[str, Any] = Field(default_factory=dict)


class _SwarmTool(ToolBase):
    _name = ""
    _description = ""
    _input: Type[BaseModel] = BaseModel
    _authority = AuthorityLevel.LEVEL_9_SWARM_CREATION
    _approval = False

    name = property(lambda self: self._name)
    description = property(lambda self: self._description)
    input_schema = property(lambda self: self._input)
    output_schema = property(lambda self: _Output)
    required_authority_level = property(lambda self: self._authority)
    requires_approval = property(lambda self: self._approval)
    category = property(lambda self: "swarm")

    async def run(self, input_data: Dict[str, Any], context: ToolContext) -> ToolResult:
        if context.db_session is None or context.workspace_id is None:
            return self.create_result(success=False, error_message="Swarm tools need a workspace and a database session.")
        try:
            data, text = await self.act(context.db_session, context, await _owner(context), input_data)
        except (LookupError, PermissionError, ValueError) as exc:
            return self.create_result(success=False, error_message=str(exc))
        return self.create_result(success=True, result_data=data, output_text=text)

    @abstractmethod
    async def act(self, db, context: ToolContext, owner: UUID, data: Dict[str, Any]):
        """Do the tool's work; return (result data, one-line summary)."""


async def _owner(context: ToolContext) -> UUID:
    from sqlalchemy import select

    from app.models.workspace import Workspace

    owner = (await context.db_session.execute(select(Workspace.owner_id).where(
        Workspace.id == context.workspace_id))).scalar_one_or_none()
    if owner is None:
        raise LookupError("Workspace not found")
    return owner


async def _in_workspace(db, swarm_run_id: str, context: ToolContext, owner: UUID):
    from app.core.swarm.manager import SwarmManager

    swarm = await SwarmManager().owned_swarm(db, UUID(str(swarm_run_id)), owner)
    if swarm.workspace_id != context.workspace_id:
        raise LookupError("Swarm run not found in this workspace")
    return swarm


async def _child_in_workspace(db, sub_agent_id: str, context: ToolContext, owner: UUID):
    from app.core.swarm.manager import SwarmManager

    child = await SwarmManager().owned_sub_agent(db, UUID(str(sub_agent_id)), owner)
    await _in_workspace(db, str(child.swarm_run_id), context, owner)
    return child


async def _lead(db, context: ToolContext, caller_level: int, lead_agent: Optional[str]):
    """The swarm lead: the calling agent's own record, or a named specialist capped at the caller's authority."""
    from sqlalchemy import select

    from app.core.agents.registry import get_registry
    from app.models.agent import Agent

    if not lead_agent and context.agent_id is not None:
        row = (await db.execute(select(Agent).where(Agent.id == context.agent_id,
                                                    Agent.workspace_id == context.workspace_id,
                                                    Agent.is_active.is_(True)))).scalar_one_or_none()
        if row is not None:
            if row.is_subagent:
                raise PermissionError("Sub-agents cannot create swarms (depth is limited to 1)")
            return row
    if not lead_agent:
        raise ValueError("Name the lead_agent whose tools and authority the sub-agents inherit")
    meta = get_registry().get_metadata(lead_agent)
    if meta is None or not get_registry().is_implemented(lead_agent):
        raise ValueError(f"'{lead_agent}' is not a registered agent")
    level = min(int(meta.required_authority_level), int(caller_level))
    if level < int(meta.required_authority_level):
        raise PermissionError(f"The caller's authority ({caller_level}) is below {lead_agent}'s "
                              f"({int(meta.required_authority_level)})")
    row = Agent(id=uuid4(), name=f"{lead_agent} swarm lead", agent_type=lead_agent,
                workspace_id=context.workspace_id, is_active=True, is_subagent=False,
                config={"role": "swarm_lead", "created_by_agent": str(context.agent_id) if context.agent_id else None},
                model_provider="configured-router", model_name="claude-sonnet-4-6", authority_level=level,
                allowed_tools=list(meta.default_tools or []), blocked_tools=[], current_state="idle",
                total_executions=0, successful_executions=0, failed_executions=0, total_tokens_used=0)
    db.add(row)
    await db.flush()
    return row


# ----- inputs ----------------------------------------------------------------------------

class _SpawnInput(BaseModel):
    agent_template: str = Field(..., description="Registered agent to run as the sub-agent, e.g. coding_agent")
    task: str = Field(..., min_length=5, description="The sub-agent's bounded task")
    swarm_run_id: Optional[str] = Field(None, description="Existing swarm; omit to start a new one")
    objective: Optional[str] = Field(None, description="Objective of a new swarm")
    lead_agent: Optional[str] = Field(None, description="For a new swarm: the specialist whose tools and authority "
                                                        "the sub-agents inherit (defaults to the caller)")
    max_sub_agents: int = Field(3, ge=1, le=50)
    authority_level: Optional[int] = Field(None, ge=0, le=10)
    allowed_tools: Optional[List[str]] = None
    timeout_seconds: int = Field(1800, ge=60, le=7200)


class _SubAgentInput(BaseModel):
    sub_agent_id: str


class _AssignInput(_SubAgentInput):
    title: str = Field(..., min_length=3)
    task: str = Field(..., min_length=5)


class _DissolveInput(_SubAgentInput):
    reason: str = "completed"


class _SwarmInput(BaseModel):
    swarm_run_id: str


class _CancelInput(_SwarmInput):
    reason: str = Field(..., min_length=5)


class _ListInput(BaseModel):
    swarm_run_id: Optional[str] = None


class _LimitInput(BaseModel):
    max_sub_agents_per_swarm: Optional[int] = Field(None, ge=1, le=50)
    max_concurrent_swarms: Optional[int] = Field(None, ge=1, le=20)
    max_total_sub_agents: Optional[int] = Field(None, ge=1, le=500)
    max_cost_per_swarm: Optional[float] = Field(None, gt=0)


class _AttachInput(_SubAgentInput):
    parent_task_id: Optional[str] = Field(None, description="Defaults to the current task")


# ----- tools ----------------------------------------------------------------------------

class SpawnSubAgentTool(_SwarmTool):
    _name = "spawn_sub_agent"
    _description = ("Spawn a scoped sub-agent and run its task now. Starts a swarm when no swarm_run_id is "
                    "given. The sub-agent's authority and tools never exceed the lead's.")
    _input = _SpawnInput

    async def act(self, db, context, owner, data):
        from app.core.agents.registry import get_registry
        from app.core.swarm.manager import SwarmManager, SwarmRunCreate
        from app.core.swarm.sub_agent import SubAgentManager

        manager = SwarmManager()
        if data.get("swarm_run_id"):
            swarm = await _in_workspace(db, data["swarm_run_id"], context, owner)
            swarm_id = swarm.id
            from sqlalchemy import select

            from app.models.agent import Agent

            lead = (await db.execute(select(Agent).where(Agent.id == swarm.parent_agent_id))).scalar_one()
        else:
            lead = await _lead(db, context, int(self.config.authority_level), data.get("lead_agent"))
            swarm_id = await manager.create_swarm_run(SwarmRunCreate(
                workspace_id=context.workspace_id, lead_agent_id=lead.id, lead_agent_name=lead.name,
                parent_task_id=context.task_id, swarm_purpose=data.get("objective") or data["task"][:500],
                max_sub_agents=data.get("max_sub_agents", 3), timeout_seconds=data.get("timeout_seconds", 1800)),
                db=db, authenticated_user_id=owner)
        meta = get_registry().get_metadata(data["agent_template"])
        if meta is None:
            raise ValueError(f"'{data['agent_template']}' is not a registered agent")
        authority = data.get("authority_level")
        if authority is None:
            authority = max(int(meta.required_authority_level), 0)
        tools = data.get("allowed_tools")
        if tools is None:
            tools = sorted(set(meta.default_tools or []) & set(lead.allowed_tools or []))
        child_id = await manager.spawn_sub_agent(swarm_id, data["agent_template"], data["task"], int(authority),
                                                 list(tools), data.get("timeout_seconds", 1800), db=db,
                                                 authenticated_user_id=owner)
        status = await SubAgentManager().get_status(db, child_id, owner)
        return ({"swarm_run_id": str(swarm_id), "sub_agent_id": str(child_id), **status},
                f"{data['agent_template']} sub-agent {'succeeded' if status['success'] else 'failed'}")


class AssignSubAgentTaskTool(_SwarmTool):
    _name = "assign_sub_agent_task"
    _description = "Give an existing sub-agent another task and run it within its original limits."
    _input = _AssignInput

    async def act(self, db, context, owner, data):
        from app.core.swarm.sub_agent import SubAgentManager, SubAgentTaskCreate

        child = await _child_in_workspace(db, data["sub_agent_id"], context, owner)
        manager = SubAgentManager()
        task_id = await manager.assign_task(db, SubAgentTaskCreate(sub_agent_id=child.id, task_title=data["title"],
                                                                   task_description=data["task"]), owner)
        status = await manager.get_status(db, child.id, owner)
        return {"task_id": str(task_id), **status}, f"task {'succeeded' if status['success'] else 'failed'}"


class CheckSubAgentStatusTool(_SwarmTool):
    _name = "check_sub_agent_status"
    _description = "Status, tasks, tokens and cost of one sub-agent."
    _input = _SubAgentInput
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        from app.core.swarm.sub_agent import SubAgentManager

        child = await _child_in_workspace(db, data["sub_agent_id"], context, owner)
        status = await SubAgentManager().get_status(db, child.id, owner)
        return status, f"{status['agent']}: {status['status']}"


class CollectSubAgentOutputTool(_SwarmTool):
    _name = "collect_sub_agent_output"
    _description = "Every task output a sub-agent produced, with a combined summary of the successful ones."
    _input = _SubAgentInput
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        from app.core.swarm.sub_agent import SubAgentManager

        child = await _child_in_workspace(db, data["sub_agent_id"], context, owner)
        output = await SubAgentManager().collect_output(db, child.id, owner)
        return output, f"{len(output['completed_tasks'])} successful task output(s)"


class DissolveSubAgentTool(_SwarmTool):
    _name = "dissolve_sub_agent"
    _description = "Dissolve a sub-agent: its agent record is deactivated and its outcome kept."
    _input = _DissolveInput

    async def act(self, db, context, owner, data):
        from app.core.swarm.manager import SwarmManager

        child = await _child_in_workspace(db, data["sub_agent_id"], context, owner)
        child = await SwarmManager().dissolve_sub_agent(db, child.id, owner, data.get("reason") or "completed")
        return {"sub_agent_id": str(child.id), "status": child.status}, "dissolved"


class ListActiveSubAgentsTool(_SwarmTool):
    _name = "list_active_sub_agents"
    _description = "Sub-agents still working in this workspace (or in one swarm)."
    _input = _ListInput
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        from app.core.swarm.sub_agent import SubAgentManager

        swarm_id = None
        if data.get("swarm_run_id"):
            swarm_id = (await _in_workspace(db, data["swarm_run_id"], context, owner)).id
        rows = await SubAgentManager().list_sub_agents(db, owner, swarm_id, active_only=True)
        from sqlalchemy import select

        from app.models.swarm import SwarmRun

        ids = set((await db.execute(select(SwarmRun.id).where(SwarmRun.workspace_id == context.workspace_id))).scalars())
        items = [r.model_dump(mode="json") for r in rows if r.swarm_run_id in ids]
        return {"sub_agents": items}, f"{len(items)} active sub-agent(s)"


class SetMaxSubAgentLimitTool(_SwarmTool):
    _name = "set_max_sub_agent_limit"
    _description = "Set this workspace's swarm limits (they can only be at or below the global limits)."
    _input = _LimitInput

    async def act(self, db, context, owner, data):
        from app.core.swarm.limits import SwarmLimitManager

        manager = SwarmLimitManager()
        await manager.set_swarm_limit(db, context.workspace_id, changed_by=owner,
                                      **{k: v for k, v in data.items() if v is not None})
        stats = await manager.get_limit_stats(db, context.workspace_id)
        return stats, f"limits: {stats['limits']}"


class ReportSwarmActivityTool(_SwarmTool):
    _name = "report_swarm_activity"
    _description = "A swarm's metrics, costs, sub-agents, timeline, issues and recommendations."
    _input = _SwarmInput
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        from app.core.swarm.tracking import SwarmTracker

        swarm = await _in_workspace(db, data["swarm_run_id"], context, owner)
        report = await SwarmTracker().report_swarm_activity(db, swarm.id)
        return report, f"{report['status']}: {report['metrics']['total_sub_agents']} sub-agent(s)"


class CalculateSwarmTokenCostTool(_SwarmTool):
    _name = "calculate_swarm_token_cost"
    _description = "Tokens and estimated cost of a swarm, by model and by sub-agent."
    _input = _SwarmInput
    _authority = AuthorityLevel.LEVEL_1_BASIC_TOOLS

    async def act(self, db, context, owner, data):
        from app.core.swarm.tracking import SwarmTracker

        swarm = await _in_workspace(db, data["swarm_run_id"], context, owner)
        costs = await SwarmTracker().calculate_swarm_cost(db, swarm.id)
        return costs, f"{costs['totals']['tokens']} tokens, ~${costs['totals']['cost']:.4f}"


class PauseSwarmTool(_SwarmTool):
    _name = "pause_swarm"
    _description = "Pause a swarm: no new sub-agents or tasks start until it is resumed."
    _input = _SwarmInput

    async def act(self, db, context, owner, data):
        from app.core.swarm.manager import SwarmManager

        swarm = await _in_workspace(db, data["swarm_run_id"], context, owner)
        swarm = await SwarmManager().pause_swarm(db, swarm.id, owner)
        return {"swarm_run_id": str(swarm.id), "status": swarm.status}, "paused"


class ResumeSwarmTool(_SwarmTool):
    _name = "resume_swarm"
    _description = "Resume a paused swarm."
    _input = _SwarmInput

    async def act(self, db, context, owner, data):
        from app.core.swarm.manager import SwarmManager

        swarm = await _in_workspace(db, data["swarm_run_id"], context, owner)
        swarm = await SwarmManager().resume_swarm(db, swarm.id, owner)
        return {"swarm_run_id": str(swarm.id), "status": swarm.status}, "resumed"


class CancelSwarmTool(_SwarmTool):
    _name = "cancel_swarm_with_boundary"
    _description = "Cancel a swarm and dissolve its unfinished sub-agents. Pauses for Richard's approval."
    _input = _CancelInput
    _approval = True

    async def act(self, db, context, owner, data):
        from app.core.swarm.manager import SwarmManager

        swarm = await _in_workspace(db, data["swarm_run_id"], context, owner)
        swarm = await SwarmManager().cancel_swarm(db, swarm.id, owner, data["reason"])
        return {"swarm_run_id": str(swarm.id), "status": swarm.status}, "cancelled"


class AttachSubAgentLogTool(_SwarmTool):
    _name = "attach_sub_agent_log_to_parent_task"
    _description = "Copy a sub-agent's log into its parent task's record and the audit trail."
    _input = _AttachInput
    _authority = AuthorityLevel.LEVEL_2_FILE_OPERATIONS

    async def act(self, db, context, owner, data):
        from app.core.swarm.sub_agent import SubAgentManager

        child = await _child_in_workspace(db, data["sub_agent_id"], context, owner)
        parent = data.get("parent_task_id") or (str(context.task_id) if context.task_id else None)
        if not parent:
            raise ValueError("parent_task_id is required outside a task")
        result = await SubAgentManager().attach_logs_to_parent_task(db, child.id, owner, UUID(parent))
        return result, f"{result['entries']} log entries attached"


SWARM_TOOLS = [SpawnSubAgentTool, AssignSubAgentTaskTool, CheckSubAgentStatusTool, CollectSubAgentOutputTool,
               DissolveSubAgentTool, ListActiveSubAgentsTool, SetMaxSubAgentLimitTool, ReportSwarmActivityTool,
               CalculateSwarmTokenCostTool, PauseSwarmTool, ResumeSwarmTool, CancelSwarmTool, AttachSubAgentLogTool]

__all__ = ["SWARM_TOOLS"] + [t.__name__ for t in SWARM_TOOLS]
