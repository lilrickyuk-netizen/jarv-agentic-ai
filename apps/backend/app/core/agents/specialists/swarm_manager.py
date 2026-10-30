"""
JARV Backend - SwarmManagerAgent

Manages agent swarming, sub-agent lifecycle, and parallel execution. This is
agent #31 in the design (Design_md.txt section 11). It runs swarms through the
swarm tools (app.tools.swarm): with a model provider it plans and coordinates
them itself; without one it runs the given tasks as one swarm, collects the
outputs and cost, and closes the swarm; with no tasks it reports the real
limits and current usage.
"""
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel


class SwarmManagerInput(BaseModel):
    """SwarmManagerAgent input"""
    action: str = Field(default="status", description="status | plan | run")
    requested_sub_agents: int = Field(default=0, description="Sub-agents requested for a plan")
    objective: Optional[str] = Field(default=None, description="What the swarm should achieve")
    lead_agent: Optional[str] = Field(default=None, description="Specialist whose tools the sub-agents inherit")
    tasks: List[Dict[str, Any]] = Field(default_factory=list,
                                        description="[{agent, task}] to run as sub-agents")


class SwarmManagerOutput(BaseModel):
    """SwarmManagerAgent output"""
    limits: Dict[str, Any]
    can_spawn: bool
    notes: list[str]


