"""
JARV Backend - Permissions API (Repair 14a)

The live authority model for the Permissions page, read from the registries
and the safety code rather than restated: authority levels, every agent's
level and tool count, tools per level and the ones that always or
conditionally wait for approval, the hard boundaries the detector pauses on,
the Command Center's approval gates, and the sub-agent rule.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from fastapi import APIRouter

from app.core.agents.base import AuthorityLevel
from app.core.auth import CurrentUserId

router = APIRouter(prefix="/api/permissions", tags=["permissions"])

MEANINGS = {
    0: "Read only: inspect state, no tools that change anything",
    1: "Basic tools: read files, scan folders, inspect logs, write reports",
    2: "Workspace edits: create and change files and records inside the workspace",
    3: "Build and test: run approved build and test commands",
    4: "System changes: install approved packages from official registries",
    5: "Network: read the web, call configured services, send under rules",
    6: "Data and repair: write operational records, restart approved services",
    7: "Deployment: staging deploys, scaling within budget; production waits for Richard",
    8: "Financial: revenue and spend operations within the approved budget",
    9: "Swarm: spawn scoped sub-agents that never exceed the lead agent",
    10: "Full autonomy: still bound by every hard boundary",
}


@router.get("/overview")
async def overview(user_id: CurrentUserId) -> Dict[str, Any]:
    from app.core.agents.registry import get_registry as agent_registry
    from app.core.command.service import _APPROVAL_PATTERNS
    from app.core.safety.hard_boundary import HARD_BOUNDARY_RULES
    from app.core.tools.registry import get_registry as tool_registry

    agents = agent_registry()
    tools = tool_registry()
    agent_rows: List[Dict[str, Any]] = []
    for name in sorted(agents.REQUIRED_AGENTS):
        meta = agents.get_metadata(name)
        if meta is None:
            continue
        agent_rows.append({"name": meta.name, "category": meta.category, "authority": meta.required_authority_level,
                           "tools": len(meta.default_tools or []), "implemented": meta.is_implemented})
    agent_rows.sort(key=lambda a: (-a["authority"], a["name"]))
    implemented = [t for t in tools.list_all() if t.is_implemented]
    by_level = Counter(t.required_authority_level for t in implemented)
    always = sorted(t.name for t in implemented if t.requires_approval)
    conditional = sorted(t.name for t in implemented if getattr(t.tool_class, "_gated", False) and not t.requires_approval)
    return {
        "levels": [{"level": level.value, "name": level.name, "meaning": MEANINGS.get(level.value, ""),
                    "agents": sum(1 for a in agent_rows if a["authority"] == level.value),
                    "tools": by_level.get(level.value, 0)} for level in AuthorityLevel],
        "agents": agent_rows,
        "tools": {"total": len(implemented), "always_approval": always, "conditional_approval": conditional},
        "hard_boundaries": [{"key": r["key"], "title": r["title"]} for r in HARD_BOUNDARY_RULES],
        "command_gates": sorted({label for _pattern, label in _APPROVAL_PATTERNS}),
        "sub_agent_rule": ("A sub-agent inherits its lead agent's role, tools and workspace; its authority can never "
                           "exceed the lead's, it cannot leave the workspace or spawn further sub-agents unless "
                           "configured, and every action is logged with the lead agent's reference."),
        "voice_rule": "Approvals are never taken by voice; they are given on the Approvals page.",
    }
