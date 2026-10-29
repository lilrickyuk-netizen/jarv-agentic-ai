"""
JARV Backend - Business API (Repair 12e-4a)

Authenticated, owner-scoped endpoints for the business pages: grounded drafts
by group (marketing, content, onboarding, community, partnership, sales),
creating a draft of any kind, the community inbox (ingest, read, moderate),
the partner and sales pipeline, and activation friction.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.business import drafting
from app.core.business.community import community_service, view as community_view
from app.core.business.onboarding import analyse_activation_friction
from app.core.business.pipelines import deal_view, partner_view, pipeline_service
from app.core.database import get_db
from app.models.business import MarketingCampaign
from app.models.content import CommunityItem, ContentItem, OnboardingFlow
from app.models.workspace import Workspace
from app.tools.business import DraftInput

router = APIRouter(prefix="/api/business", tags=["business"])


async def _owned(db: AsyncSession, user_id: str, workspace_id: UUID) -> UUID:
    owner = UUID(str(user_id))
    found = (await db.execute(select(Workspace.id).where(Workspace.id == workspace_id, Workspace.owner_id == owner))
             ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return owner


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/kinds")
async def kinds(user_id: CurrentUserId) -> List[Dict[str, Any]]:
    return [{"kind": k.tool, "group": k.group, "label": k.label, "sections": [h for _key, h in k.sections]}
            for k in drafting.KINDS.values()]


@router.get("/{workspace_id}/drafts")
async def list_drafts(workspace_id: UUID, user_id: CurrentUserId, group: Optional[str] = None,
                      limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    groups = {group} if group else {k.group for k in drafting.KINDS.values()}
    out: List[Dict[str, Any]] = []
    content = (await db.execute(select(ContentItem).where(ContentItem.workspace_id == workspace_id,
                                                          ContentItem.category.in_(list(groups)))
                                .order_by(ContentItem.created_at.desc()).limit(limit))).scalars().all()
    out += [{"id": str(c.id), "type": "content_item", "group": c.category, "kind": (c.meta_data or {}).get("tool"),
             "title": c.title, "status": c.status, "body": c.content_body,
             "needs_confirmation": (c.meta_data or {}).get("needs_confirmation", []),
             "created_at": c.created_at.isoformat() if c.created_at else None} for c in content]
    if "marketing" in groups:
        rows = (await db.execute(select(MarketingCampaign).where(MarketingCampaign.workspace_id == workspace_id)
                                 .order_by(MarketingCampaign.created_at.desc()).limit(limit))).scalars().all()
        out += [{"id": str(r.id), "type": "marketing_campaign", "group": "marketing", "kind": "create_campaign",
                 "title": r.campaign_name, "status": r.status, "body": (r.content or {}).get("plan"),
                 "needs_confirmation": (r.meta_data or {}).get("needs_confirmation", []),
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    if "onboarding" in groups:
        rows = (await db.execute(select(OnboardingFlow).where(OnboardingFlow.workspace_id == workspace_id)
                                 .order_by(OnboardingFlow.created_at.desc()).limit(limit))).scalars().all()
        out += [{"id": str(r.id), "type": "onboarding_flow", "group": "onboarding", "kind": (r.meta_data or {}).get("tool"),
                 "title": r.flow_name, "status": "active" if r.is_active else "draft",
                 "body": (r.meta_data or {}).get("body"), "steps": r.steps, "version": r.version,
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    if "community" in groups:
        rows = (await db.execute(select(CommunityItem).where(CommunityItem.workspace_id == workspace_id,
                                                             CommunityItem.status == "draft")
                                 .order_by(CommunityItem.created_at.desc()).limit(limit))).scalars().all()
        out += [{"id": str(r.id), "type": "community_item", "group": "community", "kind": (r.meta_data or {}).get("tool"),
                 "title": r.title, "status": r.status, "body": r.content,
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
    out.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    return {"drafts": out[:limit]}


@router.post("/{workspace_id}/drafts/{kind}")
async def create_draft(workspace_id: UUID, kind: str, body: DraftInput, user_id: CurrentUserId,
                       db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    owner = await _owned(db, user_id, workspace_id)
    if kind not in drafting.KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown draft kind '{kind}'")
    try:
        result = await drafting.draft(db, workspace_id, kind, body.model_dump(), owner=owner)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return result


class CommunityMessage(BaseModel):
    content: str = Field(..., min_length=1)
    author_name: str = Field(..., min_length=1)
    channel: str = "forum"
    title: Optional[str] = None
    url: Optional[str] = None
    external_id: Optional[str] = None


@router.post("/{workspace_id}/community/messages")
async def ingest_message(workspace_id: UUID, body: CommunityMessage, user_id: CurrentUserId,
                         db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    owner = await _owned(db, user_id, workspace_id)
    row = await community_service.ingest(db, workspace_id, owner, content=body.content, author_name=body.author_name,
                                         channel=body.channel, title=body.title, url=body.url,
                                         external_id=body.external_id)
    await db.commit()
    return community_view(row)


@router.get("/{workspace_id}/community/messages")
async def read_messages(workspace_id: UUID, user_id: CurrentUserId, status: Optional[str] = None,
                        channel: Optional[str] = None, limit: int = Query(50, ge=1, le=200),
                        db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    await _owned(db, user_id, workspace_id)
    return [community_view(r) for r in await community_service.read(db, workspace_id, status=status, channel=channel,
                                                                     limit=limit)]


@router.post("/{workspace_id}/community/messages/{item_id}/moderate")
async def moderate(workspace_id: UUID, item_id: str, user_id: CurrentUserId,
                   db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    owner = await _owned(db, user_id, workspace_id)
    try:
        result = await community_service.moderate(db, workspace_id, item_id, owner)
    except (LookupError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return result


@router.get("/{workspace_id}/pipeline")
async def pipeline(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    return await pipeline_service.pipeline(db, workspace_id)


class DealInput(BaseModel):
    deal_id: Optional[str] = None
    title: Optional[str] = None
    stage: Optional[str] = None
    value: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    expected_close_date: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    company: Optional[str] = None


@router.post("/{workspace_id}/deals")
async def update_deal(workspace_id: UUID, body: DealInput, user_id: CurrentUserId,
                      db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Create a deal (no deal_id) or move one through the pipeline."""
    owner = await _owned(db, user_id, workspace_id)
    if not body.deal_id and not body.title:
        raise HTTPException(status_code=400, detail="A new deal needs a title")
    try:
        deal = await pipeline_service.update_deal(db, workspace_id, owner, **body.model_dump())
    except (LookupError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return deal_view(deal)


class Candidate(BaseModel):
    name: str = Field(..., min_length=2)
    type: Optional[str] = None
    notes: Optional[str] = None
    url: Optional[str] = None


class ShortlistInput(BaseModel):
    partner_type: str = "technology"
    candidates: List[Candidate] = Field(..., min_length=1)
    criteria: Dict[str, float] = Field(default_factory=dict)


@router.post("/{workspace_id}/partners/shortlist")
async def shortlist(workspace_id: UUID, body: ShortlistInput, user_id: CurrentUserId,
                    db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    owner = await _owned(db, user_id, workspace_id)
    try:
        rows = await pipeline_service.shortlist(db, workspace_id, candidates=[c.model_dump() for c in body.candidates],
                                                criteria=body.criteria, partner_type=body.partner_type, owner=owner)
    except (LookupError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return {"partners": [partner_view(r) for r in rows]}


class PartnerUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    estimated_value: Optional[float] = Field(None, ge=0)
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None


@router.post("/{workspace_id}/partners/{partner_id}")
async def update_partner(workspace_id: UUID, partner_id: str, body: PartnerUpdate, user_id: CurrentUserId,
                         db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Richard moves a partner along from the dashboard; that is his approval for an agreement becoming active."""
    await _owned(db, user_id, workspace_id)
    try:
        row = await pipeline_service.update_partner(db, workspace_id, partner_id, approved=True, **body.model_dump())
    except (LookupError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return partner_view(row)


@router.get("/{workspace_id}/onboarding/friction")
async def friction(workspace_id: UUID, user_id: CurrentUserId, days: int = Query(30, ge=1, le=365),
                   db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    return await analyse_activation_friction(db, workspace_id, days)
