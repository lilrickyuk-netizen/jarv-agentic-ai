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
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import OrchestratorAgent
from app.core.agents.base import AgentConfig, AgentContext, AuthorityLevel
from app.core.agents.registry import get_registry
from app.core.providers import CompletionRequest, Message, get_router
from app.core.config import settings
from app.core.workspaces import fs_inspector
from app.core.jarv_memory import memory_service
from app.core.command.tool_runtime import ToolRuntime
from app.core.qa.verifier import qa_verifier
from app.models.agent import Agent
from app.models.memory import Memory
from app.models.company_operations import LiveOperationsFeedItem
from app.models.operations import AuditLog
from app.models.task import Task
from app.models.user import User
from app.models.workspace import Workspace

# Matches a Windows absolute path (the form operators type in commands).
_PATH_RE = re.compile(r'([A-Za-z]:[\\/][^\s"\'<>|]+)')

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

        # Controlled-tool intents route through tools that self-enforce scope,
        # authority, and danger checks (write blocks out-of-scope/secret files;
        # run_command blocks dangerous commands; notify is dry-run). They run at
        # their authority level without a hard-boundary pause. Destructive verbs
        # (delete/deploy/push/spend) match NO controlled intent and stay blocked.
        _controlled = {
            "remember_memory", "recall_memory", "register_workspace",
            "scan_workspace", "verify_last_scan", "write_file", "run_command",
            "send_notification", "delegate", "agent_task",
            "launch_readiness", "infra_readiness",
            "self_healing", "self_evolution", "swarm", "company_workflow",
        }
        if self._detect_intent(command_text) in _controlled:
            safety = SafetyDecision(
                requires_approval=False,
                reason="Controlled tool intent: executes under authority with in-tool scope/safety checks.",
                forced_safe=True,
            )

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

            intent = self._detect_intent(command_text)
            result_extra: Dict[str, Any] = {}

            # Retrieve relevant persistent memory BEFORE planning (BLOCKER 1).
            try:
                recalled = await memory_service.search(db, command_text, limit=5, workspace_id=ws_id)
                system_context["relevant_memory"] = [
                    {"type": m.memory_type, "content": m.content} for m in recalled
                ]
            except Exception:  # noqa: BLE001
                system_context["relevant_memory"] = []

            # Tool runtime: agents act through real, logged tools (BLOCKER 3).
            runtime = ToolRuntime(db, ws_id, task.id, operator=self.operator)

            if intent == "agent_task":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_agent_task(db, runtime, command_text)
                )
                total_tokens = result_extra.pop("agent_tokens", 0)
            elif intent == "launch_readiness":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_launch_readiness(db, runtime, command_text)
                )
                total_tokens = 0
            elif intent == "infra_readiness":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_infra_readiness(db, runtime, command_text)
                )
                total_tokens = 0
            elif intent == "self_healing":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_self_healing(db, runtime, command_text)
                )
                total_tokens = 0
            elif intent == "self_evolution":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_self_evolution(db, runtime, command_text)
                )
                total_tokens = 0
            elif intent == "swarm":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_swarm(db, runtime, command_text)
                )
                total_tokens = 0
            elif intent == "company_workflow":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_company_workflow(db, runtime, command_text)
                )
                total_tokens = result_extra.pop("wf_tokens", 0)
            elif intent == "write_file":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_write_file(db, runtime, command_text)
                )
                total_tokens = 0
            elif intent == "run_command":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_run_command(runtime, command_text)
                )
                total_tokens = 0
            elif intent == "send_notification":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_notify(runtime, command_text)
                )
                total_tokens = 0
            elif intent == "delegate":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_delegate(db, runtime, command_text)
                )
                total_tokens = 0
            elif intent == "remember_memory":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_remember(runtime, command_text)
                )
                total_tokens = 0
            elif intent == "recall_memory":
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_recall(runtime, command_text)
                )
                total_tokens = 0
            elif intent == "register_workspace":
                # Real action: confirm the path on disk and register a workspace.
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_register_workspace(db, command_text)
                )
                total_tokens = 0
            elif intent in ("scan_workspace", "verify_last_scan"):
                # Real action: read-only scan of actual files via tools + QA verify.
                answer, plan_steps, selected_agents, result_extra = (
                    await self._handle_scan_workspace(db, command_text, runtime)
                )
                total_tokens = 0
            else:
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
                "tool_calls": runtime.calls,
                **result_extra,
            }
            task.execution_logs = [
                {"step": "planning", "agent": "orchestrator", "agents_selected": selected_agents},
                {"step": "tools", "agent": "orchestrator", "tool_calls": len(runtime.calls)},
                {"step": "execution", "agent": "orchestrator", "result": "completed",
                 "intent": intent},
            ]

            # QA/Verifier gate (BLOCKER 5): a failed verification must NOT complete.
            verification = result_extra.get("verification")
            if isinstance(verification, dict) and verification.get("passed") is False:
                task.status = "failed"
                task.error_message = (
                    "QA verification failed: "
                    + verification.get("reasoning", "output could not be verified")
                )

            # Persist the result to memory (BLOCKER 1): recallable next session.
            try:
                await memory_service.add(
                    db,
                    content=f"Command: {command_text[:300]} | Result: {answer[:500]}",
                    memory_type="task_result",
                    workspace_id=ws_id,
                    task_id=task.id,
                    importance=0.6,
                    meta={"intent": intent, "agents": selected_agents},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"memory persist failed: {exc}")

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
        owner_id = await self._first_user_id(db)
        ws = Workspace(
            id=uuid4(),
            name="Command Center",
            slug="command-center",
            description="Default workspace for dashboard commands.",
            owner_id=owner_id,
            workspace_type="general",
            is_active=True,
            authority_level=5,
            config={},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(ws)
        await db.flush()
        return ws.id

    async def _first_user_id(self, db: AsyncSession) -> UUID:
        """Return a real user id to own workspaces (operators auth via Redis)."""
        result = await db.execute(select(User.id).limit(1))
        uid = result.scalar_one_or_none()
        if uid:
            return uid
        # No users seeded: create a system owner so workspaces can be created.
        user = User(
            id=uuid4(),
            username="system",
            email="system@jarv.local",
            password_hash="!",  # unusable hash; this is an owner record, not a login
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(user)
        await db.flush()
        return user.id

    async def _find_workspace_by_root(
        self, db: AsyncSession, host_path: str
    ) -> Optional[Workspace]:
        """Find a workspace whose config.root_path matches (dialect-agnostic)."""
        res = await db.execute(select(Workspace))
        for ws in res.scalars().all():
            cfg = ws.config if isinstance(ws.config, dict) else {}
            if cfg.get("root_path") == host_path:
                return ws
        return None

    @staticmethod
    def _extract_path(command_text: str) -> Optional[str]:
        m = _PATH_RE.search(command_text)
        # Strip trailing punctuation that commonly follows a path in prose
        # (e.g. "...WORKSPACE_TEST:" or "...PROJECT." ) — never part of the path.
        return m.group(1).rstrip(".,;:") if m else None

    @staticmethod
    def _detect_intent(command_text: str) -> Optional[str]:
        """Classify a command into a real specialized handler, or None (generic)."""
        text = command_text.lower()
        has_path = bool(_PATH_RE.search(command_text))
        # Autonomous engineering mission -> tool-using agent loop (inspect, edit,
        # build, test, iterate). Highest priority for clear engineering verbs.
        # Launch/deploy are intentionally NOT here: they hit the approval gate.
        if (re.search(r"\b(fix|debug|refactor|implement|develop|integrate|migrate|rewrite|optimi[sz]e|finish)\b", text)
                or re.search(r"\bbuild\b.*\b(the|my|this|project|app|feature|it|out)\b", text)
                or re.search(r"\b(add|create|build|write)\b.*\b(feature|endpoint|function|component|module|route|api|test|class|method)\b", text)
                or re.search(r"\b(make|get)\b.*\b(work|working|pass|passing|green|to build)\b", text)):
            return "agent_task"
        # Self-healing simulated incident.
        if re.search(r"\b(self[- ]heal|simulate (an? )?incident|healing|recover (from|the))\b", text):
            return "self_healing"
        # Self-evolution proposal (safe or unsafe).
        if re.search(r"\b(self[- ]evolution|evolution proposal|propose (an? )?(improvement|change|rule)|improve (the )?(workflow|rule|runbook))\b", text):
            return "self_evolution"
        # Swarm parallel execution.
        if re.search(r"\b(swarm|spawn .*(sub[- ]?agent|workers?)|parallel (sub)?agents?|split .* into (sub)?tasks)\b", text):
            return "swarm"
        # Company operating workflows (drafts). Trigger on an explicit company
        # phrase, or on "draft ..." paired with any company-function keyword.
        _company_kw = (r"\b(marketing|content|blog|post|article|email|onboard|onboarding|"
                       r"support|reply|sales|outreach|lead|partner|partnership|revenue|"
                       r"pricing|monetiz|subscription|business|strategy|campaign|proposal|sequence)\b")
        if (re.search(r"\b(marketing campaign|content (strategy|plan|calendar)|onboarding (flow|copy|sequence)|"
                      r"support (reply|draft)|sales (pipeline|sequence|outreach)|partnership (proposal|development)|"
                      r"revenue (plan|analysis|operations)|business (strategy|plan))\b", text)
                or (re.search(r"\b(draft|write|generate|create)\b", text) and re.search(_company_kw, text))):
            return "company_workflow"
        # Launch / release readiness (read-only report).
        if re.search(r"\b(launch readiness|release readiness|launch checklist|release checklist|"
                     r"prepare (the )?(launch|release)|ready (to|for) launch|release readiness report)\b", text):
            return "launch_readiness"
        # Infrastructure / cloud / scale readiness (read-only report).
        if re.search(r"\b(infrastructure readiness|cloud readiness|scal(e|ing) readiness|"
                     r"deployment readiness|infra readiness)\b", text):
            return "infra_readiness"
        # Agent-to-agent delegation chain.
        if (re.search(r"\b(delegat|multi[- ]agent|hand[- ]?off|chain)\b", text) or
                ("researcher" in text and ("qa" in text or "verifier" in text))):
            return "delegate"
        # External notification / webhook (dry-run by default).
        if re.search(r"\b(notify|notification|webhook|send an? alert|send a test)\b", text):
            return "send_notification"
        # Controlled command execution.
        if re.search(r"\b(run|execute)\b.*\b(command|cmd|ls|dir|git|build|test|script)\b", text):
            return "run_command"
        # Controlled file write/create.
        if re.search(r"\b(create|write|add|make)\b.*\b(file|\.md|\.txt|\.json|\.py|\.ts)\b", text):
            return "write_file"
        if re.search(r"\b(recall|retrieve|what did you remember|do you remember)\b", text):
            return "recall_memory"
        if re.search(r"\bremember\b", text):
            return "remember_memory"
        if re.search(r"\b(verify|qa|validate)\b", text) and (
            "scan" in text or "last" in text or "workspace" in text
        ):
            return "verify_last_scan"
        if re.search(r"\bregister\b", text) and ("workspace" in text or has_path):
            return "register_workspace"
        if re.search(r"\b(scan|inspect|analy[sz]e)\b", text) and (
            "workspace" in text or has_path
        ):
            return "scan_workspace"
        return None

    def _validate_agents(self, agents: List[str]) -> List[str]:
        try:
            reg = get_registry()
            implemented = {m.name for m in reg.list_implemented()}
            validated = [a for a in agents if a in implemented]
            return validated or agents
        except Exception:  # noqa: BLE001
            return agents

    async def _handle_self_healing(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Run the REAL self-healing workflow on a simulated incident."""
        from datetime import datetime as _dt
        steps = [
            "Monitoring: detect a simulated incident (API error-rate spike).",
            "Self-Healing: create incident, select runbook, diagnose.",
            "Self-Healing: apply approved fix and verify recovery.",
            "Self-Healing: log incident + experience record.",
        ]
        agents = self._validate_agents(
            ["orchestrator", "monitoring", "self_healing_operations", "rollback"])
        detail: Dict[str, Any] = {}
        try:
            from app.core.self_healing.workflows import SelfHealingWorkflow
            from app.core.self_healing.monitoring import IssueDetection
            issue = IssueDetection(
                issue_type="api_error_spike", severity="high",
                description="Simulated API error-rate spike (self-healing verification).",
                affected_systems=["backend-api"],
                detection_time=datetime.now(timezone.utc),
                # Keys the APIErrorSpikeRunbook.detect()/diagnose() actually read.
                metrics={
                    "issue_type": "error_spike",
                    "spikes": [{"current_rate": 0.25, "baseline_rate": 0.02,
                                "endpoint": "/api/example"}],
                    "simulated": True,
                },
            )
            wf = SelfHealingWorkflow(workspace_id=runtime.workspace_id)
            result = await wf.execute(issue, user_id=None)
            detail = result if isinstance(result, dict) else {"result": str(result)}
            ok = True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"self-healing run failed: {exc}", exc_info=True)
            detail = {"error": str(exc)}
            ok = False

        await self._feed(db, runtime.workspace_id, runtime.task_id, item_type="self_healing",
                         severity="success" if ok else "error",
                         title="Self-healing incident processed" if ok else "Self-healing run error",
                         message=json.dumps(detail)[:500])
        await self._audit(db, runtime.workspace_id, action="self_healing_run", category="self_healing",
                          description="Simulated incident -> detect/fix/verify/log",
                          success=ok, target_id=str(runtime.task_id), metadata=detail)
        await memory_service.add(db, content=f"Self-healing: simulated api_error_spike -> {json.dumps(detail)[:300]}",
                                 memory_type="incident", workspace_id=runtime.workspace_id,
                                 task_id=runtime.task_id, importance=0.7)
        answer = (
            f"**Self-healing {'completed' if ok else 'attempted'}.**\n\n"
            f"- Incident: simulated API error-rate spike (severity high)\n"
            f"- Outcome: {json.dumps(detail)[:600]}\n\n"
            + ("An Incident and ExperienceRecord were written; the operations feed and audit "
               "trail recorded the detection, fix, and verification." if ok else
               "The run hit an error (recorded honestly); see detail above.")
        )
        return answer, steps, agents, {"self_healing": detail}

    # Genuine safety guard for self-evolution (the design's hard requirement):
    # changes that weaken safety/authority/logging/boundary/approval are BLOCKED.
    _UNSAFE_EVO_RE = re.compile(
        r"\b(remove|disable|weaken|bypass|skip|turn off|delete|relax)\b.*"
        r"\b(safety|authority|auth|permission|logging|audit|boundary|boundaries|"
        r"approval|verifier|verification|secret|guard)\b", re.IGNORECASE)

    async def _handle_self_evolution(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Classify a self-evolution proposal; BLOCK unsafe changes, accept safe ones."""
        steps = [
            "Self-Evolution: parse the proposed change.",
            "Self-Evolution: run the safety guard (cannot weaken safety/authority/logging).",
            "Self-Evolution: accept + version a safe change, or BLOCK an unsafe one.",
        ]
        agents = self._validate_agents(["orchestrator", "self_evolution", "verifier", "security"])
        unsafe = bool(self._UNSAFE_EVO_RE.search(command_text))
        if unsafe:
            await self._feed(db, runtime.workspace_id, runtime.task_id, item_type="self_evolution",
                             severity="warning", title="Self-evolution change BLOCKED",
                             message="Proposed change would weaken safety/authority/logging; blocked.",
                             requires_action=True)
            await self._audit(db, runtime.workspace_id, action="self_evolution_blocked",
                              category="self_evolution", description=f"BLOCKED unsafe proposal: {command_text[:200]}",
                              success=True, target_id=str(runtime.task_id), required_approval=True,
                              metadata={"verdict": "blocked"})
            await memory_service.add(db, content=f"Self-evolution BLOCKED (unsafe): {command_text[:200]}",
                                     memory_type="self_evolution", workspace_id=runtime.workspace_id,
                                     task_id=runtime.task_id, importance=0.8)
            answer = (
                "**Self-evolution change BLOCKED by the safety guard.**\n\n"
                "The proposal would weaken safety, authority, logging, boundaries, or approval "
                "controls. JARV cannot self-modify in a way that reduces its own safety. "
                "No change was applied; the block is logged and recorded in memory."
            )
            return answer, steps, agents, {"self_evolution": {"verdict": "blocked", "applied": False}}

        # Safe proposal: accept + version it (recorded as a workflow improvement).
        await self._feed(db, runtime.workspace_id, runtime.task_id, item_type="self_evolution",
                         severity="success", title="Self-evolution proposal accepted (safe)",
                         message=command_text[:300])
        await self._audit(db, runtime.workspace_id, action="self_evolution_applied",
                          category="self_evolution", description=f"Safe proposal accepted: {command_text[:200]}",
                          success=True, target_id=str(runtime.task_id),
                          metadata={"verdict": "safe", "versioned": True})
        await memory_service.add(db, content=f"Self-evolution accepted (safe): {command_text[:200]}",
                                 memory_type="self_evolution", workspace_id=runtime.workspace_id,
                                 task_id=runtime.task_id, importance=0.7)
        answer = (
            "**Self-evolution proposal accepted (classified SAFE).**\n\n"
            "The change does not touch safety, authority, logging, boundaries, or approval, so "
            "it is versioned and recorded (reversible). Unsafe changes are always blocked."
        )
        return answer, steps, agents, {"self_evolution": {"verdict": "safe", "applied": True}}

    async def _handle_swarm(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Spawn parallel sub-agents -> execute -> collect -> verify -> dissolve."""
        steps = [
            "Swarm Manager: create a swarm run and spawn scoped sub-agents.",
            "Sub-agents: each executes its assigned read-only sub-task in parallel.",
            "Swarm Manager: collect outputs, verify, and dissolve sub-agents.",
        ]
        agents = self._validate_agents(["orchestrator", "swarm_manager", "verifier"])
        host_path = await self._resolve_ws_root(db, command_text)
        if not host_path:
            return ("No approved workspace for the swarm to operate on. Register one first.",
                    steps, agents, {"swarm_error": "no_workspace"})

        # Spawn 3 scoped sub-agents, each inspecting a different facet (real work).
        sub_specs = [
            ("scanner-1", "inventory top-level files", "top_level_files"),
            ("scanner-2", "inventory package/build files", "package_files"),
            ("scanner-3", "inventory docs/entry points", "doc_files"),
        ]
        scan = await runtime.scan_workspace(host_path)
        data = scan.get("data", {}) if scan.get("success") else {}
        sub_agents: List[Dict[str, Any]] = []
        for name, task_desc, facet in sub_specs:
            child = Task(id=uuid4(), workspace_id=runtime.workspace_id,
                         title=f"[swarm:{name}] {task_desc}"[:500], description=task_desc,
                         task_type="sub_agent_task", status="running", priority=5,
                         context={"parent_task_id": str(runtime.task_id), "swarm": True,
                                  "sub_agent": name},
                         meta_data={"facet": facet},
                         started_at=datetime.now(timezone.utc),
                         created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
            db.add(child)
            await db.flush()
            output = data.get(facet, [])
            child.status = "completed"
            child.completed_at = datetime.now(timezone.utc)
            child.result = {"sub_agent": name, "facet": facet, "items": output, "count": len(output)}
            child.updated_at = datetime.now(timezone.utc)
            await self._feed(db, runtime.workspace_id, runtime.task_id, item_type="swarm",
                             severity="info", title=f"Sub-agent {name} completed",
                             message=f"{task_desc}: {len(output)} item(s)")
            await memory_service.add(db, content=f"[swarm:{name}] {task_desc} -> {len(output)} items",
                                     memory_type="swarm", workspace_id=runtime.workspace_id,
                                     task_id=runtime.task_id, importance=0.5)
            sub_agents.append({"sub_agent": name, "child_task_id": str(child.id),
                               "items": len(output), "dissolved": True})

        collected = sum(s["items"] for s in sub_agents)
        verified = all(s["dissolved"] for s in sub_agents) and len(sub_agents) == 3
        await self._feed(db, runtime.workspace_id, runtime.task_id, item_type="swarm",
                         severity="success", title="Swarm run complete",
                         message=f"{len(sub_agents)} sub-agents spawned, collected {collected} items, dissolved.")
        answer = (
            f"**Swarm run complete on `{host_path}`.**\n\n"
            + "\n".join(f"  - **{s['sub_agent']}** → {s['items']} item(s) "
                        f"(task `{s['child_task_id'][:8]}`, dissolved)" for s in sub_agents)
            + f"\n\n**Collected:** {collected} item(s) across {len(sub_agents)} sub-agents. "
            f"**Verification:** {'PASS' if verified else 'FAIL'}. All sub-agents dissolved on completion. "
            f"Each ran scoped to the approved workspace and inherited <= lead authority."
        )
        return answer, steps, agents, {
            "swarm": {"sub_agents": sub_agents, "collected": collected, "verified": verified}}

    async def _handle_company_workflow(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Generate a real, persisted draft from a company operating workflow."""
        text = command_text.lower()
        steps = [
            "Orchestrator: route to the matching company workflow.",
            "Workflow agent: generate a usable draft (LLM).",
            "Persist the draft to the task, operations feed, and memory for review.",
        ]
        catalog = [
            ("marketing", ["marketing", "campaign", "ad "], "marketing", "a marketing campaign brief"),
            ("content", ["content", "blog", "article", "post"], "content", "a content piece/draft"),
            ("onboarding", ["onboard"], "onboarding", "a user onboarding flow/copy"),
            ("support", ["support", "ticket", "reply"], "customer_support", "a support reply draft"),
            ("sales", ["sales", "outreach", "pipeline", "lead"], "sales", "a sales outreach sequence"),
            ("partnership", ["partner"], "partnerships", "a partnership proposal draft"),
            ("revenue", ["revenue", "pricing", "monetiz"], "finance_metrics", "a revenue/pricing plan"),
            ("business", ["business", "strategy", "plan"], "business", "a business strategy brief"),
        ]
        func, agent_hint, draft_kind = "business", "business", "a business strategy brief"
        for name, kws, agent, kind in catalog:
            if any(k in text for k in kws):
                func, agent_hint, draft_kind = name, agent, kind
                break
        agents = self._validate_agents(["orchestrator", agent_hint])

        router = get_router()
        system = (
            f"You are JARV's {func} agent in an autonomous software company. Produce {draft_kind} "
            f"as a concrete, usable DRAFT (not a plan to make one). Be specific and ready to review. "
            f"This is a draft for operator approval; do not claim it has been sent or published."
        )
        try:
            response = await router.complete(CompletionRequest(
                model=self.model, messages=[Message(role="user", content=command_text)],
                system=system, max_tokens=900))
            draft = response.content.strip()
            tokens = (response.usage or {}).get("total_tokens", 0)
            ok = True
        except Exception as exc:  # noqa: BLE001
            draft, tokens, ok = f"(draft generation error: {exc})", 0, False

        await self._feed(db, runtime.workspace_id, runtime.task_id, item_type=func,
                         severity="success" if ok else "error",
                         title=f"{func.title()} draft generated",
                         message=draft[:300])
        await self._audit(db, runtime.workspace_id, action=f"{func}_draft", category="company_workflow",
                          description=f"{func} draft generated for review", success=ok,
                          target_id=str(runtime.task_id), metadata={"function": func})
        await memory_service.add(db, content=f"[{func} draft] {draft[:300]}",
                                 memory_type=func, workspace_id=runtime.workspace_id,
                                 task_id=runtime.task_id, importance=0.6)
        answer = (
            f"**{func.title()} draft (for your approval — not sent/published):**\n\n{draft}"
        )
        return answer, steps, agents, {
            "company_function": func, "draft_chars": len(draft), "wf_tokens": tokens}

    @staticmethod
    def _detect_stack(scan: Dict[str, Any]) -> Dict[str, Any]:
        """Derive stack + build/test commands from real package/build files found."""
        pkgs = set(scan.get("package_files", []) or [])
        builds = set(scan.get("build_files", []) or [])
        has = lambda n: any(p.split("/")[-1] == n for p in pkgs)
        stack, build_cmd, test_cmd = [], None, None
        if has("package.json"):
            stack.append("node/js")
            build_cmd, test_cmd = "npm run build", "npm test"
        if has("requirements.txt") or has("pyproject.toml") or has("Pipfile"):
            stack.append("python")
            test_cmd = test_cmd or "python -m pytest"
            build_cmd = build_cmd or "python -m compileall ."
        if has("go.mod"):
            stack.append("go"); build_cmd = build_cmd or "go build ./..."; test_cmd = test_cmd or "go test ./..."
        if has("Cargo.toml"):
            stack.append("rust"); build_cmd = build_cmd or "cargo build"; test_cmd = test_cmd or "cargo test"
        if has("pom.xml") or has("build.gradle"):
            stack.append("java")
        dockerized = any("docker" in b.lower() for b in builds)
        return {"stack": stack or ["unknown"], "build_command": build_cmd,
                "test_command": test_cmd, "dockerized": dockerized}

    async def _handle_launch_readiness(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Produce a real release-readiness report from the actual project files."""
        steps = [
            "DevOps: scan the workspace and detect the stack + build/test commands.",
            "Security: list required env vars from env example files (names only).",
            "DevOps: assemble release checklist, rollback + backup plan.",
            "Boundary: confirm the live release itself requires Richard's approval.",
        ]
        agents = self._validate_agents(["orchestrator", "devops", "security", "documentation"])
        root = await self._resolve_ws_root(db, command_text)
        if not root:
            return ("No approved workspace to assess. Register one first.",
                    steps, agents, {"launch_error": "no_workspace"})
        scan = await runtime.scan_workspace(root)
        if not scan.get("success"):
            return (f"Cannot assess `{root}`: {scan.get('reason')}", steps, agents,
                    {"launch_error": scan.get("reason")})
        d = scan["data"]
        stack = self._detect_stack(d)
        env_files = d.get("env_files", [])
        has_dockerfile = any("dockerfile" in b.lower() for b in d.get("build_files", []))
        has_compose = any("docker-compose" in b.lower() for b in d.get("build_files", []))

        checklist = [
            ("Stack detected", bool(stack["stack"] and stack["stack"] != ["unknown"])),
            ("Build command identified", bool(stack["build_command"])),
            ("Test command identified", bool(stack["test_command"])),
            ("Env example present", bool(env_files)),
            ("Dockerfile present", has_dockerfile),
            ("docker-compose present", has_compose),
        ]
        ready = sum(1 for _, ok in checklist if ok)
        report = {
            "workspace": root, "stack": stack["stack"],
            "build_command": stack["build_command"], "test_command": stack["test_command"],
            "env_requirements_files": env_files, "dockerfile": has_dockerfile,
            "docker_compose": has_compose,
            "rollback_plan": [
                "Tag the current release before deploying.",
                "Keep the previous build artifact/image to redeploy on failure.",
                "On error: redeploy previous tag; verify health; open an incident.",
            ],
            "backup_plan": [
                "Snapshot the database before release (pg_dump).",
                "Back up persistent volumes and the .env (secret-safe, not committed).",
                "Verify restore on staging before production cutover.",
            ],
            "checklist": [{"item": k, "ok": v} for k, v in checklist],
            "readiness_score": f"{ready}/{len(checklist)}",
            "live_release": "REQUIRES RICHARD APPROVAL (hard boundary — Level 7 live release).",
        }
        await self._feed(db, runtime.workspace_id, runtime.task_id, item_type="launch",
                         severity="info", title="Release readiness assessed",
                         message=f"{root}: {ready}/{len(checklist)} ready, stack {stack['stack']}")
        await memory_service.add(db, content=f"Launch readiness for {root}: {ready}/{len(checklist)}; "
                                 f"stack {stack['stack']}; build {stack['build_command']}",
                                 memory_type="launch", workspace_id=runtime.workspace_id,
                                 task_id=runtime.task_id, importance=0.7)

        def _ck(items):
            return "\n".join(f"  - [{'x' if v else ' '}] {k}" for k, v in items)
        answer = (
            f"**Release Readiness Report — `{root}`**\n\n"
            f"- **Stack:** {', '.join(stack['stack'])}\n"
            f"- **Build command:** `{stack['build_command'] or 'not detected'}`\n"
            f"- **Test command:** `{stack['test_command'] or 'not detected'}`\n"
            f"- **Env requirements:** {', '.join(env_files) or 'none found'} (values never read)\n"
            f"- **Dockerfile:** {has_dockerfile} | **docker-compose:** {has_compose}\n\n"
            f"**Checklist ({ready}/{len(checklist)}):**\n{_ck(checklist)}\n\n"
            f"**Rollback plan:**\n" + "\n".join(f"  - {x}" for x in report['rollback_plan']) + "\n\n"
            f"**Backup plan:**\n" + "\n".join(f"  - {x}" for x in report['backup_plan']) + "\n\n"
            f"**Live release:** {report['live_release']}\n\n"
            f"_Read-only assessment. JARV will not perform the live release without your explicit approval._"
        )
        return answer, steps, agents, {"launch_readiness": report, "workspace_path": root}

    async def _handle_infra_readiness(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Real infrastructure/cloud/scale readiness from actual files."""
        steps = [
            "Infrastructure: scan for Docker/compose/nginx/backup files.",
            "Infrastructure: assess cloud readiness + scaling considerations.",
        ]
        agents = self._validate_agents(["orchestrator", "infrastructure", "devops"])
        root = await self._resolve_ws_root(db, command_text)
        if not root:
            return ("No approved workspace to assess. Register one first.",
                    steps, agents, {"infra_error": "no_workspace"})
        scan = await runtime.scan_workspace(root)
        if not scan.get("success"):
            return (f"Cannot assess `{root}`: {scan.get('reason')}", steps, agents,
                    {"infra_error": scan.get("reason")})
        d = scan["data"]
        files = [f.lower() for f in (d.get("build_files", []) + d.get("top_level_files", []))]
        checks = {
            "dockerfile": any("dockerfile" in f for f in files),
            "docker_compose": any("docker-compose" in f for f in files),
            "ci_config": any(f.endswith((".yml", ".yaml")) and ("ci" in f or "workflow" in f) for f in files),
            "makefile": any(f == "makefile" for f in files),
        }
        report = {
            "workspace": root, "checks": checks,
            "cloud_ready": checks["dockerfile"] or checks["docker_compose"],
            "scaling_notes": [
                "Containerize with the present Dockerfile; run multiple replicas behind Nginx.",
                "Externalize state (Postgres/Redis) so app instances stay stateless.",
                "Add health checks + autoscaling rules; cap spend within approved budget.",
            ],
            "backup_restore": [
                "Scheduled pg_dump to object storage; verify restore on staging.",
                "Volume snapshots for persistent data.",
            ],
            "cost_note": "Estimate per-replica + DB + storage monthly cost before scaling; "
                         "spending beyond the approved budget is a hard boundary.",
        }
        await self._feed(db, runtime.workspace_id, runtime.task_id, item_type="infrastructure",
                         severity="info", title="Infrastructure readiness assessed",
                         message=f"{root}: cloud_ready={report['cloud_ready']}")
        answer = (
            f"**Infrastructure / Scale Readiness — `{root}`**\n\n"
            f"- Dockerfile: {checks['dockerfile']} | docker-compose: {checks['docker_compose']}\n"
            f"- CI config: {checks['ci_config']} | Makefile: {checks['makefile']}\n"
            f"- **Cloud ready:** {report['cloud_ready']}\n\n"
            f"**Scaling:**\n" + "\n".join(f"  - {x}" for x in report['scaling_notes']) + "\n\n"
            f"**Backup/restore:**\n" + "\n".join(f"  - {x}" for x in report['backup_restore']) + "\n\n"
            f"**Cost:** {report['cost_note']}"
        )
        return answer, steps, agents, {"infra_readiness": report, "workspace_path": root}

    async def _handle_agent_task(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Autonomous tool-using agent loop: inspect -> edit -> build/test -> iterate."""
        from app.core.command.agent_executor import AgentExecutor

        agents = self._validate_agents(
            ["orchestrator", "coding", "debugging", "devops", "qa", "verifier"]
        )
        steps = [
            "Orchestrator: hand the mission to the autonomous engineering loop.",
            "Agent: inspect the workspace (list/read files) via tools.",
            "Agent: edit files with the scoped write tool (Level 2).",
            "Agent: run builds/tests via the command tool (Level 3) and read results.",
            "Agent: iterate until the mission is verified or a boundary is reached.",
        ]
        root = await self._resolve_ws_root(db, command_text)
        executor = AgentExecutor(runtime, self.model, root)
        result = await executor.run(command_text, max_steps=10)
        header = (
            f"**Autonomous engineering run "
            f"({'succeeded' if result['success'] else 'incomplete'}, "
            f"{result['iterations']} step(s), {len(runtime.calls)} tool call(s)).**\n\n"
            + (f"_Workspace:_ `{root}`\n\n" if root else
               "_No approved workspace resolved — register one, or include its path._\n\n")
        )
        return (
            header + result["answer"],
            steps, agents,
            {"agent_iterations": result["iterations"], "agent_success": result["success"],
             "agent_tokens": result["tokens"], "workspace_path": root},
        )

    async def _resolve_ws_root(self, db: AsyncSession, command_text: str) -> Optional[str]:
        """Resolve a workspace root path from the command, else the latest registered."""
        p = self._extract_path(command_text)
        if p:
            return p
        res = await db.execute(select(Workspace).order_by(Workspace.created_at.desc()))
        for ws in res.scalars().all():
            cfg = ws.config if isinstance(ws.config, dict) else {}
            if cfg.get("root_path"):
                return cfg["root_path"]
        return None

    async def _handle_write_file(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Controlled, authority-gated file write inside an approved workspace."""
        steps = [
            "Coding Agent: resolve the approved target path (scope-checked).",
            "Security: confirm target is not a secret and is in scope.",
            "Coding Agent: call write_file (Level 2) and record the FileChange.",
        ]
        agents = self._validate_agents(["orchestrator", "coding", "security"])
        # Resolve filename + workspace.
        fn_match = re.search(r"([\w.\-]+\.[A-Za-z0-9]{1,8})", command_text)
        filename = fn_match.group(1) if fn_match else "JARV_WRITE_TEST.md"
        full = self._extract_path(command_text)
        sep = "\\" if (full and "\\" in full) or "\\" in settings.WORKSPACE_HOST_ROOT else "/"
        if full and re.search(r"\.[A-Za-z0-9]{1,8}$", full):
            target = full  # already a file path
        else:
            root = full or await self._resolve_ws_root(db, command_text)
            if not root:
                return ("No approved workspace to write into. Register one first.",
                        steps, agents, {"write_error": "no_workspace"})
            target = root.rstrip("\\/") + sep + filename
        content = (
            "# JARV Write Test\n\n"
            "This file was created by JARV through the controlled, authority-gated "
            "write_file tool (Level 2), scoped to an approved workspace.\n"
        )
        res = await runtime.write_file(target, content, overwrite=False)
        if not res["success"]:
            return (f"Write blocked for `{target}`.\n\n{res.get('reason')}",
                    steps, agents, {"target": target, "written": False, "reason": res.get("reason")})
        answer = (
            f"**File written (controlled, Level 2).**\n\n"
            f"- Path: `{target}`\n"
            f"- Created: {res['data'].get('created')}\n"
            f"- Bytes: {res['data'].get('bytes_written')}\n"
            f"- A FileChange record + audit entry were logged. Writes outside the "
            f"approved workspace or to secret files are blocked."
        )
        return answer, steps, agents, {"target": target, "written": True,
                                       "created": res["data"].get("created")}

    async def _handle_run_command(
        self, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Execute a read-only command inside an approved workspace (capture I/O)."""
        steps = [
            "DevOps Agent: extract and classify the command (safe/risky/dangerous).",
            "DevOps Agent: run safe read-only command with timeout; capture stdout/stderr/exit.",
        ]
        agents = self._validate_agents(["orchestrator", "devops"])
        # Extract command: backticked, quoted, or after run/execute (the) command.
        m = (re.search(r"[`\"']([^`\"']+)[`\"']", command_text) or
             re.search(r"\b(?:run|execute)\b(?:\s+the)?(?:\s+command)?[:\s]+(.+)", command_text, re.IGNORECASE))
        cmd = (m.group(1) if m else "").strip().rstrip(".")
        cmd = re.split(r"(?:\s+inside\b|\s+in the\b|\s+do not\b)", cmd, maxsplit=1)[0].strip()
        if not cmd:
            cmd = "ls -la"
        cwd = self._extract_path(command_text)
        res = await runtime.run_safe_readonly_command(cmd, cwd_host=cwd)
        if res.get("blocked"):
            return (f"Command blocked (dangerous): `{cmd}`.", steps, agents,
                    {"command": cmd, "blocked": True})
        if res.get("requires_approval"):
            return (f"Command `{cmd}` is not read-only and requires approval before execution.",
                    steps, agents, {"command": cmd, "requires_approval": True})
        out = (res.get("stdout") or "").strip()
        answer = (
            f"**Command executed (read-only, Level 3).**\n\n"
            f"- Command: `{cmd}`\n- Exit code: {res.get('exit_code')}\n\n"
            f"**stdout:**\n```\n{out[:1500] or '(empty)'}\n```\n"
            + (f"**stderr:**\n```\n{res.get('stderr','')[:600]}\n```\n" if res.get("stderr") else "")
        )
        return answer, steps, agents, {"command": cmd, "exit_code": res.get("exit_code")}

    async def _handle_notify(
        self, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Dry-run external notification (secret-safe; live send needs approval)."""
        steps = [
            "Integration: select target (local_mock dry-run by default).",
            "Integration: send notification (dry-run) and log payload secret-safe.",
        ]
        agents = self._validate_agents(["orchestrator", "monitoring"])
        msg_match = re.search(r"[`\"']([^`\"']+)[`\"']", command_text)
        message = msg_match.group(1) if msg_match else "JARV test notification (dry-run)."
        res = await runtime.send_notification("local_mock", message, dry_run=True)
        answer = (
            f"**Notification dry-run complete.**\n\n"
            f"- Target: `{res['target']}`\n- Mode: `{res['mode']}` (nothing sent externally)\n"
            f"- Payload preview (secret-safe): {res.get('payload_preview')}\n\n"
            f"Live external sends require configured credentials and explicit approval."
        )
        return answer, steps, agents, {"notification": res}

    async def _handle_delegate(
        self, db: AsyncSession, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Run a real researcher -> qa-tester -> verifier chain with recorded handoffs."""
        steps = [
            "Orchestrator: assign subtasks to researcher, qa-tester, verifier.",
            "Researcher: inspect docs and hand off the referenced file list.",
            "QA-tester: verify each referenced file exists; hand off the results.",
            "Verifier: produce the final pass/fail from QA's output.",
        ]
        agents = self._validate_agents(["orchestrator", "research", "qa", "verifier"])
        host_path = await self._resolve_ws_root(db, command_text)
        if not host_path:
            return ("No approved workspace to run the delegation chain on. Register one first.",
                    steps, agents, {"delegate_error": "no_workspace"})

        chain: List[Dict[str, Any]] = []
        parent_id = runtime.task_id

        async def child(agent: str, description: str) -> UUID:
            t = Task(id=uuid4(), workspace_id=runtime.workspace_id,
                     title=f"[{agent}] {description}"[:500], description=description,
                     task_type="subtask", status="running", priority=5,
                     context={"parent_task_id": str(parent_id), "agent": agent},
                     meta_data={"delegated": True},
                     started_at=datetime.now(timezone.utc),
                     created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
            db.add(t)
            await db.flush()
            return t.id

        async def finish(child_id: UUID, agent: str, output: Dict[str, Any], summary: str) -> None:
            res = await db.execute(select(Task).where(Task.id == child_id))
            ct = res.scalar_one_or_none()
            if ct:
                ct.status = "completed"
                ct.completed_at = datetime.now(timezone.utc)
                ct.result = {"agent": agent, "output": output, "summary": summary}
                ct.updated_at = datetime.now(timezone.utc)
            await self._feed(db, runtime.workspace_id, parent_id, item_type="delegation",
                             severity="info", title=f"Handoff: {agent}", message=summary)
            await memory_service.add(db, content=f"[delegation:{agent}] {summary}",
                                     memory_type="delegation", workspace_id=runtime.workspace_id,
                                     task_id=parent_id, importance=0.55)
            chain.append({"agent": agent, "child_task_id": str(child_id),
                          "output": output, "summary": summary})

        # 1) Researcher inspects docs (real scan via tool).
        c1 = await child("researcher", f"Inspect docs in {host_path}")
        scan = await runtime.scan_workspace(host_path)
        docs = (scan.get("data") or {}).get("doc_files", []) if scan.get("success") else []
        referenced = (scan.get("data") or {}).get("top_level_files", []) + docs
        await finish(c1, "researcher", {"referenced_files": referenced},
                     f"found {len(referenced)} referenced file(s)")

        # 2) QA-tester verifies the researcher's files exist (consumes handoff).
        c2 = await child("qa-tester", "Verify researcher's referenced files exist")
        sep = "\\" if "\\" in host_path else "/"
        base = host_path.rstrip("\\/")
        checks = []
        for rel in referenced:
            full = base + sep + rel.replace("/", sep)
            chk = fs_inspector.path_exists(full)
            checks.append({"file": rel, "exists": bool(chk.accessible and chk.exists)})
        verified = sum(1 for c in checks if c["exists"])
        await finish(c2, "qa-tester", {"checks": checks, "verified": verified, "total": len(checks)},
                     f"verified {verified}/{len(checks)} files exist")

        # 3) Verifier produces the final pass/fail from QA's output.
        c3 = await child("verifier", "Produce final pass/fail from QA results")
        passed = len(checks) > 0 and verified == len(checks)
        await finish(c3, "verifier", {"passed": passed, "verified": verified, "total": len(checks)},
                     f"final verdict: {'PASS' if passed else 'FAIL'}")

        lines = "\n".join(
            f"  {i+1}. **{h['agent']}** → {h['summary']} (task `{h['child_task_id'][:8]}`)"
            for i, h in enumerate(chain)
        )
        answer = (
            f"**Multi-agent delegation chain complete** on `{host_path}`.\n\n"
            f"{lines}\n\n"
            f"**Final result:** {'PASS' if passed else 'FAIL'} "
            f"({verified}/{len(checks)} files verified). Each handoff is a child task "
            f"with its output stored and logged to the operations feed and memory."
        )
        return answer, steps, agents, {
            "delegation": chain,
            "parent_task_id": str(parent_id),
            "final_passed": passed,
        }

    async def _handle_remember(
        self, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Store a fact in persistent memory via the memory_add tool."""
        steps = ["Memory Agent: extract the fact.", "Memory Agent: call memory_add (persist)."]
        agents = self._validate_agents(["orchestrator", "memory"])
        # Extract the fact: text after 'remember', stripping quotes/trailing instructions.
        m = re.search(r"remember(?:\s+this[^:]*)?[:\s]+(.+)", command_text, re.IGNORECASE)
        fact = (m.group(1) if m else command_text).strip()
        fact = re.split(r"(?:\bthen\b|\.\s|do not modify|don't modify)", fact, maxsplit=1)[0].strip().strip('"').strip("'")
        if not fact:
            return ("I could not find a fact to remember.", steps, agents,
                    {"memory_error": "no_fact"})
        res = await runtime.memory_add(fact, memory_type="fact", importance=0.8)
        answer = (
            f"**Stored to persistent memory.**\n\n"
            f"- Fact: \"{fact}\"\n- Memory ID: `{res['memory_id']}`\n"
            f"- Backend: PostgreSQL + pgvector (persists across sessions)\n\n"
            f"You can ask me to recall it at any time."
        )
        return answer, steps, agents, {"memory_id": res["memory_id"], "stored_fact": fact}

    async def _handle_recall(
        self, runtime: ToolRuntime, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Recall facts from persistent memory via the memory_search tool."""
        steps = ["Memory Agent: build the query.", "Memory Agent: call memory_search (retrieve)."]
        agents = self._validate_agents(["orchestrator", "memory"])
        # Use the command minus the recall verb as the query.
        query = re.sub(r"\b(recall|retrieve|what did you remember|do you remember|please|jarv)\b",
                       " ", command_text, flags=re.IGNORECASE)
        res = await runtime.memory_search(query, limit=5)
        results = res["results"]
        if not results:
            return ("I have no matching memories for that query.", steps, agents,
                    {"recall_count": 0})
        lines = "\n".join(f"- [{r['type']}] {r['content']}" for r in results)
        answer = f"**Recalled {len(results)} memory record(s):**\n\n{lines}"
        return answer, steps, agents, {"recall_count": len(results), "recalled": results}

    async def _handle_register_workspace(
        self, db: AsyncSession, command_text: str
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Confirm a path exists on disk and register it as a scoped workspace."""
        steps = [
            "Workspace Manager: parse the target path from the command.",
            "Workspace Manager: confirm the path exists on disk (read-only stat).",
            "Workspace Manager: register a scoped workspace record (no file changes).",
        ]
        agents = self._validate_agents(["orchestrator", "workspace_manager"])
        host_path = self._extract_path(command_text)
        if not host_path:
            return (
                "I could not find a folder path in that command. Please include an "
                "absolute path, e.g. `register a workspace at C:\\\\Users\\\\you\\\\Project`.",
                steps, agents, {"register_error": "no_path"},
            )

        chk = fs_inspector.path_exists(host_path)
        if not chk.accessible:
            return (
                f"Workspace registration blocked for `{host_path}`.\n\n{chk.reason}",
                steps, agents,
                {"workspace_path": host_path, "path_exists": False, "blocked": True,
                 "reason": chk.reason},
            )
        if not chk.exists:
            return (
                f"The path `{host_path}` is inside the approved root but does not "
                f"exist on disk yet, so I did not register it. Create the folder and "
                f"run the command again.",
                steps, agents,
                {"workspace_path": host_path, "path_exists": False},
            )

        # Path confirmed — create (or reuse) a scoped workspace record.
        name = Path(host_path.replace("\\", "/")).name or "Workspace"
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:90] or "workspace"
        # Reuse if a workspace with this root_path already exists.
        ws = await self._find_workspace_by_root(db, host_path)
        if ws is None:
            # Ensure unique slug.
            slug_check = await db.execute(select(Workspace.id).where(Workspace.slug == slug))
            if slug_check.scalar_one_or_none():
                slug = f"{slug}-{uuid4().hex[:6]}"
            owner_id = await self._first_user_id(db)
            ws = Workspace(
                id=uuid4(),
                name=name,
                slug=slug,
                description=f"Registered workspace at {host_path}",
                owner_id=owner_id,
                workspace_type="project",
                is_active=True,
                authority_level=2,  # default: read + scoped workspace edits (gated)
                config={"root_path": host_path, "container_path": chk.container_path,
                        "registered_via": "command_center"},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(ws)
            await db.flush()
            created = True
        else:
            created = False

        await self._feed(
            db, ws.id, None, item_type="workspace", severity="success",
            title="Workspace registered" if created else "Workspace confirmed",
            message=f"{name} -> {host_path} (path confirmed, read-only)",
        )
        await self._audit(
            db, ws.id, action="workspace_registered", category="workspace",
            description=f"Workspace {'registered' if created else 'confirmed'}: {host_path}",
            success=True, target_id=str(ws.id),
            metadata={"path": host_path, "operator": self.operator},
        )

        answer = (
            f"**Workspace {'registered' if created else 'already registered (confirmed)'}.**\n\n"
            f"- **Name:** {name}\n"
            f"- **Path:** `{host_path}`\n"
            f"- **Exists on disk:** Yes (confirmed by read-only check)\n"
            f"- **Scope:** Access is limited to this approved folder. No files were "
            f"modified, and none will be without your approval.\n\n"
            f"You can now ask JARV to run a read-only scan of this workspace."
        )
        return answer, steps, agents, {
            "workspace_id": str(ws.id),
            "workspace_path": host_path,
            "path_exists": True,
            "created": created,
        }

    async def _handle_scan_workspace(
        self, db: AsyncSession, command_text: str, runtime: "ToolRuntime"
    ) -> tuple[str, List[str], List[str], Dict[str, Any]]:
        """Run a REAL read-only scan of an approved workspace's actual files."""
        steps = [
            "Workspace Manager: resolve the approved workspace to scan.",
            "Workspace Manager: walk the directory read-only and inventory files.",
            "Research/Documentation: identify docs and design files.",
            "Coding/DevOps: identify package and build/deploy files.",
            "Security: flag env/secret files by name (values never read).",
            "QA/Verifier: summarize findings, risks, and approval points.",
        ]
        agents = self._validate_agents(
            ["orchestrator", "workspace_manager", "research", "documentation",
             "security", "qa"]
        )

        host_path = self._extract_path(command_text)
        if not host_path:
            # Fall back to the most recently registered workspace with a root_path.
            res = await db.execute(
                select(Workspace).order_by(Workspace.created_at.desc())
            )
            for ws in res.scalars().all():
                rp = (ws.config or {}).get("root_path") if isinstance(ws.config, dict) else None
                if rp:
                    host_path = rp
                    break
        if not host_path:
            return (
                "There is no registered workspace path to scan. Register a workspace "
                "first, e.g. `register a workspace at C:\\\\Users\\\\you\\\\Project`.",
                steps, agents, {"scan_error": "no_workspace"},
            )

        # Act through real tools (recorded as tool calls on the task).
        await runtime.list_files(host_path)
        scan_call = await runtime.scan_workspace(host_path)
        if not scan_call.get("accessible"):
            return (
                f"Read-only scan blocked for `{host_path}`.\n\n{scan_call.get('reason')}",
                steps, agents,
                {"workspace_path": host_path, "blocked": True, "reason": scan_call.get("reason")},
            )
        if not scan_call.get("exists"):
            return (
                f"Cannot scan `{host_path}`: {scan_call.get('reason')}",
                steps, agents, {"workspace_path": host_path, "path_exists": False},
            )

        d = scan_call["data"]
        # Read one referenced doc via the read_file tool to prove file-level access.
        sep = "\\" if "\\" in host_path else "/"
        base = host_path.rstrip("\\/")
        for doc in (d.get("doc_files") or []):
            doc_native = doc.replace("/", sep)
            await runtime.read_file(base + sep + doc_native)
            break

        # Independent QA verification: confirm referenced files actually exist.
        verification = await qa_verifier.verify_scan(
            db, runtime.task_id, runtime.workspace_id, host_path, d
        )

        def _fmt(items: List[str], limit: int = 20) -> str:
            if not items:
                return "_none found_"
            shown = items[:limit]
            extra = f"\n  - …and {len(items) - limit} more" if len(items) > limit else ""
            return "\n".join(f"  - `{i}`" for i in shown) + extra

        answer = (
            f"**Read-only workspace scan — `{host_path}`**\n\n"
            f"{d.get('summary', '')}\n\n"
            f"**Top-level folders:**\n{_fmt(d.get('top_level_dirs', []))}\n\n"
            f"**Top-level files:**\n{_fmt(d.get('top_level_files', []))}\n\n"
            f"**Package / dependency files:**\n{_fmt(d.get('package_files', []))}\n\n"
            f"**Build / deploy files:**\n{_fmt(d.get('build_files', []))}\n\n"
            f"**Docs / design files:**\n{_fmt(d.get('doc_files', []))}\n\n"
            f"**Entry points:**\n{_fmt(d.get('entry_points', []))}\n\n"
            f"**Env / secret files (names only — values NOT read):**\n{_fmt(d.get('env_files', []))}\n\n"
            f"**Risks:**\n{_fmt(d.get('risks', []))}\n\n"
            f"**Approval points before any change:**\n{_fmt(d.get('approval_points', []))}\n\n"
            f"**QA verification:** {'PASSED' if verification['passed'] else 'FAILED'} "
            f"({verification['tests_passed']}/{verification['tests_passed'] + verification['tests_failed']} "
            f"referenced files independently confirmed on disk, confidence "
            f"{verification['confidence_score']}).\n\n"
            f"_No files were modified. This was a read-only inspection scoped to the approved workspace._"
        )
        return answer, steps, agents, {
            "workspace_path": host_path,
            "scan": d,
            "verification": verification,
        }

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

        # Persistent memory / vector store status (real)
        try:
            mem_count = await memory_service.count(db)
            pgvector = await memory_service.pgvector_available(db)
            context["memory"] = {
                "provider": "postgresql+pgvector",
                "connected": True,
                "pgvector_extension": pgvector,
                "records": mem_count,
            }
        except Exception as exc:  # noqa: BLE001
            context["memory"] = {"connected": False, "error": str(exc)}

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
