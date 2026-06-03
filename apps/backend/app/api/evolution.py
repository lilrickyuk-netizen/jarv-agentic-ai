"""
JARV Backend - Self-Evolution API Endpoints

REST API for self-evolution management.
"""
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.evolution.experience import (
    ExperienceCreate,
    ExperienceResult,
    ExperienceType,
    ExperienceManager,
    LessonExtract,
)
from app.core.evolution.improvements import (
    ImprovementCreate,
    ImprovementResult,
    ImprovementType,
    ImprovementStatus,
    RiskLevel,
    ImprovementManager,
)
from app.core.evolution.verification import (
    VerificationResult,
    VerificationManager,
)
from app.core.evolution.versioning import (
    VersionCreate,
    VersionResult,
    VersionType,
    VersionStatus,
    VersionManager,
)

router = APIRouter(prefix="/api/evolution", tags=["evolution"])

# Initialize managers
experience_manager = ExperienceManager()
improvement_manager = ImprovementManager()
verification_manager = VerificationManager()
version_manager = VersionManager()


# Response models
class ExperienceResponse(BaseModel):
    """Experience response"""
    id: UUID
    message: str
    experience: Optional[ExperienceResult] = None


class ImprovementResponse(BaseModel):
    """Improvement response"""
    id: UUID
    message: str
    improvement: Optional[ImprovementResult] = None


class VerificationResponse(BaseModel):
    """Verification response"""
    id: UUID
    message: str
    verification: VerificationResult


class VersionResponse(BaseModel):
    """Version response"""
    id: UUID
    message: str
    version: Optional[VersionResult] = None


class ApprovalRequest(BaseModel):
    """Approval request"""
    user_id: UUID
    notes: Optional[str] = None


class RejectionRequest(BaseModel):
    """Rejection request"""
    user_id: UUID
    reason: str


class RollbackRequest(BaseModel):
    """Rollback request"""
    reason: str
    user_id: Optional[UUID] = None


class StatsResponse(BaseModel):
    """Statistics response"""
    workspace_id: UUID
    stats: dict


# =============================================================================
# EXPERIENCE ENDPOINTS
# =============================================================================

@router.post("/experiences", response_model=ExperienceResponse)
async def capture_experience_endpoint(experience: ExperienceCreate):
    """
    Capture agent experience.

    Creates an experience record from agent execution.
    """
    try:
        experience_id = await experience_manager.capture_experience(experience)
        return ExperienceResponse(
            id=experience_id,
            message="Experience captured successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/experiences/{experience_id}/summarize", response_model=dict)
async def summarize_experience_endpoint(experience_id: UUID):
    """
    Summarize experience.

    Creates summary of experience using LLM.
    """
    try:
        summary = await experience_manager.summarize_experience(experience_id)
        return {"experience_id": str(experience_id), "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/experiences/{experience_id}/extract-lessons", response_model=dict)
