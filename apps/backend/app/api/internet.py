"""
JARV Backend - Internet / Research API

Surfaces the safe internet tool registry, web/research source records, and asset
licence records so the dashboard can show what JARV fetched and used.
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.internet import internet_tools, APPROVED_ASSET_SOURCES
from app.models.memory import Memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools/internet", tags=["internet"])
research_router = APIRouter(prefix="/research", tags=["research"])
# Distinct prefix to avoid colliding with the existing /api/assets/{asset_id} route.
assets_lic_router = APIRouter(prefix="/asset-licences", tags=["assets-licences"])


@router.get("/list")
async def list_internet_tools() -> List[Dict[str, Any]]:
    """List the safe internet tools and their authority status."""
    return internet_tools()


@research_router.get("/records")
async def research_records(limit: int = 50, db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """Web/research source records (persisted as memory of type source/research)."""
    rows = (
        await db.execute(
            select(Memory)
            .where(or_(Memory.memory_type == "source", Memory.memory_type == "research"))
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(m.id),
            "type": m.memory_type,
            "content": m.content,
            "meta": m.meta_data or {},
            "task_id": str(m.task_id) if m.task_id else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


@assets_lic_router.get("/list")
async def asset_licences(limit: int = 50, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Asset licence/source records + the approved asset-source allowlist."""
    rows = (
        await db.execute(
            select(Memory).where(Memory.memory_type == "asset")
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
