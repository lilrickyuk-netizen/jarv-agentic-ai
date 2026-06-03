"""
JARV Backend - Memory API

RESTful API endpoints for agent memory management and retrieval.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

from app.core.database import get_db
from app.models.memory import Memory

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryInfo(BaseModel):
    id: str
    agent_id: str
    memory_type: str
    content: str
    summary: str | None
    importance_score: float
    access_count: int
    last_accessed_at: str | None
    session_id: str | None
    task_id: str | None
    context: dict | None
    expires_at: str | None
    is_permanent: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class MemoryStats(BaseModel):
    total_memories: int
    permanent_memories: int
    temporary_memories: int
    expired_memories: int
    by_type: dict[str, int]
    by_agent: dict[str, int]
    average_importance: float
    total_accesses: int
    most_accessed_memory_id: str | None


@router.get("/list", response_model=List[MemoryInfo])
async def list_memories(
    agent_id: Optional[UUID] = None,
    memory_type: Optional[str] = None,
    is_permanent: Optional[bool] = None,
    min_importance: Optional[float] = None,
    session_id: Optional[UUID] = None,
    task_id: Optional[UUID] = None,
    include_expired: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """
    List memories with optional filtering.

    Args:
        agent_id: Filter by agent
        memory_type: Filter by memory type
        is_permanent: Filter by permanent status
        min_importance: Minimum importance score
        session_id: Filter by session
        task_id: Filter by task
        include_expired: Include expired memories
        limit: Maximum number of memories to return

    Returns:
        List of memory records
    """
    query = select(Memory)

    if agent_id:
        query = query.where(Memory.agent_id == agent_id)
    if memory_type:
        query = query.where(Memory.memory_type == memory_type)
    if is_permanent is not None:
        query = query.where(Memory.is_permanent == is_permanent)
    if min_importance is not None:
        query = query.where(Memory.importance_score >= min_importance)
    if session_id:
        query = query.where(Memory.session_id == session_id)
    if task_id:
        query = query.where(Memory.task_id == task_id)

    if not include_expired:
        # Exclude expired memories
        query = query.where(
            (Memory.expires_at == None) | (Memory.expires_at > datetime.now())
        )

    query = query.order_by(Memory.importance_score.desc(), Memory.created_at.desc()).limit(limit)

    result = db.execute(query)
    memories = result.scalars().all()

    return [
        MemoryInfo(
            id=str(memory.id),
            agent_id=str(memory.agent_id),
            memory_type=memory.memory_type,
            content=memory.content,
            summary=memory.summary,
            importance_score=memory.importance_score,
            access_count=memory.access_count,
            last_accessed_at=memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
            session_id=str(memory.session_id) if memory.session_id else None,
            task_id=str(memory.task_id) if memory.task_id else None,
            context=memory.context,
            expires_at=memory.expires_at.isoformat() if memory.expires_at else None,
            is_permanent=memory.is_permanent,
            created_at=memory.created_at.isoformat() if memory.created_at else datetime.now().isoformat(),
            updated_at=memory.updated_at.isoformat() if memory.updated_at else datetime.now().isoformat(),
        )
        for memory in memories
    ]


@router.get("/{memory_id}", response_model=MemoryInfo)
async def get_memory(
    memory_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific memory.

    Args:
        memory_id: UUID of the memory

    Returns:
        Memory information
    """
    query = select(Memory).where(Memory.id == memory_id)
    result = db.execute(query)
    memory = result.scalar_one_or_none()

    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Update access count
    memory.access_count += 1
    memory.last_accessed_at = datetime.now()
    db.commit()

    return MemoryInfo(
        id=str(memory.id),
        agent_id=str(memory.agent_id),
        memory_type=memory.memory_type,
        content=memory.content,
        summary=memory.summary,
        importance_score=memory.importance_score,
        access_count=memory.access_count,
        last_accessed_at=memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
        session_id=str(memory.session_id) if memory.session_id else None,
        task_id=str(memory.task_id) if memory.task_id else None,
        context=memory.context,
        expires_at=memory.expires_at.isoformat() if memory.expires_at else None,
        is_permanent=memory.is_permanent,
        created_at=memory.created_at.isoformat() if memory.created_at else datetime.now().isoformat(),
        updated_at=memory.updated_at.isoformat() if memory.updated_at else datetime.now().isoformat(),
    )


