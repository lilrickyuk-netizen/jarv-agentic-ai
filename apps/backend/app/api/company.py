"""
JARV Backend - Company Operations API

RESTful API endpoints for company organizational structure, roles, and operations.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.models.company import CompanyRole

router = APIRouter(prefix="/api/company", tags=["company"])


class RoleInfo(BaseModel):
    id: str
    workspace_id: str
    role_name: str
    role_type: str
    department: str
    description: str | None
    responsibilities: List[str]
    kpis: Dict[str, Any]
    authority_level: int
    is_active: bool
    is_automated: bool
    parent_role_id: str | None
    total_agents: int
    active_agents: int
    tasks_completed: int
    tasks_failed: int
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class CompanyStats(BaseModel):
    total_roles: int
    active_roles: int
    automated_roles: int
    total_departments: int
    total_agents_assigned: int
    total_tasks_completed: int
    tasks_failed: int
    by_department: Dict[str, Dict[str, int]]
    by_role_type: Dict[str, int]


class DepartmentInfo(BaseModel):
    department: str
    total_roles: int
    active_roles: int
    total_agents: int
    tasks_completed: int


@router.get("/roles/list", response_model=List[RoleInfo])
async def list_company_roles(
    workspace_id: Optional[UUID] = None,
    department: Optional[str] = None,
    role_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    is_automated: Optional[bool] = None,
    db: Session = Depends(get_db)
):
    """
    List all company roles with optional filtering.

    Args:
        workspace_id: Filter by workspace
        department: Filter by department
        role_type: Filter by role type
        is_active: Filter by active status
        is_automated: Filter by automation status

    Returns:
        List of company roles with full details
    """
    query = select(CompanyRole)

    if workspace_id:
        query = query.where(CompanyRole.workspace_id == workspace_id)
    if department:
        query = query.where(CompanyRole.department == department)
    if role_type:
        query = query.where(CompanyRole.role_type == role_type)
    if is_active is not None:
        query = query.where(CompanyRole.is_active == is_active)
    if is_automated is not None:
        query = query.where(CompanyRole.is_automated == is_automated)

    query = query.order_by(CompanyRole.department, CompanyRole.role_name)

    result = db.execute(query)
    roles = result.scalars().all()

    return [
        RoleInfo(
            id=str(role.id),
            workspace_id=str(role.workspace_id),
            role_name=role.role_name,
            role_type=role.role_type,
            department=role.department,
            description=role.description,
            responsibilities=role.responsibilities or [],
            kpis=role.kpis or {},
            authority_level=role.authority_level,
            is_active=role.is_active,
            is_automated=role.is_automated,
            parent_role_id=str(role.parent_role_id) if role.parent_role_id else None,
            total_agents=role.total_agents,
            active_agents=role.active_agents,
            tasks_completed=role.tasks_completed,
            tasks_failed=role.tasks_failed,
            created_at=role.created_at.isoformat() if role.created_at else datetime.now().isoformat(),
            updated_at=role.updated_at.isoformat() if role.updated_at else datetime.now().isoformat(),
        )
        for role in roles
    ]


@router.get("/roles/{role_id}", response_model=RoleInfo)
async def get_company_role(
    role_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific company role.

    Args:
        role_id: UUID of the role

    Returns:
        Role information with full details
    """
    query = select(CompanyRole).where(CompanyRole.id == role_id)
    result = db.execute(query)
    role = result.scalar_one_or_none()

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    return RoleInfo(
        id=str(role.id),
        workspace_id=str(role.workspace_id),
        role_name=role.role_name,
        role_type=role.role_type,
        department=role.department,
        description=role.description,
        responsibilities=role.responsibilities or [],
        kpis=role.kpis or {},
        authority_level=role.authority_level,
        is_active=role.is_active,
        is_automated=role.is_automated,
        parent_role_id=str(role.parent_role_id) if role.parent_role_id else None,
        total_agents=role.total_agents,
        active_agents=role.active_agents,
        tasks_completed=role.tasks_completed,
        tasks_failed=role.tasks_failed,
        created_at=role.created_at.isoformat() if role.created_at else datetime.now().isoformat(),
        updated_at=role.updated_at.isoformat() if role.updated_at else datetime.now().isoformat(),
    )


