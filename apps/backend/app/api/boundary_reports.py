"""
JARV Backend - Boundary Reports API

RESTful API endpoints for boundary violation reports.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.models.boundary import BoundaryReport

router = APIRouter(prefix="/api/boundary-reports", tags=["boundary-reports"])


class BoundaryReportInfo(BaseModel):
    id: str
    session_id: str
    agent_id: str
    report_type: str
    severity: str
    title: str
    description: str
    boundary_type: str
    attempted_action: str
    authority_level_required: int
    authority_level_available: int
    context: dict
    was_blocked: bool
    action_taken: str
    resolution: str | None
    approval_requested: bool
    approval_id: str | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class BoundaryReportStats(BaseModel):
    total_reports: int
    blocked_actions: int
    by_severity: dict[str, int]
    by_type: dict[str, int]
    approval_request_rate: float


@router.get("/list", response_model=List[BoundaryReportInfo])
async def list_boundary_reports(
    severity: Optional[str] = None,
    report_type: Optional[str] = None,
    was_blocked: Optional[bool] = None,
    approval_requested: Optional[bool] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    List boundary reports with optional filtering.
    """
    query = select(BoundaryReport)

    if severity:
        query = query.where(BoundaryReport.severity == severity)
    if report_type:
        query = query.where(BoundaryReport.report_type == report_type)
    if was_blocked is not None:
        query = query.where(BoundaryReport.was_blocked == was_blocked)
    if approval_requested is not None:
        query = query.where(BoundaryReport.approval_requested == approval_requested)

    query = query.order_by(BoundaryReport.created_at.desc()).limit(limit)

    result = await db.execute(query)
    reports = result.scalars().all()

    return [
        BoundaryReportInfo(
            id=str(report.id),
            session_id=str(report.session_id),
            agent_id=str(report.agent_id),
            report_type=report.report_type,
            severity=report.severity,
            title=report.title,
            description=report.description,
            boundary_type=report.boundary_type,
            attempted_action=report.attempted_action,
            authority_level_required=report.authority_level_required,
            authority_level_available=report.authority_level_available,
            context=report.context,
            was_blocked=report.was_blocked,
            action_taken=report.action_taken,
            resolution=report.resolution,
            approval_requested=report.approval_requested,
            approval_id=str(report.approval_id) if report.approval_id else None,
            created_at=report.created_at.isoformat() if report.created_at else datetime.now().isoformat(),
            updated_at=report.updated_at.isoformat() if report.updated_at else datetime.now().isoformat(),
        )
        for report in reports
    ]


@router.get("/stats", response_model=BoundaryReportStats)
async def get_boundary_report_stats(db: Session = Depends(get_db)):
    """
    Get aggregated statistics for boundary reports.
    """
    result = await db.execute(select(BoundaryReport))
    all_reports = result.scalars().all()

    total_reports = len(all_reports)
    blocked_actions = sum(1 for r in all_reports if r.was_blocked)

    by_severity: dict[str, int] = {}
    for report in all_reports:
        by_severity[report.severity] = by_severity.get(report.severity, 0) + 1

    by_type: dict[str, int] = {}
    for report in all_reports:
        by_type[report.report_type] = by_type.get(report.report_type, 0) + 1

    approval_requests = sum(1 for r in all_reports if r.approval_requested)
    approval_request_rate = (approval_requests / total_reports) if total_reports > 0 else 0.0

    return BoundaryReportStats(
        total_reports=total_reports,
        blocked_actions=blocked_actions,
        by_severity=by_severity,
        by_type=by_type,
        approval_request_rate=round(approval_request_rate, 2),
    )
