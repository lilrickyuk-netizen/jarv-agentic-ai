"""
JARV Backend - Swarm tracking

Metrics, costs, and activity reports computed from the persisted swarm rows
(SwarmRun, SubAgent, SubAgentTask, SubAgentLog). When a swarm finishes, its
totals are recorded once as a SwarmCostRecord.

Costs are estimates: the runner reports total tokens per sub-agent, so a
model's cost is tokens x the mean of its published input and output price.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.swarm import SubAgent, SubAgentLog, SubAgentTask, SwarmCostRecord as CostRow, SwarmRun

logger = logging.getLogger(__name__)


class SwarmCostRecord(BaseModel):
    id: UUID
    swarm_run_id: UUID
    model_costs: Dict[str, float]
    total_cost: float
    currency: str
    total_tokens: int
    total_api_calls: int
    total_subagents: int
    created_at: Optional[datetime]


class SwarmMetrics(BaseModel):
    swarm_run_id: UUID
    total_sub_agents: int
    active_sub_agents: int
    completed_sub_agents: int
    failed_sub_agents: int
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    total_tokens: Dict[str, int]
    total_cost: float
    avg_task_duration_seconds: float
    success_rate: float


def price_per_million(model: str) -> float:
    """Mean of the model's published input/output price per million tokens (0 when unknown)."""
    from app.core.providers.claude import ClaudeProvider
    from app.core.providers.gemini import GeminiProvider
    from app.core.providers.openai import OpenAIProvider

    for catalog in (ClaudeProvider.MODELS, OpenAIProvider.MODELS, GeminiProvider.MODELS):
        if model in catalog:
            entry = catalog[model]
            return (float(entry["input_cost"]) + float(entry["output_cost"])) / 2
    return 0.0


def estimate_cost(model: str, tokens: int) -> float:
    return round(int(tokens or 0) * price_per_million(model) / 1_000_000, 6)


async def _children(db: AsyncSession, swarm_run_id: UUID) -> List[SubAgent]:
    return list((await db.execute(select(SubAgent).where(SubAgent.swarm_run_id == swarm_run_id)
                                  .order_by(SubAgent.created_at))).scalars().all())


