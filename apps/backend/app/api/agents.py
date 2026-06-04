"""
JARV Backend - Agent Management API

Endpoints for discovering and managing JARV agents.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.agents import get_registry, AgentMetadata
from app.core.agents.runner import agent_runner, LEADS_WITH_EMPLOYEES
from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.core.jarv_memory import memory_service
from app.models.task import Task
from app.models.workspace import Workspace
from app.models.user import User
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import AuditLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentRunRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=4000)
    spawn_employees: bool = False


class AgentInfo(BaseModel):
    """Information about a registered agent"""
    name: str
    role: str
    category: str
    description: str
    required_authority_level: int
    default_tools: List[str]
    is_implemented: bool


class AgentStats(BaseModel):
    """Agent registry statistics"""
    total_required: int
    total_registered: int
    implemented: int
    unimplemented: int
    completion_percentage: float
    by_category: Dict[str, Dict[str, int]]


class AgentValidation(BaseModel):
    """Agent registry validation results"""
    is_complete: bool
    total_required: int
    total_registered: int
    total_implemented: int
    missing_agents: List[Dict[str, str]]
    placeholder_agents: List[Dict[str, str]]


@router.get(
    "/list",
    response_model=List[AgentInfo],
    summary="List all agents",
    description="Get a list of all registered agents with their metadata"
)
async def list_all_agents(
    category: Optional[str] = None,
    only_implemented: bool = False,
) -> List[AgentInfo]:
    """
    List all registered agents.

    Args:
        category: Optional category filter (core, development, infrastructure, business, customer, financial, specialized)
        only_implemented: Only return implemented agents

    Returns:
        List of agent information
    """
    try:
        registry = get_registry()

        # Get agents
        if category:
            agents = registry.list_by_category(category)
        else:
            agents = registry.list_all()

        # Filter if needed
        if only_implemented:
            agents = [a for a in agents if a.is_implemented]

        # Convert to response model
        return [
            AgentInfo(
                name=agent.name,
                role=agent.role,
                category=agent.category,
                description=agent.description,
                required_authority_level=agent.required_authority_level,
                default_tools=agent.default_tools,
                is_implemented=agent.is_implemented,
            )
            for agent in agents
        ]

    except Exception as e:
        logger.error(f"Error listing agents: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list agents: {str(e)}"
        )


@router.get(
    "/categories",
    response_model=List[str],
    summary="List agent categories",
    description="Get list of all agent categories"
)
async def list_categories() -> List[str]:
    """
    List all agent categories.

    Returns:
        List of category names
    """
    try:
        registry = get_registry()
        return registry.get_categories()

    except Exception as e:
        logger.error(f"Error listing categories: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list categories: {str(e)}"
        )


@router.get(
    "/stats",
    response_model=AgentStats,
    summary="Get agent statistics",
    description="Get statistics about agent registry including completion percentage"
)
async def get_agent_stats() -> AgentStats:
    """
    Get agent registry statistics.

    Returns:
        Agent statistics including counts by category
    """
    try:
        registry = get_registry()
        stats = registry.get_stats()
        return AgentStats(**stats)

    except Exception as e:
        logger.error(f"Error getting agent stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent stats: {str(e)}"
        )


@router.get(
    "/validate",
    response_model=AgentValidation,
    summary="Validate agent completeness",
    description="Check if all 31 required agents are implemented"
)
async def validate_agents() -> AgentValidation:
    """
    Validate that all required agents are implemented.

    Returns:
        Validation results with missing and placeholder agents
    """
    try:
        registry = get_registry()
        validation = registry.validate_completeness()
        return AgentValidation(**validation)

    except Exception as e:
        logger.error(f"Error validating agents: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate agents: {str(e)}"
        )


@router.get(
    "/{agent_name}",
    response_model=AgentInfo,
    summary="Get agent details",
    description="Get detailed information about a specific agent"
)
async def get_agent_details(agent_name: str) -> AgentInfo:
    """
    Get details for a specific agent.

    Args:
        agent_name: Name of agent to retrieve

    Returns:
        Agent information

    Raises:
        404: If agent not found
    """
    try:
        registry = get_registry()
        metadata = registry.get_metadata(agent_name)

        if not metadata:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent '{agent_name}' not found in registry"
            )

        return AgentInfo(
            name=metadata.name,
            role=metadata.role,
            category=metadata.category,
            description=metadata.description,
            required_authority_level=metadata.required_authority_level,
            default_tools=metadata.default_tools,
            is_implemented=metadata.is_implemented,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent details: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get agent details: {str(e)}"
        )


@router.get(
    "/category/{category}",
    response_model=List[AgentInfo],
    summary="List agents by category",
    description="Get all agents in a specific category"
)
async def list_agents_by_category(
    category: str,
    only_implemented: bool = False,
) -> List[AgentInfo]:
    """
    List agents in a specific category.

    Args:
        category: Category name
        only_implemented: Only return implemented agents

    Returns:
        List of agents in category
    """
    try:
        registry = get_registry()

        # Check if category exists
        if category not in registry.get_categories():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Category '{category}' not found"
            )

        agents = registry.list_by_category(category)

        # Filter if needed
        if only_implemented:
            agents = [a for a in agents if a.is_implemented]

        return [
            AgentInfo(
                name=agent.name,
                role=agent.role,
                category=agent.category,
                description=agent.description,
                required_authority_level=agent.required_authority_level,
                default_tools=agent.default_tools,
                is_implemented=agent.is_implemented,
            )
            for agent in agents
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing agents by category: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list agents by category: {str(e)}"
        )


@router.post("/{agent_name}/run")
async def run_agent(
    agent_name: str,
    body: AgentRunRequest,
    operator: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Invoke one of the 31 lead agents on a real role-specific task. Persists a
    Task + operations feed + audit + memory, verifies the output, and (optionally)
    has the Swarm Manager spawn scoped employees. Status is honest: completed only
    when the agent succeeded with non-empty output.
    """
    reg = get_registry()
    if not reg.is_implemented(agent_name):
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not implemented")

    ws_id = (await db.execute(select(Workspace.id).limit(1))).scalar_one_or_none()
    if ws_id is None:
        owner = (await db.execute(select(User.id).limit(1))).scalar_one_or_none()
        ws = Workspace(id=uuid4(), name="Command Center", slug=f"cc-{uuid4().hex[:6]}",
                       description="default", owner_id=owner, workspace_type="general",
                       is_active=True, authority_level=5, config={},
                       created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
        db.add(ws); await db.flush(); ws_id = ws.id

    task = Task(id=uuid4(), workspace_id=ws_id, title=f"[agent:{agent_name}] {body.task}"[:500],
                description=body.task, task_type="agent_role", status="running", priority=5,
                context={"agent": agent_name, "operator": operator},
                meta_data={"channel": "agent_run"},
                started_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db.add(task); await db.flush()

    result = await agent_runner.run_agent(agent_name, body.task, ws_id)
    employees: List[Dict[str, Any]] = []
    if body.spawn_employees and agent_name in LEADS_WITH_EMPLOYEES:
        employees = await agent_runner.spawn_employees(db, agent_name, task.id, ws_id, body.task)

    ok = bool(result.get("success"))
    has_output = bool(result.get("output_text"))
    if ok:
        new_status = "completed"
    elif has_output:
        new_status = "partial"
    else:
        new_status = "failed"
    # Verification: independent check that output is non-empty + agent reported success.
    verification = {"verifier": "verifier", "passed": ok,
                    "reason": "agent reported success with non-empty output" if ok
                              else (result.get("error") or "no verifiable output")}

    task.status = new_status
    task.completed_at = datetime.now(timezone.utc) if new_status == "completed" else None
    if new_status == "failed":
        task.failed_at = datetime.now(timezone.utc)
        task.error_message = result.get("error") or "agent produced no verifiable output"
    task.result = {"response": result.get("output_text") or result.get("error") or "",
                   "agent": agent_name, "agent_output": result, "employees": employees,
                   "verification": verification, "task_status": new_status,
                   "selected_agents": [agent_name], "provider": "claude"}
    task.tokens_used = int(result.get("tokens", 0) or 0)
    task.updated_at = datetime.now(timezone.utc)

    db.add(LiveOperationsFeedItem(
        id=uuid4(), workspace_id=ws_id, item_type="agent_execution",
        severity="success" if ok else ("warning" if has_output else "error"),
        title=f"Agent {agent_name} {new_status}",
        message=(result.get("output_text") or result.get("error") or "")[:300],
        related_task_id=task.id, requires_action=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    db.add(AuditLog(
        id=uuid4(), workspace_id=ws_id, actor_type="agent", action=f"agent_run:{agent_name}",
        action_category="agent_execution",
        description=f"{agent_name} role task -> {new_status}", target_type="task",
        target_id=str(task.id), after_state={"agent": agent_name, "status": new_status,
                                              "employees": len(employees)},
        success=ok, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
    try:
        await memory_service.add(db, content=f"[agent:{agent_name}] {body.task[:200]} -> {new_status}",
                                 memory_type="task_result", workspace_id=ws_id, task_id=task.id,
                                 importance=0.55, meta={"agent": agent_name})
    except Exception:  # noqa: BLE001
        pass
    await db.commit()

    return {"task_id": str(task.id), "agent": agent_name, "status": new_status,
            "verified": ok, "output_preview": (result.get("output_text") or "")[:400],
            "result_keys": result.get("result_keys", []),
            "employees": employees, "tokens": task.tokens_used,
            "error": result.get("error")}


# The 6 design departments and their lead agents (names match the registry).
DEPARTMENTS: Dict[str, List[str]] = {
    "Executive Office": ["orchestrator", "company_operator", "business", "finance"],
    "Product & Engineering": ["workspace_manager", "coding_agent", "debugging_agent",
                              "qa", "verifier", "documentation"],
    "Launch & Infrastructure": ["devops", "infrastructure", "monitoring",
                                "self_healing", "rollback", "security"],
    "Growth & Market": ["marketing", "growth", "content", "creation", "analytics"],
    "Customer & Commercial": ["customer_support", "onboarding", "community", "sales",
                              "partnerships", "legal"],
    "Intelligence & Evolution": ["research", "memory", "self_evolution", "swarm_manager"],
}


@router.get("/departments/overview")
async def departments_overview() -> List[Dict[str, Any]]:
    """The autonomous company by department: agents, tools, and authority."""
    reg = get_registry()
    out: List[Dict[str, Any]] = []
    for dept, members in DEPARTMENTS.items():
        agents_info = []
        for name in members:
            m = reg.get_metadata(name)
            if not m:
                continue
            agents_info.append({
                "name": m.name, "role": m.role,
                "authority_level": m.required_authority_level,
                "tool_count": len(m.default_tools or []),
                "tools": m.default_tools or [],
                "implemented": m.is_implemented,
            })
        out.append({"department": dept, "agent_count": len(agents_info),
                    "agents": agents_info})
    return out


@router.get("/{agent_name}/tools")
async def agent_tools(agent_name: str) -> Dict[str, Any]:
    """An agent's tool catalog, cross-referenced with the live tool registry."""
    reg = get_registry()
    m = reg.get_metadata(agent_name)
    if not m:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    try:
        from app.core.tools.registry import get_registry as get_tool_registry
        treg = get_tool_registry()
        tools = [{"name": t, "implemented": treg.is_implemented(t)} for t in (m.default_tools or [])]
    except Exception:  # noqa: BLE001
        tools = [{"name": t, "implemented": None} for t in (m.default_tools or [])]
    dept = next((d for d, members in DEPARTMENTS.items() if agent_name in members), "Unassigned")
    return {"agent": m.name, "role": m.role, "department": dept,
            "authority_level": m.required_authority_level, "tools": tools,
            "tool_count": len(tools)}


# Slug <-> department name (for /dashboard/departments/{slug}).
DEPT_SLUGS = {
    "executive-office": "Executive Office",
    "product-engineering": "Product & Engineering",
    "launch-infrastructure": "Launch & Infrastructure",
    "growth-market": "Growth & Market",
    "customer-commercial": "Customer & Commercial",
    "intelligence-evolution": "Intelligence & Evolution",
}
DEPT_PURPOSE = {
    "Executive Office": "Mission intake, planning, company operations, business, finance.",
    "Product & Engineering": "Build, debug, test, verify, and document the product.",
    "Launch & Infrastructure": "Deploy, run, monitor, self-heal, roll back, and secure.",
    "Growth & Market": "Marketing, growth, content, creation, analytics.",
    "Customer & Commercial": "Support, onboarding, community, sales, partnerships, legal.",
    "Intelligence & Evolution": "Research, memory, self-evolution, swarm orchestration.",
}


def _dept_from_slug(slug: str) -> str:
    name = DEPT_SLUGS.get(slug) or next((d for d in DEPARTMENTS if d.lower() == slug.lower()), None)
    if not name:
        raise HTTPException(status_code=404, detail=f"Department '{slug}' not found")
    return name


def _dept_members(name: str) -> List[str]:
    return DEPARTMENTS.get(name, [])


@router.get("/departments/{slug}")
async def department_detail(slug: str) -> Dict[str, Any]:
    name = _dept_from_slug(slug)
    reg = get_registry()
    members = _dept_members(name)
    agents = []
    for m in members:
        md = reg.get_metadata(m)
        if md:
            agents.append({"name": md.name, "role": md.role,
                           "authority_level": md.required_authority_level,
                           "tools": md.default_tools or [], "implemented": md.is_implemented})
    return {"department": name, "slug": slug, "purpose": DEPT_PURPOSE.get(name, ""),
            "agent_count": len(agents), "agents": agents}


def _is_member_task(t: Task, members: List[str]) -> bool:
    ctx = t.context if isinstance(t.context, dict) else {}
    res = t.result if isinstance(t.result, dict) else {}
    agent = ctx.get("agent") or ctx.get("lead_agent")
    if agent in members:
        return True
    sel = res.get("selected_agents") or []
    return any(a in members for a in sel)


@router.get("/departments/{slug}/tasks")
async def department_tasks(slug: str, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    name = _dept_from_slug(slug)
    members = _dept_members(name)
    rows = (await db.execute(select(Task).order_by(Task.created_at.desc()).limit(300))).scalars().all()
    mine = [t for t in rows if _is_member_task(t, members)]
    counts = {"completed": 0, "partial": 0, "failed": 0, "blocked": 0,
              "waiting_on_approval": 0, "running": 0, "pending": 0}
    for t in mine:
        counts[t.status] = counts.get(t.status, 0) + 1
    recent = [{"id": str(t.id), "title": t.title[:80], "status": t.status,
               "task_type": t.task_type,
               "created_at": t.created_at.isoformat() if t.created_at else None}
              for t in mine[:25]]
    return {"department": name, "total": len(mine), "counts": counts, "recent": recent}


@router.get("/departments/{slug}/tools")
async def department_tools(slug: str) -> Dict[str, Any]:
    name = _dept_from_slug(slug)
    reg = get_registry()
    tools: set = set()
    for m in _dept_members(name):
        md = reg.get_metadata(m)
        if md:
            tools.update(md.default_tools or [])
    return {"department": name, "tools": sorted(tools), "tool_count": len(tools)}


@router.get("/departments/{slug}/operations")
async def department_operations(slug: str, db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    name = _dept_from_slug(slug)
    members = _dept_members(name)
    task_rows = (await db.execute(select(Task).order_by(Task.created_at.desc()).limit(300))).scalars().all()
    ids = {t.id for t in task_rows if _is_member_task(t, members)}
    if not ids:
        return []
    feed = (await db.execute(
        select(LiveOperationsFeedItem).order_by(LiveOperationsFeedItem.created_at.desc()).limit(200)
    )).scalars().all()
    out = [{"item_type": f.item_type, "severity": f.severity, "title": f.title,
            "message": (f.message or "")[:200],
            "created_at": f.created_at.isoformat() if f.created_at else None}
           for f in feed if f.related_task_id in ids][:25]
    return out


@router.get("/departments/{slug}/memory")
async def department_memory(slug: str, db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    from app.models.memory import Memory
    name = _dept_from_slug(slug)
    members = set(_dept_members(name))
    rows = (await db.execute(select(Memory).order_by(Memory.created_at.desc()).limit(200))).scalars().all()
    out = []
    for m in rows:
        meta = m.meta_data if isinstance(m.meta_data, dict) else {}
        if meta.get("agent") in members or meta.get("lead_agent") in members:
            out.append({"type": m.memory_type, "content": m.content[:200],
                        "created_at": m.created_at.isoformat() if m.created_at else None})
        if len(out) >= 25:
            break
    return out


@router.get("/departments/{slug}/experience")
async def department_experience(slug: str, db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    from app.models.memory import Memory
    name = _dept_from_slug(slug)
    rows = (await db.execute(
        select(Memory).where(Memory.memory_type.in_(["experience", "incident"]))
        .order_by(Memory.created_at.desc()).limit(25))).scalars().all()
    return [{"type": m.memory_type, "content": m.content[:200],
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in rows]