class SwarmManagerAgent(AgentBase):
    """Coordinates scoped, bounded parallel sub-agent execution (real swarm subsystem)."""

    @property
    def name(self) -> str:
        return "swarm_manager"

    @property
    def role(self) -> str:
        return "Manages agent swarming, sub-agent lifecycle, and bounded parallel execution"

    @property
    def input_schema(self) -> Type[BaseModel]:
        return SwarmManagerInput

    @property
    def output_schema(self) -> Type[BaseModel]:
        return SwarmManagerOutput

    @property
    def required_authority_level(self) -> AuthorityLevel:
        # Spawning swarms is the highest-coordination authority.
        return AuthorityLevel.LEVEL_9_SWARM_CREATION

    @property
    def default_tools(self) -> list[str]:
        from app.tools.swarm import SWARM_TOOLS
        from app.core.tools.base import ToolConfig

        return [tool(ToolConfig()).name for tool in SWARM_TOOLS]

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """Run a swarm for the given tasks, or report real limits and capacity."""
        tasks = [t for t in (input_data.get("tasks") or []) if isinstance(t, dict) and t.get("agent") and t.get("task")]
        if self.tools_enabled(context) and (tasks or input_data.get("objective")):
            outcome = await self.use_tools(context, _brief(input_data), instructions=_INSTRUCTIONS, max_steps=24)
            return self.result_from_tools(outcome, mode="tools")
        if tasks and context.db_session is not None and context.workspace_id is not None:
            return await self._run_tasks(input_data, tasks, context)
        return await self._report(input_data, context)

    async def _run_tasks(self, input_data: Dict[str, Any], tasks: list, context: AgentContext) -> AgentResult:
        """Spawn one sub-agent per task in one swarm, collect outputs, report cost, then close the swarm."""
        from app.core.agents.toolbox import AgentToolbox
        from app.core.swarm.manager import SwarmManager

        box = await AgentToolbox(self, context).prepare()
        swarm_id = None
        spawned: list = []
        for item in tasks[:10]:
            args = {"agent_template": item["agent"], "task": item["task"],
                    "objective": input_data.get("objective") or "parallel execution",
                    "lead_agent": input_data.get("lead_agent"), "max_sub_agents": min(len(tasks), 10)}
            if swarm_id:
                args = {"agent_template": item["agent"], "task": item["task"], "swarm_run_id": swarm_id}
            result = await box.call("spawn_sub_agent", args)
            data = result.get("data") or {}
            swarm_id = swarm_id or data.get("swarm_run_id")
            spawned.append({"agent": item["agent"], "success": bool(result.get("success") and data.get("success")),
                            "sub_agent_id": data.get("sub_agent_id"),
                            "error": result.get("error") or data.get("error")})
        outputs, report = [], {}
        if swarm_id:
            for child in spawned:
                if child["sub_agent_id"]:
                    collected = await box.call("collect_sub_agent_output", {"sub_agent_id": child["sub_agent_id"]})
                    outputs.append((collected.get("data") or {}).get("summary", ""))
            report = (await box.call("report_swarm_activity", {"swarm_run_id": swarm_id})).get("data") or {}
            from sqlalchemy import select

            from app.models.workspace import Workspace

            owner = (await context.db_session.execute(select(Workspace.owner_id).where(
                Workspace.id == context.workspace_id))).scalar_one()
            try:
                await SwarmManager().complete_swarm(context.db_session, swarm_id, owner)
            except ValueError as exc:
                self.logger.warning(f"swarm {swarm_id} left open: {exc}")
        ok = sum(1 for c in spawned if c["success"])
        trail = box.summary()
        return self.create_result(
            success=bool(spawned) and ok == len(spawned),
            result_data={"limits": report.get("metrics", {}), "can_spawn": True, "notes": [],
                         "swarm_run_id": swarm_id, "sub_agents": spawned, "outputs": outputs,
                         "costs": report.get("costs"), "tool_calls": trail["calls"]},
            output_text=f"Swarm ran {len(spawned)} sub-agent(s); {ok} succeeded.",
            tools_used=sorted({c["name"] for c in trail["calls"]}),
            error_message=None if ok == len(spawned) else f"{len(spawned) - ok} sub-agent(s) failed")

    async def _report(self, input_data: Dict[str, Any], context: AgentContext) -> AgentResult:
        """Real limits and capacity (workspace policy and usage when a database is available)."""
        from app.core.swarm.limits import SwarmLimitManager, global_limits

        requested = int(input_data.get("requested_sub_agents", 0) or 0)
        notes: list[str] = ["Sub-agents inherit the lead's authority, tools and workspace; they cannot escalate "
                            "or spawn sub-agents of their own."]
        limits: Dict[str, Any] = global_limits()
        usage: Dict[str, Any] = {}
        if context.db_session is not None and context.workspace_id is not None:
            manager = SwarmLimitManager()
            limits = await manager.effective_limits(context.db_session, context.workspace_id)
            usage = await manager.usage(context.db_session, context.workspace_id)
        can_spawn = (not requested or requested <= limits["max_sub_agents_per_swarm"]) and \
            usage.get("active_swarms", 0) < limits["max_concurrent_swarms"]
        if requested and requested > limits["max_sub_agents_per_swarm"]:
            notes.append(f"Requested {requested} sub-agents exceeds the per-swarm limit "
                         f"{limits['max_sub_agents_per_swarm']}.")
        return self.create_result(
            success=True,
            result_data={"limits": {**limits, "usage": usage}, "can_spawn": can_spawn, "notes": notes},
            output_text=(f"Swarm limits: {limits['max_sub_agents_per_swarm']} sub-agents per swarm, "
                         f"{limits['max_concurrent_swarms']} concurrent swarms"
                         + (f"; {usage.get('active_swarms', 0)} active now." if usage else ".")),
            tools_used=[], iterations_used=1)


_INSTRUCTIONS = (
    "Split the objective into independent, bounded tasks and run each as a sub-agent with spawn_sub_agent "
    "(the first call starts the swarm; pass its swarm_run_id to the rest). Pick the specialist that fits each "
    "task. Check results with check_sub_agent_status and collect_sub_agent_output, attach logs to the parent task, "
    "and dissolve sub-agents when done. Report cost with calculate_swarm_token_cost. Cancelling a swarm pauses for "
    "Richard's approval. Combine the outputs into one result in your finish summary.")


def _brief(input_data: Dict[str, Any]) -> str:
    lines = [f"Objective: {input_data.get('objective') or 'run the tasks below in parallel'}"]
    if input_data.get("lead_agent"):
        lines.append(f"Lead agent (sub-agents inherit its tools): {input_data['lead_agent']}")
    for item in input_data.get("tasks") or []:
        if isinstance(item, dict):
            lines.append(f"- {item.get('agent')}: {item.get('task')}")
    return "\n".join(lines)
