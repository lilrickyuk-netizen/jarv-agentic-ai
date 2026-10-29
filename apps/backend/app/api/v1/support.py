"""
JARV Backend - Support API

The workspace's support inbox on persisted tickets (app.core.business.support):
create tickets (including from an inbound email webhook), list and read them,
recategorise, draft a reply, send it (Richard sending from the dashboard is
the approval), update the FAQ, summarise feedback, and pull new mail from the
configured inbox. Every endpoint is authenticated and limited to the caller's
own workspaces.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUserId
from app.core.business import mailer
from app.core.business.support import support_service, view
from app.core.database import get_db
from app.models.workspace import Workspace

router = APIRouter(prefix="/support", tags=["support"])


async def _owned(db: AsyncSession, user_id: str, workspace_id: UUID) -> None:
    found = (await db.execute(select(Workspace.id).where(Workspace.id == workspace_id,
                                                         Workspace.owner_id == UUID(str(user_id))))).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="Workspace not found")


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


class CreateTicketRequest(BaseModel):
    subject: str = Field(..., min_length=3)
    description: str = Field(..., min_length=3)
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None


class CategoriseRequest(BaseModel):
    category: Optional[str] = None
    priority: Optional[str] = None


class DraftReplyRequest(BaseModel):
    tone: str = "friendly"


class SendReplyRequest(BaseModel):
    reply_content: Optional[str] = Field(None, description="Send this instead of the last draft")


class FaqRequest(BaseModel):
    question: str = Field(..., min_length=5)
    answer: str = Field(..., min_length=5)
    faq_id: Optional[str] = None


@router.post("/{workspace_id}/tickets")
async def create_ticket(workspace_id: UUID, body: CreateTicketRequest, user_id: CurrentUserId,
                        db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    ticket = await support_service.create_ticket(db, workspace_id, subject=body.subject, description=body.description,
                                                 customer_email=body.customer_email, customer_name=body.customer_name,
                                                 category=body.category, priority=body.priority, source="api")
    await db.commit()
    return view(ticket)


@router.get("/{workspace_id}/tickets")
async def list_tickets(workspace_id: UUID, user_id: CurrentUserId, status: Optional[str] = None,
                       category: Optional[str] = None, limit: int = Query(50, ge=1, le=200),
                       db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    await _owned(db, user_id, workspace_id)
    return [view(t) for t in await support_service.list(db, workspace_id, status=status, category=category, limit=limit)]


@router.get("/{workspace_id}/tickets/{ticket_id}")
async def get_ticket(workspace_id: UUID, ticket_id: str, user_id: CurrentUserId,
                     db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    try:
        return view(await support_service._ticket(db, workspace_id, ticket_id))
    except LookupError as exc:
        raise _http(exc)


@router.post("/{workspace_id}/tickets/{ticket_id}/categorise")
async def categorise(workspace_id: UUID, ticket_id: str, body: CategoriseRequest, user_id: CurrentUserId,
                     db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    try:
        ticket = await support_service.categorise(db, workspace_id, ticket_id, body.category, body.priority)
    except (LookupError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return view(ticket)


@router.post("/{workspace_id}/tickets/{ticket_id}/draft-reply")
async def draft_reply(workspace_id: UUID, ticket_id: str, body: DraftReplyRequest, user_id: CurrentUserId,
                      db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    try:
        draft = await support_service.draft_reply(db, workspace_id, ticket_id, tone=body.tone)
    except (LookupError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return draft


@router.post("/{workspace_id}/tickets/{ticket_id}/reply")
async def send_reply(workspace_id: UUID, ticket_id: str, body: SendReplyRequest, user_id: CurrentUserId,
                     db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """Richard sends the reply from the dashboard: that is the approval for this one message."""
    await _owned(db, user_id, workspace_id)
    try:
        sent = await support_service.send_reply(db, workspace_id, ticket_id, approved=True, body=body.reply_content)
    except (LookupError, PermissionError, RuntimeError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return sent


@router.post("/{workspace_id}/faq")
async def update_faq(workspace_id: UUID, body: FaqRequest, user_id: CurrentUserId,
                     db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    try:
        row = await support_service.update_faq(db, workspace_id, question=body.question, answer=body.answer,
                                               faq_id=body.faq_id, author=UUID(str(user_id)))
    except (LookupError, ValueError) as exc:
        raise _http(exc)
    await db.commit()
    return {"id": str(row.id), "question": row.title, "answer": row.content_body,
            "version": (row.meta_data or {}).get("version")}


@router.get("/{workspace_id}/feedback")
async def feedback(workspace_id: UUID, user_id: CurrentUserId, days: int = Query(30, ge=1, le=365),
                   db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    return await support_service.feedback_summary(db, workspace_id, days)


@router.post("/{workspace_id}/inbox/sync")
async def sync_inbox(workspace_id: UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    await _owned(db, user_id, workspace_id)
    try:
        result = await support_service.sync_inbox(db, workspace_id)
    except RuntimeError as exc:
        raise _http(exc)
    await db.commit()
    return result


@router.get("/email/status")
async def email_status(user_id: CurrentUserId) -> Dict[str, Any]:
    return mailer.status()
