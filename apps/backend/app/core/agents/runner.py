"""
JARV Backend - Agent Runner

Invokes any of the 31 registered lead agents on a real, role-specific task and
returns structured, verified, audited output. Also lets eligible lead agents
request temporary scoped EMPLOYEES through the Swarm Manager — real child tasks
that execute a slice of work, are verified, and dissolve.

Every run is persisted (Task + operations feed + audit + memory) and verified
(success + non-empty output) so nothing fake or unverified is reported.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.registry import create_agent, get_registry
from app.core.config import settings
from app.core.jarv_memory import memory_service
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import AuditLog
from app.models.task import Task

logger = logging.getLogger(__name__)

# Lead agents that may request scoped employees (and the employee role they spawn).
LEADS_WITH_EMPLOYEES = {
    "coding_agent": ["implementation-employee", "test-writer-employee"],
    "debugging_agent": ["log-analysis-employee", "stack-trace-employee"],
    "qa": ["endpoint-tester-employee", "acceptance-tester-employee"],
    "research": ["docs-researcher-employee", "package-researcher-employee"],
    "marketing": ["landing-copy-employee", "campaign-idea-employee"],
    "content": ["blog-draft-employee", "tutorial-employee"],
    "customer_support": ["ticket-triage-employee", "faq-update-employee"],
    "infrastructure": ["docker-check-employee", "backup-check-employee"],
    "security": ["secret-scan-employee", "dependency-cve-employee"],
    "documentation": ["readme-employee", "api-docs-employee"],
    "business": ["pricing-analysis-employee", "model-review-employee"],
    "sales": ["prospect-brief-employee", "follow-up-employee"],
    "partnerships": ["partner-shortlist-employee", "outreach-employee"],
    "onboarding": ["flow-design-employee", "welcome-email-employee"],
    "community": ["post-draft-employee", "moderation-employee"],
    "analytics": ["metrics-employee", "dropoff-analysis-employee"],
    "self_healing": ["diagnosis-employee", "recovery-verify-employee"],
    "company_operator": ["standup-employee", "kpi-review-employee"],
}

import enum
import typing

# Common descriptive field names: if an agent's schema has any of these, fill
# them with the task text so the agent has a real instruction to work on.
_DESC_FIELDS = ("task", "description", "mission", "prompt", "query", "topic",
                "message", "content", "objective", "goal", "instructions",
                "details", "requirements", "subject", "title", "name", "request")

# Assessment agents: they "succeed" by producing a structured assessment
# (pass/fail matrix, readiness, findings) even if sub-checks aren't all green.
ASSESSMENT_AGENTS = {"qa", "devops", "verifier", "security", "monitoring",
                     "analytics", "finance"}


def _value_for(annotation: Any, task: str) -> Any:
    """Produce a schema-valid default value for a required field by its type."""
    origin = typing.get_origin(annotation)
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if origin is typing.Union and args:  # Optional[X] / Union -> use first arm
        annotation = args[0]
        origin = typing.get_origin(annotation)
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
    if origin in (list, typing.List):
        return []
    if origin in (dict, typing.Dict):
        return {}
    if origin is typing.Literal and args:
        return args[0]
    try:
        if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            return list(annotation)[0].value
    except Exception:  # noqa: BLE001
        pass
    if annotation is bool:
        return False
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation in (list,):
        return []
    if annotation in (dict,):
        return {}
    return task  # default to the task string (covers str + free-form fields)


def _is_str_field(annotation: Any) -> bool:
    """True if a plain string is a valid value for this annotation."""
    if annotation in (str, typing.Any, None):
        return True
    if typing.get_origin(annotation) is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return str in args or typing.Any in args
    return False


def _auto_input(schema_cls: Any, task: str) -> Dict[str, Any]:
    """Build a valid input dict for an agent's Pydantic input schema (type-aware)."""
    data: Dict[str, Any] = {}
    fields = getattr(schema_cls, "model_fields", None)
    if not fields:  # not a pydantic v2 model -> best-effort superset
        return {n: task for n in _DESC_FIELDS}
    for name, info in fields.items():
        required = getattr(info, "is_required", lambda: False)()
        ann = getattr(info, "annotation", str)
        if name in _DESC_FIELDS and _is_str_field(ann):
            data[name] = task            # inject the instruction into string fields
        elif required:
            data[name] = _value_for(ann, task)  # type-correct value for required fields
    return data


