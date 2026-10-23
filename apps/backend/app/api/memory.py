"""
JARV Backend - Memory API

Authenticated memory endpoints. Every call is limited to workspaces the caller
owns; global memories (no workspace) are readable but only workspace memories
can be changed.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.core.jarv_memory import memory_service
from app.core.memory.taxonomy import MEMORY_CATEGORIES
from app.models.agent import Agent
from app.models.memory import Memory
from app.models.workspace import Workspace

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryInfo(BaseModel):
    id: str
    agent_id: str
    workspace_id: str | None
    memory_type: str
    memory_category: str
    content: str
    summary: str | None
    importance_score: float
    confidence_score: float
    source_ref: str | None
    version: int
    embedding_model: str | None
    access_count: int
    last_accessed_at: str | None
    session_id: str | None
    task_id: str | None
    parent_agent_id: str | None
    sub_agent_id: str | None
    approval_id: str | None
    checkpoint_id: str | None
    boundary_input_id: str | None
    context: dict | None
    expires_at: str | None
    is_permanent: bool
    created_at: str
    updated_at: str
    score: float | None = None


class MemoryStats(BaseModel):
    total_memories: int
    permanent_memories: int
    temporary_memories: int
    expired_memories: int
    embedded_memories: int
    by_type: dict[str, int]
    by_category: dict[str, int]
    by_agent: dict[str, int]
    average_importance: float
    total_accesses: int
    most_accessed_memory_id: str | None


class MemoryCreate(BaseModel):
    workspace_id: UUID
    content: str = Field(..., min_length=1, max_length=50000)
    memory_type: str = Field("fact", max_length=50)
    category: Optional[str] = None
    summary: Optional[str] = Field(None, max_length=1000)
    importance_score: float = Field(0.6, ge=0.0, le=1.0)
    confidence_score: float = Field(0.5, ge=0.0, le=1.0)
    source_ref: Optional[str] = Field(None, max_length=255)
    task_id: Optional[UUID] = None
    is_permanent: bool = True
    meta: Dict[str, Any] = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    content: Optional[str] = Field(None, min_length=1, max_length=50000)
    summary: Optional[str] = Field(None, max_length=1000)
    importance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    category: Optional[str] = None
    is_permanent: Optional[bool] = None
    meta: Optional[Dict[str, Any]] = None


class MemorySearch(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    workspace_id: UUID
    categories: Optional[List[str]] = None
    task_id: Optional[UUID] = None
    limit: int = Field(10, ge=1, le=50)
    include_global: bool = True


class LinkTask(BaseModel):
    task_id: UUID


class LinkWorkspace(BaseModel):
    workspace_id: UUID


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _uuid(value: Any) -> Optional[str]:
    return str(value) if value else None


def _info(memory: Memory, score: Optional[float] = None) -> MemoryInfo:
    now = datetime.now(timezone.utc).isoformat()
    return MemoryInfo(
        id=str(memory.id), agent_id=str(memory.agent_id), workspace_id=_uuid(memory.workspace_id),
        memory_type=memory.memory_type, memory_category=memory.memory_category or "global",
        content=memory.content, summary=memory.summary,
        importance_score=memory.importance_score, confidence_score=memory.confidence_score or 0.0,
        source_ref=memory.source_ref, version=memory.version or 1,
        embedding_model=memory.embedding_model, access_count=memory.access_count or 0,
        last_accessed_at=_iso(memory.last_accessed_at), session_id=_uuid(memory.session_id),
        task_id=_uuid(memory.task_id), parent_agent_id=_uuid(memory.parent_agent_id),
        sub_agent_id=_uuid(memory.sub_agent_id), approval_id=_uuid(memory.approval_id),
        checkpoint_id=_uuid(memory.checkpoint_id), boundary_input_id=_uuid(memory.boundary_input_id),
        context=memory.context, expires_at=_iso(memory.expires_at), is_permanent=memory.is_permanent,
        created_at=_iso(memory.created_at) or now, updated_at=_iso(memory.updated_at) or now,
        score=round(score, 4) if score is not None else None,
    )


async def _owned_workspaces(db: AsyncSession, user_id: str) -> List[UUID]:
    return list((await db.execute(
        select(Workspace.id).where(Workspace.owner_id == UUID(str(user_id)))
    )).scalars().all())


async def _require_workspace(db: AsyncSession, user_id: str, workspace_id: UUID) -> UUID:
    if workspace_id not in await _owned_workspaces(db, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace_id


def _visible(owned: List[UUID]):
    """Memories in the caller's workspaces, plus workspace-less rows owned by an
    agent in one of those workspaces. Nothing is visible across owners."""
    if not owned:
        return Memory.id.is_(None)
    owned_agents = select(Agent.id).where(Agent.workspace_id.in_(owned))
    return or_(Memory.workspace_id.in_(owned),
               and_(Memory.workspace_id.is_(None), Memory.agent_id.in_(owned_agents)))


async def _owned_memory(db: AsyncSession, user_id: str, memory_id: UUID) -> Memory:
    """A memory the caller may change: it must belong to one of their workspaces."""
    owned = await _owned_workspaces(db, user_id)
    memory = (await db.execute(select(Memory).where(Memory.id == memory_id))).scalar_one_or_none()
    if memory is None or memory.workspace_id not in owned:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.get("/categories", response_model=List[str])
async def list_categories(user_id: CurrentUserId) -> List[str]:
    return list(MEMORY_CATEGORIES)


@router.get("/list", response_model=List[MemoryInfo])
async def list_memories(
    user_id: CurrentUserId,
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    memory_type: Optional[str] = None,
    category: Optional[str] = None,
    is_permanent: Optional[bool] = None,
    min_importance: Optional[float] = None,
    session_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    include_expired: bool = False,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned_workspaces(db, user_id)
    query = select(Memory).where(_visible(owned))
    if workspace_id:
        await _require_workspace(db, user_id, workspace_id)
        query = query.where(Memory.workspace_id == workspace_id)
    if agent_id:
        query = query.where(Memory.agent_id == agent_id)
    if memory_type:
        query = query.where(Memory.memory_type == memory_type)
    if category:
        query = query.where(Memory.memory_category == category)
    if is_permanent is not None:
        query = query.where(Memory.is_permanent == is_permanent)
    if min_importance is not None:
        query = query.where(Memory.importance_score >= min_importance)
    if session_id:
        query = query.where(Memory.session_id == session_id)
    if task_id:
        query = query.where(Memory.task_id == task_id)
    if not include_expired:
        query = query.where(or_(Memory.expires_at.is_(None),
                                Memory.expires_at > datetime.now(timezone.utc)))
    query = query.order_by(Memory.importance_score.desc(), Memory.created_at.desc()).limit(limit)
    return [_info(m) for m in (await db.execute(query)).scalars().all()]


@router.get("/stats", response_model=MemoryStats)
async def get_memory_stats(
    user_id: CurrentUserId,
    workspace_id: Optional[UUID] = None,
    agent_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned_workspaces(db, user_id)
    query = select(Memory).where(_visible(owned))
    if workspace_id:
        await _require_workspace(db, user_id, workspace_id)
        query = query.where(Memory.workspace_id == workspace_id)
    if agent_id:
        query = query.where(Memory.agent_id == agent_id)
    rows = (await db.execute(query)).scalars().all()
    now = datetime.now(timezone.utc)

    def expired(m: Memory) -> bool:
        if not m.expires_at:
            return False
        expires = m.expires_at if m.expires_at.tzinfo else m.expires_at.replace(tzinfo=timezone.utc)
        return expires <= now

    by_type: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    for m in rows:
        by_type[m.memory_type] = by_type.get(m.memory_type, 0) + 1
        by_category[m.memory_category or "global"] = by_category.get(m.memory_category or "global", 0) + 1
        by_agent[str(m.agent_id)] = by_agent.get(str(m.agent_id), 0) + 1
    most = max(rows, key=lambda m: m.access_count or 0) if rows else None
    total = len(rows)
    return MemoryStats(
        total_memories=total,
        permanent_memories=sum(1 for m in rows if m.is_permanent),
        temporary_memories=sum(1 for m in rows if not m.is_permanent),
        expired_memories=sum(1 for m in rows if expired(m)),
        embedded_memories=sum(1 for m in rows if m.embedding_model),
        by_type=by_type, by_category=by_category, by_agent=by_agent,
        average_importance=round(sum(m.importance_score for m in rows) / total, 2) if total else 0.0,
        total_accesses=sum(m.access_count or 0 for m in rows),
        most_accessed_memory_id=str(most.id) if most else None,
    )


@router.post("/search", response_model=List[MemoryInfo])
async def search_memories(body: MemorySearch, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _require_workspace(db, user_id, body.workspace_id)
    try:
        hits = await memory_service.search_scored(
            db, body.query, limit=body.limit, workspace_id=body.workspace_id,
            categories=body.categories, task_id=body.task_id, include_global=body.include_global,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return [_info(hit.memory, hit.score) for hit in hits]


@router.post("", response_model=MemoryInfo, status_code=201)
async def create_memory(body: MemoryCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    await _require_workspace(db, user_id, body.workspace_id)
    try:
        memory = await memory_service.add(
            db, content=body.content, memory_type=body.memory_type, category=body.category,
            workspace_id=body.workspace_id, task_id=body.task_id, importance=body.importance_score,
            confidence=body.confidence_score, summary=body.summary, source_ref=body.source_ref,
            permanent=body.is_permanent, meta={**body.meta, "created_by": "memory_api", "user_id": user_id},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _info(memory)


@router.get("/agent/{agent_id}/recent", response_model=List[MemoryInfo])
async def get_agent_recent_memories(
    agent_id: UUID, user_id: CurrentUserId, limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned_workspaces(db, user_id)
    rows = (await db.execute(
        select(Memory).where(Memory.agent_id == agent_id, _visible(owned),
                             or_(Memory.expires_at.is_(None), Memory.expires_at > datetime.now(timezone.utc)))
        .order_by(Memory.created_at.desc()).limit(limit)
    )).scalars().all()
    return [_info(m) for m in rows]


@router.get("/important", response_model=List[MemoryInfo])
async def get_important_memories(
    user_id: CurrentUserId,
    min_importance: float = 0.7,
    limit: int = Query(20, ge=1, le=200),
    agent_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db),
):
    owned = await _owned_workspaces(db, user_id)
    query = select(Memory).where(
        _visible(owned), Memory.importance_score >= min_importance,
        or_(Memory.expires_at.is_(None), Memory.expires_at > datetime.now(timezone.utc)),
    )
    if agent_id:
        query = query.where(Memory.agent_id == agent_id)
    rows = (await db.execute(query.order_by(Memory.importance_score.desc()).limit(limit))).scalars().all()
    return [_info(m) for m in rows]


@router.patch("/{memory_id}", response_model=MemoryInfo)
async def update_memory(
    memory_id: UUID, body: MemoryUpdate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    memory = await _owned_memory(db, user_id, memory_id)
    try:
        updated = await memory_service.update(
            db, memory.id, memory.workspace_id, content=body.content, summary=body.summary,
            importance=body.importance_score, confidence=body.confidence_score,
            category=body.category, meta=body.meta, permanent=body.is_permanent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _info(updated)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    memory = await _owned_memory(db, user_id, memory_id)
    await memory_service.delete(db, memory.id, memory.workspace_id)


@router.post("/{memory_id}/link-task", response_model=MemoryInfo)
async def link_memory_to_task(
    memory_id: UUID, body: LinkTask, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    memory = await _owned_memory(db, user_id, memory_id)
    try:
        linked = await memory_service.link_to_task(db, memory.id, memory.workspace_id, body.task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return _info(linked)


@router.post("/{memory_id}/link-workspace", response_model=MemoryInfo)
async def link_memory_to_workspace(
    memory_id: UUID, body: LinkWorkspace, user_id: CurrentUserId, db: AsyncSession = Depends(get_db),
):
    await _require_workspace(db, user_id, body.workspace_id)
    try:
        linked = await memory_service.link_to_workspace(db, memory_id, body.workspace_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if linked is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return _info(linked)


# Dynamic single-segment route declared last so it does not shadow the static routes.
@router.get("/{memory_id}", response_model=MemoryInfo)
async def get_memory(memory_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)):
    owned = await _owned_workspaces(db, user_id)
    memory = (await db.execute(
        select(Memory).where(Memory.id == memory_id, _visible(owned))
    )).scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    memory.access_count = (memory.access_count or 0) + 1
    memory.last_accessed_at = datetime.now(timezone.utc)
    memory.updated_at = memory.last_accessed_at
    await db.flush()
    return _info(memory)
