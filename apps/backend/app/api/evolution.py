"""
JARV Backend - Self-Evolution API Endpoints

REST API for self-evolution management.
"""
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId, get_current_user_id
from app.core.database import get_db
from app.models.workspace import Workspace
from pydantic import BaseModel, Field

from app.core.evolution.experience import (
    ExperienceCreate,
    ExperienceResult,
    ExperienceType,
    ExperienceManager,
    LessonExtract,
)
from app.core.evolution.engine import TYPES, evolution_engine, view as evolution_view
from app.models.agent import Agent
from app.models.self_evolution import SelfEvolutionRecord

router = APIRouter(
    prefix="/api/evolution", tags=["evolution"],
    dependencies=[Depends(get_current_user_id)],
)

experience_manager = ExperienceManager()


# Response models
class ExperienceResponse(BaseModel):
    """Experience response"""
    id: UUID
    message: str
    experience: Optional[ExperienceResult] = None


class ImprovementCreate(BaseModel):
    """A proposed self-evolution change to one component of a workspace."""
    workspace_id: UUID
    improvement_type: str = Field(..., description="rule, runbook, agent_instruction, tool_selection, "
                                                   "operating_plan, swarm_strategy, workflow")
    target: dict = Field(default_factory=dict, description="{name} | {agent} | {plan_id} | {}")
    change: dict = Field(..., description="The fields to set on the component")
    title: str = Field(..., min_length=3)
    reasoning: str = Field(..., min_length=3)
    expected_benefit: str = Field("", description="What should improve")


class ApprovalRequest(BaseModel):
    """Richard's approval of a verified change."""
    notes: Optional[str] = None


class RejectionRequest(BaseModel):
    reason: str = Field(..., min_length=3)


class RollbackRequest(BaseModel):
    reason: str = Field(..., min_length=3)


class StatsResponse(BaseModel):
    """Statistics response"""
    workspace_id: UUID
    stats: dict


# =============================================================================
# EXPERIENCE ENDPOINTS
# =============================================================================

async def _owned_workspaces(db: AsyncSession, user_id: str) -> List[UUID]:
    return list((await db.execute(
        select(Workspace.id).where(Workspace.owner_id == UUID(str(user_id)))
    )).scalars().all())