@router.get("/stats", response_model=MemoryStats)
async def get_memory_stats(
    agent_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    Get aggregated statistics for memories.

    Args:
        agent_id: Optional agent filter

    Returns:
        Memory statistics including counts and metrics
    """
    query = select(Memory)
    if agent_id:
        query = query.where(Memory.agent_id == agent_id)

    result = db.execute(query)
    all_memories = result.scalars().all()

    # Calculate statistics
    total_memories = len(all_memories)
    permanent_memories = sum(1 for m in all_memories if m.is_permanent)
    temporary_memories = total_memories - permanent_memories

    # Count expired memories
    now = datetime.now()
    expired_memories = sum(
        1 for m in all_memories
        if m.expires_at and m.expires_at <= now
    )

    # By type
    by_type: dict[str, int] = {}
    for memory in all_memories:
        by_type[memory.memory_type] = by_type.get(memory.memory_type, 0) + 1

    # By agent
    by_agent: dict[str, int] = {}
    for memory in all_memories:
        agent_key = str(memory.agent_id)
        by_agent[agent_key] = by_agent.get(agent_key, 0) + 1

    # Average importance
    importance_values = [m.importance_score for m in all_memories]
    average_importance = sum(importance_values) / len(importance_values) if importance_values else 0.0

    # Total accesses
    total_accesses = sum(m.access_count for m in all_memories)

    # Most accessed memory
    most_accessed = max(all_memories, key=lambda m: m.access_count) if all_memories else None
    most_accessed_memory_id = str(most_accessed.id) if most_accessed else None

    return MemoryStats(
        total_memories=total_memories,
        permanent_memories=permanent_memories,
        temporary_memories=temporary_memories,
        expired_memories=expired_memories,
        by_type=by_type,
        by_agent=by_agent,
        average_importance=round(average_importance, 2),
        total_accesses=total_accesses,
        most_accessed_memory_id=most_accessed_memory_id,
    )


@router.get("/agent/{agent_id}/recent", response_model=List[MemoryInfo])
async def get_agent_recent_memories(
    agent_id: UUID,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Get recent memories for a specific agent.

    Args:
        agent_id: UUID of the agent
        limit: Number of recent memories to return

    Returns:
        List of recent memory records
    """
    query = (
        select(Memory)
        .where(Memory.agent_id == agent_id)
        .where((Memory.expires_at == None) | (Memory.expires_at > datetime.now()))
        .order_by(Memory.created_at.desc())
        .limit(limit)
    )

    result = db.execute(query)
    memories = result.scalars().all()

    return [
        MemoryInfo(
            id=str(memory.id),
            agent_id=str(memory.agent_id),
            memory_type=memory.memory_type,
            content=memory.content,
            summary=memory.summary,
            importance_score=memory.importance_score,
            access_count=memory.access_count,
            last_accessed_at=memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
            session_id=str(memory.session_id) if memory.session_id else None,
            task_id=str(memory.task_id) if memory.task_id else None,
            context=memory.context,
            expires_at=memory.expires_at.isoformat() if memory.expires_at else None,
            is_permanent=memory.is_permanent,
            created_at=memory.created_at.isoformat() if memory.created_at else datetime.now().isoformat(),
            updated_at=memory.updated_at.isoformat() if memory.updated_at else datetime.now().isoformat(),
        )
        for memory in memories
    ]


@router.get("/important", response_model=List[MemoryInfo])
async def get_important_memories(
    min_importance: float = 0.7,
    limit: int = 20,
    agent_id: Optional[UUID] = None,
    db: Session = Depends(get_db)
):
    """
    Get high-importance memories across agents or for a specific agent.

    Args:
        min_importance: Minimum importance score (default 0.7)
        limit: Maximum number of memories to return
        agent_id: Optional agent filter

    Returns:
        List of important memory records
    """
    query = (
        select(Memory)
        .where(Memory.importance_score >= min_importance)
        .where((Memory.expires_at == None) | (Memory.expires_at > datetime.now()))
    )

    if agent_id:
        query = query.where(Memory.agent_id == agent_id)

    query = query.order_by(Memory.importance_score.desc()).limit(limit)

    result = db.execute(query)
    memories = result.scalars().all()

    return [
        MemoryInfo(
            id=str(memory.id),
            agent_id=str(memory.agent_id),
            memory_type=memory.memory_type,
            content=memory.content,
            summary=memory.summary,
            importance_score=memory.importance_score,
            access_count=memory.access_count,
            last_accessed_at=memory.last_accessed_at.isoformat() if memory.last_accessed_at else None,
            session_id=str(memory.session_id) if memory.session_id else None,
            task_id=str(memory.task_id) if memory.task_id else None,
            context=memory.context,
            expires_at=memory.expires_at.isoformat() if memory.expires_at else None,
            is_permanent=memory.is_permanent,
            created_at=memory.created_at.isoformat() if memory.created_at else datetime.now().isoformat(),
            updated_at=memory.updated_at.isoformat() if memory.updated_at else datetime.now().isoformat(),
        )
        for memory in memories
    ]
