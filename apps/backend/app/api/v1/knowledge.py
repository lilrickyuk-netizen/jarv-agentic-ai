"""
JAI Backend - What JAI remembers of Richard and its prompt checks (Wave 6)

GET /api/richard-memory/status          the knowledge service, documents, browser and prompt checks: on and answering
GET /api/richard-memory/memories        what Mem0 keeps of what Richard has told JAI
DELETE /api/richard-memory/memories/ID  forget one of them
POST /api/richard-memory/checks         run a prompt check (suite voice, or boundaries with instructions)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core import evals, knowledge_service as ks
from app.core.auth import get_current_user_id
from app.core.config import settings

router = APIRouter(prefix="/richard-memory", tags=["richard-memory"], dependencies=[Depends(get_current_user_id)])


class Check(BaseModel):
    suite: str = Field(pattern="^(voice|boundaries)$")
    instructions: Optional[str] = Field(default=None, max_length=60000)


async def _answers(url: str) -> str:
    if not url:
        return "off"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            return "answering" if (await client.get(f"{url.rstrip('/')}/health")).status_code < 400 else "not answering"
    except httpx.HTTPError:
        return "not answering"


@router.get("/status")
async def status() -> Dict[str, Any]:
    return {"knowledge": await _answers(ks.knowledge_url()), "documents": await _answers(settings.DOCLING_URL or ""),
            "browser": await _answers(settings.BROWSER_URL or ""), "prompt_checks": await _answers(evals.promptfoo_url()),
            "gateway": "on" if settings.JAI_GATEWAY_TOKEN else "off"}


@router.get("/memories")
async def memories(limit: int = 100) -> Dict[str, Any]:
    try:
        return {"memories": await ks.memories(limit, timeout=15.0)}
    except ks.KnowledgeUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@router.delete("/memories/{memory_id}")
async def forget(memory_id: str) -> Dict[str, Any]:
    try:
        return await ks.forget(memory_id, timeout=15.0)
    except ks.KnowledgeUnavailable as exc:
        raise HTTPException(503 if "answered 404" not in str(exc) else 404, str(exc)) from exc


@router.post("/checks")
async def check(body: Check) -> Dict[str, Any]:
    try:
        return await evals.run(body.suite, body.instructions)
    except evals.ChecksUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