@router.post("/experiences", response_model=ExperienceResponse)
async def capture_experience_endpoint(
    experience: ExperienceCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    """Capture an experience into the verified-learning lifecycle."""
    if experience.workspace_id not in await _owned_workspaces(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        experience_id = await experience_manager.capture_experience(db, experience)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    stored = await experience_manager.get_experience(db, experience_id, [experience.workspace_id])
    return ExperienceResponse(id=experience_id, message="Experience captured", experience=stored)


@router.post("/experiences/{experience_id}/summarize", response_model=dict)
async def summarize_experience_endpoint(
    experience_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    """Summary built from the stored record."""
    summary = await experience_manager.summarize_experience(
        db, experience_id, await _owned_workspaces(db, user_id))
    if summary is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return {"experience_id": str(experience_id), "summary": summary}


@router.post("/experiences/{experience_id}/extract-lessons", response_model=dict)
async def extract_lessons_endpoint(
    experience_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    """The lesson held by the record and its verification status."""
    lessons = await experience_manager.extract_lesson(
        db, experience_id, await _owned_workspaces(db, user_id))
    if lessons is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return {"experience_id": str(experience_id), "lessons": [lesson.model_dump() for lesson in lessons]}


@router.get("/experiences/stats/{workspace_id}", response_model=StatsResponse)
async def get_experience_stats_endpoint(
    workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    if workspace_id not in await _owned_workspaces(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    stats = await experience_manager.get_experience_stats(db, workspace_id)
    return StatsResponse(workspace_id=workspace_id, stats=stats)


@router.get("/experiences/{experience_id}", response_model=ExperienceResponse)
async def get_experience_endpoint(
    experience_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    experience = await experience_manager.get_experience(
        db, experience_id, await _owned_workspaces(db, user_id))
    if not experience:
        raise HTTPException(status_code=404, detail="Experience not found")
    return ExperienceResponse(id=experience_id, message="Experience retrieved", experience=experience)


@router.get("/experiences", response_model=List[ExperienceResult])
async def list_experiences_endpoint(
    user_id: CurrentUserId,
    workspace_id: Optional[UUID] = Query(None),
    agent_id: Optional[UUID] = Query(None),
    experience_type: Optional[ExperienceType] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned_workspaces(db, user_id)
    if workspace_id is not None:
        if workspace_id not in owned:
            raise HTTPException(status_code=404, detail="Workspace not found")
        owned = [workspace_id]
    return await experience_manager.list_experiences(
        db, owned, agent_id=agent_id, experience_type=experience_type, limit=limit)


# =============================================================================
# IMPROVEMENT (SELF-EVOLUTION) ENDPOINTS
# =============================================================================

def _improvement(record: SelfEvolutionRecord) -> dict:
    """A self-evolution record in the dashboard's improvement shape, with the full record attached."""
    data = evolution_view(record)
    priority = {"needs_approval": 1, "verified": 2, "proposed": 3}.get(record.status, 5)
    return {**data, "improvement_type": record.evolution_type, "priority": priority,
            "estimated_impact": record.expected_benefit, "approved_at": data["applied_at"],
            "implemented_at": data["applied_at"]}


async def _owned_record(db: AsyncSession, user_id: str, record_id: UUID):
    owned = await _owned_workspaces(db, user_id)
    row = (await db.execute(select(SelfEvolutionRecord, Agent.workspace_id)
                            .join(Agent, SelfEvolutionRecord.agent_id == Agent.id)
                            .where(SelfEvolutionRecord.id == record_id, Agent.workspace_id.in_(owned or [None]))
                            )).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Self-evolution record not found")
    return row[0], row[1]


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/improvements")
async def propose_improvement_endpoint(
    improvement: ImprovementCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    """Propose a change; it is safety-checked and verified straight away."""
    if improvement.workspace_id not in await _owned_workspaces(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        record = await evolution_engine.propose(
            db, improvement.workspace_id, evolution_type=improvement.improvement_type, target=improvement.target,
            change=improvement.change, title=improvement.title, reasoning=improvement.reasoning,
            expected_benefit=improvement.expected_benefit, proposed_by="richard", trigger="api")
        if record.status != "blocked":
            await evolution_engine.verify(db, improvement.workspace_id, record)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return _improvement(record)


@router.get("/improvements")
async def list_improvements_endpoint(
    user_id: CurrentUserId,
    workspace_id: Optional[UUID] = Query(None),
    improvement_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned_workspaces(db, user_id)
    if workspace_id is not None:
        if workspace_id not in owned:
            raise HTTPException(status_code=404, detail="Workspace not found")
        owned = [workspace_id]
    rows = await evolution_engine.history(db, owned, evolution_type=improvement_type, status=status, limit=limit)
    return [_improvement(r) for r in rows]


@router.get("/improvements/stats/{workspace_id}", response_model=StatsResponse)
async def get_improvement_stats_endpoint(workspace_id: UUID, user_id: CurrentUserId,
                                         db: AsyncSession = Depends(get_db)):
    if workspace_id not in await _owned_workspaces(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return StatsResponse(workspace_id=workspace_id, stats=await evolution_engine.stats(db, workspace_id))


@router.get("/improvements/{improvement_id}")
async def get_improvement_endpoint(improvement_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    record, _ws = await _owned_record(db, user_id, improvement_id)
    return _improvement(record)


@router.post("/improvements/{improvement_id}/verify")
async def verify_improvement_endpoint(improvement_id: UUID, user_id: CurrentUserId,
                                      db: AsyncSession = Depends(get_db)):
    record, ws = await _owned_record(db, user_id, improvement_id)
    result = await evolution_engine.verify(db, ws, record)
    await db.commit()
    return {"improvement": _improvement(record), "verification": {
        "passed": result.passed, "recommendation": result.recommendation, "checks": result.tests_run,
        "warnings": result.warnings}}


@router.post("/improvements/{improvement_id}/approve")
async def approve_improvement_endpoint(improvement_id: UUID, user_id: CurrentUserId,
                                       request: Optional[ApprovalRequest] = None,
                                       db: AsyncSession = Depends(get_db)):
    """Richard approves: a verified change is applied (protected-rule changes included)."""
    record, ws = await _owned_record(db, user_id, improvement_id)
    try:
        await evolution_engine.approve(db, ws, record, approved_by=UUID(str(user_id)), richard_approved=True)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return _improvement(record)


@router.post("/improvements/{improvement_id}/apply")
async def apply_improvement_endpoint(improvement_id: UUID, user_id: CurrentUserId,
                                     db: AsyncSession = Depends(get_db)):
    """Apply a verified change that needs no protected-rule approval."""
    record, ws = await _owned_record(db, user_id, improvement_id)
    try:
        await evolution_engine.approve(db, ws, record, approved_by=UUID(str(user_id)))
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return _improvement(record)


@router.post("/improvements/{improvement_id}/reject")
async def reject_improvement_endpoint(improvement_id: UUID, request: RejectionRequest, user_id: CurrentUserId,
                                      db: AsyncSession = Depends(get_db)):
    record, ws = await _owned_record(db, user_id, improvement_id)
    try:
        await evolution_engine.reject(db, ws, record, request.reason)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return _improvement(record)


@router.post("/improvements/{improvement_id}/rollback")
async def rollback_improvement_endpoint(improvement_id: UUID, request: RollbackRequest, user_id: CurrentUserId,
                                        db: AsyncSession = Depends(get_db)):
    record, ws = await _owned_record(db, user_id, improvement_id)
    try:
        await evolution_engine.rollback(db, ws, record, request.reason, richard_approved=True,
                                        rolled_back_by=UUID(str(user_id)))
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return _improvement(record)


@router.get("/improvements/{improvement_id}/monitor")
async def monitor_improvement_endpoint(improvement_id: UUID, user_id: CurrentUserId,
                                       duration_hours: int = Query(168, ge=24, le=720),
                                       db: AsyncSession = Depends(get_db)):
    """Success rate of the affected work before and after the change."""
    record, ws = await _owned_record(db, user_id, improvement_id)
    try:
        result = await evolution_engine.assess(db, ws, record, days=max(1, duration_hours // 24))
    except ValueError as exc:
        raise _http(exc)
    await db.commit()
    return {"improvement_id": str(improvement_id), "monitoring_results": result}


# =============================================================================
# VERSION HISTORY (applied changes) AND RESTORE
# =============================================================================

@router.get("/versions")
async def list_versions_endpoint(user_id: CurrentUserId, workspace_id: Optional[UUID] = Query(None),
                                 component: Optional[str] = Query(None, description="e.g. rule:branch names"),
                                 limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db)):
    owned = await _owned_workspaces(db, user_id)
    if workspace_id is not None:
        if workspace_id not in owned:
            raise HTTPException(status_code=404, detail="Workspace not found")
        owned = [workspace_id]
    rows = await evolution_engine.history(db, owned, component=component, limit=500)
    return [evolution_view(r) for r in rows if r.is_applied][:limit]


@router.post("/snapshots/{workspace_id}/restore")
async def restore_snapshot_endpoint(workspace_id: UUID, user_id: CurrentUserId,
                                    snapshot_date: str = Query(..., description="ISO datetime; changes applied "
                                                                                "after it are rolled back"),
                                    db: AsyncSession = Depends(get_db)):
    from datetime import datetime

    if workspace_id not in await _owned_workspaces(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        since = datetime.fromisoformat(snapshot_date.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {exc}")
    result = await evolution_engine.restore_since(db, workspace_id, since, f"restore to {snapshot_date}")
    await db.commit()
    return {"workspace_id": str(workspace_id), "snapshot_date": snapshot_date, **result}


def _evolution_health(stats: dict) -> dict:
    """Rates computed from stored experiences; None where there is no data yet."""
    total = stats.get("total", 0)
    by_status = stats.get("by_status", {})
    by_outcome = stats.get("by_outcome", {})
    verified, retired = by_status.get("verified", 0), by_status.get("retired", 0)
    return {
        "learning_rate": round(verified / total, 3) if total else None,
        "success_rate": round(by_outcome.get("success", 0) / total, 3) if total else None,
        "rollback_rate": round(retired / (verified + retired), 3) if verified + retired else None,
        "experiences": total,
    }


# =============================================================================
# DASHBOARD ENDPOINTS
# =============================================================================

@router.get("/dashboard/{workspace_id}")
async def get_evolution_dashboard(
    workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    """Self-evolution dashboard: experience, proposed/applied/rolled-back changes, and health."""
    if workspace_id not in await _owned_workspaces(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    experience_stats = await experience_manager.get_experience_stats(db, workspace_id)
    recent_experiences = await experience_manager.list_experiences(db, [workspace_id], limit=10)
    recent = await evolution_engine.history(db, [workspace_id], limit=10)
    return {
        "workspace_id": str(workspace_id),
        "experience_stats": experience_stats,
        "improvement_stats": await evolution_engine.stats(db, workspace_id),
        "recent_experiences": [exp.dict() for exp in recent_experiences],
        "recent_improvements": [_improvement(r) for r in recent],
        "recent_versions": [evolution_view(r) for r in recent if r.is_applied],
        "evolution_health": _evolution_health(experience_stats),
        "change_types": list(TYPES),
    }