@router.get("/stats", response_model=CompanyStats)
async def get_company_stats(
    workspace_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    Get aggregated statistics for company operations.

    Args:
        workspace_id: Optional workspace filter

    Returns:
        Company statistics including role counts, departments, and performance metrics
    """
    query = select(CompanyRole)
    if workspace_id:
        query = query.where(CompanyRole.workspace_id == workspace_id)

    result = db.execute(query)
    all_roles = result.scalars().all()

    # Calculate statistics
    total_roles = len(all_roles)
    active_roles = sum(1 for role in all_roles if role.is_active)
    automated_roles = sum(1 for role in all_roles if role.is_automated)
    total_agents_assigned = sum(role.total_agents for role in all_roles)
    total_tasks_completed = sum(role.tasks_completed for role in all_roles)
    tasks_failed = sum(role.tasks_failed for role in all_roles)

    # Get unique departments
    departments = set(role.department for role in all_roles if role.department)
    total_departments = len(departments)

    # By department statistics
    by_department: Dict[str, Dict[str, int]] = {}
    for role in all_roles:
        dept = role.department or "Unassigned"
        if dept not in by_department:
            by_department[dept] = {
                "total_roles": 0,
                "active_roles": 0,
                "total_agents": 0,
                "tasks_completed": 0,
            }
        by_department[dept]["total_roles"] += 1
        if role.is_active:
            by_department[dept]["active_roles"] += 1
        by_department[dept]["total_agents"] += role.total_agents
        by_department[dept]["tasks_completed"] += role.tasks_completed

    # By role type statistics
    by_role_type: Dict[str, int] = {}
    for role in all_roles:
        role_type = role.role_type or "other"
        by_role_type[role_type] = by_role_type.get(role_type, 0) + 1

    return CompanyStats(
        total_roles=total_roles,
        active_roles=active_roles,
        automated_roles=automated_roles,
        total_departments=total_departments,
        total_agents_assigned=total_agents_assigned,
        total_tasks_completed=total_tasks_completed,
        tasks_failed=tasks_failed,
        by_department=by_department,
        by_role_type=by_role_type,
    )


@router.get("/departments", response_model=List[DepartmentInfo])
async def list_departments(
    workspace_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    List all departments with aggregated statistics.

    Args:
        workspace_id: Optional workspace filter

    Returns:
        List of departments with role and performance statistics
    """
    query = select(CompanyRole)
    if workspace_id:
        query = query.where(CompanyRole.workspace_id == workspace_id)

    result = db.execute(query)
    all_roles = result.scalars().all()

    # Group by department
    dept_stats: Dict[str, DepartmentInfo] = {}
    for role in all_roles:
        dept = role.department or "Unassigned"
        if dept not in dept_stats:
            dept_stats[dept] = DepartmentInfo(
                department=dept,
                total_roles=0,
                active_roles=0,
                total_agents=0,
                tasks_completed=0,
            )

        dept_stats[dept].total_roles += 1
        if role.is_active:
            dept_stats[dept].active_roles += 1
        dept_stats[dept].total_agents += role.total_agents
        dept_stats[dept].tasks_completed += role.tasks_completed

    return sorted(dept_stats.values(), key=lambda x: x.total_roles, reverse=True)


@router.get("/hierarchy", response_model=List[Dict[str, Any]])
async def get_role_hierarchy(
    workspace_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    Get organizational role hierarchy.

    Args:
        workspace_id: Optional workspace filter

    Returns:
        Hierarchical structure of roles with parent-child relationships
    """
    query = select(CompanyRole)
    if workspace_id:
        query = query.where(CompanyRole.workspace_id == workspace_id)

    result = db.execute(query)
    all_roles = result.scalars().all()

    # Build role lookup
    role_map = {str(role.id): role for role in all_roles}

    # Build hierarchy (roles without parents are top-level)
    def build_node(role: CompanyRole) -> Dict[str, Any]:
        children = [
            build_node(child)
            for child in all_roles
            if child.parent_role_id and str(child.parent_role_id) == str(role.id)
        ]

        return {
            "id": str(role.id),
            "role_name": role.role_name,
            "role_type": role.role_type,
            "department": role.department,
            "is_active": role.is_active,
            "total_agents": role.total_agents,
            "children": children,
        }

    # Get top-level roles (no parent)
    top_level = [role for role in all_roles if not role.parent_role_id]

    return [build_node(role) for role in top_level]
