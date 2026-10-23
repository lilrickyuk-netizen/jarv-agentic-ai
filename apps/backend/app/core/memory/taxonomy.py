"""
JARV Backend - Memory taxonomy

The design requires 23 memory categories. Callers across the codebase already
write finer-grained ``memory_type`` values ("task_result", "delegation",
"launch", ...). Those values are kept as written, and every record is also
filed under exactly one of the 23 categories so the memory system can be
queried, isolated, and audited by category.
"""
from __future__ import annotations

from typing import Optional

MEMORY_CATEGORIES = (
    "global",
    "workspace",
    "company_operating",
    "task",
    "incident",
    "asset",
    "customer",
    "business",
    "revenue",
    "infrastructure",
    "content",
    "onboarding",
    "community",
    "partnership",
    "sales",
    "decision",
    "boundary",
    "experience",
    "self_evolution",
    "swarm",
    "approval",
    "checkpoint",
    "richard_boundary_operator",
)

_ALIASES = {
    # task / execution
    "task_result": "task", "task": "task", "delegation": "task", "conversation": "task",
    "agent_output": "task", "coding": "task", "debugging": "task", "qa": "task",
    # operations
    "incident": "incident", "self_healing": "incident", "monitoring": "incident",
    "rollback": "incident",
    "infrastructure": "infrastructure", "launch": "infrastructure", "deployment": "infrastructure",
    "devops": "infrastructure", "security": "infrastructure",
    # company functions
    "company_operating": "company_operating", "operating_plan": "company_operating",
    "standup": "company_operating", "daily_loop": "company_operating",
    "customer": "customer", "support": "customer", "customer_support": "customer",
    "business": "business", "finance": "business", "legal": "business", "growth": "business",
    "analytics": "business",
    "revenue": "revenue",
    "content": "content", "marketing": "content", "documentation": "content",
    "onboarding": "onboarding",
    "community": "community",
    "partnership": "partnership", "partnerships": "partnership",
    "sales": "sales",
    "asset": "asset", "creation": "asset", "source": "asset",
    # control plane
    "decision": "decision", "fact": "workspace", "workspace": "workspace", "scan": "workspace",
    "boundary": "boundary", "hard_boundary": "boundary",
    "experience": "experience", "learning": "experience", "verified_learning": "experience",
    "lesson": "experience",
    "self_evolution": "self_evolution", "evolution": "self_evolution",
    "swarm": "swarm", "sub_agent": "swarm",
    "approval": "approval",
    "checkpoint": "checkpoint", "resume": "checkpoint",
    "richard_boundary_operator": "richard_boundary_operator", "richard": "richard_boundary_operator",
    "richard_boundary_input": "richard_boundary_operator",
    "global": "global",
}


def categorise(memory_type: Optional[str], *, has_workspace: bool) -> str:
    """Map a free-form memory_type to one of the 23 design categories.

    Unknown types fall into ``workspace`` when the memory belongs to a workspace
    and ``global`` otherwise, so nothing is left uncategorised.
    """
    key = (memory_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key in MEMORY_CATEGORIES:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    return "workspace" if has_workspace else "global"


def validate_category(category: str) -> str:
    key = (category or "").strip().lower()
    if key not in MEMORY_CATEGORIES:
        raise ValueError(
            f"Unknown memory category '{category}'. Valid categories: {', '.join(MEMORY_CATEGORIES)}"
        )
    return key
