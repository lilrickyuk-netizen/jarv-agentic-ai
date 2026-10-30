"""
JARV Backend - Internet / Research API

Surfaces the safe internet tool registry, web/research source records, and asset
licence records so the dashboard can show what JARV fetched and used.
"""
import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends
from app.core.auth import get_current_user_id
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import CurrentUserId
from app.core.internet import internet_tools, APPROVED_ASSET_SOURCES
from app.models.memory import Memory
from app.models.agent_knowledge import AgentKnowledge
from app.models.agent import Agent
from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools/internet", tags=["internet"], dependencies=[Depends(get_current_user_id)])
research_router = APIRouter(prefix="/research", tags=["research"], dependencies=[Depends(get_current_user_id)])
# Distinct prefix to avoid colliding with the existing /api/assets/{asset_id} route.
assets_lic_router = APIRouter(prefix="/asset-licences", tags=["assets-licences"], dependencies=[Depends(get_current_user_id)])


@router.get("/list")
async def list_internet_tools() -> List[Dict[str, Any]]:
    """List the safe internet tools and their authority status."""
    return internet_tools()


@research_router.get("/records")
async def research_records(
    user_id: CurrentUserId,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return persisted source memories and attributed ResearchAgent results."""
    owner_id = UUID(str(user_id))
    memory_rows = (
        await db.execute(
            select(Memory)
            .join(Agent, Memory.agent_id == Agent.id)
            .join(Workspace, Agent.workspace_id == Workspace.id)
            .where(or_(Memory.memory_type == "source", Memory.memory_type == "research"))
            .where(Workspace.owner_id == owner_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    knowledge_rows = (
        await db.execute(
            select(AgentKnowledge)
            .where(
                AgentKnowledge.agent_name == "research",
                AgentKnowledge.knowledge_key.startswith("public-source-"),
                AgentKnowledge.is_active.is_(True),
            )
            .order_by(AgentKnowledge.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    memories = [
        {
            "id": str(m.id),
            "type": m.memory_type,
            "content": m.content,
            "meta": m.meta_data or {},
            "task_id": str(m.task_id) if m.task_id else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in memory_rows
    ]
    sources = [{
        "id": str(row.id),
        "type": "public_research",
        "content": row.content,
        "meta": {
            "title": row.title,
            "source_url": row.source_url,
            "source_title": row.source_title,
            "source_publisher": row.source_publisher,
            "source_license": row.source_license,
            "source_author": row.source_author,
            "source_author_url": row.source_author_url,
            "verified_at": row.verified_at.isoformat(),
            "version": row.version,
            "content_sha256": row.content_sha256,
        },
        "task_id": None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    } for row in knowledge_rows]
    return sorted(memories + sources, key=lambda record: record["created_at"] or "",
                  reverse=True)[:limit]


@assets_lic_router.get("/list")
async def asset_licences(
    user_id: CurrentUserId,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Asset licence/source records + the approved asset-source allowlist."""
    owner_id = UUID(str(user_id))
    rows = (
        await db.execute(
            select(Memory)
            .join(Agent, Memory.agent_id == Agent.id)
            .join(Workspace, Agent.workspace_id == Workspace.id)
            .where(Memory.memory_type == "asset", Workspace.owner_id == owner_id)
            .order_by(Memory.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return {
        "approved_sources": sorted(APPROVED_ASSET_SOURCES),
        "records": [
            {"id": str(m.id), "content": m.content, "meta": m.meta_data or {},
             "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in rows
        ],
    }