async def extract_lessons_endpoint(experience_id: UUID):
    """
    Extract lessons from experience.

    Analyzes experience and extracts actionable lessons.
    """
    try:
        lessons = await experience_manager.extract_lesson(experience_id)
        return {
            "experience_id": str(experience_id),
            "lessons": [lesson.dict() for lesson in lessons]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/experiences/{experience_id}", response_model=ExperienceResponse)
async def get_experience_endpoint(experience_id: UUID):
    """Get experience by ID"""
    experience = await experience_manager.get_experience(experience_id)
    if not experience:
        raise HTTPException(status_code=404, detail="Experience not found")
    return ExperienceResponse(
        id=experience_id,
        message="Experience retrieved",
        experience=experience
    )


@router.get("/experiences", response_model=List[ExperienceResult])
async def list_experiences_endpoint(
    workspace_id: Optional[UUID] = Query(None),
    agent_id: Optional[UUID] = Query(None),
    experience_type: Optional[ExperienceType] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """List experiences with filters"""
    return await experience_manager.list_experiences(
        workspace_id=workspace_id,
        agent_id=agent_id,
        experience_type=experience_type,
        limit=limit,
    )


@router.get("/experiences/stats/{workspace_id}", response_model=StatsResponse)
async def get_experience_stats_endpoint(workspace_id: UUID):
    """Get experience statistics"""
    stats = await experience_manager.get_experience_stats(workspace_id)
    return StatsResponse(workspace_id=workspace_id, stats=stats)


# =============================================================================
# IMPROVEMENT ENDPOINTS
# =============================================================================

@router.post("/improvements", response_model=ImprovementResponse)
async def propose_improvement_endpoint(improvement: ImprovementCreate):
    """
    Propose improvement.

    Creates improvement proposal with risk classification.
    """
    try:
        improvement_id = await improvement_manager.propose_improvement(improvement)
        return ImprovementResponse(
            id=improvement_id,
            message="Improvement proposed successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/improvements/{improvement_id}", response_model=ImprovementResponse)
async def get_improvement_endpoint(improvement_id: UUID):
    """Get improvement by ID"""
    improvement = await improvement_manager.get_improvement(improvement_id)
    if not improvement:
        raise HTTPException(status_code=404, detail="Improvement not found")
    return ImprovementResponse(
        id=improvement_id,
        message="Improvement retrieved",
        improvement=improvement
    )


@router.get("/improvements", response_model=List[ImprovementResult])
async def list_improvements_endpoint(
    workspace_id: Optional[UUID] = Query(None),
    improvement_type: Optional[ImprovementType] = Query(None),
    status: Optional[ImprovementStatus] = Query(None),
    risk_level: Optional[RiskLevel] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """List improvements with filters"""
    return await improvement_manager.list_improvements(
        workspace_id=workspace_id,
        improvement_type=improvement_type,
        status=status,
        risk_level=risk_level,
        limit=limit,
    )


@router.get("/improvements/stats/{workspace_id}", response_model=StatsResponse)
async def get_improvement_stats_endpoint(workspace_id: UUID):
    """Get improvement statistics"""
    stats = await improvement_manager.get_improvement_stats(workspace_id)
    return StatsResponse(workspace_id=workspace_id, stats=stats)


# =============================================================================
# VERIFICATION ENDPOINTS
# =============================================================================

@router.post("/improvements/{improvement_id}/verify", response_model=VerificationResponse)
async def verify_improvement_endpoint(improvement_id: UUID):
    """
    Verify improvement safety.

    Runs safety checks on improvement proposal.
    """
    try:
        result = await verification_manager.verify_improvement(improvement_id)
        return VerificationResponse(
            id=improvement_id,
            message="Improvement verified",
            verification=result
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/improvements/{improvement_id}/approve", response_model=dict)
async def approve_improvement_endpoint(improvement_id: UUID, request: ApprovalRequest):
    """
    Approve improvement.

    Approves improvement for application.
    """
    try:
        success = await verification_manager.approve_improvement(
            improvement_id,
            request.user_id,
            request.notes,
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to approve improvement")
        return {
            "improvement_id": str(improvement_id),
            "status": "approved",
            "message": "Improvement approved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/improvements/{improvement_id}/reject", response_model=dict)
async def reject_improvement_endpoint(improvement_id: UUID, request: RejectionRequest):
    """
    Reject improvement.

    Rejects improvement with reason.
    """
    try:
        success = await verification_manager.reject_improvement(
            improvement_id,
            request.user_id,
            request.reason,
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to reject improvement")
        return {
            "improvement_id": str(improvement_id),
            "status": "rejected",
            "message": "Improvement rejected"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/improvements/{improvement_id}/apply", response_model=dict)
async def apply_improvement_endpoint(improvement_id: UUID):
    """
    Apply improvement.

    Applies approved improvement.
    """
    try:
        success = await verification_manager.apply_improvement(improvement_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to apply improvement")
        return {
            "improvement_id": str(improvement_id),
            "status": "applied",
            "message": "Improvement applied successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/improvements/{improvement_id}/monitor", response_model=dict)
async def monitor_improvement_endpoint(
    improvement_id: UUID,
    duration_hours: int = Query(24, ge=1, le=168),
):
    """
    Monitor improvement results.

    Tracks metrics after improvement application.
    """
    try:
        result = await verification_manager.monitor_improvement_result(
            improvement_id,
            duration_hours,
        )
        return {
            "improvement_id": str(improvement_id),
            "monitoring_results": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# VERSIONING ENDPOINTS
# =============================================================================

@router.post("/versions", response_model=VersionResponse)
async def create_version_endpoint(version: VersionCreate):
    """
    Create version snapshot.

    Creates version before applying change.
    """
    try:
        version_id = await version_manager.create_version(version)
        return VersionResponse(
            id=version_id,
            message="Version created successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/versions/{version_id}/rollback", response_model=dict)
async def rollback_version_endpoint(version_id: UUID, request: RollbackRequest):
    """
    Rollback version.

    Restores previous version.
    """
    try:
        success = await version_manager.rollback_version(
            version_id,
            request.reason,
            request.user_id,
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to rollback version")
        return {
            "version_id": str(version_id),
            "status": "rolled_back",
            "message": "Version rolled back successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions/{version_id}", response_model=VersionResponse)
async def get_version_endpoint(version_id: UUID):
    """Get version by ID"""
    version = await version_manager.get_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    return VersionResponse(
        id=version_id,
        message="Version retrieved",
        version=version
    )


@router.get("/versions", response_model=List[VersionResult])
async def list_versions_endpoint(
    workspace_id: Optional[UUID] = Query(None),
    version_type: Optional[VersionType] = Query(None),
    status: Optional[VersionStatus] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """List versions with filters"""
    return await version_manager.list_versions(
        workspace_id=workspace_id,
        version_type=version_type,
        status=status,
        limit=limit,
    )


@router.get("/versions/component/{workspace_id}/{version_type}/{component_name}")
async def get_component_versions_endpoint(
    workspace_id: UUID,
    version_type: VersionType,
    component_name: str,
):
    """Get all versions for a component"""
    return await version_manager.get_component_versions(
        workspace_id,
        version_type,
        component_name,
    )


@router.get("/versions/stats/{workspace_id}", response_model=StatsResponse)
async def get_version_stats_endpoint(workspace_id: UUID):
    """Get version statistics"""
    stats = await version_manager.get_version_stats(workspace_id)
    return StatsResponse(workspace_id=workspace_id, stats=stats)


@router.post("/snapshots/{workspace_id}", response_model=dict)
async def create_snapshot_endpoint(workspace_id: UUID):
    """
    Create system snapshot.

    Snapshots all components.
    """
    try:
        snapshot_versions = await version_manager.create_snapshot(workspace_id)
        return {
            "workspace_id": str(workspace_id),
            "snapshot_versions": {k: str(v) for k, v in snapshot_versions.items()},
            "message": "Snapshot created successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/snapshots/{workspace_id}/restore", response_model=dict)
async def restore_snapshot_endpoint(
    workspace_id: UUID,
    snapshot_date: str = Query(..., description="ISO format datetime"),
):
    """
    Restore system snapshot.

    Rolls back all components to snapshot date.
    """
    try:
        from datetime import datetime
        target_date = datetime.fromisoformat(snapshot_date.replace('Z', '+00:00'))

        success = await version_manager.restore_snapshot(workspace_id, target_date)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to restore snapshot")
        return {
            "workspace_id": str(workspace_id),
            "snapshot_date": snapshot_date,
            "status": "restored",
            "message": "Snapshot restored successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# DASHBOARD ENDPOINTS
# =============================================================================

@router.get("/dashboard/{workspace_id}")
async def get_evolution_dashboard(workspace_id: UUID):
    """
    Get self-evolution dashboard data.

    Returns comprehensive evolution metrics and status.
    """
    try:
        experience_stats = await experience_manager.get_experience_stats(workspace_id)
        improvement_stats = await improvement_manager.get_improvement_stats(workspace_id)
        version_stats = await version_manager.get_version_stats(workspace_id)

        recent_experiences = await experience_manager.list_experiences(
            workspace_id=workspace_id,
            limit=10,
        )

        recent_improvements = await improvement_manager.list_improvements(
            workspace_id=workspace_id,
            limit=10,
        )

        recent_versions = await version_manager.list_versions(
            workspace_id=workspace_id,
            limit=10,
        )

        return {
            "workspace_id": str(workspace_id),
            "experience_stats": experience_stats,
            "improvement_stats": improvement_stats,
            "version_stats": version_stats,
            "recent_experiences": [exp.dict() for exp in recent_experiences],
            "recent_improvements": [imp.dict() for imp in recent_improvements],
            "recent_versions": [ver.dict() for ver in recent_versions],
            "evolution_health": {
                "learning_rate": 0.0,
                "improvement_rate": 0.0,
                "success_rate": 0.0,
                "rollback_rate": 0.0,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
