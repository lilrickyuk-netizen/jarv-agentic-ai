"""
JARV Backend - SwarmManagerAgent

Manages agent swarming, sub-agent lifecycle, and parallel execution. This is
agent #31 in the design (Design_md.txt section 11). It is a thin agent that
exposes the real swarm subsystem (app.core.swarm) - sub-agent limits, scoping,
and lifecycle policy - through the standard agent interface so it appears in
the registry and can be coordinated by the orchestrator.
"""
from typing import Any, Dict, Type

from pydantic import BaseModel, Field

from app.core.agents.base import AgentBase, AgentConfig, AgentContext, AgentResult, AuthorityLevel


class SwarmManagerInput(BaseModel):
    """SwarmManagerAgent input"""
    action: str = Field(default="status", description="status | plan")
    requested_sub_agents: int = Field(default=0, description="Sub-agents requested for a plan")


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
        return ["swarm_spawn", "swarm_dissolve", "swarm_track"]

    async def run(
        self,
        input_data: Dict[str, Any],
        context: AgentContext,
    ) -> AgentResult:
        """Report real swarm limits/capability from the swarm subsystem."""
        requested = int(input_data.get("requested_sub_agents", 0) or 0)
        notes: list[str] = []
        limits: Dict[str, Any] = {}
        can_spawn = True

        try:
            from app.core.swarm.limits import SwarmLimitManager

            limit_mgr = SwarmLimitManager()
            limits = dict(getattr(limit_mgr, "default_limits", {})) or {}
            if requested and limits.get("max_sub_agents_per_swarm"):
                can_spawn = requested <= limits["max_sub_agents_per_swarm"]
                if not can_spawn:
                    notes.append(
                        f"Requested {requested} sub-agents exceeds per-swarm limit "
                        f"{limits['max_sub_agents_per_swarm']}; would require approved limit increase."
                    )
            notes.append("Sub-agents inherit Lead Agent authority and workspace scope; they cannot escalate.")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Swarm subsystem unavailable: {exc}")
            can_spawn = False

        return self.create_result(
            success=True,
            result_data={"limits": limits, "can_spawn": can_spawn, "notes": notes},
            output_text=(
                "Swarm manager ready. "
                + (f"Limits: {limits}. " if limits else "")
                + ("Capacity available for requested sub-agents." if can_spawn else "Requested swarm exceeds limits.")
            ),
            tools_used=["swarm_track"],
            iterations_used=1,
        )