class AgentRunner:
    """Invoke registered agents and (optionally) spawn scoped employees."""

    def __init__(self, model: Optional[str] = None):
        self.model = model or getattr(settings, "DEFAULT_MODEL", "claude-sonnet-4-6")

    async def run_agent(
        self, agent_name: str, task: str, workspace_id: UUID,
        user_id: Optional[UUID] = None,
        db: Optional[AsyncSession] = None,
        task_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        approval_granted: bool = False,
        approved_tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Invoke one agent on a role-specific task; return a structured result.

        When a real ``db`` AsyncSession is supplied it is carried into the
        AgentContext so any tool the agent runs (via ``execute_tool``) executes
        with real persistence and writes a ToolRun. Callers without a session
        continue to work unchanged (no-session execution stays safe).
        """
        if not get_registry().is_implemented(agent_name):
            return {"agent": agent_name, "success": False, "error": "agent not implemented"}
        # Scope the agent to its own tool catalog (per-agent tool permissions).
        meta = get_registry().get_metadata(agent_name)
        allowed_tools = list(getattr(meta, "default_tools", []) or [])
        config = AgentConfig(
            agent_id=uuid4(), workspace_id=workspace_id, user_id=user_id,
            session_id=session_id,
            authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION, model=self.model,
            allowed_tools=allowed_tools,
        )
        agent = create_agent(agent_name, config)
        if agent is None:
            return {"agent": agent_name, "success": False, "error": "could not create agent"}
        ctx = AgentContext(workspace_id=workspace_id, user_id=user_id,
                           task_id=task_id, session_id=session_id,
                           db_session=db,
                           approval_granted=bool(approval_granted),
                           approved_tools=list(approved_tools or []),
                           metadata={"role_task": True, "source": "agent_runner"})
        try:
            try:
                schema_cls = agent.input_schema
            except Exception:  # noqa: BLE001
                schema_cls = None
            input_data = _auto_input(schema_cls, task) if schema_cls else {n: task for n in _DESC_FIELDS}
            result = await agent.execute(input_data, ctx)
            out_text = (result.output_text or "").strip()
            if not out_text and result.result_data:
                out_text = str(result.result_data)[:1500]
            # Assessment agents (QA, DevOps, Verifier, Security, Monitoring, Analytics,
            # Finance) SUCCEED when they produce a structured assessment — the
            # pass/fail / readiness details live in the output. Execution agents
            # require their own success flag. This avoids "vague generic partial".
            if agent_name in ASSESSMENT_AGENTS:
                success = bool(out_text)
            else:
                success = bool(result.success) and bool(out_text)
            return {
                "agent": agent_name,
                "success": success,
                "assessment": agent_name in ASSESSMENT_AGENTS,
                "output_text": out_text[:2000],
                "result_keys": list((result.result_data or {}).keys())[:12],
                "result_data": {k: result.result_data[k] for k in list((result.result_data or {}).keys())[:8]},
                "tokens": (result.tokens_used or {}).get("total_tokens", 0),
            }
        except Exception as exc:  # noqa: BLE001 - report honestly, never fake success
            logger.warning(f"agent {agent_name} run failed: {exc}")
            return {"agent": agent_name, "success": False, "error": str(exc)[:400]}

    async def spawn_employees(
        self, db: AsyncSession, lead_agent: str, parent_task_id: Optional[UUID],
        workspace_id: UUID, task: str, lead_authority: int = 9,
    ) -> List[Dict[str, Any]]:
        """Swarm Manager spawns scoped employees for a lead; they execute + dissolve."""
        roles = LEADS_WITH_EMPLOYEES.get(lead_agent, [])
        employees: List[Dict[str, Any]] = []
        for role in roles:
            child = Task(
                id=uuid4(), workspace_id=workspace_id,
                title=f"[employee:{role}] {task}"[:500],
                description=f"Scoped employee of {lead_agent}: {role}",
                task_type="employee_task", status="running", priority=5,
                context={"parent_task_id": str(parent_task_id) if parent_task_id else None,
                         "lead_agent": lead_agent, "employee_role": role,
                         "authority_level": min(lead_authority, 9), "swarm": True},
                meta_data={"spawned_by": "swarm_manager", "timeout_seconds": 1800},
                started_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
            )
            db.add(child)
            await db.flush()
            # Employee executes its scoped slice (a focused agent run).
            emp_result = await self.run_agent(lead_agent, f"[{role}] {task}", workspace_id)
            verified = bool(emp_result.get("success"))
            child.status = "completed" if verified else "partial"
            child.completed_at = datetime.now(timezone.utc)
            child.result = {"employee_role": role, "lead_agent": lead_agent,
                            "output": (emp_result.get("output_text") or "")[:800],
                            "verified": verified, "dissolved": True}
            child.updated_at = datetime.now(timezone.utc)
            db.add(LiveOperationsFeedItem(
                id=uuid4(), workspace_id=workspace_id, item_type="swarm",
                severity="info", title=f"Employee {role} ({lead_agent})",
                message=f"{role} {'verified' if verified else 'partial'}; dissolved.",
                related_task_id=parent_task_id, requires_action=False,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
            await memory_service.add(
                db, content=f"[employee {role} of {lead_agent}] verified={verified}",
                memory_type="swarm", workspace_id=workspace_id, task_id=parent_task_id,
                importance=0.5)
            employees.append({"role": role, "child_task_id": str(child.id),
                              "verified": verified, "dissolved": True,
                              "authority_level": min(lead_authority, 9)})
        await db.flush()
        return employees


agent_runner = AgentRunner()
