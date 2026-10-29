"""
JARV Backend - Self-evolution engine (persisted)

How JARV changes its own way of working, safely:

1. Propose. A change to one component (workspace rule, runbook, agent
   instructions, tool selection, operating plan, swarm strategy, or a workflow
   note) is stored as a ``SelfEvolutionRecord``. Text that would weaken safety,
   authority, logging, audit, boundaries, approvals, verification, secret
   handling or sub-agent scope is blocked at once and can never be applied.
2. Verify. Checks run against the live component and are stored as a
   ``VerificationResult``: safety guard, target validity, no authority or limit
   increase, no disabling of protected rules or safety tools, a real change.
   Changing a protected rule's content needs Richard's approval.
3. Apply. Only a verified change is applied. The component's current state is
   saved as ``previous_state`` and the component's own versioning records the
   change (rule versions, runbook versions, strategy versions, plan versions).
4. Monitor and roll back. Outcomes before and after the change are compared;
   any applied change can be rolled back to its saved state (newest first),
   itself versioned.

Applied changes take effect through ``guidance_for`` (agent instructions,
workflow notes, runbooks, swarm strategy) and ``blocked_tools_for`` (tool
selection), which the agent tool loop reads. They sit below system and safety
rules and can only narrow what an agent does, never widen its authority.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.safety.evolution_guard import classify_change
from app.core.security import redact_text
from app.models.agent import Agent
from app.models.agent_strategy import AgentStrategyVersion
from app.models.operating_plan import OperatingPlan, OperatingPlanVersion
from app.models.runbook import Runbook, RunbookVersion
from app.models.self_evolution import ExperienceRecord, SelfEvolutionRecord, VerificationResult
from app.models.tool_system import ToolSelectionRule
from app.models.workspace import Workspace
from app.models.workspace_rules import WorkspaceRule

logger = logging.getLogger(__name__)

TYPES = ("rule", "runbook", "agent_instruction", "tool_selection", "operating_plan", "swarm_strategy", "workflow")
STRATEGIES = {"parallel", "sequential", "hierarchical", "pipeline"}
SAFETY_TOOL_CATEGORIES = {"boundary", "approval", "resume"}
SAFETY_TOOL_WORDS = ("boundary", "approval", "verify", "verifier", "audit", "redact", "rollback")
APPLIED, ROLLED_BACK = "applied", "rolled_back"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _id(value: Any, what: str = "id") -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"'{value}' is not a valid {what}") from None


def view(record: SelfEvolutionRecord) -> Dict[str, Any]:
    meta = record.meta_data or {}
    return {"id": str(record.id), "workspace_id": meta.get("workspace_id"), "type": record.evolution_type,
            "component": meta.get("component"), "title": record.title, "description": record.description,
            "change": (record.new_state or {}).get("change"), "target": (record.new_state or {}).get("target"),
            "previous_state": record.previous_state, "status": record.status,
            "verification_status": record.verification_status, "needs_approval": bool(meta.get("needs_approval")),
            "reasoning": record.reasoning, "expected_benefit": record.expected_benefit,
            "proposed_by": meta.get("proposed_by"), "version": meta.get("version"),
            "is_applied": record.is_applied,
            "applied_at": _aware(record.applied_at).isoformat() if record.applied_at else None,
            "is_rolled_back": record.is_rolled_back, "rollback_reason": record.rollback_reason,
            "performance_delta": record.performance_delta, "is_successful": record.is_successful,
            "created_at": _aware(record.created_at).isoformat() if record.created_at else None}


class EvolutionEngine:
    # ----- scope ---------------------------------------------------------------------------

    async def _agent(self, db: AsyncSession, workspace_id: UUID, name: Optional[str] = None,
                     create: bool = False) -> Optional[Agent]:
        """The workspace's agent record for ``name`` (or its system agent)."""
        if name is None:
            from app.core.jarv_memory import memory_service

            agent_id = await memory_service._agent_id(db, workspace_id)
            return (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one()
        row = (await db.execute(select(Agent).where(
            Agent.workspace_id == workspace_id, Agent.agent_type == name, Agent.is_subagent.is_(False))
            .order_by(Agent.created_at.asc()).limit(1))).scalar_one_or_none()
        if row is None and create:
            from app.core.agents.registry import get_registry

            meta = get_registry().get_metadata(name)
            if meta is None:
                raise ValueError(f"'{name}' is not a registered agent")
            ws_level = (await db.execute(select(Workspace.authority_level).where(Workspace.id == workspace_id))
                        ).scalar_one()
            row = Agent(id=uuid4(), name=name, agent_type=name, workspace_id=workspace_id, is_active=True,
                        is_subagent=False, config={"role": "workspace agent record"},
                        model_provider="configured-router", model_name="claude-sonnet-4-6",
                        authority_level=min(int(meta.required_authority_level), int(ws_level or 1)),
                        allowed_tools=list(meta.default_tools or []), blocked_tools=[], current_state="idle",
                        total_executions=0, successful_executions=0, failed_executions=0, total_tokens_used=0)
            db.add(row)
            await db.flush()
        return row

    async def get(self, db: AsyncSession, workspace_id: UUID, record_id: Any) -> SelfEvolutionRecord:
        row = (await db.execute(select(SelfEvolutionRecord).join(Agent, SelfEvolutionRecord.agent_id == Agent.id)
                                .where(SelfEvolutionRecord.id == _id(record_id, "self-evolution record id"),
                                       Agent.workspace_id == workspace_id))).scalar_one_or_none()
        if row is None:
            raise LookupError("Self-evolution record not found in this workspace")
        return row

    async def history(self, db: AsyncSession, workspace_ids: Sequence[UUID], *, evolution_type: Optional[str] = None,
                      status: Optional[str] = None, component: Optional[str] = None, limit: int = 50
                      ) -> List[SelfEvolutionRecord]:
        if not workspace_ids:
            return []
        query = (select(SelfEvolutionRecord).join(Agent, SelfEvolutionRecord.agent_id == Agent.id)
                 .where(Agent.workspace_id.in_(list(workspace_ids))))
        if evolution_type:
            query = query.where(SelfEvolutionRecord.evolution_type == evolution_type)
        if status:
            query = query.where(SelfEvolutionRecord.status == status)
        rows = list((await db.execute(query.order_by(SelfEvolutionRecord.created_at.desc()).limit(500))
                     ).scalars().all())
        if component:
            rows = [r for r in rows if (r.meta_data or {}).get("component") == component]
        return rows[:limit]

    async def stats(self, db: AsyncSession, workspace_id: UUID) -> Dict[str, Any]:
        rows = await self.history(db, [workspace_id], limit=500)
        by_status: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for row in rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1
            by_type[row.evolution_type] = by_type.get(row.evolution_type, 0) + 1
        applied = by_status.get(APPLIED, 0) + by_status.get(ROLLED_BACK, 0)
        return {"total": len(rows), "by_status": by_status, "by_type": by_type,
                "rollback_rate": round(by_status.get(ROLLED_BACK, 0) / applied, 3) if applied else None,
                "blocked": by_status.get("blocked", 0)}

    # ----- components ----------------------------------------------------------------------

    @staticmethod
    def component_key(evolution_type: str, target: Dict[str, Any]) -> str:
        name = target.get("name") or target.get("agent") or target.get("plan_id") or "workspace"
        return f"{evolution_type}:{name}"

    async def snapshot(self, db: AsyncSession, workspace_id: UUID, evolution_type: str,
                       target: Dict[str, Any]) -> Dict[str, Any]:
        """The component's current state, in the same shape a change is written in."""
        if evolution_type == "rule":
            row = await self._rule(db, workspace_id, target["name"])
            if row is None:
                return {"exists": False}
            return {"exists": True, "type": row.rule_type, "description": row.description,
                    "content": row.rule_content, "conditions": row.conditions, "actions": row.actions,
                    "active": row.is_active, "priority": row.priority}
        if evolution_type == "runbook":
            row = await self._runbook(db, workspace_id, target["name"])
            if row is None:
                return {"exists": False}
            return {"exists": True, "runbook_type": row.runbook_type, "description": row.description,
                    "steps": row.steps, "prerequisites": row.prerequisites,
                    "expected_outcome": row.expected_outcome, "active": row.is_active}
        if evolution_type == "agent_instruction":
            agent = await self._agent(db, workspace_id, target["agent"])
            version = await self._active_strategy(db, agent.id) if agent else None
            if version is None:
                return {"exists": False}
            return {"exists": True, "instructions": version.system_prompt, "strategy": version.strategy,
                    "version": version.version_number}
        if evolution_type == "tool_selection":
            row = await self._tool_rule(db, workspace_id, target["name"])
            if row is None:
                return {"exists": False}
            return {"exists": True, "agent": (row.conditions or {}).get("agent"), "conditions": row.conditions,
                    "recommended_tools": row.recommended_tools, "blocked_tools": row.blocked_tools,
                    "priority": row.priority, "active": row.is_active}
        if evolution_type == "operating_plan":
            plan = await self._plan(db, workspace_id, target["plan_id"])
            return {"exists": True, "objectives": plan.objectives, "strategies": plan.strategies,
                    "milestones": plan.milestones, "status": plan.status}
        if evolution_type == "swarm_strategy":
            ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
            strategy = (ws.config or {}).get("swarm_strategy")
            return {"exists": True, **strategy} if strategy else {"exists": False}
        if evolution_type == "workflow":
            return {"exists": False}
        raise ValueError(f"Unknown change type '{evolution_type}' (use one of {', '.join(TYPES)})")

    async def _rule(self, db, workspace_id, name) -> Optional[WorkspaceRule]:
        return (await db.execute(select(WorkspaceRule).where(WorkspaceRule.workspace_id == workspace_id,
                                                             WorkspaceRule.rule_name == name))).scalar_one_or_none()

    async def _runbook(self, db, workspace_id, name) -> Optional[Runbook]:
        return (await db.execute(select(Runbook).where(Runbook.workspace_id == workspace_id,
                                                       Runbook.runbook_name == name))).scalar_one_or_none()

    async def _tool_rule(self, db, workspace_id, name) -> Optional[ToolSelectionRule]:
        return (await db.execute(select(ToolSelectionRule).where(ToolSelectionRule.workspace_id == workspace_id,
                                                                 ToolSelectionRule.rule_name == name))
                ).scalar_one_or_none()

    async def _active_strategy(self, db, agent_id) -> Optional[AgentStrategyVersion]:
        return (await db.execute(select(AgentStrategyVersion).where(
            AgentStrategyVersion.agent_id == agent_id, AgentStrategyVersion.is_active.is_(True))
            .order_by(AgentStrategyVersion.version_number.desc()).limit(1))).scalar_one_or_none()

    async def _plan(self, db, workspace_id, plan_id) -> OperatingPlan:
        plan = (await db.execute(select(OperatingPlan).where(OperatingPlan.id == _id(plan_id, "plan id"),
                                                             OperatingPlan.workspace_id == workspace_id))
                ).scalar_one_or_none()
        if plan is None:
            raise LookupError("Operating plan not found in this workspace")
        return plan

    # ----- propose --------------------------------------------------------------------------

    async def propose(self, db: AsyncSession, workspace_id: UUID, *, evolution_type: str, target: Dict[str, Any],
                      change: Dict[str, Any], title: str, reasoning: str, expected_benefit: str,
                      proposed_by: str = "agent", trigger: str = "self_evolution",
                      task_id: Optional[UUID] = None) -> SelfEvolutionRecord:
        if evolution_type not in TYPES:
            raise ValueError(f"Unknown change type '{evolution_type}' (use one of {', '.join(TYPES)})")
        target, change = dict(target or {}), dict(change or {})
        self._check_target(evolution_type, target)
        text = redact_text(json.dumps(change, default=str) + " " + title + " " + reasoning)
        unsafe, matched = classify_change(text)
        key = self.component_key(evolution_type, target)
        agent = await self._agent(db, workspace_id)
        now = _now()
        record = SelfEvolutionRecord(
            id=uuid4(), agent_id=agent.id, evolution_type=evolution_type, title=redact_text(title)[:480],
            description=redact_text(reasoning)[:4000] or title,
            previous_state={}, new_state={"target": target, "change": change},
            changes=[{"field": k, "action": "set"} for k in change] or [{"field": evolution_type, "action": "note"}],
            trigger=trigger[:100], reasoning=(f"Blocked by safety guard: '{matched}'" if unsafe else redact_text(reasoning))[:4000],
            expected_benefit=redact_text(expected_benefit)[:2000] or "not stated",
            requires_verification=True, verification_status="rejected" if unsafe else "pending",
            status="blocked" if unsafe else "proposed", is_applied=False, is_rolled_back=False,
            meta_data={"workspace_id": str(workspace_id), "component": key, "proposed_by": proposed_by,
                       "task_id": str(task_id) if task_id else None,
                       **({"blocked_reason": f"safety guard: '{matched}'"} if unsafe else {})},
            created_at=now, updated_at=now)
        db.add(record)
        await db.flush()
        return record

    @staticmethod
    def _check_target(evolution_type: str, target: Dict[str, Any]) -> None:
        needed = {"rule": "name", "runbook": "name", "tool_selection": "name", "agent_instruction": "agent",
                  "operating_plan": "plan_id"}.get(evolution_type)
        if needed and not str(target.get(needed) or "").strip():
            raise ValueError(f"A {evolution_type} change needs target.{needed}")

    # ----- verify ---------------------------------------------------------------------------

    async def verify(self, db: AsyncSession, workspace_id: UUID, record: SelfEvolutionRecord,
                     verifier: str = "self_evolution_verifier") -> VerificationResult:
        started = _now()
        etype = record.evolution_type
        target = (record.new_state or {}).get("target") or {}
        change = (record.new_state or {}).get("change") or {}
        checks: List[Dict[str, Any]] = []
        warnings: List[str] = []
        needs_approval = False

        def check(name: str, ok: bool, detail: str) -> None:
            checks.append({"check": name, "passed": bool(ok), "detail": detail})

        unsafe, matched = classify_change(json.dumps(change, default=str) + " " + record.title)
        check("safety_guard", not unsafe, f"matches '{matched}'" if unsafe else "no safety-weakening wording")
        current: Dict[str, Any] = {}
        try:
            current = await self.snapshot(db, workspace_id, etype, target)
            problems, approval = await self._validate(db, workspace_id, etype, target, change, current)
            needs_approval = approval
            check("target_and_change_valid", not problems, "; ".join(problems) or "target and change are valid")
        except (LookupError, ValueError) as exc:
            check("target_and_change_valid", False, str(exc))
        if etype != "workflow" and current:
            merged = self._preview(etype, current, change)
            check("changes_something", merged != {k: v for k, v in current.items() if k in merged},
                  "the change alters the component" if merged else "nothing to change")
        if needs_approval:
            warnings.append("Changes a protected rule: Richard must approve before it is applied.")
        passed = all(c["passed"] for c in checks)
        # Wording that weakens safety, or a change that would disable a safety control, is blocked for good.
        blocked = unsafe or any(not c["passed"] and "self-evolution may not" in c["detail"] for c in checks)
        now = _now()
        result = VerificationResult(
            id=uuid4(), evolution_record_id=record.id, verification_type="self_evolution", verifier=verifier,
            tests_run=checks, tests_passed=sum(1 for c in checks if c["passed"]),
            tests_failed=sum(1 for c in checks if not c["passed"]),
            overall_status="passed" if passed else "failed", passed=passed,
            confidence_score=round(sum(1 for c in checks if c["passed"]) / len(checks), 3) if checks else 0.0,
            findings=checks, issues=[c["detail"] for c in checks if not c["passed"]], warnings=warnings,
            recommendation=("reject" if blocked or not passed else "needs_approval" if needs_approval else "apply"),
            reasoning="; ".join(f"{c['check']}: {c['detail']}" for c in checks), started_at=started,
            completed_at=now, duration_seconds=0, meta_data={"needs_approval": needs_approval},
            created_at=now, updated_at=now)
        db.add(result)
        record.verification_status = "passed" if passed else ("rejected" if blocked else "failed")
        if record.status not in (APPLIED, ROLLED_BACK, "rejected"):
            record.status = ("blocked" if blocked else "verified" if passed and not needs_approval
                             else "needs_approval" if passed else "failed_verification")
        record.meta_data = {**(record.meta_data or {}), "needs_approval": needs_approval,
                            "verification_id": str(result.id)}
        record.updated_at = now
        await db.flush()
        return result

    def _preview(self, etype: str, current: Dict[str, Any], change: Dict[str, Any]) -> Dict[str, Any]:
        """The fields the change would set, as they would read after applying it."""
        if etype == "operating_plan":
            from app.core.company_ops.service import _merge

            return {k: _merge(list(current.get(k) or []), change[k]) for k in ("objectives", "strategies", "milestones")
                    if change.get(k) is not None}
        keys = {"instructions": "instructions", "strategy": "strategy"} if etype == "agent_instruction" else None
        out = {}
        for key, value in change.items():
            if value is None:
                continue
            out[keys.get(key, key) if keys else key] = value
        if current.get("exists") is False:
            out["exists"] = True
        return out

    async def _validate(self, db, workspace_id, etype, target, change, current) -> Tuple[List[str], bool]:
        """(problems, needs_approval) for a change against the live component."""
        from app.core.workspaces.lifecycle import PROTECTED_RULE_TYPES

        problems: List[str] = []
        approval = False
        if etype == "rule":
            rule_type = str(change.get("type") or current.get("type") or "workflow").lower()
            protected = rule_type in PROTECTED_RULE_TYPES or current.get("type") in PROTECTED_RULE_TYPES
            if protected and (change.get("active") is False or change.get("remove")):
                problems.append("self-evolution may not disable or remove a protected rule")
            elif protected and current.get("exists"):
                approval = True
            if current.get("exists") is False and not change.get("content"):
                problems.append("a new rule needs content")
        elif etype == "runbook":
            steps = change.get("steps")
            if steps is not None and (not isinstance(steps, list) or not all(
                    isinstance(s, (str, dict)) and (s if isinstance(s, str) else s.get("action") or s.get("title"))
                    for s in steps)):
                problems.append("steps must be a list of strings or {action|title, ...}")
            if current.get("exists") is False and not steps:
                problems.append("a new runbook needs steps")
            if change.get("auto_execute"):
                problems.append("self-evolution may not make a runbook run automatically")
        elif etype == "agent_instruction":
            from app.core.agents.registry import get_registry

            if get_registry().get_metadata(target["agent"]) is None:
                problems.append(f"'{target['agent']}' is not a registered agent")
            text = str(change.get("instructions") or "")
            if not text.strip():
                problems.append("instructions are empty")
            elif len(text) > 4000:
                problems.append("instructions are longer than 4000 characters")
        elif etype == "tool_selection":
            from app.core.tools.registry import get_registry as tools

            registry = tools()
            names = list(change.get("recommended_tools") or []) + list(change.get("blocked_tools") or [])
            unknown = [n for n in names if registry.get_metadata(n) is None]
            if unknown:
                problems.append(f"unknown tools: {', '.join(unknown)}")
            safety = [n for n in change.get("blocked_tools") or [] if self._is_safety_tool(n)]
            if safety:
                problems.append(f"self-evolution may not block safety tools: {', '.join(safety)}")
            if not names:
                problems.append("a tool selection rule needs recommended_tools or blocked_tools")
        elif etype == "operating_plan":
            if not any(change.get(k) is not None for k in ("objectives", "strategies", "milestones")):
                problems.append("an operating plan change needs objectives, strategies or milestones")
        elif etype == "swarm_strategy":
            from app.core.swarm.limits import SwarmLimitManager

            if change.get("coordination_strategy") and change["coordination_strategy"] not in STRATEGIES:
                problems.append(f"coordination_strategy is one of {', '.join(sorted(STRATEGIES))}")
            limits = await SwarmLimitManager().effective_limits(db, workspace_id)
            parallel = change.get("max_parallel_sub_agents")
            if parallel is not None and int(parallel) > int(limits["max_sub_agents_per_swarm"]):
                problems.append(f"max_parallel_sub_agents {parallel} exceeds the swarm limit "
                                f"{limits['max_sub_agents_per_swarm']} (self-evolution may not raise limits)")
            extra = set(change) - {"coordination_strategy", "max_parallel_sub_agents", "preferred_leads", "notes"}
            if extra:
                problems.append(f"unsupported swarm strategy fields: {', '.join(sorted(extra))}")
        elif etype == "workflow":
            if not str(change.get("note") or "").strip():
                problems.append("a workflow change needs a note")
        return problems, approval

    @staticmethod
    def _is_safety_tool(name: str) -> bool:
        from app.core.tools.registry import get_registry

        meta = get_registry().get_metadata(name)
        category = getattr(meta, "category", "") or ""
        return category in SAFETY_TOOL_CATEGORIES or any(w in name for w in SAFETY_TOOL_WORDS)

    # ----- apply / reject / roll back --------------------------------------------------------

    async def approve(self, db: AsyncSession, workspace_id: UUID, record: SelfEvolutionRecord, *,
                      approved_by: Optional[UUID] = None, richard_approved: bool = False) -> SelfEvolutionRecord:
        """Apply a verified change (verifying first when it has not been)."""
        if record.status in ("blocked", "rejected", APPLIED, ROLLED_BACK):
            raise ValueError(f"This change is {record.status} and cannot be applied")
        if record.verification_status == "pending" or record.status == "proposed":
            await self.verify(db, workspace_id, record)
        if record.status in ("blocked", "failed_verification"):
            raise ValueError(f"Verification did not pass ({record.status}); see the verification result")
        if record.status == "needs_approval" and not richard_approved:
            raise PermissionError("This change touches a protected rule and needs Richard's approval")
        etype = record.evolution_type
        target = (record.new_state or {}).get("target") or {}
        change = (record.new_state or {}).get("change") or {}
        previous = await self.snapshot(db, workspace_id, etype, target)
        summary = f"self-evolution {record.id}: {record.title}"[:500]
        await self._write(db, workspace_id, etype, target, change, summary, approved_by, merge=True)
        key = (record.meta_data or {}).get("component")
        version = 1 + sum(1 for r in await self.history(db, [workspace_id], component=key, limit=500)
                          if r.id != record.id and r.is_applied)
        now = _now()
        record.previous_state = previous
        record.status, record.is_applied, record.applied_at = APPLIED, True, now
        record.meta_data = {**(record.meta_data or {}), "version": version,
                            "approved_by": str(approved_by) if approved_by else None,
                            "richard_approved": richard_approved}
        record.updated_at = now
        await db.flush()
        await self._feed(db, workspace_id, f"Self-evolution applied: {record.title}",
                         f"{etype} change v{version} applied; it can be rolled back.", "success")
        return record

    async def reject(self, db: AsyncSession, workspace_id: UUID, record: SelfEvolutionRecord, reason: str
                     ) -> SelfEvolutionRecord:
        if record.status in (APPLIED, ROLLED_BACK):
            raise ValueError("An applied change is undone with a rollback, not a rejection")
        record.status, record.verification_status = "rejected", "rejected"
        record.meta_data = {**(record.meta_data or {}), "rejected_reason": reason}
        record.updated_at = _now()
        await db.flush()
        return record

    async def rollback(self, db: AsyncSession, workspace_id: UUID, record: SelfEvolutionRecord, reason: str, *,
                       richard_approved: bool = False, rolled_back_by: Optional[UUID] = None) -> SelfEvolutionRecord:
        if record.status != APPLIED or record.is_rolled_back:
            raise ValueError("Only an applied change can be rolled back")
        key = (record.meta_data or {}).get("component")
        later = [r for r in await self.history(db, [workspace_id], component=key, limit=500)
                 if r.status == APPLIED and r.id != record.id and _aware(r.applied_at) > _aware(record.applied_at)]
        if later:
            raise ValueError(f"Roll back the later change to {key} first ({later[0].id})")
        etype = record.evolution_type
        target = (record.new_state or {}).get("target") or {}
        previous = record.previous_state or {}
        if etype == "rule":
            from app.core.workspaces.lifecycle import PROTECTED_RULE_TYPES

            current = await self.snapshot(db, workspace_id, etype, target)
            if current.get("type") in PROTECTED_RULE_TYPES and not richard_approved and (
                    previous.get("exists") is False or previous.get("active") is False):
                raise PermissionError("Rolling back would disable a protected rule; Richard must approve")
        await self._write(db, workspace_id, etype, target, previous, f"rollback of {record.id}: {reason}"[:500],
                          rolled_back_by, merge=False)
        now = _now()
        record.status, record.is_rolled_back, record.rolled_back_at, record.rollback_reason = \
            ROLLED_BACK, True, now, reason
        record.updated_at = now
        await db.flush()
        await self._feed(db, workspace_id, f"Self-evolution rolled back: {record.title}", reason, "warning")
        return record

    async def restore_since(self, db: AsyncSession, workspace_id: UUID, since: datetime, reason: str
                            ) -> Dict[str, Any]:
        """Roll back every change applied after ``since``, newest first."""
        since = _aware(since)
        applied = [r for r in await self.history(db, [workspace_id], status=APPLIED, limit=500)
                   if _aware(r.applied_at) and _aware(r.applied_at) > since]
        applied.sort(key=lambda r: _aware(r.applied_at), reverse=True)
        done, skipped = [], []
        for record in applied:
            try:
                await self.rollback(db, workspace_id, record, reason)
                done.append(str(record.id))
            except (PermissionError, ValueError) as exc:
                skipped.append({"id": str(record.id), "reason": str(exc)})
        return {"rolled_back": done, "skipped": skipped}

    async def assess(self, db: AsyncSession, workspace_id: UUID, record: SelfEvolutionRecord, days: int = 7
                     ) -> Dict[str, Any]:
        """Compare success rates before and after the change (needs at least 3 outcomes on each side)."""
        if not record.applied_at:
            raise ValueError("The change has not been applied")
        applied = _aware(record.applied_at)
        agent = ((record.new_state or {}).get("target") or {}).get("agent")
        query = select(ExperienceRecord.outcome, ExperienceRecord.created_at).where(
            ExperienceRecord.workspace_id == workspace_id,
            ExperienceRecord.created_at >= applied - timedelta(days=days),
            ExperienceRecord.created_at <= applied + timedelta(days=days))
        if agent:
            query = query.where(ExperienceRecord.agent_name == agent)
        rows = (await db.execute(query)).all()

        def rate(items):
            judged = [o for o in items if o in ("success", "failure")]
            return (round(sum(1 for o in judged if o == "success") / len(judged), 3), len(judged)) if judged else (None, 0)

        before, n_before = rate([o for o, at in rows if _aware(at) < applied])
        after, n_after = rate([o for o, at in rows if _aware(at) >= applied])
        enough = n_before >= 3 and n_after >= 3
        if enough:
            record.performance_delta = round(after - before, 3)
            record.is_successful = after >= before
            record.actual_benefit = f"success rate {before:.0%} -> {after:.0%} ({n_before}/{n_after} outcomes)"
            record.updated_at = _now()
            await db.flush()
        return {"before": before, "after": after, "outcomes_before": n_before, "outcomes_after": n_after,
                "delta": record.performance_delta if enough else None, "enough_data": enough,
                "is_successful": record.is_successful if enough else None}

    async def _feed(self, db, workspace_id, title, message, severity) -> None:
        from app.core.company_ops.service import company_ops

        await company_ops.post_feed(db, workspace_id, item_type="self_evolution", title=title[:500],
                                    message=message, severity=severity)

    # ----- writing components --------------------------------------------------------------------

    async def _write(self, db, workspace_id, etype, target, state, summary, actor, *, merge: bool) -> None:
        """Write ``state`` into the component. merge=True applies a change; False restores a snapshot."""
        now = _now()
        if etype == "rule":
            from app.core.workspaces.lifecycle import workspace_lifecycle

            ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
            if state.get("exists") is False:
                change = {"name": target["name"], "remove": True}
                if await self._rule(db, workspace_id, target["name"]) is None:
                    return
            else:
                change = {"name": target["name"], **{k: v for k, v in state.items() if k != "exists"}}
            planned = await workspace_lifecycle.rule_changes(db, ws, [change])
            await workspace_lifecycle.apply_rule_changes(db, ws, planned, actor, summary)
        elif etype == "runbook":
            row = await self._runbook(db, workspace_id, target["name"])
            if state.get("exists") is False:
                if row is not None:
                    row.is_active = False
                    row.updated_at = now
                    await db.flush()
                return
            if row is None:
                row = Runbook(id=uuid4(), runbook_name=target["name"][:255], workspace_id=workspace_id,
                              runbook_type=str(state.get("runbook_type") or "operational")[:50],
                              description=str(state.get("description") or target["name"]), steps=[],
                              is_global=False, auto_execute=False, is_active=True, is_verified=True,
                              current_version=0, execution_count=0, success_count=0, failure_count=0,
                              created_by=actor, tags=["self_evolution"], meta_data={}, created_at=now, updated_at=now)
                db.add(row)
            for key, column in (("description", "description"), ("steps", "steps"), ("prerequisites", "prerequisites"),
                                ("expected_outcome", "expected_outcome"), ("runbook_type", "runbook_type")):
                if state.get(key) is not None:
                    value = state[key]
                    if key == "steps":
                        value = [s if isinstance(s, dict) else {"action": s} for s in value]
                    setattr(row, column, value)
            row.is_active = True if state.get("active") is None else bool(state["active"])
            row.current_version = int(row.current_version or 0) + 1
            row.updated_at = now
            await db.flush()
            db.add(RunbookVersion(id=uuid4(), runbook_id=row.id, version_number=row.current_version,
                                  description=row.description, steps=row.steps, prerequisites=row.prerequisites,
                                  expected_outcome=row.expected_outcome, changed_by=actor, change_summary=summary,
                                  is_verified=True, meta_data={}, created_at=now, updated_at=now))
        elif etype == "agent_instruction":
            agent = await self._agent(db, workspace_id, target["agent"], create=True)
            versions = (await db.execute(select(AgentStrategyVersion).where(AgentStrategyVersion.agent_id == agent.id)
                                         )).scalars().all()
            for version in versions:
                version.is_active = False
            if state.get("exists") is False:
                await db.flush()
                return
            current = await self._active_strategy(db, agent.id) if merge else None
            number = 1 + max([v.version_number for v in versions] or [0])
            db.add(AgentStrategyVersion(
                id=uuid4(), agent_id=agent.id, version_number=number, version_name=f"v{number}",
                description=summary, strategy=state.get("strategy") or (current.strategy if current else {}) or {},
                system_prompt=redact_text(str(state.get("instructions") or "")), total_executions=0,
                changed_by=actor, change_reason=summary, is_active=True, meta_data={"source": "self_evolution"},
                created_at=now, updated_at=now))
        elif etype == "tool_selection":
            row = await self._tool_rule(db, workspace_id, target["name"])
            if state.get("exists") is False:
                if row is not None:
                    row.is_active = False
                    row.updated_at = now
                return
            agent_name = state.get("agent") or target.get("agent")
            conditions = dict(state.get("conditions") or {})
            if agent_name:
                conditions["agent"] = agent_name
            if row is None:
                row = ToolSelectionRule(id=uuid4(), workspace_id=workspace_id, rule_name=target["name"][:255],
                                        rule_type="selection", description=summary, conditions=conditions,
                                        recommended_tools=[], blocked_tools=[], priority=5, is_active=True,
                                        times_applied=0, created_by=actor, meta_data={}, created_at=now,
                                        updated_at=now)
                db.add(row)
            row.conditions = conditions or row.conditions
            for key in ("recommended_tools", "blocked_tools"):
                if state.get(key) is not None:
                    setattr(row, key, list(state[key]))
            if state.get("priority") is not None:
                row.priority = int(state["priority"])
            row.is_active = True if state.get("active") is None else bool(state["active"])
            row.description, row.updated_at = summary, now
        elif etype == "operating_plan":
            from app.core.company_ops.service import _merge, _progress

            plan = await self._plan(db, workspace_id, target["plan_id"])
            for key in ("objectives", "strategies", "milestones"):
                if state.get(key) is not None:
                    setattr(plan, key, _merge(list(getattr(plan, key) or []), state[key]) if merge else list(state[key]))
            if state.get("status") and not merge:
                plan.status = state["status"]
            plan.objectives_completed, plan.objectives_total, plan.completion_percentage = _progress(plan.objectives)
            plan.current_version += 1
            plan.updated_at = now
            db.add(OperatingPlanVersion(id=uuid4(), plan_id=plan.id, version_number=plan.current_version,
                                        version_description=summary, objectives=plan.objectives,
                                        strategies=plan.strategies, milestones=plan.milestones, changed_by=actor,
                                        change_summary=summary, created_at=now, updated_at=now))
        elif etype == "swarm_strategy":
            ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
            cfg = dict(ws.config or {})
            if state.get("exists") is False:
                cfg.pop("swarm_strategy", None)
            else:
                base = dict(cfg.get("swarm_strategy") or {}) if merge else {}
                base.update({k: v for k, v in state.items() if k != "exists" and v is not None})
                cfg["swarm_strategy"] = base
            ws.config = cfg
            ws.updated_at = now
        elif etype == "workflow":
            return  # a workflow note takes effect through guidance_for while it is applied
        await db.flush()

    # ----- effect on agents ----------------------------------------------------------------------

    async def guidance_for(self, db: AsyncSession, workspace_id: UUID, agent_name: str) -> str:
        """Approved, applied changes that shape this agent's work (below system and safety rules)."""
        parts: List[str] = []
        agent = await self._agent(db, workspace_id, agent_name)
        if agent is not None:
            strategy = await self._active_strategy(db, agent.id)
            if strategy is not None and strategy.system_prompt:
                parts.append(f"Approved instructions for the {agent_name} agent (v{strategy.version_number}): "
                             f"{strategy.system_prompt}")
        notes = [r for r in await self.history(db, [workspace_id], evolution_type="workflow", status=APPLIED, limit=10)]
        for note in notes:
            parts.append(f"Approved workflow: {((note.new_state or {}).get('change') or {}).get('note')}")
        rules = (await db.execute(select(ToolSelectionRule).where(ToolSelectionRule.workspace_id == workspace_id,
                                                                  ToolSelectionRule.is_active.is_(True)))).scalars().all()
        preferred = sorted({t for r in rules if (r.conditions or {}).get("agent") in (None, agent_name)
                            for t in r.recommended_tools or []})
        if preferred:
            parts.append(f"Preferred tools here: {', '.join(preferred)}.")
        if agent_name in ("self_healing", "devops", "monitoring", "rollback", "infrastructure"):
            books = (await db.execute(select(Runbook).where(Runbook.workspace_id == workspace_id,
                                                            Runbook.is_active.is_(True)).limit(5))).scalars().all()
            for book in books:
                steps = "; ".join(str(s.get("action") or s.get("title")) for s in (book.steps or [])[:8])
                parts.append(f"Runbook '{book.runbook_name}': {steps}")
        if agent_name == "swarm_manager":
            ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
            strategy = (ws.config or {}).get("swarm_strategy") if ws else None
            if strategy:
                parts.append(f"Swarm strategy: {json.dumps(strategy, default=str)}")
        if not parts:
            return ""
        return ("Workspace guidance from approved self-evolution (follow it unless it conflicts with the rules "
                "above):\n- " + "\n- ".join(p[:800] for p in parts))

    async def blocked_tools_for(self, db: AsyncSession, workspace_id: UUID, agent_name: str) -> Set[str]:
        rules = (await db.execute(select(ToolSelectionRule).where(ToolSelectionRule.workspace_id == workspace_id,
                                                                  ToolSelectionRule.is_active.is_(True)))).scalars().all()
        return {t for r in rules if (r.conditions or {}).get("agent") in (None, agent_name)
                for t in r.blocked_tools or [] if not self._is_safety_tool(t)}


evolution_engine = EvolutionEngine()
