"""
JARV Backend - Swarm Management Layer

Enables controlled parallel execution through temporary scoped sub-agents.
"""
from app.core.swarm.manager import (
    SwarmManager,
    SwarmRunCreate,
    SwarmRunResult,
    SubAgentStatus,
    create_swarm_run,
    spawn_sub_agent,
    dissolve_sub_agent,
)
from app.core.swarm.sub_agent import (
    SubAgentManager,
    SubAgentCreate,
    SubAgentResult,
    SubAgentTaskCreate,
    SubAgentTaskResult,
    assign_sub_agent_task,
    get_sub_agent_status,
    collect_sub_agent_output,
)
from app.core.swarm.limits import (
    SwarmLimitPolicy,
    SwarmLimitManager,
    check_swarm_limits,
    set_swarm_limit,
)
from app.core.swarm.tracking import (
    SwarmCostRecord,
    SwarmTracker,
    calculate_swarm_cost,
    get_swarm_metrics,
)

__all__ = [
    # Swarm Manager
    "SwarmManager",
    "SwarmRunCreate",
    "SwarmRunResult",
    "SubAgentStatus",
    "create_swarm_run",
    "spawn_sub_agent",
    "dissolve_sub_agent",
    # Sub-Agent Manager
    "SubAgentManager",
    "SubAgentCreate",
    "SubAgentResult",
    "SubAgentTaskCreate",
    "SubAgentTaskResult",
    "assign_sub_agent_task",
    "get_sub_agent_status",
    "collect_sub_agent_output",
    # Limits
    "SwarmLimitPolicy",
    "SwarmLimitManager",
    "check_swarm_limits",
    "set_swarm_limit",
    # Tracking
    "SwarmCostRecord",
    "SwarmTracker",
    "calculate_swarm_cost",
    "get_swarm_metrics",
]
