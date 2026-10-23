"""Authenticated access to the versioned specialist knowledge corpus."""
from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agents.registry import get_registry
from app.core.auth import CurrentUserId
from app.core.database import get_db
from app.core.knowledge.catalog import specialist_knowledge
from app.core.knowledge.service import knowledge_service
from app.models.user import User


router = APIRouter(prefix="/knowledge", tags=["agent-knowledge"])


class KnowledgeRevisionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    content: str = Field(..., min_length=1, max_length=12000)
    keywords: List[str] = Field(..., min_length=1, max_length=30)
    source_url: HttpUrl
    source_title: str = Field(..., min_length=1, max_length=500)
    source_publisher: str = Field(..., min_length=1, max_length=200)
    source_license: str | None = Field(None, max_length=100)
    source_author: str | None = Field(None, max_length=255)
    source_author_url: HttpUrl | None = None
    verified_at: datetime


async def _require_admin(db: AsyncSession, user_id) -> None:
    is_admin = (await db.execute(select(User.is_admin).where(
        User.id == UUID(str(user_id)))))\
        .scalar_one_or_none()
    if is_admin is not True:
        raise HTTPException(status_code=403, detail="Administrator access is required")


@router.get("/agents/{agent_name}")
async def retrieve_agent_knowledge(
    agent_name: str,
    user_id: CurrentUserId,
    query: str = Query(..., min_length=1, max_length=4000),
    db: AsyncSession = Depends(get_db),
):
    if not get_registry().is_implemented(agent_name):
        raise HTTPException(status_code=404, detail="Unknown agent")
    records = await knowledge_service.retrieve(db, agent_name=agent_name, query=query)
    return {"agent_name": agent_name, "query": query, "records": records,
            "count": len(records)}


@router.post("/catalog/install")
async def install_curated_knowledge(
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(db, user_id)
    result = await knowledge_service.ingest(db, specialist_knowledge())
    return {"status": "installed", **result}


@router.put("/agents/{agent_name}/{knowledge_key}")
async def revise_agent_knowledge(
    agent_name: str,
    knowledge_key: str,
    revision: KnowledgeRevisionRequest,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin(db, user_id)
    try:
        record = await knowledge_service.revise(
            db,
            agent_name=agent_name,
            knowledge_key=knowledge_key,
            title=revision.title,
            content=revision.content,
            keywords=revision.keywords,
            source_url=str(revision.source_url),
            source_title=revision.source_title,
            source_publisher=revision.source_publisher,
            verified_at=revision.verified_at,
            source_license=revision.source_license,
            source_author=revision.source_author,
            source_author_url=(str(revision.source_author_url)
                               if revision.source_author_url else None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "agent_name": record.agent_name,
        "knowledge_key": record.knowledge_key,
        "version": record.version,
        "active": record.is_active,
        "source_url": record.source_url,
        "source_title": record.source_title,
        "source_license": record.source_license,
        "source_author": record.source_author,
        "source_author_url": record.source_author_url,
        "verified_at": record.verified_at.isoformat(),
        "content_sha256": record.content_sha256,
    }