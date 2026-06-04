"""
JARV Backend - Command Execution Service

The live command pipeline. A command typed or spoken in the dashboard flows:

    dashboard command
    -> CommandService.execute()
    -> safety/approval classification
    -> real Task record (pending)
    -> real system context gathering
    -> Orchestrator + Claude planning (model router)
    -> agent selection (validated against the agent registry)
    -> live execution (Claude answer over real context + plan)
    -> task status pending -> running -> completed/failed
    -> Live Operations Feed entries
    -> structured result returned to the dashboard

Commands that only inspect or plan run immediately. Commands that would
modify files, run destructive commands, deploy, push, delete, or spend money
are paused at an approval gate (task blocked + boundary feed item) instead of
being executed.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import OrchestratorAgent
from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.registry import get_registry
from app.core.providers import CompletionRequest, Message, get_router
from app.core.config import settings
from app.models.agent import Agent
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import AuditLog
from app.models.task import Task
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)


# ===== Safety / approval classification =====

# Verbs/phrases that indicate an action requiring a hard-boundary approval.
# These map to the hard boundaries in Design_md.txt / Claude_md.txt.
_APPROVAL_PATTERNS: List[tuple[str, str]] = [
    (r"\b(modify|edit|change|overwrite|rewrite|update)\b.*\bfile", "modifies files"),
    (r"\b(write|create|save)\b.*\bfile", "writes files"),
    (r"\bdelete\b", "deletes data or files"),
    (r"\b(rm|remove)\b.*\b(file|folder|dir|directory)", "removes files"),
    (r"\bdeploy\b", "deploys"),
    (r"\b(git\s+push|push to (main|master|prod|production)|force[- ]push)\b", "pushes code"),
    (r"\brelease\b.*\b(prod|production|live|public)\b", "publishes a live release"),
    (r"\b(drop|truncate)\b.*\b(table|database|db)\b", "makes irreversible database changes"),
    (r"\b(pay|payment|purchase|buy|spend|charge|invoice|wire transfer)\b", "spends money"),
    (r"\b(install|uninstall)\b", "installs/uninstalls packages"),
    (r"\b(send|blast)\b.*\b(mass )?email", "sends email"),
    (r"\bpost\b.*\b(publicly|to (twitter|x|linkedin|facebook|instagram))\b", "posts publicly"),
    (r"\b(disable|weaken|remove)\b.*\b(audit|logging|verifier|boundary|safety|authority)\b",
     "weakens safety controls"),
]

# Phrases that explicitly constrain the command to read-only/plan-only work.
_FORCE_SAFE_PATTERNS: List[str] = [
    r"do not modify",
    r"don't modify",
    r"without modifying",
    r"do not change",
    r"don't change",
    r"read[- ]only",
    r"do not write",
    r"do not edit",
    r"do not delete",
    r"no file changes",
    r"do not deploy",
    r"do not push",
]


@dataclass
class SafetyDecision:
    requires_approval: bool
    reason: str
    boundary_type: Optional[str] = None
    forced_safe: bool = False


def classify_command_safety(command_text: str) -> SafetyDecision:
    """
    Deterministically classify whether a command needs an approval gate.

    A deterministic classifier (not the LLM) is used for the safety decision so
    the gate cannot be talked around by model output.
    """
    text = command_text.lower()

    # Explicit read-only/plan-only constraints win: the user has told JARV not
    # to perform the risky action, so it may run as inspect/plan only.
    for pat in _FORCE_SAFE_PATTERNS:
        if re.search(pat, text):
            return SafetyDecision(
                requires_approval=False,
                reason="Command explicitly constrained to inspect/plan only (no modifications).",
                forced_safe=True,
            )

    for pat, label in _APPROVAL_PATTERNS:
        if re.search(pat, text):
            return SafetyDecision(
                requires_approval=True,
                reason=f"This command {label}, which requires Richard's approval before execution.",
                boundary_type=label,
            )

    return SafetyDecision(
        requires_approval=False,
        reason="Command is inspect/plan only and is safe to execute.",
    )


@dataclass
class CommandResult:
    task_id: str
    command: str
    status: str
    requires_approval: bool
    response_text: str
    plan_steps: List[str] = field(default_factory=list)
    selected_agents: List[str] = field(default_factory=list)
    provider: Optional[str] = None
    model: Optional[str] = None
    execution_time: float = 0.0
    tokens_used: int = 0
    approval_reason: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "command": self.command,
            "status": self.status,
            "requires_approval": self.requires_approval,
            "response_text": self.response_text,
            "plan_steps": self.plan_steps,
            "selected_agents": self.selected_agents,
            "provider": self.provider,
            "model": self.model,
            "execution_time": round(self.execution_time, 3),
            "tokens_used": self.tokens_used,
            "approval_reason": self.approval_reason,
            "error": self.error,
        }


class CommandService:
    """Runs the live command pipeline against the real orchestrator + Claude."""

    def __init__(self, model: Optional[str] = None):
        # Default to the configured Claude model (Claude is the primary provider).
        self.model = model or getattr(settings, "DEFAULT_MODEL", None) or "claude-sonnet-4-6"

    async def execute(
        self,
        command_text: str,
        db: AsyncSession,
        workspace_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        operator: Optional[str] = None,
    ) -> CommandResult:
        start = time.time()
        command_text = (command_text or "").strip()
        if not command_text:
            raise ValueError("Command text is required")
        self.operator = operator or "operator"

        # 1) Safety / approval classification (deterministic gate)
        safety = classify_command_safety(command_text)

        # 2) Resolve a workspace to attach the task to
        ws_id = await self._resolve_workspace(db, workspace_id)

        # 3) Create the real Task record (pending)
        task = Task(
            id=uuid4(),
            workspace_id=ws_id,
            title=command_text[:500],
            description=command_text,
            task_type="command",
            status="pending",
            priority=5,
            context={
                "source": "command_center",
                "requires_approval": safety.requires_approval,
                "safety_reason": safety.reason,
            },
            meta_data={"channel": "dashboard"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.flush()
        task_id = str(task.id)

        await self._feed(
            db, ws_id, task.id,
            item_type="command",
            severity="info",
            title="Command received",
            message=command_text,
        )
        await self._audit(
            db, ws_id, action="command_received", category="command",
            description=f"Command received from {self.operator}: {command_text[:300]}",
            success=True, target_id=task_id,
            metadata={"operator": self.operator, "provider": "claude", "model": self.model},
        )

        # 4) Approval gate: do NOT execute, pause the blocked action
        if safety.requires_approval:
            task.status = "blocked"
            task.meta_data = {**(task.meta_data or {}), "blocked_reason": safety.reason}
            task.updated_at = datetime.now(timezone.utc)
            await self._feed(
                db, ws_id, task.id,
                item_type="boundary",
                severity="warning",
                title="Approval required before execution",
                message=safety.reason,
                requires_action=True,
            )
            await self._audit(
                db, ws_id, action="command_blocked", category="approval",
                description=f"BLOCKED pending approval ({safety.boundary_type}): {command_text[:300]}",
                success=True, target_id=task_id, required_approval=True,
                metadata={"operator": self.operator, "reason": safety.reason,
                          "boundary_type": safety.boundary_type},
            )
            await db.commit()
            return CommandResult(
                task_id=task_id,
                command=command_text,
                status="blocked",
                requires_approval=True,
                response_text=(
                    "This command requires your approval before JARV will execute it.\n\n"
                    f"Reason: {safety.reason}\n\n"
                    "The action has been paused (task is blocked) and recorded in the "
                    "Operations Feed. Approve it on the Approvals page to continue, or "
                    "rephrase the command to inspect/plan only."
                ),
                approval_reason=safety.reason,
                provider="claude",
                model=self.model,
                execution_time=time.time() - start,
            )

        # 5) Execute: mark running, persist immediately so the dashboard sees it
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        task.updated_at = task.started_at
        await self._feed(
            db, ws_id, task.id,
            item_type="agent_execution",
            severity="info",
            title="Orchestrator running",
            message=f"JARV is planning and executing: {command_text[:200]}",
        )
        await db.commit()

        try:
            system_context = await self._gather_system_context(db)

            # 5a) Real orchestrator + Claude planning
            plan = await self._run_orchestrator(command_text, ws_id, user_id, system_context)
            plan_steps = plan["steps"]
            selected_agents = plan["agents"]
            total_tokens = plan.get("tokens", 0)

            # 5b) Live execution: Claude produces the real answer using the real
            #     system context and the orchestrator's plan.
            answer, answer_tokens = await self._run_answer(
                command_text, system_context, plan_steps, selected_agents
            )
            total_tokens += answer_tokens

            # 6) Complete the task with a real result
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            task.updated_at = task.completed_at
            if task.started_at:
                task.execution_duration_seconds = int(
                    (task.completed_at - task.started_at).total_seconds()
                )
            task.tokens_used = total_tokens
            task.result = {
                "response": answer,
                "plan_steps": plan_steps,
                "selected_agents": selected_agents,
                "provider": "claude",
                "model": self.model,
            }
            task.execution_logs = [
                {"step": "planning", "agent": "orchestrator", "agents_selected": selected_agents},
                {"step": "execution", "agent": "orchestrator", "result": "completed"},
            ]
            task.updated_at = datetime.now(timezone.utc)

            await self._feed(
                db, ws_id, task.id,
                item_type="task",
                severity="success",
                title="Command completed",
                message=f"JARV completed: {command_text[:200]}",
            )
            await self._audit(
                db, ws_id, action="command_executed", category="execution",
                description=f"Command executed successfully by {self.operator}: {command_text[:300]}",
                success=True, target_id=task_id,
                metadata={"operator": self.operator, "provider": "claude", "model": self.model,
                          "selected_agents": selected_agents, "tokens_used": total_tokens},
            )
            await db.commit()

            return CommandResult(
                task_id=task_id,
                command=command_text,
                status="completed",
                requires_approval=False,
                response_text=answer,
                plan_steps=plan_steps,
                selected_agents=selected_agents,
                provider="claude",
                model=self.model,
                execution_time=time.time() - start,
                tokens_used=total_tokens,
            )

        except Exception as exc:  # noqa: BLE001 - surface real failure on the task
            logger.error(f"Command execution failed: {exc}", exc_info=True)
            task.status = "failed"
            task.failed_at = datetime.now(timezone.utc)
            task.error_message = str(exc)
            task.updated_at = datetime.now(timezone.utc)
            try:
                await self._feed(
                    db, ws_id, task.id,
                    item_type="error",
                    severity="error",
                    title="Command failed",
                    message=str(exc)[:1000],
                )
                await self._audit(
                    db, ws_id, action="command_failed", category="execution",
                    description=f"Command failed: {command_text[:200]}",
                    success=False, target_id=task_id, error_message=str(exc)[:1000],
                    metadata={"operator": self.operator},
                )
                await db.commit()
            except Exception:
                await db.rollback()
            return CommandResult(
                task_id=task_id,
                command=command_text,
                status="failed",
                requires_approval=False,
                response_text=f"JARV could not complete the command: {exc}",
                provider="claude",
                model=self.model,
                execution_time=time.time() - start,
                error=str(exc),
            )

    # ===== Pipeline steps =====

    async def _resolve_workspace(
        self, db: AsyncSession, workspace_id: Optional[UUID]
    ) -> UUID:
        if workspace_id:
            return workspace_id
        result = await db.execute(select(Workspace.id).limit(1))
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        # No workspace yet: create a Command Center workspace so commands have a home.
        ws = Workspace(
            id=uuid4(),
            name="Command Center",
            slug="command-center",
            description="Default workspace for dashboard commands.",
            workspace_type="general",
            is_active=True,
            authority_level=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(ws)
        await db.flush()
        return ws.id

    async def _gather_system_context(self, db: AsyncSession) -> Dict[str, Any]:
        """Collect REAL system facts the backend can verify (no fabrication)."""
        context: Dict[str, Any] = {}

        # Database connectivity + real counts
        try:
            agent_count = (await db.execute(select(func.count(Agent.id)))).scalar() or 0
            task_count = (await db.execute(select(func.count(Task.id)))).scalar() or 0
            ws_count = (await db.execute(select(func.count(Workspace.id)))).scalar() or 0
            context["database"] = {
                "connected": True,
                "agents": int(agent_count),
                "tasks": int(task_count),
                "workspaces": int(ws_count),
            }
        except Exception as exc:  # noqa: BLE001
            context["database"] = {"connected": False, "error": str(exc)}

        # Redis health (real ping)
        try:
            from app.core.redis import check_redis_health

            context["redis"] = await check_redis_health()
        except Exception as exc:  # noqa: BLE001
            context["redis"] = {"status": "unknown", "error": str(exc)}

        # LLM providers actually configured
        try:
            providers = list(get_router().get_provider_info().keys())
        except Exception:  # noqa: BLE001
            providers = []
        context["llm_providers"] = providers

        # Registered/implemented agents (real registry data)
        try:
            reg = get_registry()
            stats = reg.get_stats()
            context["agents"] = {
                "implemented": stats.get("implemented"),
                "total_required": stats.get("total_required"),
            }
        except Exception:  # noqa: BLE001
            pass

        return context

    async def _run_orchestrator(
        self,
        command_text: str,
        workspace_id: UUID,
        user_id: Optional[UUID],
        system_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run the real Orchestrator (Claude planning) and return plan + agents."""
        config = AgentConfig(
            agent_id=uuid4(),
            workspace_id=workspace_id,
            user_id=user_id,
            authority_level=AuthorityLevel.LEVEL_9_SWARM_CREATION,
            model=self.model,
        )
        orchestrator = OrchestratorAgent(config=config)
        context = AgentContext(
            workspace_id=workspace_id,
            user_id=user_id,
            metadata={"source": "command_center", "system_context": system_context},
        )
        result = await orchestrator.execute(
            input_data={"mission": command_text, "context": "Dashboard command", "priority": "normal"},
            context=context,
        )
        steps: List[str] = []
        agents: List[str] = []
        plan = (result.result_data or {}).get("task_plan", [])
        for t in plan:
            desc = t.get("description") if isinstance(t, dict) else None
            if desc:
                steps.append(desc)
            assigned = t.get("assigned_agent") if isinstance(t, dict) else None
            if assigned and assigned not in agents:
                agents.append(assigned)
        # Validate selected agents against the registry of implemented agents.
        try:
            reg = get_registry()
            implemented = {m.name for m in reg.list_implemented()}
            validated = [a for a in agents if a in implemented]
            agents = validated or agents
        except Exception:  # noqa: BLE001
            pass
        return {
            "steps": steps,
            "agents": agents,
            "summary": result.output_text or "",
            "tokens": (result.tokens_used or {}).get("total_tokens", 0),
        }

    async def _run_answer(
        self,
        command_text: str,
        system_context: Dict[str, Any],
        plan_steps: List[str],
        selected_agents: List[str],
    ) -> tuple[str, int]:
        """Produce the final user-facing answer with Claude over real context."""
        router = get_router()
        system_prompt = (
            "You are JARV, a private autonomous multi-agent AI operations system. "
            "Answer the operator's command directly and concretely using the REAL "
            "system context and the execution plan provided. "
            "If the command says not to modify files, only inspect and plan - never "
            "claim to have modified, deployed, or deleted anything. "
            "Be concise and specific. When asked about system/service health, base "
            "your answer strictly on the provided real context."
        )
        user_prompt = (
            f"OPERATOR COMMAND:\n{command_text}\n\n"
            f"REAL SYSTEM CONTEXT (verified by the backend):\n"
            f"{json.dumps(system_context, indent=2)}\n\n"
            f"EXECUTION PLAN (from the orchestrator, Claude-generated):\n"
            f"- Selected agents: {', '.join(selected_agents) or 'orchestrator'}\n"
            + "\n".join(f"- Step {i+1}: {s}" for i, s in enumerate(plan_steps))
            + "\n\nProvide the response now."
        )
        request = CompletionRequest(
            model=self.model,
            messages=[Message(role="user", content=user_prompt)],
            system=system_prompt,
            max_tokens=1500,
        )
        response = await router.complete(request)
        tokens = (response.usage or {}).get("total_tokens", 0)
        return response.content.strip(), int(tokens)

    async def _feed(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        task_id: Optional[UUID],
        item_type: str,
        severity: str,
        title: str,
        message: str,
        requires_action: bool = False,
    ) -> None:
        """Write a Live Operations Feed entry (non-fatal)."""
        try:
            item = LiveOperationsFeedItem(
                id=uuid4(),
                workspace_id=workspace_id,
                item_type=item_type,
                severity=severity,
                title=title,
                message=message,
                related_task_id=task_id,
                requires_action=requires_action,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(item)
            await db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to write operations feed item: {exc}")

    async def _audit(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        action: str,
        category: str,
        description: str,
        success: bool,
        target_id: Optional[str] = None,
        required_approval: bool = False,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a persistent AuditLog row (non-fatal) using the real model fields."""
        try:
            entry = AuditLog(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="operator",
                action=action,
                action_category=category,
                description=description,
                target_type="command",
                target_id=target_id,
                after_state=metadata or {},
                success=success,
                error_message=error_message,
                required_approval=required_approval,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(entry)
            await db.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to write audit log: {exc}")
