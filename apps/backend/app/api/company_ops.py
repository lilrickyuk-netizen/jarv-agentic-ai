"""
JARV Backend - Company operating layer API (Repair 12e-3c)

Authenticated, owner-scoped endpoints over app.core.company_ops: the
workspace's operating overview (plan, daily loop, weekly plan, standup, KPIs,
risks, decisions, next actions), running the daily loop, recording KPIs,
risks and decisions, and the plan's version history.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.company_ops.service import company_ops, decision_view, kpi_view, loop_view, risk_view, standup_view
from app.core.database import get_db
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/company-ops", tags=["company-operations"])


async def _owned(db: AsyncSession, user_id: str, workspace_id: UUID) -> Workspace:
    row = (await db.execute(select(Workspace).where(
        Workspace.id == workspace_id, Workspace.owner_id == UUID(str(user_id))))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return row


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 400, detail=str(exc))


class KPIInput(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    value: float
    target: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    higher_is_better: bool = True
    period_start: Optional[str] = None


class RiskInput(BaseModel):
    title: str = Field(..., min_length=3)
    description: str = Field(..., min_length=3)
    category: str = "operational"
    probability: str
    impact: str
    mitigation_strategy: Optional[str] = None


class DecisionInput(BaseModel):
    title: str = Field(..., min_length=3)
    description: str = Field(..., min_length=3)
    decision_type: str = "operational"
    rationale: Optional[str] = None
    alternatives: List[str] = Field(default_factory=list)


@router.get("/{workspace_id}/overview")
async def overview(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    return await company_ops.overview(db, workspace_id)


@router.get("/{workspace_id}/next-actions")
async def next_actions(workspace_id: UUID, user_id: CurrentUserId, limit: int = 10,
                       db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    return {"actions": await company_ops.next_best_actions(db, workspace_id, limit=max(1, min(limit, 50)))}


@router.post("/{workspace_id}/daily-loop/run")
async def run_daily_loop(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)
                         ) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    loop = await company_ops.run_daily_loop(db, workspace_id)
    await db.commit()
    return loop_view(loop)


@router.post("/{workspace_id}/standups")
async def create_standup(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)
                         ) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    row = await company_ops.create_standup(db, workspace_id)
    await db.commit()
    return standup_view(row)


@router.post("/{workspace_id}/kpis")
async def record_kpi(workspace_id: UUID, body: KPIInput, user_id: CurrentUserId,
                     db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    try:
        row = await company_ops.record_kpi(db, workspace_id, name=body.name, value=body.value, target=body.target,
                                           unit=body.unit, category=body.category,
                                           higher_is_better=body.higher_is_better, period_start=body.period_start)
    except (LookupError, ValueError) as exc:
        raise _bad(exc)
    await db.commit()
    return kpi_view(row)


@router.post("/{workspace_id}/risks")
async def create_risk(workspace_id: UUID, body: RiskInput, user_id: CurrentUserId,
                      db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    try:
        row = await company_ops.create_risk(db, workspace_id, title=body.title, description=body.description,
                                            category=body.category, probability=body.probability, impact=body.impact,
                                            mitigation_strategy=body.mitigation_strategy, owner_id=UUID(str(user_id)))
    except (LookupError, ValueError) as exc:
        raise _bad(exc)
    await db.commit()
    return risk_view(row)


@router.post("/{workspace_id}/decisions")
async def log_decision(workspace_id: UUID, body: DecisionInput, user_id: CurrentUserId,
                       db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    row = await company_ops.log_decision(db, workspace_id, title=body.title, description=body.description,
                                         decision_type=body.decision_type, rationale=body.rationale,
                                         alternatives=body.alternatives, made_by=UUID(str(user_id)))
    await db.commit()
    return decision_view(row)


@router.get("/{workspace_id}/plans/{plan_id}/versions")
async def plan_versions(workspace_id: UUID, plan_id: UUID, user_id: CurrentUserId,
                        db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    try:
        return {"versions": await company_ops.plan_versions(db, workspace_id, plan_id)}
    except (LookupError, ValueError) as exc:
        raise _bad(exc)