class SwarmTracker:
    async def calculate_swarm_cost(self, db: AsyncSession, swarm_run_id: UUID) -> Dict[str, Any]:
        by_model: Dict[str, Dict[str, float]] = {}
        by_child: Dict[str, Dict[str, Any]] = {}
        for child in await _children(db, swarm_run_id):
            cost = float(child.cost or 0) or estimate_cost(child.model_name, child.tokens_used)
            entry = by_model.setdefault(child.model_name, {"tokens": 0, "cost": 0.0})
            entry["tokens"] += int(child.tokens_used or 0)
            entry["cost"] = round(entry["cost"] + cost, 6)
            by_child[str(child.id)] = {"agent": child.subagent_name, "status": child.status,
                                       "tokens": int(child.tokens_used or 0), "cost": round(cost, 6)}
        return {"swarm_run_id": str(swarm_run_id), "by_model": by_model, "by_sub_agent": by_child,
                "totals": {"tokens": sum(m["tokens"] for m in by_model.values()),
                           "cost": round(sum(m["cost"] for m in by_model.values()), 6)},
                "currency": "USD", "estimated": True}

    async def get_swarm_metrics(self, db: AsyncSession, swarm_run_id: UUID) -> SwarmMetrics:
        children = await _children(db, swarm_run_id)
        tasks = list((await db.execute(select(SubAgentTask).join(SubAgent, SubAgentTask.subagent_id == SubAgent.id)
                                       .where(SubAgent.swarm_run_id == swarm_run_id))).scalars().all())
        finished = [t for t in tasks if t.completed_at and t.started_at]
        durations = [(t.completed_at - t.started_at).total_seconds() for t in finished]
        done = sum(1 for c in children if c.status == "completed" or (c.status == "dissolved" and c.success))
        failed = sum(1 for c in children if c.status in ("failed", "timed_out") or (c.status == "dissolved" and c.success is False))
        tokens: Dict[str, int] = {}
        for child in children:
            tokens[child.model_name] = tokens.get(child.model_name, 0) + int(child.tokens_used or 0)
        cost = (await self.calculate_swarm_cost(db, swarm_run_id))["totals"]["cost"]
        judged = done + failed
        return SwarmMetrics(
            swarm_run_id=swarm_run_id, total_sub_agents=len(children),
            active_sub_agents=sum(1 for c in children if c.status in ("spawning", "idle", "working")),
            completed_sub_agents=done, failed_sub_agents=failed, total_tasks=len(tasks),
            completed_tasks=sum(1 for t in tasks if t.status == "completed"),
            failed_tasks=sum(1 for t in tasks if t.status == "failed"), total_tokens=tokens, total_cost=cost,
            avg_task_duration_seconds=round(sum(durations) / len(durations), 2) if durations else 0.0,
            success_rate=round(done / judged, 3) if judged else 0.0)

    async def report_swarm_activity(self, db: AsyncSession, swarm_run_id: UUID) -> Dict[str, Any]:
        swarm = (await db.execute(select(SwarmRun).where(SwarmRun.id == swarm_run_id))).scalar_one_or_none()
        if swarm is None:
            raise ValueError("Swarm run not found")
        children = await _children(db, swarm_run_id)
        logs = list((await db.execute(select(SubAgentLog).join(SubAgent, SubAgentLog.subagent_id == SubAgent.id)
                                      .where(SubAgent.swarm_run_id == swarm_run_id)
                                      .order_by(SubAgentLog.logged_at))).scalars().all())
        metrics = await self.get_swarm_metrics(db, swarm_run_id)
        issues = [f"{c.subagent_name}: {c.error_message or (c.result or {}).get('error') or 'failed'}"
                  for c in children if c.status in ("failed", "timed_out")]
        recommendations = []
        if issues:
            recommendations.append("Review the failed sub-agents' errors before re-running their tasks.")
        if metrics.active_sub_agents == 0 and swarm.status in ("running", "initializing"):
            recommendations.append("All sub-agents have finished; complete or dissolve the swarm.")
        return {
            "swarm_run_id": str(swarm_run_id), "objective": swarm.objective, "status": swarm.status,
            "metrics": metrics.model_dump(mode="json"), "costs": await self.calculate_swarm_cost(db, swarm_run_id),
            "sub_agents": [{"id": str(c.id), "agent": c.subagent_name, "status": c.status, "success": c.success,
                            "tokens": c.tokens_used,
                            "summary": str((c.result or {}).get("output_text") or "")[:300]} for c in children],
            "timeline": [{"at": l.logged_at.isoformat() if l.logged_at else None, "level": l.log_level,
                          "category": l.log_category, "message": l.log_message[:500]} for l in logs],
            "issues": issues, "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat()}

    async def record_final_cost(self, db: AsyncSession, swarm: SwarmRun) -> CostRow:
        """One SwarmCostRecord per finished swarm (idempotent), with totals copied to the run."""
        existing = (await db.execute(select(CostRow).where(CostRow.swarm_run_id == swarm.id))).scalar_one_or_none()
        costs = await self.calculate_swarm_cost(db, swarm.id)
        children = await _children(db, swarm.id)
        now = datetime.now(timezone.utc)
        model_costs = {model: round(v["cost"], 6) for model, v in costs["by_model"].items()}
        total = Decimal(str(round(costs["totals"]["cost"], 4)))
        if existing is None:
            existing = CostRow(id=uuid4(), swarm_run_id=swarm.id, model_costs=model_costs, total_cost=total,
                               currency="USD", total_tokens=costs["totals"]["tokens"],
                               total_api_calls=sum(int(c.api_calls or 0) for c in children),
                               total_subagents=len(children), meta_data={"estimated": True},
                               created_at=now, updated_at=now)
            db.add(existing)
        else:
            existing.model_costs, existing.total_cost = model_costs, total
            existing.total_tokens, existing.total_subagents = costs["totals"]["tokens"], len(children)
            existing.updated_at = now
        swarm.total_tokens_used = costs["totals"]["tokens"]
        swarm.total_cost = total
        await db.flush()
        return existing

    async def list_cost_records(self, db: AsyncSession, workspace_ids: List[UUID], swarm_run_id: Optional[UUID] = None,
                                limit: int = 100) -> List[SwarmCostRecord]:
        query = select(CostRow).join(SwarmRun, CostRow.swarm_run_id == SwarmRun.id).where(
            SwarmRun.workspace_id.in_(workspace_ids))
        if swarm_run_id is not None:
            query = query.where(CostRow.swarm_run_id == swarm_run_id)
        rows = (await db.execute(query.order_by(CostRow.created_at.desc()).limit(limit))).scalars().all()
        return [SwarmCostRecord(id=r.id, swarm_run_id=r.swarm_run_id,
                                model_costs={k: float(v) for k, v in (r.model_costs or {}).items()},
                                total_cost=float(r.total_cost or 0), currency=r.currency, total_tokens=r.total_tokens,
                                total_api_calls=r.total_api_calls, total_subagents=r.total_subagents,
                                created_at=r.created_at) for r in rows]

    async def get_workspace_swarm_costs(self, db: AsyncSession, workspace_id: UUID,
                                        start: Optional[datetime] = None,
                                        end: Optional[datetime] = None) -> Dict[str, Any]:
        query = select(SwarmRun).where(SwarmRun.workspace_id == workspace_id)
        if start is not None:
            query = query.where(SwarmRun.created_at >= start)
        if end is not None:
            query = query.where(SwarmRun.created_at <= end)
        swarms = list((await db.execute(query)).scalars().all())
        by_date: Dict[str, Dict[str, float]] = {}
        totals = {"tokens": 0, "cost": 0.0, "sub_agents": 0}
        for swarm in swarms:
            costs = await self.calculate_swarm_cost(db, swarm.id)
            day = (swarm.created_at or datetime.now(timezone.utc)).date().isoformat()
            bucket = by_date.setdefault(day, {"tokens": 0, "cost": 0.0, "swarms": 0})
            bucket["tokens"] += costs["totals"]["tokens"]
            bucket["cost"] = round(bucket["cost"] + costs["totals"]["cost"], 6)
            bucket["swarms"] += 1
            totals["tokens"] += costs["totals"]["tokens"]
            totals["cost"] = round(totals["cost"] + costs["totals"]["cost"], 6)
            totals["sub_agents"] += len(costs["by_sub_agent"])
        return {"workspace_id": str(workspace_id),
                "period": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
                "total_swarms": len(swarms), "total_sub_agents": totals["sub_agents"],
                "total_tokens": totals["tokens"], "total_cost": totals["cost"],
                "avg_cost_per_swarm": round(totals["cost"] / len(swarms), 6) if swarms else 0.0,
                "by_date": [{"date": d, **v} for d, v in sorted(by_date.items())], "estimated": True}


_swarm_tracker = SwarmTracker()


async def calculate_swarm_cost(db: AsyncSession, swarm_run_id: UUID) -> Dict[str, Any]:
    return await _swarm_tracker.calculate_swarm_cost(db, swarm_run_id)


async def get_swarm_metrics(db: AsyncSession, swarm_run_id: UUID) -> SwarmMetrics:
    return await _swarm_tracker.get_swarm_metrics(db, swarm_run_id)
